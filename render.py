"""Shared SVG graph and self-contained HTML screenshot report."""
from __future__ import annotations

import html
import math
import re
import unicodedata
from collections import Counter

from .analysis import date_label
from .identity import REFERENCE, member_names, plain_text
from .graph_layout import positions_for, route_link

REPORT_WIDTH = 1480


def esc(value) -> str:
    return html.escape(str(value), quote=True)


def overview(report: dict) -> dict:
    """A sparse, readable overview; every analyzed relationship remains in the cards."""
    members = {m["id"]: m for m in report["members"]}
    roles = report.get("context_analysis", {}).get("relationships", [])
    selected = []
    for role in roles:
        for uid in (role["source"], role["target"]):
            if uid in members and uid not in selected and len(selected) < 12:
                selected.append(uid)
    for member in report["graph"]["nodes"]:
        if member["id"] not in selected and len(selected) < 12:
            selected.append(member["id"])
    shown_roles = [r for r in roles if r["source"] in selected and r["target"] in selected][:12]
    used = {tuple(sorted((r["source"], r["target"]))) for r in shown_roles}
    degree = Counter(uid for pair in used for uid in pair)
    edges = []
    for edge in report["edges"]:
        a, b = edge["source"], edge["target"]
        if len(edges) + len(shown_roles) >= 14:
            break
        if a not in selected or b not in selected or tuple(sorted((a, b))) in used or edge["events"] < report.get("min_events", 2):
            continue
        if degree[a] >= 3 or degree[b] >= 3:
            continue
        edges.append(edge)
        degree[a] += 1
        degree[b] += 1
        used.add(tuple(sorted((a, b))))
    return {"nodes": [members[uid] for uid in selected], "edges": edges, "roles": shown_roles}


def avatar_uri(report: dict, uid: str) -> str:
    value = report.get("avatars", {}).get(uid, "")
    return value if re.fullmatch(r"data:image/(?:png|jpeg|gif|webp);base64,[A-Za-z0-9+/=]+", value) else ""


def person(report: dict, uid: str, names: dict[str, str], *, tiny=False) -> str:
    name = names.get(uid, "某位成员")
    avatar = avatar_uri(report, uid)
    face = f'<img src="{avatar}" alt="">' if avatar else f'<span class="face-fallback">{esc(name[:1])}</span>'
    return f'<span class="person {"tiny" if tiny else ""}">{face}<span class="person-name">{esc(name)}</span></span>'


def rich_text(text: str, report: dict, names: dict[str, str]) -> str:
    parts, previous = [], 0
    for match in REFERENCE.finditer(str(text)):
        if match.group(1) not in names:
            continue
        parts.append(esc(text[previous:match.start()]))
        parts.append(person(report, match.group(1), names, tiny=True))
        previous = match.end()
    parts.append(esc(str(text)[previous:]))
    return "".join(parts)


def avatar_member_ids(report: dict) -> list[str]:
    ids = [m["id"] for m in overview(report)["nodes"]]
    roles = report.get("context_analysis", {}).get("relationships", [])
    texts = [report.get("context_analysis", {}).get("summary", "")]
    for role in roles:
        ids.extend((role["source"], role["target"]))
        texts.append(role["reason"])
        for quote in role["evidence"]:
            ids.append(quote["sender"])
            texts.append(quote["text"])
    for edge in report["edges"][:4]:
        ids.extend((edge["source"], edge["target"]))
    known = {m["id"] for m in report["members"]}
    ids.extend(m.group(1) for text in texts for m in REFERENCE.finditer(text) if m.group(1) in known)
    return list(dict.fromkeys(ids))[:64]


def name_lines(name: str, width: int = 20) -> list[str]:
    lines, current, length = [], "", 0
    for char in name:
        size = 2 if unicodedata.east_asian_width(char) in "WF" else 1
        if length + size > width:
            lines.append(current)
            current, length = "", 0
            if len(lines) == 2:
                lines[-1] = lines[-1][:-1] + "…"
                return lines
        current += char
        length += size
    return (lines + [current])[:2]


def graph_svg(report: dict) -> str:
    graph = overview(report)
    nodes, edges = graph["nodes"], graph["edges"]
    names = member_names(report["members"])
    positions, height = positions_for(nodes, edges + graph["roles"])
    captions = {}
    name_boxes = []
    for node in nodes:
        uid = node['id']
        lines = name_lines(names[uid], width=18)
        width = 18 + max(sum(18 if unicodedata.east_asian_width(c) in 'WF' else 9 for c in line) for line in lines)
        caption_height = len(lines)*24+10
        captions[uid] = (lines, width, caption_height)
        x,y = positions[uid]
        name_boxes.append((x, y+36+caption_height/2, width, caption_height))
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1000 {height}" role="img" aria-label="群聊互动关系概览">',
             '<defs><radialGradient id="halo"><stop stop-color="#83b7ff" stop-opacity=".12"/><stop offset="1" stop-color="#83b7ff" stop-opacity="0"/></radialGradient></defs>',
             f'<ellipse cx="500" cy="{height/2}" rx="480" ry="{height/2}" fill="url(#halo)"/>', '<g id="graph-content">']
    for e in edges:
        x1, y1 = positions[e["source"]]
        x2, y2 = positions[e["target"]]
        color = "#8cbfff" if e["mutual"] >= .4 else "#657795"
        width = min(7, 1.5 + math.log1p(e["events"]))
        route = route_link((x1, y1), (x2, y2), positions, height, name_boxes=name_boxes)
        parts.append(f'<path class="edge" data-source="{esc(e["source"])}" data-target="{esc(e["target"])}" '
                     f'd="{route["path"]}" fill="none" stroke="{color}" stroke-width="{width:.2f}" '
                     f'stroke-opacity=".62"><title>{e["events"]} 次互动 · {e["days"]} 天</title></path>')
    label_positions = []
    for role in graph["roles"]:
        if role["source"] not in positions or role["target"] not in positions:
            continue
        x1, y1 = positions[role["source"]]
        x2, y2 = positions[role["target"]]
        label = role["label"]
        label_width = 20 + sum(18 if unicodedata.east_asian_width(c) in "WF" else 9 for c in label)
        half_width = label_width / 2
        route = route_link((x1, y1), (x2, y2), positions, height,
                           half_width=half_width, labels=label_positions, name_boxes=name_boxes)
        x, y = route["label"]
        label_positions.append((x, y, half_width))
        parts.append(f'<path class="relationship" d="{route["path"]}" fill="none" stroke="#eea5d3" stroke-opacity=".75" stroke-width="2" stroke-dasharray="5 6"/>'
                     f'<rect class="relation-label" x="{x-half_width}" y="{y-14}" width="{label_width}" height="27" rx="8" fill="#34203b"/>'
                     f'<text x="{x}" y="{y+5}" text-anchor="middle" fill="#ffc5e9" font-size="18">{esc(label)}</text>')
    for u in nodes:
        x, y = positions[u["id"]]
        radius = 30
        name = names[u["id"]]
        avatar = avatar_uri(report, u["id"])
        clip_id = f'avatar-{nodes.index(u)}'
        face = (f'<defs><clipPath id="{clip_id}"><circle r="{radius}"/></clipPath></defs>'
                f'<image x="-{radius}" y="-{radius}" width="{radius*2}" height="{radius*2}" href="{avatar}" clip-path="url(#{clip_id})" preserveAspectRatio="xMidYMid slice"/>') if avatar else (
                f'<text text-anchor="middle" dominant-baseline="central" fill="{u["color"]}" font-size="23" font-weight="700">{esc(name[:1])}</text>')
        label_lines, caption_width, caption_height = captions[u['id']]
        label_text = "".join(f'<text text-anchor="middle" y="{54+line*24}" fill="#e4ebf7" font-size="18">{esc(value)}</text>' for line, value in enumerate(label_lines))
        parts.append(f'<g class="node" data-id="{esc(u["id"])}" transform="translate({x},{y})" tabindex="0" role="button" aria-label="{esc(u["name"])}">'
                     f'<circle r="{radius + 6:.1f}" fill="{u["color"]}" fill-opacity=".1"/>'
                     f'<circle r="{radius:.1f}" fill="#18253b" stroke="{u["color"]}" stroke-width="2"/>'
                     f'{face}<rect class="member-name" x="{-caption_width/2}" y="36" width="{caption_width}" height="{caption_height}" rx="8" fill="#101b2d"/>{label_text}'
                     f'<title>{esc(u["name"])} · {u["messages"]} 条发言 · {u["degree"]} 位互动成员</title></g>')
    if not nodes:
        parts.append(f'<text x="500" y="{height/2}" text-anchor="middle" fill="#93a4bf" font-size="22">暂无群聊互动数据</text>')
    parts.append('</g></svg>')
    return "".join(parts)


def text_report(report: dict, uid: str = "") -> str:
    names = member_names(report["members"])
    m = report["meta"]
    lines = [f"{report['channel_name']} · 最近 {report['days']} 天群关系", f"{m['messages']} 条记录 / {m['members']} 位成员 / {m['interactions']} 次明确互动"]
    edges = report["edges"]
    if uid:
        member = next((u for u in report["members"] if u["id"] == uid), None)
        if not member:
            return "本期没有你的可用互动数据。可能尚未积累记录，或你已退出统计。"
        lines.append(f"{member['name']}：发言 {member['messages']} 条，主动互动 {member['sent']} 次，被互动 {member['received']} 次。")
        edges = [e for e in edges if uid in (e["source"], e["target"])]
    for i, e in enumerate(edges[:5], 1):
        lines.append(f"{i}. {names[e['source']]} × {names[e['target']]}：{e['events']} 次，{e['days']} 天，{e['label']}")
    context = report.get("context_analysis", {})
    roles = [r for r in context.get("relationships", []) if not uid or uid in (r["source"], r["target"])]
    if roles:
        lines.append("群聊关系剧本（前者扮演角色）：")
        for r in roles:
            lines.append(f"{names[r['source']]} → {names[r['target']]}：{r['label']} · {r['basis']}\n{plain_text(r['reason'], names)}")
            for quote in r["evidence"][:2]:
                lines.append(f"  {names.get(quote['sender'], quote['sender'])}：{plain_text(quote['text'], names)}")
    if context.get("summary") and not uid:
        lines.append("聊天赏析：" + plain_text(context["summary"], names))
    lines.extend(report["notes"])
    if report.get("ai_comment"):
        lines.append("AI 娱乐点评：" + report["ai_comment"])
    if report.get("warning"):
        lines.append(report["warning"])
    return "\n".join(lines)


def image_html(report: dict) -> str:
    m = report["meta"]
    names = member_names(report["members"])
    graph = overview(report)
    rankings = "".join(f'<div class="pair"><b class="rank">{i:02d}</b><div><strong>{esc(names[e["source"]])} <span>×</span> {esc(names[e["target"]])}</strong><small>{e["events"]} 次互动 · {e["days"]} 天</small></div><b>{e["score"]}</b></div>' for i, e in enumerate(report["edges"][:4], 1))
    notes = "".join(f'<p>{esc(n)}</p>' for n in report["notes"])
    context = report.get("context_analysis", {})
    roles = []
    for r in context.get("relationships", []):
        quotes = "".join(f'<blockquote>{person(report, q["sender"], names, tiny=True)}：{rich_text(q["text"], report, names)}</blockquote>' for q in r["evidence"][:1])
        roles.append(f'<article class="role"><div class="rolehead"><b class="tag">{esc(r["label"])}</b></div><div class="actors">{person(report, r["source"], names)}<span class="arrow">→</span>{person(report, r["target"], names)}</div><p>{rich_text(r["reason"], report, names)}</p>{quotes}<small>{esc(r["basis"])} · 共 {len(r["evidence"])} 条依据 · 原话节选</small></article>')
    context_info = f'抽样 {context.get("sampled", 0)} 条聊天' if "sampled" in context else ""
    if context.get("generated_at"):
        context_info += " · 赏析时间 " + date_label(context["generated_at"])
    if context.get("truncated") or context.get("sampled", 0) < context.get("available", 0):
        context_info += " · 部分样本"
    columns = 3 if len(roles) > 12 else 2
    theater = f'<div class="roles {"dense" if columns == 3 else ""}" style="grid-template-columns:repeat({columns},minmax(0,1fr))">' + "".join(roles) + f'</div><div class="summary"><p>{rich_text(context.get("summary", "本次未赏析聊天正文。"), report, names)}</p><small>{esc(context_info)}</small></div>'
    if report.get("ai_comment"):
        notes += f'<div class="ai"><b>AI 娱乐点评</b><p>{esc(report["ai_comment"])}</p></div>'
    if report.get("warning"):
        notes += f'<p class="warning">{esc(report["warning"])}</p>'
    return f'''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><style>
    *{{box-sizing:border-box}}body{{margin:0;background:#080f1b;color:#e5edf9;font-family:"Noto Sans CJK SC","Microsoft YaHei",sans-serif;width:{REPORT_WIDTH}px;padding:18px;display:grid;grid-template-columns:1fr 1fr;gap:16px}}
    .sheet{{min-width:0;background:#101b2d;border:1px solid #26354d;border-radius:18px;padding:22px;display:flex;flex-direction:column}}
    .eyebrow{{color:#8bbcff;font-size:12px;letter-spacing:2px}}h1{{font-size:24px;margin:8px 0 6px;overflow-wrap:anywhere;display:-webkit-box;-webkit-box-orient:vertical;-webkit-line-clamp:2;overflow:hidden}}.sub,small{{color:#8fa1bd}}.sub{{font-size:12px}}.stats{{display:flex;gap:8px;margin:16px 0 6px}}
    .stat{{background:#162239;border-radius:10px;padding:12px;flex:1}}.stat b{{font-size:23px;display:block}}.stat span{{font-size:11px;color:#91a4c0}}
    .panel{{border-top:1px solid #26354d;padding:10px 0 0;margin:10px 0 0}}h2{{font-size:16px;margin:0 0 8px}}svg{{display:block;width:100%;max-height:400px}}.legend{{font-size:11px;color:#8fa1bd;line-height:1.7}}
    .rankings{{display:grid;grid-template-columns:1fr 1fr;gap:8px}}.pair{{display:flex;align-items:center;gap:8px;padding:10px;background:#162239;border-radius:9px;min-width:0}}.rank{{font-size:17px;color:#6c88b2}}.pair div{{flex:1;min-width:0}}.pair strong{{display:block;font-size:12px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}}.pair span{{color:#7185a6}}small{{display:block;font-size:10px;margin-top:5px;line-height:1.5}}.pair>b:last-child{{font-size:13px;text-align:right;color:#a9cfff}}
    p{{line-height:1.7;font-size:13px;margin:6px 0}}.ai{{background:#1b2440;border-radius:10px;padding:10px;margin-top:10px}}.warning{{color:#eac38a}}footer{{font-size:10px;color:#7385a1;margin-top:auto;padding-top:16px;line-height:1.6}}
    .roles{{display:grid;gap:8px;margin-top:14px}}.role{{background:#172136;border:1px solid #2b354b;border-radius:10px;padding:8px;min-width:0}}.rolehead{{display:flex;align-items:center;gap:6px;line-height:1.4}}.rolehead strong{{flex:1;min-width:0;font-size:13px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}}.tag{{flex-shrink:0;color:#ffc5e9;background:#34203b;padding:2px 6px;border-radius:6px;font-size:11px}}blockquote{{margin:5px 0 3px;padding:4px 6px;border-left:2px solid #ba82a8;background:#111b2e;color:#aebed5;font-size:11px;line-height:1.5;overflow-wrap:anywhere;display:-webkit-box;-webkit-box-orient:vertical;-webkit-line-clamp:2;overflow:hidden}}.role p{{font-size:12px;line-height:1.5;margin:5px 0;overflow-wrap:anywhere;display:-webkit-box;-webkit-box-orient:vertical;-webkit-line-clamp:2;overflow:hidden;min-height:36px}}.role small{{font-size:9px;line-height:1.4;margin-top:3px}}.summary{{margin-top:14px;padding:12px;background:#1b2440;border-radius:10px}}.summary p{{margin:0}}.observations p{{font-size:11px;margin:5px 0}}
    .rolehead{{justify-content:space-between}}.reference{{font-size:10px;color:#94acd0;letter-spacing:1px}}.actors{{display:flex;align-items:center;gap:5px;margin:7px 0;min-height:30px}}.arrow{{color:#7d95b8;flex-shrink:0}}.actors>.person{{flex:1;min-width:0}}.person{{display:inline-flex;vertical-align:middle;align-items:center;gap:5px;max-width:100%;color:#dceaff}}.person img,.face-fallback{{width:28px;height:28px;flex-shrink:0;border-radius:50%;object-fit:cover;background:#2a3d5b}}.face-fallback{{display:inline-flex;align-items:center;justify-content:center;color:#b4d3ff;font-size:13px}}.person-name{{min-width:0;font-size:12px;font-weight:600;overflow:hidden;display:-webkit-box;-webkit-box-orient:vertical;-webkit-line-clamp:2;overflow-wrap:anywhere;line-height:1.35}}.tiny{{gap:3px;max-width:125px;background:#23334d;border-radius:12px;padding:1px 4px 1px 1px;margin:0 1px}}.tiny img,.tiny .face-fallback{{width:16px;height:16px;font-size:10px}}.tiny .person-name{{display:block;white-space:nowrap;text-overflow:ellipsis;font-size:11px;font-weight:500}}.role p{{-webkit-line-clamp:3;min-height:54px}}.summary p{{font-size:12px}}
    .role{{height:166px;display:flex;flex-direction:column;overflow:hidden}}.rolehead{{height:18px;flex-shrink:0}}.actors{{margin:5px 0;min-height:30px;flex-shrink:0}}.role p{{-webkit-line-clamp:2;min-height:0;height:36px;flex-shrink:0;margin:4px 0}}.role blockquote{{max-height:36px;flex-shrink:0;line-height:1.4;margin:3px 0}}.role small{{margin-top:auto}}
    .dense .role{{height:156px;padding:6px}}.dense .person img,.dense .person>.face-fallback{{width:22px;height:22px}}.dense .tiny img,.dense .tiny>.face-fallback{{width:16px;height:16px}}.dense .actors{{margin:3px 0}}.summary p{{display:-webkit-box;-webkit-box-orient:vertical;-webkit-line-clamp:4;overflow:hidden}}
    .actors{{height:30px;margin:2px 0}}.person-name{{line-height:1.25}}.role p{{margin:2px 0}}.role blockquote{{height:40px;max-height:40px;padding:2px 4px;margin:1px 0;line-height:18px}}.role p .tiny,.role blockquote .tiny{{height:16px;vertical-align:-3px}}.role p .tiny img,.role blockquote .tiny img,.role p .tiny .face-fallback,.role blockquote .tiny .face-fallback{{width:14px;height:14px}}.dense .actors{{margin:2px 0}}.dense .role p{{height:34px;line-height:17px}}.dense .role blockquote{{height:36px;max-height:36px;line-height:16px}}
    </style><body><section class="sheet"><div class="eyebrow">01 / 群关系图</div><h1>{esc(report['channel_name'])}</h1><div class="sub">最近 {report['days']} 天 · {date_label(m['start'])} — {date_label(m['end'] - 1)}</div>
    <div class="stats">{''.join(f'<div class="stat"><b>{value}</b><span>{label}</span></div>' for label, value in [('记录消息',m['messages']),('参与成员',m['members']),('明确互动',m['interactions']),('互动组合',m['pairs'])])}</div>
    <section class="panel">{graph_svg(report)}<div class="legend">蓝线：主要互动 · 粉色虚线：赏析关系，角色方向与原话见右侧<br>概览 {len(graph['nodes'])} / {m['members']} 位成员 · {len(graph['edges']) + len(graph['roles'])} 条主要连线；全部 {len(roles)} 条赏析见右侧。</div></section>
    <section class="panel"><h2>聊天搭子榜</h2><div class="rankings">{rankings or '<p>还没有明确互动记录。</p>'}</div></section><section class="panel observations">{notes}</section>
    <footer>互动指数用于排序 · 根据本群已记录消息生成</footer></section>
    <section class="sheet"><div class="eyebrow">02 / 聊天赏析</div><h1>群聊关系</h1><div class="sub">前者 → 后者：前者扮演标签身份 · 最近 {report['days']} 天</div>{theater}
    <footer>原话为节选 · 角色按群聊语境赏析 · 供娱乐</footer></section></body></html>'''
