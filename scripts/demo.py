"""Generate synthetic-only demo artifacts: python scripts/demo.py OUTPUT_DIR."""
import json
import random
import sys
import time
import types
from pathlib import Path

root = Path(__file__).resolve().parents[1]
package = types.ModuleType("group_relations")
package.__path__ = [str(root)]
sys.modules["group_relations"] = package
from group_relations.analysis import analyze, enrich
from group_relations.render import graph_svg, image_html

folder = Path(sys.argv[1])
folder.mkdir(parents=True, exist_ok=True)
names = ["小橘", "阿澈", "晚风", "栗子", "星河", "团子", "薄荷", "小满", "乌龙", "青禾", "木木", "南栀"]
rng = random.Random(42)
now = int(time.time())
rows = []
for i in range(620):
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
report["svg"] = graph_svg(report)
(folder / "demo.json").write_text(json.dumps(report, ensure_ascii=False), encoding="utf-8")
(folder / "demo-report.html").write_text(image_html(report), encoding="utf-8")
print("Synthetic demo generated")
