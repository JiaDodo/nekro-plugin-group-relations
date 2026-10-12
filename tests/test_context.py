import json
import unittest
from types import SimpleNamespace

import bootstrap
from group_relations.context import LABELS, parse_relationships, sample_context
from group_relations.render import image_html, text_report
from group_relations.analysis import analyze, enrich


def row(i, sender="a", text="你好", mentions=None, ts=None):
    return {"id": str(i), "sender": sender, "name": {"a": "小甲", "b": "小乙", "hidden": "隐身成员"}.get(sender, sender),
            "text": text, "ts": ts if ts is not None else int(i), "mentions": mentions or [], "reply_sender": "", "reply": ""}


MEMBERS = [{"id": "a", "name": "小甲"}, {"id": "b", "name": "小乙"}]


class ContextTests(unittest.TestCase):
    def context(self):
        return sample_context([row(1, "a", "爸爸帮帮我", ["b"]), row(2, "b", "儿子，来了")], MEMBERS, set())

    def parse(self, context=None, **changes):
        role = {"source": "U2", "target": "U1", "label": "父亲", "reason": "接了认爹梗", "evidence_ids": ["M1", "M2"], **changes}
        return parse_relationships(json.dumps({"relationships": [role], "summary": "大型认亲现场"}), context or self.context(), LABELS)

    def test_direction_evidence_and_reciprocity_preserved(self):
        role = self.parse()["relationships"][0]
        self.assertEqual((role["source"], role["target"], role["label"]), ("b", "a", "父亲"))
        self.assertEqual(role["basis"], "双向接梗")
        self.assertEqual(role["evidence"][0]["text"], "爸爸帮帮我")

    def test_fabricated_member_or_message_rejected(self):
        self.assertEqual(self.parse(source="U999")["relationships"], [])
        self.assertEqual(self.parse(evidence_ids=["M999"])["relationships"], [])

    def test_missing_role_language_rejected(self):
        for label in ("情妇", "恋人", "主人"):
            self.assertEqual(self.parse(label=label)["relationships"], [])

    def test_explicit_spicy_role_accepted_as_chat_role(self):
        context = sample_context([row(1, "a", "这局你当我的情妇，演一下", ["b"]), row(2, "b", "好，剧本给我")], MEMBERS, set())
        self.assertEqual(self.parse(context, label="情妇")["relationships"][0]["label"], "情妇")

    def test_unrelated_single_party_quote_rejected(self):
        context = sample_context([row(1, "a", "我爸爸叫我回家吃饭"), row(2, "b", "天气很好", ts=900)], MEMBERS, set())
        self.assertEqual(self.parse(context)["relationships"], [])

    def test_one_sided_targeted_quote_marked(self):
        self.assertEqual(self.parse(evidence_ids=["M1"])["relationships"][0]["basis"], "单方喊话")

    def test_inverse_role_for_same_pair_is_deduplicated(self):
        roles = [{"source": "U2", "target": "U1", "label": "父亲", "evidence_ids": ["M1", "M2"]},
                 {"source": "U1", "target": "U2", "label": "儿子", "evidence_ids": ["M1", "M2"]}]
        result = parse_relationships(json.dumps({"relationships": roles}), self.context(), LABELS)
        self.assertEqual(len(result["relationships"]), 1)

    def test_same_group_reply_resolves_author_for_evidence(self):
        rows = [row(1, "a", "爸爸帮帮我"), {**row(2, "b", "儿子来了"), "reply": "1"}]
        context = sample_context(rows, MEMBERS, set())
        self.assertEqual(context["messages"][1]["reply_to"], "U1")
        self.assertEqual(len(self.parse(context)["relationships"]), 1)

    def test_unknown_label_and_bad_output_rejected(self):
        self.assertEqual(self.parse(label="真实出轨对象")["relationships"], [])
        with self.assertRaises(ValueError):
            parse_relationships("[]", self.context(), LABELS)

    def test_provider_preface_and_markdown_json_supported(self):
        role = {"source": "U2", "target": "U1", "label": "父亲", "evidence_ids": ["M1", "M2"]}
        raw = '以下是赏析结果：\n```json\n' + json.dumps({"relationships": [role]}) + '\n```'
        self.assertEqual(len(parse_relationships(raw, self.context(), LABELS)["relationships"]), 1)

    def test_sampling_cap_timeline_and_length(self):
        rows = [row(i, text="主人来啦" if i % 10 == 0 else "你好" * 200) for i in range(1000)]
        context = sample_context(rows, MEMBERS, set(), cap=40, chars=80)
        self.assertEqual(context["sampled"], 40)
        self.assertEqual((context["messages"][0]["time"], context["messages"][-1]["time"]), (0, 999))
        self.assertTrue(all(len(m["text"]) <= 80 for m in context["messages"]))

    def test_excluded_author_targets_and_name_removed(self):
        rows = [row(1, "hidden", "秘密"), row(2, text="隐身成员今天来了吗"), row(3, mentions=["hidden"]), row(4, text="安全正文")]
        result = sample_context(rows, MEMBERS, {"hidden"})
        self.assertEqual([m["text"] for m in result["messages"]], ["安全正文"])

    def test_model_and_quotes_html_escaped(self):
        context = self.context()
        context["lookup"]["M1"]["text"] = '<script>爸爸</script>'
        roles = self.parse(context, reason='<img src=x onerror=x>')
        report = enrich(analyze([row(1, mentions=["b"]), row(2, "b")], 0, 10), analyze([], -10, 0))
        report.update(channel_name="测试群", days=7, min_events=1, context_analysis=roles)
        html = image_html(report)
        self.assertNotIn("<script>", html)
        self.assertNotIn("<img src=x", html)
        self.assertIn("&lt;script&gt;", html)
        self.assertIn("：父亲 ·", text_report(report))
        self.assertIn('class="tag">父亲</b>', html)
        self.assertNotIn("父亲梗", html)


class CacheTests(unittest.IsolatedAsyncioTestCase):
    def service(self):
        from group_relations.service import RelationsService
        service = object.__new__(RelationsService)
        service.config = lambda: SimpleNamespace(ENABLE_CONTEXT_ANALYSIS=True, MODEL_GROUP="", MAX_CONTEXT_MESSAGES=20,
            CONTEXT_MESSAGE_CHARS=80, MAX_RELATIONSHIPS=3, RELATION_LABELS=LABELS)
        service.context_cache, service.context_locks, service.revisions, service.cache = {}, {}, {}, {}
        return service

    async def test_clear_during_model_call_discards_pending_result(self):
        service = self.service()
        async def fake(report):
            service.invalidate("group", context=True)
            return {"relationships": [], "summary": "stale"}
        service._interpret = fake
        with self.assertRaises(ValueError):
            await service.interpret({"chat_key": "group", "days": 7, "enabled": True})
        self.assertEqual(service.context_cache, {})

    async def test_context_cached_until_refresh(self):
        service = self.service()
        calls = []
        async def fake(report):
            calls.append(1)
            return {"relationships": [], "summary": "fresh"}
        service._interpret = fake
        report = {"chat_key": "group", "days": 7, "enabled": True}
        await service.interpret(report)
        service.invalidate("group")
        await service.interpret(report)
        self.assertEqual(len(calls), 1)
        await service.interpret(report, refresh=True)
        self.assertEqual(len(calls), 2)
