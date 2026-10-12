import copy
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace, ModuleType
from unittest.mock import AsyncMock, patch

import bootstrap
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'scripts'))
from layout_fixtures import make_report
from group_relations.analysis import analyze, personal_report
from group_relations.context import sample_context
from group_relations.render import image_html, text_report
from group_relations.service import RelationsService


class PersonalTests(unittest.TestCase):
    def test_only_personal_edges_cards_and_statistics_are_shown(self):
        original = make_report(12, 'normal', 12)
        before = copy.deepcopy(original)
        report = personal_report(original, 'demo-0')
        self.assertEqual(original, before)
        self.assertTrue(all('demo-0' in (e['source'],e['target']) for e in report['edges']))
        self.assertTrue(all('demo-0' in (e['source'],e['target']) for e in report['context_analysis']['relationships']))
        own = next(m for m in original['members'] if m['id'] == 'demo-0')
        self.assertEqual(report['meta']['messages'], own['messages'])
        self.assertEqual(report['meta']['interactions'], sum(e['events'] for e in report['edges']))
        self.assertIn('我的发言', image_html(report))
        self.assertIn('我的群关系', text_report(report))
        self.assertEqual(report['members'][0]['id'], 'demo-0')

    def test_unrelated_references_remain_readable_and_unknown_user_fails(self):
        original = make_report(12, 'normal', 12)
        original['context_analysis']['relationships'][0]['reason'] = '[demo-0]接话，[demo-7]路过'
        report = personal_report(original, 'demo-0')
        self.assertNotIn('[demo-7]', image_html(report))
        self.assertIn('小满', image_html(report))
        with self.assertRaisesRegex(ValueError, '没有你的'):
            personal_report(original, 'missing')

    def test_no_interaction_is_valid_personal_image(self):
        original = make_report(1, 'normal', 0)
        report = personal_report(original, 'demo-0')
        self.assertEqual(report['meta']['interactions'], 0)
        self.assertEqual(report['context_analysis']['relationships'], [])
        self.assertIn('我的群关系', image_html(report))

    def test_bot_is_eligible_for_context_and_has_visible_marker(self):
        report = make_report(5, 'small', 6)
        bot = next(m for m in report['members'] if m['id']=='demo-1')
        bot['is_bot'] = True
        rows = [dict(id='x', sender='demo-1', name=bot['name'], ts=1, text='儿子来了', mentions=['demo-0']),
                dict(id='y', sender='demo-0', name='小橘', ts=2, text='爸爸救我', mentions=['demo-1'])]
        context = sample_context(rows, report['members'], {'', '0', '-1'})
        self.assertTrue(any(m['is_bot'] for m in context['members']))
        self.assertEqual(context['sampled'], 2)
        self.assertIn('（机器人）', image_html(report))


class BotSyncTests(unittest.IsolatedAsyncioTestCase):
    async def test_historical_bot_and_new_outgoing_messages_are_imported(self):
        messages = []
        def message(id, sender, platform, targets, name):
            return SimpleNamespace(id=id, sender_id=sender, platform_userid=platform, message_id=str(id),
                sender_name=name, sender_nickname=name, chat_key='g', is_recalled=False, send_timestamp=100+id,
                content_data=[{'type':'at','target_platform_userid':t} for t in targets],
                ext_data={}, content_text='爸爸救我' if sender != '-1' else '儿子来了')
        messages.extend([message(1,'person','67890',['12345'],'群友'), message(2,'-1','12345',['67890'],'机器人'),
                         message(3,'-1','0',[],'SYSTEM')])
        class Query:
            def __init__(self, filters): self.filters = filters
            def filter(self, **kwargs): return Query(self.filters | kwargs)
            def selected(self):
                return [m for m in messages if m.id > self.filters.get('id__gt',0) and
                        ('message_id__in' not in self.filters or m.message_id in self.filters['message_id__in'])]
            async def count(self): return len(self.selected())
            def order_by(self, *_): return self
            def limit(self, *_): return self
            async def all(self): return self.selected()
            async def values(self, *fields): return [{f:getattr(m,f) for f in fields} for m in self.selected()]
        model = ModuleType('nekro_agent.models.db_chat_message')
        model.DBChatMessage = SimpleNamespace(filter=lambda **kwargs: Query(kwargs))
        with tempfile.TemporaryDirectory() as folder, patch.dict(sys.modules, {'nekro_agent.models.db_chat_message':model}):
            cfg = SimpleNamespace(RETENTION_DAYS=90, MAX_HISTORY_MESSAGES=50000)
            service = RelationsService(SimpleNamespace(get_plugin_data_dir=lambda:Path(folder)), lambda:cfg)
            service.channel = AsyncMock(return_value=SimpleNamespace(channel_name='模拟群'))
            service.bot_ids['g'] = '12345'
            await service.sync('g',7)
            messages.append(message(4,'-1','12345',['67890'],'机器人'))
            await service.sync('g',7,incremental=True)
            rows = service.repo.rows('g',0,1000)
            self.assertEqual(len(rows),3)
            self.assertEqual({r['sender'] for r in rows}, {'12345','67890'})
            report = analyze(rows,0,1000)
            self.assertEqual(report['edges'][0]['events'],3)
            self.assertGreater(report['edges'][0]['mutual'],0)
