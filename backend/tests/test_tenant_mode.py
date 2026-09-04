import pytest
from unittest.mock import AsyncMock, patch
from fastapi.testclient import TestClient

from app.main import app
from app.core.security import require_admin_role

@pytest.fixture(autouse=True)
def override_admin():
    app.dependency_overrides[require_admin_role] = lambda: {
        "user_id": 1, "role": "admin", "username": "admin"
    }
    yield
    app.dependency_overrides.pop(require_admin_role, None)

def test_set_tenant_mode_vanna_and_tier1():
    client = TestClient(app)

    fake_pool = AsyncMock()
    fake_pool.fetchrow = AsyncMock(return_value={"id": 1, "branch_code": "TST_01"})
    fake_pool.execute = AsyncMock(return_value="UPDATE 1")

    with patch("app.routers.admin.tenants.get_core_pool", return_value=fake_pool), \
         patch("app.routers.admin.tenants.tulis_audit", new_callable=AsyncMock):
        
        # Test set mode to vanna
        resp = client.post(
            "/admin/tenants/TST_01/mode",
            json={"mode": "vanna"}
        )
        assert resp.status_code == 200
        assert resp.json() == {"branch_code": "TST_01", "chat_mode": "vanna", "chat_tier2": False}

        # Test set mode to tier1
        resp = client.post(
            "/admin/tenants/TST_01/mode",
            json={"mode": "tier1"}
        )
        assert resp.status_code == 200
        assert resp.json() == {"branch_code": "TST_01", "chat_mode": "tier1", "chat_tier2": False}

def test_set_tenant_mode_invalid():
    client = TestClient(app)
    resp = client.post(
        "/admin/tenants/TST_01/mode",
        json={"mode": "invalid_mode"}
    )
    assert resp.status_code == 422
