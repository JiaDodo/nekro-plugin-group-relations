"""Shared SVG graph and self-contained HTML screenshot report."""
from __future__ import annotations

import html
import math

from .analysis import date_label, layout


def esc(value) -> str:
    return html.escape(str(value), quote=True)


def graph_svg(report: dict) -> str:
    nodes, edges = report["graph"]["nodes"], report["graph"]["edges"]
    positions = layout(nodes, edges)
    parts = ['<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1000 650" role="img" aria-label="群聊互动关系网络">',
             '<defs><radialGradient id="halo"><stop stop-color="#83b7ff" stop-opacity=".12"/><stop offset="1" stop-color="#83b7ff" stop-opacity="0"/></radialGradient></defs>',
             '<circle cx="500" cy="310" r="310" fill="url(#halo)"/>', '<g id="graph-content">']
    for e in edges:
        x1, y1 = positions[e["source"]]
        x2, y2 = positions[e["target"]]
        color = "#8cbfff" if e["mutual"] >= .4 else "#657795"
        width = min(7, 1.5 + math.log1p(e["events"]))
        parts.append(f'<line class="edge" data-source="{esc(e["source"])}" data-target="{esc(e["target"])}" '
                     f'x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="{color}" stroke-width="{width:.2f}" '
                     f'stroke-opacity=".62"><title>{e["events"]} 次互动 · {e["days"]} 天</title></line>')
    for u in nodes:
        x, y = positions[u["id"]]
        radius = min(30, 19 + math.sqrt(u["sent"] + u["received"]))
        name = u["name"][:10] + ("…" if len(u["name"]) > 10 else "")
        parts.append(f'<g class="node" data-id="{esc(u["id"])}" transform="translate({x},{y})" tabindex="0" role="button" aria-label="{esc(u["name"])}">'
                     f'<circle r="{radius + 6:.1f}" fill="{u["color"]}" fill-opacity=".1"/>'
                     f'<circle r="{radius:.1f}" fill="#18253b" stroke="{u["color"]}" stroke-width="2"/>'
                     f'<text text-anchor="middle" dominant-baseline="central" fill="{u["color"]}" font-size="17" font-weight="700">{esc(u["name"][:1])}</text>'
                     f'<text text-anchor="middle" y="{radius + 23:.1f}" fill="#e4ebf7" font-size="15">{esc(name)}</text>'
                     f'<title>{esc(u["name"])} · {u["messages"]} 条发言 · {u["degree"]} 位互动成员</title></g>')
    if not nodes:
        parts.append('<text x="500" y="310" text-anchor="middle" fill="#93a4bf" font-size="22">暂无群聊互动数据</text>')
    parts.append('</g></svg>')
    return "".join(parts)


def text_report(report: dict, uid: str = "") -> str:
    names = {u["id"]: u["name"] for u in report["members"]}
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
    lines.extend(report["notes"])
    if report.get("ai_comment"):
        lines.append("AI 娱乐点评：" + report["ai_comment"])
    if report.get("warning"):
        lines.append(report["warning"])
    return "\n".join(lines)


def image_html(report: dict) -> str:
    m = report["meta"]
    names = {u["id"]: u["name"] for u in report["members"]}
    rankings = "".join(f'<div class="pair"><b class="rank">{i:02d}</b><div><strong>{esc(names[e["source"]])} <span>×</span> {esc(names[e["target"]])}</strong><small>{e["events"]} 次互动 · {e["days"]} 天 · {esc(e["label"])}</small></div><b>{e["score"]}<small>互动指数</small></b></div>' for i, e in enumerate(report["edges"][:6], 1))
    notes = "".join(f'<p>{esc(n)}</p>' for n in report["notes"])
    if report.get("ai_comment"):
        notes += f'<div class="ai"><b>AI 娱乐点评</b><p>{esc(report["ai_comment"])}</p></div>'
    if report.get("warning"):
        notes += f'<p class="warning">{esc(report["warning"])}</p>'
    return f'''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><style>
    *{{box-sizing:border-box}}body{{margin:0;background:#0b1220;color:#e5edf9;font-family:"Noto Sans CJK SC","Microsoft YaHei",sans-serif;width:1080px;padding:42px}}
    .eyebrow{{color:#8bbcff;font-size:14px;letter-spacing:3px}}h1{{font-size:38px;margin:10px 0}}.sub,small{{color:#8fa1bd}}.sub{{font-size:17px}}.stats{{display:flex;gap:15px;margin:28px 0}}
    .stat{{background:#142036;border:1px solid #26354d;border-radius:15px;padding:20px;flex:1}}.stat b{{font-size:30px;display:block}}.stat span{{font-size:14px;color:#91a4c0}}
    .panel{{background:#101b2d;border:1px solid #26354d;border-radius:20px;padding:25px;margin:20px 0}}h2{{font-size:20px;margin:0 0 10px}}svg{{display:block;width:100%}}.legend{{font-size:14px;color:#8fa1bd}}
    .pair{{display:flex;align-items:center;gap:18px;padding:17px 0;border-bottom:1px solid #25334a}}.rank{{font-size:24px;color:#6c88b2}}.pair div{{flex:1}}.pair strong{{font-size:18px}}.pair span{{color:#7185a6}}small{{display:block;font-size:13px;margin-top:6px}}.pair>b:last-child{{text-align:right;color:#a9cfff}}
    p{{line-height:1.9;font-size:16px;margin:12px 0}}.ai{{background:#1b2440;border-radius:12px;padding:18px;margin-top:20px}}.warning{{color:#eac38a}}footer{{font-size:13px;color:#7385a1;text-align:center;margin-top:26px}}
    </style><body><div class="eyebrow">NEKRO · GROUP RELATIONS</div><h1>{esc(report['channel_name'])}</h1><div class="sub">群聊互动关系报告 · 最近 {report['days']} 天 · {date_label(m['start'])} — {date_label(m['end'] - 1)}</div>
    <div class="stats">{''.join(f'<div class="stat"><b>{value}</b><span>{label}</span></div>' for label, value in [('记录消息',m['messages']),('参与成员',m['members']),('明确互动',m['interactions']),('互动组合',m['pairs'])])}</div>
    <section class="panel"><h2>本群互动星图</h2>{graph_svg(report)}<div class="legend">线越粗，互动次数越多；蓝色线表示双向互动较多。显示前 {m['shown_members']} 位成员，至少 {report['min_events']} 次互动才连线。</div></section>
    <section class="panel"><h2>聊天搭子榜</h2>{rankings or '<p>还没有明确互动记录。</p>'}</section><section class="panel"><h2>关系观察</h2>{notes}</section>
    <footer>仅依据本群已记录的 @ 与引用回复 · 互动指数不是关系概率 · 供娱乐</footer></body></html>'''
