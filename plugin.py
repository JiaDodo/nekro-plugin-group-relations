"""群关系观察：原生 WebUI 命令、聊天赏析与图片报告。"""
from __future__ import annotations

from pydantic import Field

from nekro_agent.api.plugin import (
    Arg, CmdCtl, CommandExecutionContext, CommandPermission, ConfigBase,
    ExtraField, NekroPlugin, SandboxMethodType,
)
from nekro_agent.api.schemas import AgentCtx
from nekro_agent.api.message import ChatMessage
from nekro_agent.services.command.schemas import CommandOutputSegment, CommandOutputSegmentType

from .context import LABELS
from .render import text_report
from .service import RelationsService, extract

plugin = NekroPlugin(
    name="群关系观察", module_name="group_relations", author="JiaDodo", version="0.2.0",
    description="根据本群聊天赏析亲属、损友、CP、情妇、主仆等娱乐关系，附原话依据和图片报告；直接使用原生 WebUI。",
    url="https://github.com/JiaDodo/nekro-plugin-group-relations", support_adapter=["onebot_v11"],
    allow_sleep=True, sleep_brief="分析本群互动关系、查询我的聊天搭子、生成群关系图和关系周报。",
)


@plugin.mount_config()
class RelationsConfig(ConfigBase):
    GROUP_ALLOWLIST: list[str] = Field(default_factory=list, title="群白名单", description="填完整 chat_key，如 onebot_v11-group_123456。留空允许所有 QQ 群。")
    RETENTION_DAYS: int = Field(default=90, ge=60, le=365, title="互动记录保留天数")
    MAX_HISTORY_MESSAGES: int = Field(default=50000, ge=1000, le=200000, title="单次历史同步消息上限", description="超过上限会明确显示样本不完整。")
    MIN_EDGE_EVENTS: int = Field(default=2, ge=1, le=20, title="关系图最少互动次数")
    DAILY_PAIR_CAP: int = Field(default=20, ge=1, le=200, title="单日单向互动计分上限", description="实际次数完整展示，仅限制刷屏对互动指数的影响。")
    ENABLE_CONTEXT_ANALYSIS: bool = Field(default=True, title="启用聊天赏析", description="请求关系报告时，将本群抽样聊天正文和昵称交给所选模型分析；不自动逐条调用。关系按群聊剧本呈现。")
    MODEL_GROUP: str = Field(default="", title="聊天赏析模型组", description="留空使用系统主模型组。", json_schema_extra=ExtraField(ref_model_groups=True, model_type="chat").model_dump())
    MAX_CONTEXT_MESSAGES: int = Field(default=360, ge=20, le=1000, title="聊天赏析样本条数", description="均匀抽样与关系词附近对话结合，结果缓存30分钟；refresh:true 强制重新赏析。")
    CONTEXT_MESSAGE_CHARS: int = Field(default=240, ge=80, le=500, title="单条赏析文本字数上限")
    MAX_RELATIONSHIPS: int = Field(default=12, ge=1, le=20, title="最多展示剧本关系数")
    RELATION_LABELS: list[str] = Field(default_factory=lambda: list(LABELS), title="允许的娱乐关系", description="父亲、母亲、儿子、女儿、兄弟、姐妹、祖孙、朋友、损友、恋人、夫妻、情妇、情夫、主人、仆人、欢喜冤家、舔狗、金主、工具人。方向表示前者扮演该角色。")
    RENDER_ENDPOINT: str = Field(default="http://nekro_html2img:3000", title="图片渲染服务", description="browserless Chromium 服务；必须由管理员配置。")
    RENDER_TOKEN: str = Field(default="", title="图片渲染令牌", json_schema_extra=ExtraField(is_secret=True).model_dump())
    RENDER_TIMEOUT: int = Field(default=60, ge=10, le=180, title="渲染超时秒数")


_service: RelationsService | None = None


def config() -> RelationsConfig:
    return plugin.get_config(RelationsConfig)


def service() -> RelationsService:
    if _service is None:
        raise RuntimeError("关系插件尚未完成初始化")
    return _service


@plugin.mount_init_method()
async def initialize():
    global _service
    _service = RelationsService(plugin, config)
    await _service.start()
    plugin.logger.info("群关系观察已就绪；在原生 WebUI 命令中运行 relations")


@plugin.mount_cleanup_method()
async def cleanup():
    global _service
    if _service:
        await _service.stop()
        _service = None


@plugin.mount_on_user_message()
async def collect(_ctx: AgentCtx, message: ChatMessage):
    if not _service or not _service.allowed(message.chat_key):
        return None
    try:
        row = extract(message, _service.bot_ids.get(message.chat_key, ""))
        if row["sender"] != _service.bot_ids.get(message.chat_key):
            _service.enqueue(message.chat_key, _ctx.channel_name or message.chat_key, row)
    except Exception:
        plugin.logger.warning("忽略无法解析的互动消息；正常聊天继续处理")
    return None


async def deliver(ctx: AgentCtx, days: int, image: bool = True, ai: bool = True):
    report = await service().report(ctx.chat_key, days, ai=ai)
    if image:
        try:
            path = await service().image(report)
            await ctx.send_image(str(path))
            return "群关系报告图片已发送。" + (" " + report["warning"] if report["warning"] else "")
        except Exception:
            plugin.logger.warning("群关系图片生成或发送失败，回退文字报告")
    return text_report(report)


@plugin.mount_command(name="relations", aliases=["群关系图", "群关系周报", "群关系赏析"], description="赏析本群角色关系，生成带聊天依据的图片；WebUI 内直接显示", permission=CommandPermission.PUBLIC, usage="relations [days] [contextual:true] [refresh:false]", category="群关系")
async def relations_command(context: CommandExecutionContext, days: int = Arg("最近天数，1–30", default=7, positional=True), contextual: bool = Arg("赏析聊天正文", default=True), refresh: bool = Arg("强制同步和重新赏析", default=False)):
    yield CmdCtl.message("正在整理本群互动和聊天语境，生成关系报告……")
    try:
        report = await service().report(context.chat_key, days, ai=contextual, refresh=refresh)
        try:
            path = await service().image(report)
        except Exception:
            plugin.logger.warning("关系图片生成失败，回退文字报告")
            yield CmdCtl.success(text_report(report))
            return
        analysis = report.get("context_analysis", {})
        summary = "群关系报告已生成 · 最近 " + str(days) + " 天 · 角色均为群聊剧本。"
        if contextual:
            if analysis.get("error"):
                summary += " 聊天赏析暂时不可用，已保留互动统计。"
            elif "sampled" in analysis:
                summary += f' 赏析 {analysis["sampled"]} 条聊天，提取 {len(analysis.get("relationships", []))} 组角色梗。'
            else:
                summary += " " + analysis.get("summary", "")
        # Let the command framework route the attachment. WebUI execution never sends to QQ.
        yield CmdCtl.success([
            CommandOutputSegment(type=CommandOutputSegmentType.TEXT, text=summary),
            CommandOutputSegment(type=CommandOutputSegmentType.IMAGE, file_path=str(path)),
        ])
    except ValueError as e:
        yield CmdCtl.failed(str(e))
    except Exception:
        plugin.logger.exception("关系报告生成失败")
        yield CmdCtl.failed("关系报告暂时不可用，请查看插件日志。")


@plugin.mount_command(name="my_relations", aliases=["我的群关系"], description="查看自己在本群的互动搭子", permission=CommandPermission.PUBLIC, usage="my_relations [days]", category="群关系")
async def my_command(context: CommandExecutionContext, days: int = Arg("最近天数，1–30", default=7, positional=True)):
    try:
        if context.adapter_key == "webui":
            return CmdCtl.failed("个人关系请由本人在群里执行 /my_relations；后台管理员账号不是 QQ 成员身份。")
        return CmdCtl.success(text_report(await service().report(context.chat_key, days), str(context.user_id)))
    except ValueError as e:
        return CmdCtl.failed(str(e))


@plugin.mount_command(name="relations_optout", aliases=["退出关系统计"], description="退出本群关系统计并清理自己的互动数据", permission=CommandPermission.PUBLIC, category="群关系")
async def optout_command(context: CommandExecutionContext):
    import asyncio
    if context.adapter_key == "webui":
        return CmdCtl.failed("请由本人在群里执行 /relations_optout。")
    await service().channel(context.chat_key)
    await asyncio.to_thread(service().repo.opt_out, context.chat_key, str(context.user_id), True)
    await asyncio.to_thread(service().purge_exports)
    service().invalidate(context.chat_key, context=True)
    return CmdCtl.success("你已退出本群关系统计，插件中的个人互动记录已清理。")


@plugin.mount_command(name="relations_optin", aliases=["加入关系统计"], description="重新加入本群关系统计", permission=CommandPermission.PUBLIC, category="群关系")
async def optin_command(context: CommandExecutionContext):
    import asyncio
    if context.adapter_key == "webui":
        return CmdCtl.failed("请由本人在群里执行 /relations_optin。")
    await service().channel(context.chat_key)
    await asyncio.to_thread(service().repo.opt_out, context.chat_key, str(context.user_id), False)
    service().invalidate(context.chat_key, context=True)
    return CmdCtl.success("你已重新加入；之后的历史同步可能重新导入仍保留的群聊互动。")


@plugin.mount_command(name="relations_manage", aliases=["群关系管理"], description="管理当前群关系统计：status/sync/pause/resume/clear", permission=CommandPermission.SUPER_USER, usage="relations_manage [action] [days:7]", category="群关系")
async def manage_command(context: CommandExecutionContext, action: str = Arg("clear会清空本群记录", default="status", positional=True, choices=["status", "sync", "pause", "resume", "clear"]), days: int = Arg("同步最近天数，1–30", default=7, range=(1, 30))):
    import asyncio
    svc = service()
    try:
        await svc.channel(context.chat_key)
        if action not in {"status", "sync", "pause", "resume", "clear"} or not 1 <= days <= 30:
            return CmdCtl.failed("action 为 status/sync/pause/resume/clear；days 为1–30。")
        if action == "sync":
            result = await svc.sync(context.chat_key, days)
            svc.invalidate(context.chat_key, context=True)
            return CmdCtl.success("历史同步完成。" + str(result))
        if action in {"pause", "resume"}:
            await asyncio.to_thread(svc.repo.set_enabled, context.chat_key, action == "resume")
        elif action == "clear":
            await asyncio.to_thread(svc.repo.clear, context.chat_key)
        if action != "status":
            svc.invalidate(context.chat_key, context=True)
            await asyncio.to_thread(svc.purge_exports)
        state = await asyncio.to_thread(svc.repo.state, context.chat_key)
        return CmdCtl.success(("本群记录已清空，旧历史不会重新导入。" if action == "clear" else "") + ("采集已开启。" if state["enabled"] else "采集已暂停。"))
    except ValueError as e:
        return CmdCtl.failed(str(e))


@plugin.mount_sandbox_method(SandboxMethodType.TOOL, name="分析本群关系", description="赏析当前群聊天中的亲属、CP、情妇、主仆等角色梗，引用原话并生成图片；仅访问当前群。")
async def analyze_group_relations(_ctx: AgentCtx, days: int = 7, send_image: bool = True, ai_comment: bool = True) -> str:
    """Analyze current-group conversation and generate an evidence-based entertainment relationship report.
    days: 1–30. send_image sends PNG. ai_comment enables chat-context analysis (default true).
    Roles include family, lovers, mistress and master/servant as in-chat jokes, not real-world relationship claims.
    """
    return await deliver(_ctx, days, send_image, ai_comment)


@plugin.mount_sandbox_method(SandboxMethodType.TOOL, name="查询我的群关系", description="查询触发者在当前群的互动搭子。")
async def get_my_group_relations(_ctx: AgentCtx, days: int = 7) -> str:
    """Show the triggering user's interaction partners in the current group. days: 1–30."""
    user = _ctx.db_user
    if not user:
        return "无法确认本次请求的用户，请使用 /my_relations 命令。"
    return text_report(await service().report(_ctx.chat_key, days), str(user.platform_userid))
