"""Generate synthetic-only demo artifacts: python scripts/demo.py OUTPUT_DIR."""
import json
import random
import sys
import time
import types
import base64
import struct
import zlib
from pathlib import Path

root = Path(__file__).resolve().parents[1]
package = types.ModuleType("group_relations")
package.__path__ = [str(root)]
sys.modules["group_relations"] = package
from group_relations.analysis import analyze, enrich
from group_relations.render import graph_svg, image_html

folder = Path(sys.argv[1])
folder.mkdir(parents=True, exist_ok=True)
names = ["小橘", "阿澈（今晚负责救场）", "晚风", "栗子", "星河", "团子", "薄荷", "小满", "乌龙", "青禾", "木木", "南栀"]
names += [f"茶话会成员{i:02d}" for i in range(12, 54)]
rng = random.Random(42)
now = int(time.time())
rows = []
for i in range(3824):
    person = rng.randrange(len(names))
    target = (person + rng.choice([1, 1, 2, 4])) % len(names)
    rows.append({"id": f"demo-{i}", "sender": f"demo-{person}", "name": names[person],
                 "ts": now - rng.randrange(14 * 86400), "mentions": [f"demo-{target}"] if i % 3 else [],
                 "reply": "", "reply_sender": ""})
report = enrich(analyze(rows, now - 7 * 86400, now + 1), analyze(rows, now - 14 * 86400, now - 7 * 86400))
report.update(channel_name="星河茶话会 · 模拟数据", chat_key="demo", days=7, min_events=2,
              generated_at=now, enabled=True, ai_comment="", warning="本页全部使用生成的模拟数据。", excluded_count=0)
report["context_analysis"] = {
    "sampled": 160, "available": 305, "generated_at": now,
    "summary": "本群像个临时剧组：小橘缺救援时现场认爹，团子上班式认领主仆剧本，另一边情妇名额还得靠抽卡竞争。角色喊得很满，接梗也很熟练。",
    "relationships": [
        {"source": "demo-1", "target": "demo-0", "label": "父亲", "basis": "双向接梗", "reason": "小橘遇到难题先喊爸爸，阿澈顺势认儿子：救援还没到，辈分先结算了。", "evidence": [
            {"sender": "demo-0", "ts": now - 3600, "text": "@阿澈 爸爸救救，这题怎么做啊"},
            {"sender": "demo-1", "ts": now - 3590, "text": "儿子别急，截图发我，爹来看看"}]},
        {"source": "demo-4", "target": "demo-5", "label": "主人", "basis": "双向接梗", "reason": "团子主动喊主人，星河立刻派活：一句称呼，直接接上了一份群内差事。", "evidence": [
            {"sender": "demo-5", "ts": now - 2400, "text": "@星河 主人，今天有什么吩咐"},
            {"sender": "demo-4", "ts": now - 2390, "text": "乖仆人，把昨晚那份攻略交出来"}]},
        {"source": "demo-7", "target": "demo-6", "label": "情妇", "basis": "双向接梗", "reason": "两人当场约好群聊剧本，情妇角色还带抽卡待遇；这是角色招募现场，双方都在演。", "evidence": [
            {"sender": "demo-6", "ts": now - 1200, "text": "@小满 来演我的情妇，抽到金卡就给你加戏"},
            {"sender": "demo-7", "ts": now - 1190, "text": "这个剧本我接了，先把金卡交出来"}]},
    ],
}

# Synthetic geometric faces: no real member photos or chat records in the demo.
def demo_avatar(index):
    size = 64
    color = ((index * 61 + 68) % 180 + 40, (index * 29 + 90) % 180 + 40, (index * 41 + 70) % 180 + 40)
    pixels = bytearray()
    for y in range(size):
        pixels.append(0)
        for x in range(size):
            eye = ((x-22)**2 + (y-25)**2 < 7 or (x-42)**2 + (y-25)**2 < 7)
            smile = 22 <= x <= 42 and abs(y-(42-((x-32)/5)**2)) < 1.5
            pixels.extend((240, 245, 255) if eye or smile else color)
    def chunk(kind, data):
        return struct.pack('>I', len(data)) + kind + data + struct.pack('>I', zlib.crc32(kind + data))
    png = b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', size, size, 8, 2, 0, 0, 0)) + chunk(b'IDAT', zlib.compress(bytes(pixels))) + chunk(b'IEND', b'')
    return 'data:image/png;base64,' + base64.b64encode(png).decode()

report["avatars"] = {f"demo-{i}": demo_avatar(i) for i in range(len(names))}
labels = ["损友", "恋人", "母亲", "金主", "兄弟", "夫妻", "仆人", "工具人", "欢喜冤家"]
for i, label in enumerate(labels, 3):
    a, b = f"demo-{i}", f"demo-{(i+3)%12}"
    report["context_analysis"]["relationships"].append({
        "source": a, "target": b, "label": label, "basis": "双向接梗",
        "reason": f"[{a}]主动认领{label}角色，[{b}]顺着接话，两人的日常拌嘴又多了一个新剧本。",
        "evidence": [{"sender": a, "ts": now-500, "text": f"[{b}] 今天这个{label}的剧本我接了，你记得配合一下"},
                     {"sender": b, "ts": now-490, "text": "好好好，先把今天的任务完成再说"}]})
report["context_analysis"]["summary"] = "[demo-0]现场认爹，[demo-1]接得顺手；[demo-5]和[demo-4]一来一回认领主仆剧本，[demo-7]的情妇角色还得靠抽卡争取。称呼大胆，接话熟练，群里每天都有新剧情。"
report["svg"] = graph_svg(report)
(folder / "demo.json").write_text(json.dumps(report, ensure_ascii=False), encoding="utf-8")
(folder / "demo-report.html").write_text(image_html(report), encoding="utf-8")
print("Synthetic demo generated")
