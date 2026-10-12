from __future__ import annotations

import asyncio
import hashlib
import json
import time
from pathlib import Path

import httpx

from .analysis import analyze, enrich
from .render import graph_svg, image_html
from .repository import Repository
from .context import LABELS, SYSTEM_PROMPT, parse_relationships, sample_context


def extract(message, bot_id: str = "") -> dict:
    """Accept both live ChatMessage and a DBChatMessage. Do not retain raw text."""
    content = message.content_data
    if isinstance(content, str):
        content = json.loads(content or "[]")
    ext = message.ext_data
    if isinstance(ext, str):
        ext = json.loads(ext or "{}")
    mentions = []
    for item in content:
        item = item if isinstance(item, dict) else item.model_dump()
        kind = getattr(item.get("type"), "value", item.get("type"))
        target = str(item.get("target_platform_userid", ""))
        if kind == "at" and target not in {"", "all", "0", bot_id}:
            mentions.append(target)
    sender = str(message.platform_userid or message.sender_id)
    msg_id = str(message.message_id or f"db:{getattr(message, 'id', '')}")
    if msg_id == "db:":
        # Some notice events have no platform ID. Stable hash prevents duplicate event counts.
        msg_id = "event:" + hashlib.sha256(f"{sender}:{message.send_timestamp}:{message.content_text}".encode()).hexdigest()[:24]
    reply_sender = str(ext.get("ref_sender_id") or "")
    same_group = ext.get("ref_chat_key", "") in {"", message.chat_key}
    return {"id": msg_id, "sender": sender, "name": str(message.sender_nickname or message.sender_name or sender),
            "ts": int(message.send_timestamp), "mentions": sorted(set(mentions)),
            "reply": str(ext.get("ref_msg_id") or "") if same_group else "",
            "reply_sender": reply_sender if same_group and reply_sender != bot_id else ""}


class RelationsService:
    def __init__(self, plugin, config):
        self.plugin, self.config = plugin, config
        self.repo = Repository(plugin.get_plugin_data_dir() / "relations.sqlite3")
        self.queue = asyncio.Queue(maxsize=5000)
        self.worker = None
        self.locks, self.cache, self.bot_ids, self.render_locks = {}, {}, {}, {}
        self.model_lock = asyncio.Semaphore(1)
        self.context_cache = {}
        self.context_locks = {}
        self.revisions = {}
        self.dropped = 0
        self.sync_status = {}

    def allowed(self, chat_key: str) -> bool:
        allowed = self.config().GROUP_ALLOWLIST
        return chat_key.startswith("onebot_v11-group_") and (not allowed or chat_key in allowed)

    async def start(self):
        await asyncio.to_thread(self.repo.prune, int(time.time()) - self.config().RETENTION_DAYS * 86400)
        await asyncio.to_thread(self.prune_exports)
        self.worker = asyncio.create_task(self._consume())

    async def stop(self):
        if self.worker:
            try:
                await asyncio.wait_for(self.queue.join(), timeout=10)
            except asyncio.TimeoutError:
                self.plugin.logger.warning("关系插件退出时仍有未写入事件，可通过历史同步补齐")
            self.worker.cancel()
            try:
                await self.worker
            except asyncio.CancelledError:
                pass

    def enqueue(self, chat_key: str, name: str, row: dict):
        if self.allowed(chat_key) and row["sender"] not in {"", "-1"}:
            try:
                self.queue.put_nowait((chat_key, name, row))
            except asyncio.QueueFull:
                self.dropped += 1
                if self.dropped == 1 or self.dropped % 100 == 0:
                    self.plugin.logger.warning("关系插件事件队列已满，请使用 relations_manage sync 补齐历史")

    async def _consume(self):
        last_prune = time.monotonic()
        while True:
            key, name, row = await self.queue.get()
            try:
                await asyncio.to_thread(self.repo.insert, key, name, [row])
                self.invalidate(key)
                if time.monotonic() - last_prune > 3600:
                    await asyncio.to_thread(self.repo.prune, int(time.time()) - self.config().RETENTION_DAYS * 86400)
                    self.prune_exports()
                    last_prune = time.monotonic()
            except Exception:
                self.plugin.logger.exception("关系插件写入失败，可通过历史同步补齐")
            finally:
                self.queue.task_done()

    def invalidate(self, key, *, context=False):
        self.cache = {k: v for k, v in self.cache.items() if k[0] != key}
        if context:
            self.revisions[key] = self.revisions.get(key, 0) + 1
            self.context_cache = {k: v for k, v in self.context_cache.items() if k[0] != key}

    async def channel(self, key: str):
        from nekro_agent.models.db_chat_channel import DBChatChannel
        if not self.allowed(key):
            raise ValueError("该群不在插件支持范围或群白名单内")
        channel = await DBChatChannel.get_or_none(chat_key=key)
        if not channel or channel.channel_type != "group":
            raise ValueError("未找到群聊频道")
        await asyncio.to_thread(self.repo.ensure_channel, key, channel.channel_name or key)
        if key not in self.bot_ids:
            try:
                from nekro_agent.adapters.utils import adapter_utils
                adapter = await adapter_utils.get_adapter_for_chat(key)
                self.bot_ids[key] = str((await adapter.get_self_info()).user_id)
            except Exception:
                self.bot_ids[key] = ""
        return channel

    async def channels(self):
        from nekro_agent.models.db_chat_channel import DBChatChannel
        channels = await DBChatChannel.filter(channel_type="group", adapter_key="onebot_v11").all()
        result = []
        for c in channels:
            if self.allowed(c.chat_key):
                state = await asyncio.to_thread(self.repo.state, c.chat_key)
                result.append({"key": c.chat_key, "name": c.channel_name or c.chat_key, "enabled": bool(state["enabled"])})
        return result

    async def sync(self, key: str, days: int):
        from nekro_agent.models.db_chat_message import DBChatMessage
        lock = self.locks.setdefault(key, asyncio.Lock())
        async with lock:
            channel = await self.channel(key)
            state = await asyncio.to_thread(self.repo.state, key)
            if not state["enabled"]:
                return {"imported": 0, "paused": True, "truncated": False}
            cutoff = max(int(time.time()) - min(days * 2, self.config().RETENTION_DAYS) * 86400, state["cleared_at"] + 1)
            base = DBChatMessage.filter(chat_key=key, send_timestamp__gte=cutoff, is_recalled=False).exclude(sender_id="-1")
            count = await base.count()
            cap = self.config().MAX_HISTORY_MESSAGES
            source = await base.order_by("-id").limit(cap).all()
            bot_id = self.bot_ids.get(key, "")
            rows = []
            for message in source:
                try:
                    row = extract(message, bot_id)
                    if row["sender"] != bot_id:
                        rows.append(row)
                except (ValueError, TypeError, AttributeError):
                    continue
            # Resolve references in the same group only, including targets outside the selected period.
            known = {r["id"]: r["sender"] for r in rows}
            unresolved = sorted({r["reply"] for r in rows if r["reply"] and r["reply"] not in known})
            for i in range(0, len(unresolved), 500):
                refs = await DBChatMessage.filter(chat_key=key, message_id__in=unresolved[i:i + 500], is_recalled=False).values("message_id", "platform_userid", "sender_id")
                for ref in refs:
                    sender = str(ref["platform_userid"] or ref["sender_id"])
                    if str(ref["sender_id"]) != "-1" and sender != bot_id:
                        known[ref["message_id"]] = sender
            for r in rows:
                # Ignore reply-to-bot events even when a transport exposes a ref_sender_id.
                r["reply_sender"] = known.get(r["reply"], r["reply_sender"])
                if r["reply_sender"] == bot_id or r["reply_sender"] == "-1":
                    r["reply_sender"] = ""
                    r["reply"] = ""
            await asyncio.to_thread(self.repo.insert, key, channel.channel_name or key, rows,
                                    max((m.id for m in source), default=state["cursor"]))
            covered = max(cutoff, min((r["ts"] for r in rows), default=cutoff)) if count > cap else cutoff
            await asyncio.to_thread(self.repo.mark_sync, key, covered)
            self.sync_status[key] = {"imported": len(rows), "available": count, "truncated": count > cap}
            self.invalidate(key)
            return self.sync_status[key]

    async def report(self, key: str, days: int = 7, limit: int = 20, *, refresh=False, ai=True) -> dict:
        if not 1 <= days <= 30 or not 2 <= limit <= 40:
            raise ValueError("统计周期为 1–30 天，展示人数为 2–40")
        channel = await self.channel(key)
        info = await asyncio.to_thread(self.repo.sync_info, key)
        required_from = int(time.time()) - days * 2 * 86400
        if refresh or not info or info.get("covered_from", 2**63) > required_from + 120:
            await self.sync(key, days)
        cache_key = (key, days, limit)
        cached = self.cache.get(cache_key)
        if cached and time.monotonic() - cached[0] < 120:
            result = json.loads(json.dumps(cached[1]))
        else:
            end = int(time.time()) + 1
            start = end - days * 86400
            rows = await asyncio.to_thread(self.repo.rows, key, start - days * 86400, end)
            excluded = await asyncio.to_thread(self.repo.excluded, key)
            excluded |= {self.bot_ids.get(key, ""), "-1"}
            def compute():
                report = analyze(rows, start, end, limit=limit, excluded=excluded,
                                 min_events=self.config().MIN_EDGE_EVENTS, daily_cap=self.config().DAILY_PAIR_CAP)
                previous = analyze(rows, start - days * 86400, start, excluded=excluded)
                return enrich(report, previous)
            result = await asyncio.to_thread(compute)
            result.update(channel_name=channel.channel_name or key, chat_key=key, days=days,
                          min_events=self.config().MIN_EDGE_EVENTS, ai_comment="", generated_at=end - 1,
                          excluded_count=len(excluded - {"", "-1", self.bot_ids.get(key, "")}),
                          enabled=bool((await asyncio.to_thread(self.repo.state, key))["enabled"]))
            result["sync"] = self.sync_status.get(key, {})
            warnings = []
            if result["sync"].get("truncated"):
                warnings.append(f"历史记录超过单次上限 {self.config().MAX_HISTORY_MESSAGES} 条，本报告为部分样本。")
            if not result["previous"]["messages"]:
                warnings.append("上一周期无可用记录，互动增量不能直接解释为关系升温。")
            if self.dropped:
                warnings.append("曾发生事件队列溢出，可运行 relations_manage sync 补齐历史。")
            if not result["enabled"]:
                warnings.append("本群已暂停采集，报告仅包含此前记录。")
            result["warning"] = " ".join(warnings)
            result["svg"] = await asyncio.to_thread(graph_svg, result)
            self.cache[cache_key] = (time.monotonic(), result)
            result = json.loads(json.dumps(result))
        if ai:
            result["context_analysis"] = await self.interpret(result, refresh=refresh)
        else:
            result["context_analysis"] = {"relationships": [], "summary": "本次仅统计互动，未调用聊天赏析模型。"}
        return result

    async def interpret(self, report: dict, *, refresh=False) -> dict:
        """Read chat text on demand; only evidence snippets survive in an in-memory cache."""
        empty = {"relationships": [], "summary": ""}
        cfg = self.config()
        if not cfg.ENABLE_CONTEXT_ANALYSIS:
            return {**empty, "summary": "聊天赏析未开启；可在插件配置中启用。"}
        if not report["enabled"]:
            return {**empty, "summary": "本群已暂停采集，暂不读取新聊天正文进行赏析。"}
        key = report["chat_key"]
        signature = (key, report["days"], cfg.MODEL_GROUP, cfg.MAX_CONTEXT_MESSAGES,
                     cfg.CONTEXT_MESSAGE_CHARS, cfg.MAX_RELATIONSHIPS, tuple(cfg.RELATION_LABELS))
        async with self.context_locks.setdefault(signature, asyncio.Lock()):
            cached = self.context_cache.get(signature)
            if not refresh and cached and time.monotonic() - cached[0] < 1800:
                return json.loads(json.dumps(cached[1]))
            revision = self.revisions.get(key, 0)
            result = await self._interpret(report)
            # An opt-out/clear/pause while the model was working invalidates that response too.
            if revision != self.revisions.get(key, 0):
                raise ValueError("群关系数据在分析期间已更新，请重新生成报告。")
            if not result.get("error"):
                self.context_cache[signature] = (time.monotonic(), result)
            return json.loads(json.dumps(result))

    async def _interpret(self, report: dict) -> dict:
        empty = {"relationships": [], "summary": ""}
        from nekro_agent.api.core import config
        from nekro_agent.models.db_chat_message import DBChatMessage
        from openai import AsyncOpenAI
        group = config.MODEL_GROUPS.get(self.config().MODEL_GROUP or config.USE_MODEL_GROUP)
        if not group or group.MODEL_TYPE != "chat":
            return {**empty, "summary": "没有可用聊天模型组，已保留互动统计。", "error": True}
        cfg = self.config()
        key = report["chat_key"]
        state = await asyncio.to_thread(self.repo.state, key)
        cutoff = max(report["meta"]["start"], state["cleared_at"] + 1)
        base = DBChatMessage.filter(chat_key=key, send_timestamp__gte=cutoff,
                                   send_timestamp__lt=report["meta"]["end"], is_recalled=False).exclude(sender_id="-1")
        total = await base.count()
        source = await base.order_by("-id").limit(cfg.MAX_HISTORY_MESSAGES).all()
        rows = []
        for message in source:
            try:
                rows.append({**extract(message, self.bot_ids.get(key, "")), "text": message.content_text or ""})
            except (ValueError, TypeError, AttributeError):
                continue
        excluded = await asyncio.to_thread(self.repo.excluded, key)
        excluded |= {self.bot_ids.get(key, ""), "", "-1"}
        context = await asyncio.to_thread(sample_context, rows, report["members"], excluded,
                                          cfg.MAX_CONTEXT_MESSAGES, cfg.CONTEXT_MESSAGE_CHARS)
        if len(context["messages"]) < 2:
            return {**empty, "summary": "可用聊天正文太少，暂不生成关系剧本。", "sampled": context["sampled"]}
        allowed = [label for label in cfg.RELATION_LABELS if label in LABELS]
        payload = {"members": context["members"], "messages": context["messages"],
                   "allowed_labels": allowed, "max_relationships": cfg.MAX_RELATIONSHIPS}
        try:
            async with self.model_lock:
                async with httpx.AsyncClient(proxy=group.CHAT_PROXY or None, timeout=90) as http:
                    async with AsyncOpenAI(api_key=group.API_KEY, base_url=group.BASE_URL or None,
                                           http_client=http, max_retries=1) as client:
                        response = await client.chat.completions.create(model=group.CHAT_MODEL,
                            messages=[{"role": "system", "content": SYSTEM_PROMPT},
                                      {"role": "user", "content": json.dumps(payload, ensure_ascii=False)}], max_tokens=3000)
            result = parse_relationships(response.choices[0].message.content or "", context, allowed, cfg.MAX_RELATIONSHIPS)
            result.update(generated_at=int(time.time()), truncated=total > cfg.MAX_HISTORY_MESSAGES)
            return result
        except Exception as error:
            self.plugin.logger.warning(f"聊天赏析失败（{type(error).__name__}，HTTP {getattr(error, 'status_code', '-')}），已保留互动统计")
            return {**empty, "summary": "聊天赏析暂时不可用，互动统计与关系图仍可使用。", "error": True}

    def prune_exports(self):
        folder = self.plugin.get_plugin_data_dir() / "exports"
        if folder.exists():
            for file in folder.glob("*.png"):
                if file.stat().st_mtime < time.time() - 86400:
                    file.unlink(missing_ok=True)

    def purge_exports(self):
        folder = self.plugin.get_plugin_data_dir() / "exports"
        if folder.exists():
            for file in folder.glob("*.png"):
                file.unlink(missing_ok=True)

    async def image(self, report: dict) -> Path:
        payload = image_html(report)
        digest = hashlib.sha256(payload.encode()).hexdigest()
        folder = self.plugin.get_plugin_data_dir() / "exports"
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"{digest}.png"
        lock = self.render_locks.setdefault(digest, asyncio.Lock())
        try:
            async with lock:
                if path.exists():
                    return path
                cfg = self.config()
                async with httpx.AsyncClient(timeout=cfg.RENDER_TIMEOUT) as client:
                    response = await client.post(cfg.RENDER_ENDPOINT.rstrip("/") + "/screenshot",
                        params={"token": cfg.RENDER_TOKEN} if cfg.RENDER_TOKEN else {},
                        json={"html": payload, "options": {"type": "png", "fullPage": True},
                              "viewport": {"width": 1080, "height": 900, "deviceScaleFactor": 2},
                              "waitForFunction": {"fn": "document.fonts.status === 'loaded'"}})
                    response.raise_for_status()
                    if not response.content.startswith(b"\x89PNG\r\n\x1a\n"):
                        raise ValueError("渲染服务未返回 PNG")
                    await asyncio.to_thread(path.write_bytes, response.content)
                return path
        finally:
            if not lock.locked():
                self.render_locks.pop(digest, None)
