import json
import os
import tempfile
import time
import unittest
from pathlib import Path

import bootstrap
import httpx
from group_relations.avatars import AvatarCache, MAX_BYTES, TTL, data_uri
from group_relations.identity import canonical_text, member_names, plain_text
from group_relations.context import LABELS, parse_relationships, sample_context
from group_relations.analysis import analyze, enrich
from group_relations.render import avatar_uri, graph_svg, image_html, overview, text_report


class IdentityTests(unittest.TestCase):
    def test_alias_boundaries_and_transport_mentions(self):
        aliases = {"U1": "10001", "U10": "10010", "U13": "10013"}
        text = 'U1喊U10爸爸，[@id:U13;nickname:伪造昵称]笑了；U999、URL_U1'
        result = canonical_text(text, aliases, set(aliases.values()))
        self.assertEqual(plain_text(result, {"10001": "甲", "10010": "乙", "10013": "丙"}),
                         '甲喊乙爸爸，丙笑了；某位成员、URL_U1')

    def test_all_fields_restore_identity_and_keep_source_quote(self):
        members = [{"id": "10001", "name": "甲"}, {"id": "10002", "name": "乙"}]
        rows = [{"id": "1", "sender": "10001", "name": "甲", "ts": 1,
                 "text": '[@id:10002;nickname:旧名字]爸爸救我', "mentions": ["10002"], "reply": "", "reply_sender": ""},
                {"id": "2", "sender": "10002", "name": "乙", "ts": 2, "text": "儿子来了",
                 "mentions": ["10001"], "reply": "", "reply_sender": ""}]
        context = sample_context(rows, members, set())
        self.assertEqual(context["lookup"]["M1"]["text"], rows[0]["text"])
        raw = {"summary": "U1认爹，U2在M2里接话", "relationships": [{"source": "U2", "target": "U1",
               "label": "父亲", "reason": "U1喊U2爸爸，见M1", "evidence_ids": ["M1", "M2"]}]}
        report = enrich(analyze(rows, 0, 10), analyze([], -10, 0))
        report.update(channel_name="测试", days=7, min_events=1,
                      context_analysis=parse_relationships(json.dumps(raw), context, LABELS))
        for result in (image_html(report), text_report(report)):
            self.assertNotRegex(result, r'[UM]\d+|\[@id:|\[1000[12]\]')
            self.assertNotIn("旧名字", result)
        self.assertIn("甲喊乙爸爸", text_report(report))

    def test_duplicate_nicknames_are_distinguishable(self):
        names = member_names([{"id": "12345", "name": "同名"}, {"id": "67890", "name": "同名"}])
        self.assertNotEqual(names["12345"], names["67890"])

    def test_dense_group_keeps_full_cards_and_sparse_overview(self):
        rows = [{"id": f"{a}-{b}", "sender": str(a), "name": f"群友{a}", "ts": a + b,
                 "mentions": [str(b)], "reply": "", "reply_sender": ""}
                for a in range(54) for b in range(54) if a != b]
        report = enrich(analyze(rows, 0, 200, limit=40), analyze([], -200, 0))
        roles = [{"source": str(i % 10), "target": str((i + 1) % 10), "label": "朋友",
                  "reason": f"[{i % 10}]聊天", "basis": "双向接梗", "evidence": []} for i in range(20)]
        report.update(channel_name="密集群", days=7, min_events=1,
                      context_analysis={"relationships": roles, "summary": ""})
        graph = overview(report)
        self.assertLessEqual(len(graph["nodes"]), 12)
        self.assertLessEqual(len(graph["edges"]) + len(graph["roles"]), 14)
        self.assertEqual(image_html(report).count('<article class="role">'), 20)
        self.assertEqual(graph_svg(report).count('class="node"'), len(graph["nodes"]))
        report["avatars"] = {"0": "https://evil.invalid/avatar.svg"}
        self.assertEqual(avatar_uri(report, "0"), "")
        self.assertNotIn("evil.invalid", image_html(report))


class AvatarTests(unittest.IsolatedAsyncioTestCase):
    async def test_cache_and_failed_refresh_use_embedded_image(self):
        with tempfile.TemporaryDirectory() as folder:
            cache = AvatarCache(Path(folder))
            calls = []
            png = b'\x89PNG\r\n\x1a\nmock'
            def fetch(request):
                calls.append(request.url)
                return httpx.Response(200, content=png) if len(calls) == 1 else httpx.Response(503)
            async with httpx.AsyncClient(transport=httpx.MockTransport(fetch)) as client:
                first = await cache.get("12345", client)
                self.assertEqual(first, data_uri(png))
                self.assertEqual(await cache.get("12345", client), first)
                self.assertEqual(len(calls), 1)
                path = Path(folder) / "12345.bin"
                os.utime(path, (time.time() - TTL - 1,) * 2)
                self.assertEqual(await cache.get("12345", client), first)
                self.assertEqual(await cache.get("12345", client), first)
                self.assertEqual(len(calls), 2)
                self.assertEqual(await cache.get("../../secret", client), "")
            cache.purge()
            self.assertFalse(list(Path(folder).glob("*.bin")))

    async def test_invalid_or_oversized_avatar_falls_back(self):
        for content in (b'<html>error</html>', b'\x89PNG\r\n\x1a\n' + b'x' * MAX_BYTES):
            with tempfile.TemporaryDirectory() as folder:
                cache = AvatarCache(Path(folder))
                async with httpx.AsyncClient(transport=httpx.MockTransport(lambda req: httpx.Response(200, content=content))) as client:
                    self.assertEqual(await cache.get("12345", client), "")
                self.assertFalse(list(Path(folder).glob("*.bin")))
