import unittest
from unittest.mock import patch
import sys
import types
from types import SimpleNamespace

import bootstrap
from fastapi import FastAPI
from fastapi.testclient import TestClient
from group_relations.web import admin, create_router


class FakeService:
    async def channels(self):
        return [{"key": "demo", "name": "模拟群", "enabled": True}]

    async def report(self, key, days, limit, **kwargs):
        if key != "demo":
            raise ValueError("群不存在")
        return {"chat_key": key, "days": days}


class WebTests(unittest.TestCase):
    def setUp(self):
        self.app = FastAPI()
        self.app.include_router(create_router(lambda: FakeService()), prefix="/plugins/test")
        self.client = TestClient(self.app)

    def test_public_shell_has_no_chat_data(self):
        result = self.client.get("/plugins/test/")
        self.assertEqual(result.status_code, 200)
        self.assertIn("Content-Security-Policy", result.headers)
        self.assertNotIn("模拟群", result.text)

    def test_data_requires_bearer(self):
        self.assertEqual(self.client.get("/plugins/test/api/channels").status_code, 401)
        self.assertEqual(self.client.post("/plugins/test/api/report", json={"chat_key": "demo"}).status_code, 401)

    def test_query_credentials_rejected(self):
        self.assertEqual(self.client.get("/plugins/test/api/channels?token=secret", headers={"Authorization": "Bearer test"}).status_code, 401)

    def test_non_admin_and_inactive_user_rejected(self):
        deps = types.ModuleType("nekro_agent.services.user.deps")
        role = types.ModuleType("nekro_agent.services.user.role")
        role.Role = SimpleNamespace(Admin=2)
        async def current(_request):
            return self.fake_user
        deps.get_current_user = current
        with patch.dict(sys.modules, {deps.__name__: deps, role.__name__: role}):
            self.fake_user = SimpleNamespace(is_active=True, perm_level=1)
            self.assertEqual(self.client.get("/plugins/test/api/channels", headers={"Authorization": "Bearer valid"}).status_code, 403)
            self.fake_user = SimpleNamespace(is_active=False, perm_level=3)
            self.assertEqual(self.client.get("/plugins/test/api/channels", headers={"Authorization": "Bearer valid"}).status_code, 403)
            self.fake_user = SimpleNamespace(is_active=True, perm_level=2)
            result = self.client.get("/plugins/test/api/channels", headers={"Authorization": "Bearer valid"})
            self.assertEqual(result.status_code, 200)
            self.assertEqual(result.headers.get("cache-control"), "no-store")

    def test_asset_traversal_unavailable(self):
        self.assertEqual(self.client.get("/plugins/test/assets/secret.py").status_code, 404)
        self.assertEqual(self.client.get("/plugins/test/assets/app.js").status_code, 200)

    def test_authenticated_report_and_input_bounds(self):
        self.app.dependency_overrides[admin] = lambda: SimpleNamespace(perm_level=3)
        self.assertEqual(self.client.post("/plugins/test/api/report", json={"chat_key": "demo", "days": 7}).status_code, 200)
        self.assertEqual(self.client.post("/plugins/test/api/report", json={"chat_key": "demo", "days": 365}).status_code, 422)
        self.assertEqual(self.client.post("/plugins/test/api/report", json={"chat_key": "other"}).status_code, 400)

    def test_clear_requires_explicit_confirmation(self):
        self.app.dependency_overrides[admin] = lambda: SimpleNamespace(perm_level=3)
        self.assertEqual(self.client.post("/plugins/test/api/clear", json={"chat_key": "demo", "confirmation": ""}).status_code, 400)
