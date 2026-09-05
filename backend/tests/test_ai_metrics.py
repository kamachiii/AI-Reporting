"""Test unit & integrasi untuk router admin ai_metrics (Overview, Timeline, Branch Usage, Update Quota)."""
from datetime import date, datetime
from unittest.mock import AsyncMock, patch, MagicMock
from fastapi.testclient import TestClient

from app.main import app
from app.core.security import require_admin_role


def test_get_ai_metrics_overview():
    """Memastikan endpoint /admin/ai-metrics/overview mengembalikan agregasi dan estimasi token yang akurat."""
    app.dependency_overrides[require_admin_role] = lambda: {"role": "admin", "sub": "admin"}
    mock_pool = MagicMock()
    mock_pool.fetchrow = AsyncMock(return_value={
        "total_queries": 20,
        "total_success": 18,
        "total_error": 1,
        "total_rejected": 1,
        "memory_hits": 6,
        "today_total": 10,
        "today_success": 9,
        "avg_latency_ms": 142.5,
    })

    try:
        with patch("app.routers.admin.ai_metrics.get_core_pool", AsyncMock(return_value=mock_pool)):
            client = TestClient(app)
            res = client.get("/admin/ai-metrics/overview")
            assert res.status_code == 200
            data = res.json()

            assert data["total_queries"] == 20
            assert data["total_success"] == 18
            assert data["memory_hits"] == 6
            # llm_queries = 18 - 6 = 12
            assert data["llm_queries"] == 12
            # tokens_estimated = 12 * 650 = 7800
            assert data["tokens_estimated"] == 7800
            # tokens_saved = 6 * 1500 = 9000
            assert data["tokens_saved"] == 9000
            # success_rate = (18 / 20) * 100 = 90.0%
            assert data["success_rate"] == 90.0
            assert data["avg_latency_ms"] == 142.5
    finally:
        app.dependency_overrides.pop(require_admin_role, None)


def test_get_ai_metrics_timeline():
    """Memastikan endpoint /admin/ai-metrics/timeline mengembalikan deret waktu lengkap 7 hari."""
    app.dependency_overrides[require_admin_role] = lambda: {"role": "admin", "sub": "admin"}
    today = date.today()
    mock_pool = MagicMock()
    mock_pool.fetch = AsyncMock(return_value=[
        {
            "query_date": today,
            "total_queries": 5,
            "success_queries": 4,
            "memory_hits": 2,
            "llm_queries": 2,
        }
    ])

    try:
        with patch("app.routers.admin.ai_metrics.get_core_pool", AsyncMock(return_value=mock_pool)):
            client = TestClient(app)
            res = client.get("/admin/ai-metrics/timeline?days=7")
            assert res.status_code == 200
            data = res.json()
            assert data["days"] == 7
            assert len(data["timeline"]) == 7

            today_entry = next((e for e in data["timeline"] if e["date"] == today.isoformat()), None)
            assert today_entry is not None
            assert today_entry["total_queries"] == 5
            assert today_entry["success_queries"] == 4
            assert today_entry["memory_hits"] == 2
            assert today_entry["estimated_tokens"] == 1300  # 2 * 650
            assert today_entry["saved_tokens"] == 3000      # 2 * 1500
    finally:
        app.dependency_overrides.pop(require_admin_role, None)


def test_get_branch_usage():
    """Memastikan endpoint /admin/ai-metrics/branch-usage menghitung kuota dan status cabang dengan benar."""
    app.dependency_overrides[require_admin_role] = lambda: {"role": "admin", "sub": "admin"}
    mock_pool = MagicMock()
    mock_pool.fetch = AsyncMock(return_value=[
        {
            "branch_code": "TST_01",
            "branch_name": "Cabang Test 01",
            "company_name": "PT Maju Mobil",
            "daily_token_quota": 50000,
            "is_active": True,
            "today_llm_queries": 10,
            "today_total_queries": 15,
            "all_time_queries": 120,
            "last_active_at": datetime(2026, 9, 5, 14, 30),
        },
        {
            "branch_code": "JKT_01",
            "branch_name": "Cabang Jakarta Pusat",
            "company_name": "PT Aleza Motor",
            "daily_token_quota": 10000,
            "is_active": True,
            "today_llm_queries": 22,  # 22 * 500 = 11.000 (exceeded)
            "today_total_queries": 25,
            "all_time_queries": 300,
            "last_active_at": datetime(2026, 9, 5, 15, 0),
        }
    ])

    try:
        with patch("app.routers.admin.ai_metrics.get_core_pool", AsyncMock(return_value=mock_pool)):
            client = TestClient(app)
            res = client.get("/admin/ai-metrics/branch-usage")
            assert res.status_code == 200
            data = res.json()
            assert len(data["branches"]) == 2

            tst = data["branches"][0]
            assert tst["branch_code"] == "TST_01"
            assert tst["today_tokens_used"] == 5000  # 10 * 500
            assert tst["quota_percentage"] == 10.0
            assert tst["status"] == "ok"

            jkt = data["branches"][1]
            assert jkt["branch_code"] == "JKT_01"
            assert jkt["today_tokens_used"] == 11000
            assert jkt["quota_percentage"] == 110.0
            assert jkt["status"] == "exceeded"
    finally:
        app.dependency_overrides.pop(require_admin_role, None)


def test_update_branch_quota_success():
    """Memastikan kuota token cabang dapat diperbarui oleh admin."""
    app.dependency_overrides[require_admin_role] = lambda: {"role": "admin", "username": "superadmin"}
    mock_pool = MagicMock()
    mock_pool.fetchrow = AsyncMock(return_value={"branch_code": "TST_01"})
    mock_pool.execute = AsyncMock(return_value=None)

    try:
        with patch("app.routers.admin.ai_metrics.get_core_pool", AsyncMock(return_value=mock_pool)):
            client = TestClient(app)
            res = client.patch("/admin/ai-metrics/branch-quota/TST_01", json={"daily_token_quota": 100000})
            assert res.status_code == 200
            data = res.json()
            assert data["success"] is True
            assert data["daily_token_quota"] == 100000
            assert "100,000" in data["message"]

            mock_pool.execute.assert_called_once()
    finally:
        app.dependency_overrides.pop(require_admin_role, None)


def test_update_branch_quota_not_found():
    """Memastikan update kuota cabang yang tidak terdaftar menghasilkan 404."""
    app.dependency_overrides[require_admin_role] = lambda: {"role": "admin", "username": "superadmin"}
    mock_pool = MagicMock()
    mock_pool.fetchrow = AsyncMock(return_value=None)

    try:
        with patch("app.routers.admin.ai_metrics.get_core_pool", AsyncMock(return_value=mock_pool)):
            client = TestClient(app)
            res = client.patch("/admin/ai-metrics/branch-quota/CABANG_GHAIB", json={"daily_token_quota": 20000})
            assert res.status_code == 404
            assert "tidak ditemukan" in res.json()["detail"]
    finally:
        app.dependency_overrides.pop(require_admin_role, None)


def test_update_branch_quota_validation_error():
    """Memastikan kuota di luar rentang (1.000 s/d 5.000.000) ditolak oleh validasi Pydantic."""
    app.dependency_overrides[require_admin_role] = lambda: {"role": "admin", "username": "superadmin"}

    try:
        client = TestClient(app)
        # Kurang dari 1000
        res = client.patch("/admin/ai-metrics/branch-quota/TST_01", json={"daily_token_quota": 500})
        assert res.status_code == 422

        # Lebih dari 5.000.000
        res2 = client.patch("/admin/ai-metrics/branch-quota/TST_01", json={"daily_token_quota": 10000000})
        assert res2.status_code == 422
    finally:
        app.dependency_overrides.pop(require_admin_role, None)
