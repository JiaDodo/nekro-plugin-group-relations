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
report["svg"] = graph_svg(report)
(folder / "demo.json").write_text(json.dumps(report, ensure_ascii=False), encoding="utf-8")
(folder / "demo-report.html").write_text(image_html(report), encoding="utf-8")
print("Synthetic demo generated")
