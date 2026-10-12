"""Run command contract checks when the Nekro runtime is available."""
import importlib.util
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import bootstrap
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'scripts'))
from layout_fixtures import make_report


@unittest.skipUnless(importlib.util.find_spec('nekro_agent'), 'requires Nekro runtime')
class PersonalCommandTests(unittest.IsolatedAsyncioTestCase):
    async def invoke(self, *, adapter='onebot_v11', fail_image=False, image=True, uid='demo-0'):
        from group_relations import plugin as module
        fake = SimpleNamespace(report=AsyncMock(return_value=make_report(5,'small',6)),
                               image=AsyncMock(return_value=Path('/tmp/my-relations.png')))
        if fail_image:
            fake.image.side_effect = RuntimeError('render unavailable')
        ctx = SimpleNamespace(adapter_key=adapter, chat_key='demo', user_id=uid)
        with patch.object(module,'_service',fake):
            results = [r async for r in module.my_command(ctx,7,True,False,image)]
        return results, fake

    async def test_default_command_returns_personal_image_attachment(self):
        responses, service = await self.invoke()
        final = responses[-1]
        self.assertEqual(final.status,'success')
        self.assertEqual(final.output_segments[0].type,'image')
        self.assertEqual(service.image.call_args.args[0]['personal']['uid'],'demo-0')

    async def test_render_failure_and_explicit_text_use_personal_text(self):
        for options in ({'fail_image':True},{'image':False}):
            responses, service = await self.invoke(**options)
            final = responses[-1]
            self.assertEqual(final.status,'success')
            self.assertIsNone(final.output_segments)
            self.assertIn('我的群关系',final.message)
            if options.get('image') is False:
                service.image.assert_not_awaited()

    async def test_webui_cannot_impersonate_member_and_unknown_member_fails(self):
        responses, service = await self.invoke(adapter='webui')
        self.assertEqual(responses[-1].status,'error')
        service.report.assert_not_awaited()
        responses, service = await self.invoke(uid='missing')
        self.assertEqual(responses[-1].status,'error')
        service.image.assert_not_awaited()
