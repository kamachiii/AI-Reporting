"""Test unit & integrasi sorting pada endpoint audit logs admin."""
from unittest.mock import AsyncMock, patch, MagicMock
from fastapi.testclient import TestClient
from app.main import app
from app.core.security import require_admin_role


def test_get_audit_logs_invalid_sort_by():
    """Memastikan sort_by di luar whitelist ditolak dengan 400 Bad Request."""
    app.dependency_overrides[require_admin_role] = lambda: {"role": "admin", "sub": "admin"}
    try:
        client = TestClient(app)
        res = client.get("/admin/audit-logs?sort_by=invalid_column&sort_dir=asc")
        assert res.status_code == 400
        assert "sort_by tidak valid" in res.json()["detail"]
    finally:
        app.dependency_overrides.pop(require_admin_role, None)


def test_get_audit_logs_valid_sort_by():
    """Memastikan query SQL tersusun dengan kolom & arah sort yang aman."""
    app.dependency_overrides[require_admin_role] = lambda: {"role": "admin", "sub": "admin"}
    mock_pool = MagicMock()
    mock_pool.fetchval = AsyncMock(return_value=1)
    mock_pool.fetch = AsyncMock(return_value=[])

    try:
        with patch("app.routers.admin.audit_logs.get_core_pool", AsyncMock(return_value=mock_pool)):
            client = TestClient(app)
            res = client.get("/admin/audit-logs?sort_by=execution_time_ms&sort_dir=asc")
            assert res.status_code == 200
            data = res.json()
            assert data["total"] == 1
            assert data["data"] == []

        call_args = mock_pool.fetch.call_args[0]
        sql_executed = call_args[0]
        assert "ORDER BY al.execution_time_ms ASC, al.id DESC" in sql_executed
    finally:
        app.dependency_overrides.pop(require_admin_role, None)


def test_get_audit_logs_sort_by_ai_provider_and_category():
    """Memastikan sort_by ai_provider dan log_category didukung."""
    app.dependency_overrides[require_admin_role] = lambda: {"role": "admin", "sub": "admin"}
    mock_pool = MagicMock()
    mock_pool.fetchval = AsyncMock(return_value=1)
    mock_pool.fetch = AsyncMock(return_value=[])

    try:
        with patch("app.routers.admin.audit_logs.get_core_pool", AsyncMock(return_value=mock_pool)):
            client = TestClient(app)
            res = client.get("/admin/audit-logs?sort_by=ai_provider&sort_dir=desc")
            assert res.status_code == 200

        call_args = mock_pool.fetch.call_args[0]
        assert "ORDER BY al.ai_json_filter->>'provider' DESC, al.id DESC" in call_args[0]
    finally:
        app.dependency_overrides.pop(require_admin_role, None)


def test_get_audit_logs_filter_provider_and_category():
    """Memastikan filter provider dan category tersusun ke WHERE clause."""
    app.dependency_overrides[require_admin_role] = lambda: {"role": "admin", "sub": "admin"}
    mock_pool = MagicMock()
    mock_pool.fetchval = AsyncMock(return_value=1)
    mock_pool.fetch = AsyncMock(return_value=[])

    try:
        with patch("app.routers.admin.audit_logs.get_core_pool", AsyncMock(return_value=mock_pool)):
            client = TestClient(app)
            res = client.get("/admin/audit-logs?provider=groq&category=data_query")
            assert res.status_code == 200

        count_args = mock_pool.fetchval.call_args[0]
        count_sql = count_args[0]
        assert "COALESCE(al.ai_json_filter->>'category', al.ai_json_filter->>'mode', 'data_query') = $1" in count_sql
        assert "al.ai_json_filter->>'provider' ILIKE $2" in count_sql
        assert count_args[1] == "data_query"
        assert count_args[2] == "%groq%"
    finally:
        app.dependency_overrides.pop(require_admin_role, None)

