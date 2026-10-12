"""Reproducible, entirely synthetic reports for visual acceptance checks."""
import base64
import struct
import zlib

from group_relations.analysis import analyze, enrich

CASES = [
    ("01-five", "5人 · 交叉关系", 5, "small", 6),
    ("02-twelve", "12人 · 普通关系网", 12, "normal", 12),
    ("03-fifty-four", "54人 · 密集群聊", 54, "dense", 20),
    ("04-hub", "12人 · 单人中心", 12, "hub", 11),
    ("05-islands", "8人 · 分组与重名", 8, "islands", 4),
    ("06-empty", "无互动记录", 0, "empty", 0),
]


def avatar(index):
    size = 48
    color = ((index*61+68)%180+40, (index*29+90)%180+40, (index*41+70)%180+40)
    pixels = bytearray()
    for y in range(size):
        pixels.append(0)
        for x in range(size):
            face = ((x-16)**2+(y-18)**2 < 5 or (x-32)**2+(y-18)**2 < 5 or
                    (16 <= x <= 32 and abs(y-(32-((x-24)/4)**2)) < 1.3))
            pixels.extend((245, 248, 255) if face else color)
    def chunk(kind, data):
        return struct.pack('>I', len(data))+kind+data+struct.pack('>I', zlib.crc32(kind+data))
    png = b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR', struct.pack('>IIBBBBB', size, size, 8, 2, 0, 0, 0))
    png += chunk(b'IDAT', zlib.compress(pixels))+chunk(b'IEND', b'')
    return 'data:image/png;base64,'+base64.b64encode(png).decode()


def make_report(count, kind, role_count):
    now = 1791792000
    names = ["小橘", "阿澈（今天也要认真接话）", "晚风", "栗子", "星河", "团子", "薄荷", "小满", "乌龙", "青禾", "木木", "南栀"]
    names += [f"模拟群友{i:02d}" for i in range(12, count)]
    if kind == "islands":
        names[0] = names[1] = "同名群友"
    if kind == "small":
        pairs = [(0,1), (0,2), (0,3), (4,0), (3,1), (4,1)]
    elif kind == "hub":
        pairs = [(0, i) for i in range(1, count)]
    elif kind == "islands":
        pairs = [(i, i+1) for i in range(0, count, 2)]
    else:
        pairs = [(i, (i+1)%count) for i in range(count)] if count else []
        pairs += [(i, (i+4)%count) for i in range(count)] if count > 6 else []
    rows = []
    for i in range(count):
        rows.append(dict(id=f'hello-{i}', sender=f'demo-{i}', name=names[i], ts=now-300,
                         mentions=[], reply='', reply_sender=''))
    for i, (a, b) in enumerate(pairs):
        for j in range(4):
            for sender, target in ((a,b),(b,a)):
                rows.append(dict(id=f'{i}-{j}-{sender}', sender=f'demo-{sender}', name=names[sender],
                                 ts=now-86400*(j%3)-i*30, mentions=[f'demo-{target}'], reply='', reply_sender=''))
    report = enrich(analyze(rows, now-7*86400, now+1), analyze([], now-14*86400, now-7*86400))
    report.update(channel_name="模拟群聊 · 连线排版测试", days=7, min_events=2, chat_key="demo",
                  enabled=True, ai_comment="", warning="全部为虚构成员与对话，不调用聊天模型。")
    labels = ["父亲", "母亲", "欢喜冤家", "损友", "朋友", "恋人", "主人", "仆人", "工具人", "金主", "夫妻", "兄弟"]
    roles = []
    for i, (a,b) in enumerate(pairs[:role_count]):
        source, target = f'demo-{a}', f'demo-{b}'
        roles.append(dict(source=source, target=target, label=labels[i%len(labels)], basis="双向接梗",
                          reason=f"[{source}]主动认领角色，[{target}]顺着接话，两人约好一起演这段群聊剧本。",
                          evidence=[dict(sender=source, ts=now-30, text=f"[{target}]这段剧情我接了，你来配合一下"),
                                    dict(sender=target, ts=now-20, text="好，先说好今天谁请喝茶")]))
    report['context_analysis'] = dict(relationships=roles, summary="虚构成员相互接话，关系名称仅用于检查连线、标签、头像与长昵称排版。",
                                      sampled=len(rows), available=len(rows), generated_at=now)
    report['avatars'] = {f'demo-{i}': avatar(i) for i in range(count)}
    return report
