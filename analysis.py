"""Deterministic interaction statistics. No model calls and no raw chat text."""
from __future__ import annotations

import math
import copy
from collections import Counter, defaultdict
from datetime import datetime
from zoneinfo import ZoneInfo

from .identity import REFERENCE, member_names

TZ = ZoneInfo("Asia/Shanghai")


def personal_report(report: dict, uid: str) -> dict:
    """Build an independent ego report; unrelated pairs never enter its cards."""
    source = next((m for m in report["members"] if m["id"] == uid), None)
    if not source:
        raise ValueError("本期没有你的可用互动数据。可能尚未积累记录，或你已退出统计。")
    result = copy.deepcopy(report)
    edges = [e for e in result["edges"] if uid in (e["source"], e["target"])]
    context = result.setdefault("context_analysis", {})
    roles = [r for r in context.get("relationships", []) if uid in (r["source"], r["target"])]
    known = {uid} | {x for e in edges+roles for x in (e["source"], e["target"])}
    names = member_names(report["members"])
    # Third-party references in genuine excerpts retain a readable nickname.
    def references(text):
        return REFERENCE.sub(lambda m: m.group(0) if m.group(1) in known else names.get(m.group(1), "某位成员"), text)
    for role in roles:
        role["reason"] = references(role["reason"])
        for quote in role["evidence"]:
            quote["text"] = references(quote["text"])
    members = [m for m in result["members"] if m["id"] in known]
    members.sort(key=lambda m: m["id"] != uid)
    result["members"], result["edges"] = members, edges
    result["graph"] = {"nodes": members[:20], "edges": edges}
    result["clusters"] = []
    result["personal"] = {"uid": uid, "name": source["name"], "sent": source["sent"], "received": source["received"]}
    result["group_name"] = report["channel_name"]
    result["channel_name"] = names[uid]+" · 我的群关系"
    result["meta"].update(messages=source["messages"], members=len(members), interactions=sum(e["events"] for e in edges),
                          pairs=len(edges), shown_members=min(20,len(members)), shown_edges=len(edges))
    context["relationships"] = roles
    context["summary"] = f"本期我与 {len(known)-1} 位成员产生关联，有 {sum(e['events'] for e in edges)} 次明确互动，赏析出 {len(roles)} 组与我相关的关系。"
    if context.get("error"):
        context["summary"] += " 聊天赏析暂时不可用，已保留互动统计。"
    result["notes"] = [f"我主动互动 {source['sent']} 次，被互动 {source['received']} 次。"]
    if edges:
        top = edges[0]
        peer = top["target"] if top["source"] == uid else top["source"]
        result["notes"].append(f"我的首位聊天搭子：{names[peer]}，共 {top['events']} 次互动，分布在 {top['days']} 天。")
    result["notes"].append("只展示本人相关的互动与角色；没有连线不代表关系疏远。")
    result["ai_comment"] = ""
    result["avatars"] = {k:v for k,v in result.get("avatars", {}).items() if k in known}
    return result


def date_label(timestamp: int) -> str:
    return datetime.fromtimestamp(timestamp, TZ).strftime("%Y-%m-%d")


def analyze(rows: list[dict], start: int, end: int, *, limit: int = 20,
            excluded: set[str] | None = None, min_events: int = 2,
            daily_cap: int = 20) -> dict:
    excluded = excluded or set()
    all_rows = [r for r in rows if r["sender"] not in excluded and r["sender"] not in {"", "-1"}]
    lookup = {r["id"]: r["sender"] for r in all_rows}
    current = [r for r in all_rows if start <= r["ts"] < end]
    names, users, pairs = {}, {}, {}
    daily = Counter()
    for r in sorted(all_rows, key=lambda x: (x["ts"], x["id"])):
        names[r["sender"]] = r.get("name") or r["sender"]

    def member(uid):
        return users.setdefault(uid, {"id": uid, "name": names.get(uid, uid), "messages": 0,
                                      "sent": 0, "received": 0, "days_set": set(), "peers": set()})

    for r in sorted(current, key=lambda x: (x["ts"], x["id"])):
        source = r["sender"]
        day = date_label(r["ts"])
        member(source)["messages"] += 1
        member(source)["days_set"].add(day)
        targets = {str(t): "at" for t in r.get("mentions", [])}
        reply = r.get("reply_sender") or lookup.get(r.get("reply", ""))
        if reply:
            targets[reply] = "reply"  # one message→one target counts once, prefer the stronger signal
        for target, kind in targets.items():
            if target in excluded or target in {source, "", "-1", "all", "0"}:
                continue
            a, b = sorted((source, target))
            edge = pairs.setdefault((a, b), {"source": a, "target": b, "events": 0,
                "mentions": 0, "replies": 0, "ab": 0, "ba": 0, "days_set": set(), "weight": 0.0})
            edge["events"] += 1
            edge["replies" if kind == "reply" else "mentions"] += 1
            edge["ab" if source == a else "ba"] += 1
            edge["days_set"].add(day)
            daily[(day, source, target)] += 1
            if daily[(day, source, target)] <= daily_cap:
                edge["weight"] += 3 if kind == "reply" else 2
            member(source)["sent"] += 1
            member(target)["received"] += 1
            member(source)["peers"].add(target)
            member(target)["peers"].add(source)

    edges = []
    for edge in pairs.values():
        a, b = edge["source"], edge["target"]
        mutual = 2 * min(edge["ab"], edge["ba"]) / edge["events"]
        days = len(edge.pop("days_set"))
        denominator = math.sqrt(max(1, users[a]["messages"] + users[b]["messages"]))
        score = edge.pop("weight") / denominator * (0.55 + 0.45 * mutual) * (1 + 0.15 * math.log1p(days)) * 10
        edge.update(score=round(score, 2), mutual=round(mutual, 3), days=days,
                    label="稳定聊天搭子" if days >= 3 and mutual >= 0.4 else
                          "双向互动" if mutual >= 0.4 else "单向互动较多")
        edges.append(edge)
    edges.sort(key=lambda e: (-e["score"], e["source"], e["target"]))
    for u in users.values():
        u["active_days"] = len(u.pop("days_set"))
        u["degree"] = len(u.pop("peers"))
        u["role"] = "主动开聊" if u["sent"] > max(3, u["received"] * 2) else \
                    "大家常找" if u["received"] > max(3, u["sent"] * 2) else "群聊参与者"
    ranked = sorted(users.values(), key=lambda u: (-(u["sent"] + u["received"]), -u["messages"], u["id"]))
    selected = {u["id"] for u in ranked[:limit]}
    shown = [e for e in edges if e["source"] in selected and e["target"] in selected and e["events"] >= min_events]
    # Connected components of repeated, reciprocal interactions. These are descriptive clusters, not real social affiliations.
    adjacency = defaultdict(set)
    for e in shown:
        if e["events"] >= 3 and e["mutual"] >= 0.4:
            adjacency[e["source"]].add(e["target"])
            adjacency[e["target"]].add(e["source"])
    groups, visited = [], set()
    for uid in sorted(adjacency):
        if uid in visited:
            continue
        stack, component = [uid], []
        while stack:
            cur = stack.pop()
            if cur in visited:
                continue
            visited.add(cur)
            component.append(cur)
            stack.extend(sorted(adjacency[cur] - visited))
        if len(component) > 1:
            groups.append(component)
    palette = ["#83b7ff", "#b9a0ff", "#6edfc6", "#f5bd78", "#ef94bc"]
    for i, group in enumerate(groups):
        for uid in group:
            users[uid]["color"] = palette[i % len(palette)]
    for u in ranked:
        u.setdefault("color", "#83b7ff")
    return {"members": ranked, "edges": edges, "graph": {"nodes": ranked[:limit], "edges": shown},
            "clusters": groups, "meta": {"messages": len(current), "members": len(users),
                "interactions": sum(e["events"] for e in edges), "pairs": len(edges),
                "shown_members": len(selected), "shown_edges": len(shown),
                "first_message": min((r["ts"] for r in current), default=None),
                "last_message": max((r["ts"] for r in current), default=None),
                "start": start, "end": end}}


def enrich(report: dict, previous: dict) -> dict:
    old = {(e["source"], e["target"]): e for e in previous["edges"]}
    for e in report["edges"]:
        prior = old.get((e["source"], e["target"]), {}).get("events", 0)
        e["previous_events"] = prior
        e["change"] = e["events"] - prior
    names = {u["id"]: u["name"] for u in report["members"]}
    notes = []
    if report["edges"]:
        top = report["edges"][0]
        notes.append(f"本期互动最突出的组合：{names[top['source']]} × {names[top['target']]}，"
                     f"共 {top['events']} 次明确互动，分布在 {top['days']} 天。")
        stable = next((e for e in report["edges"] if e["label"] == "稳定聊天搭子"), None)
        if stable:
            notes.append(f"稳定聊天搭子：{names[stable['source']]} × {names[stable['target']]}，有多天双向互动。")
    else:
        notes.append("本期还没有足够的 @ 或引用回复证据。普通相邻发言不会自动算作互动。")
    if report["meta"]["messages"] < 30:
        notes.append("样本较少，先当作群聊互动速写，积累更多记录后再看趋势。")
    notes.append("连线表示已记录的互动，不代表现实亲密度；没有连线也不代表关系疏远。")
    report["notes"] = notes
    report["previous"] = previous["meta"]
    return report


def layout(nodes: list[dict], edges: list[dict]) -> dict[str, tuple[float, float]]:
    """Small deterministic force layout, normalized to a 1000×650 canvas."""
    n = len(nodes)
    if not n:
        return {}
    if n == 1:
        return {nodes[0]["id"]: (500.0, 325.0)}
    ids = [u["id"] for u in nodes]
    pos = {uid: [math.cos(i * math.tau / n) * 250, math.sin(i * math.tau / n) * 250] for i, uid in enumerate(ids)}
    for iteration in range(140):
        force = {uid: [0.0, 0.0] for uid in ids}
        for i, a in enumerate(ids):
            for b in ids[i + 1:]:
                dx, dy = pos[a][0] - pos[b][0], pos[a][1] - pos[b][1]
                dist = max(1.0, math.hypot(dx, dy))
                magnitude = 10000 / dist ** 2
                for axis, diff in enumerate((dx, dy)):
                    f = diff / dist * magnitude
                    force[a][axis] += f
                    force[b][axis] -= f
        for e in edges:
            a, b = e["source"], e["target"]
            if a not in pos or b not in pos:
                continue
            dx, dy = pos[b][0] - pos[a][0], pos[b][1] - pos[a][1]
            dist = max(1, math.hypot(dx, dy))
            magnitude = (dist - 160) * 0.012 * (1 + math.log1p(e["events"]) / 3)
            for axis, diff in enumerate((dx, dy)):
                f = diff / dist * magnitude
                force[a][axis] += f
                force[b][axis] -= f
        temperature = 5 * (1 - iteration / 160)
        for uid in ids:
            for axis in (0, 1):
                f = force[uid][axis] - pos[uid][axis] * 0.002
                pos[uid][axis] += max(-temperature, min(temperature, f))
    xs, ys = [p[0] for p in pos.values()], [p[1] for p in pos.values()]
    scale = min(820 / max(1, max(xs) - min(xs)), 460 / max(1, max(ys) - min(ys)))
    cx, cy = (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2
    return {uid: (round(500 + (p[0] - cx) * scale, 2), round(310 + (p[1] - cy) * scale, 2)) for uid, p in pos.items()}
