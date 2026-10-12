import tempfile
import time
import unittest
from pathlib import Path

import bootstrap
from group_relations.analysis import analyze, enrich, layout
from group_relations.render import graph_svg, image_html
from group_relations.repository import Repository


def row(id, sender="a", ts=100, mentions=None, reply="", reply_sender="", name=""):
    return {"id": str(id), "sender": sender, "name": name or sender, "ts": ts,
            "mentions": mentions or [], "reply": reply, "reply_sender": reply_sender}


class AnalysisTests(unittest.TestCase):
    def test_adjacent_messages_are_not_edges(self):
        result = analyze([row(1), row(2, "b", 101)], 0, 200)
        self.assertEqual(result["edges"], [])

    def test_duplicate_at_and_reply_count_once(self):
        result = analyze([row(1, "b"), row(2, mentions=["b", "b"], reply="1")], 0, 200)
        edge = result["edges"][0]
        self.assertEqual((edge["events"], edge["mentions"], edge["replies"]), (1, 0, 1))

    def test_ignore_self_everyone_bot_and_excluded(self):
        result = analyze([row(1, mentions=["a", "all", "0", "bot", "hidden"])], 0, 200, excluded={"bot", "hidden"})
        self.assertEqual(result["edges"], [])

    def test_external_reference_target_is_used(self):
        result = analyze([row(1, reply="old", reply_sender="b")], 0, 200)
        self.assertEqual(result["edges"][0]["replies"], 1)

    def test_mutual_multi_day_label(self):
        rows = [row(i, "a" if i % 2 == 0 else "b", i * 86400 + 100,
                    ["b" if i % 2 == 0 else "a"]) for i in range(6)]
        result = analyze(rows, 0, 600000)
        self.assertEqual(result["edges"][0]["label"], "稳定聊天搭子")
        self.assertEqual(result["edges"][0]["mutual"], 1)

    def test_daily_cap_keeps_actual_counts(self):
        rows = [row(i, mentions=["b"]) for i in range(100)]
        capped = analyze(rows, 0, 200, daily_cap=2)
        unlimited = analyze(rows, 0, 200, daily_cap=200)
        self.assertEqual(capped["edges"][0]["events"], 100)
        self.assertLess(capped["edges"][0]["score"], unlimited["edges"][0]["score"])

    def test_period_end_exclusive_and_trend(self):
        rows = [row(1, ts=99, mentions=["b"]), row(2, ts=100, mentions=["b"]), row(3, ts=200, mentions=["b"])]
        result = enrich(analyze(rows, 100, 200), analyze(rows, 0, 100))
        self.assertEqual(result["meta"]["messages"], 1)
        self.assertEqual(result["edges"][0]["change"], 0)

    def test_graph_limit_does_not_change_totals(self):
        rows = [row(i, str(i), mentions=["target"]) for i in range(8)]
        result = analyze(rows, 0, 200, limit=2, min_events=1)
        self.assertEqual(result["meta"]["members"], 9)
        self.assertEqual(len(result["graph"]["nodes"]), 2)
        ids = {n["id"] for n in result["graph"]["nodes"]}
        self.assertTrue(all(e["source"] in ids and e["target"] in ids for e in result["graph"]["edges"]))

    def test_layout_is_deterministic_and_in_bounds(self):
        report = analyze([row(i, str(i), mentions=["b"]) for i in range(20)], 0, 200)
        positions = layout(report["graph"]["nodes"], report["graph"]["edges"])
        self.assertEqual(positions, layout(report["graph"]["nodes"], report["graph"]["edges"]))
        self.assertTrue(all(60 <= x <= 940 and 60 <= y <= 590 for x, y in positions.values()))

    def test_svg_escapes_untrusted_nicknames(self):
        report = enrich(analyze([row(1, name='<script>alert("x")</script>', mentions=["b"])], 0, 200), analyze([], -200, 0))
        report.update(channel_name="<img onerror=x>", days=7, min_events=1)
        self.assertNotIn("<script>", graph_svg(report))
        self.assertNotIn("<img onerror", image_html(report))
        self.assertIn("&lt;", graph_svg(report))


class StorageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.repo = Repository(Path(self.temp.name) / "test.sqlite3")

    def tearDown(self):
        self.temp.cleanup()

    def test_group_scoping_and_idempotent_import(self):
        self.repo.insert("g1", "群一", [row(1), row(1)])
        self.repo.insert("g2", "群二", [row(1, "b")])
        self.assertEqual(len(self.repo.rows("g1", 0, 200)), 1)
        self.assertEqual(self.repo.rows("g2", 0, 200)[0]["sender"], "b")

    def test_sync_repairs_reply_resolution(self):
        self.repo.insert("g", "g", [row(1, reply="old")])
        self.repo.insert("g", "g", [row(1, reply="old", reply_sender="b")])
        self.assertEqual(self.repo.rows("g", 0, 200)[0]["reply_sender"], "b")

    def test_optout_removes_person_and_incoming_mentions(self):
        self.repo.insert("g", "g", [row(1), row(2, "b", mentions=["a"], reply_sender="a")])
        self.repo.opt_out("g", "a", True)
        self.repo.insert("g", "g", [row(3)])
        rows = self.repo.rows("g", 0, 200)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["mentions"], [])
        self.assertEqual(rows[0]["reply_sender"], "")
        self.assertIn("a", self.repo.excluded("g"))

    def test_pause_and_clear_prevent_reimport(self):
        self.repo.insert("g", "g", [row(1)])
        self.repo.set_enabled("g", False)
        self.repo.insert("g", "g", [row(2)])
        self.assertEqual(len(self.repo.rows("g", 0, 200)), 1)
        self.repo.set_enabled("g", True)
        self.repo.clear("g")
        self.repo.insert("g", "g", [row(1), row(3, ts=int(time.time()) + 1)])
        self.assertEqual([r["id"] for r in self.repo.rows("g", 0, 2**40)], ["3"])


if __name__ == "__main__":
    unittest.main()
