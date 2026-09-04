"""Unit test untuk Vanna pgvector service dan admin training router."""
from unittest.mock import AsyncMock, patch, MagicMock

import pytest

from app.services.vanna_pgvector import (
    hitung_embedding,
    cari_konteks_pgvector,
    latih_pertanyaan_sql,
)


@pytest.mark.anyio
async def test_hitung_embedding_local():
    # Menguji embedding lokal menghasilkan list float berdimensi 384
    vec = await hitung_embedding("omzet penjualan kendaraan", provider="local")
    assert isinstance(vec, list)
    assert len(vec) == 384
    assert all(isinstance(x, float) for x in vec)


@pytest.mark.anyio
async def test_cari_konteks_pgvector_mock():
    fake_pool = AsyncMock()
    # Mock row dengan content dan metadata
    fake_pool.fetch = AsyncMock(side_effect=[
        [{"content": "Table untt_penjualan (nomor, hjakhir, tanggal)", "metadata": "{}"}],
        [{"content": "SELECT SUM(hjakhir) FROM untt_penjualan;", "metadata": {"question": "Berapa omzet?"}}]
    ])

    with patch("app.services.vanna_pgvector.hitung_embedding", return_value=[0.1] * 384):
        ctx, tables = await cari_konteks_pgvector(
            fake_pool,
            branch_code="TST_01",
            question="omzet penjualan",
            limit=5
        )
        assert "untt_penjualan" in ctx
        assert "untt_penjualan" in tables
        assert "Example SQL:" in ctx


@pytest.mark.anyio
async def test_latih_pertanyaan_sql_mock():
    fake_pool = AsyncMock()
    fake_pool.fetchrow = AsyncMock(return_value={"id": 42})

    with patch("app.services.vanna_pgvector.hitung_embedding", return_value=[0.1] * 384):
        res = await latih_pertanyaan_sql(
            fake_pool,
            branch_code="TST_01",
            question="Total unit terjual 2025",
            sql="SELECT COUNT(*) FROM untt_penjualan WHERE EXTRACT(YEAR FROM tanggal) = 2025;"
        )
        assert res["status"] == "success"
        assert res["id"] == 42
        assert res["branch_code"] == "TST_01"


def test_chat_explain_endpoint():
    from fastapi.testclient import TestClient
    from app.main import app
    from app.core.security import require_user_role

    client = TestClient(app)
    app.dependency_overrides[require_user_role] = lambda: {
        "user_id": 1,
        "username": "tester01",
        "role": "user",
        "allowed_branches": ["TST_01"]
    }
    try:
        with patch("app.services.vanna_engine.buat_penjelasan_naratif", return_value="Tren penjualan stabil dan meningkat 15%."):
            resp = client.post("/chat/explain", json={
                "branch_code": "TST_01",
                "question": "penjualan 2025",
                "sql": "SELECT 1;",
                "rows": [{"a": 1}]
            })
            assert resp.status_code == 200
            assert resp.json()["narasi"] == "Tren penjualan stabil dan meningkat 15%."
    finally:
        app.dependency_overrides.pop(require_user_role, None)


def test_admin_vanna_train_endpoint():
    from fastapi.testclient import TestClient
    from app.main import app
    from app.core.security import require_admin_role

    client = TestClient(app)
    app.dependency_overrides[require_admin_role] = lambda: {
        "user_id": 99,
        "username": "admin",
        "role": "admin"
    }
    try:
        with patch("app.routers.admin.vanna_training.latih_pertanyaan_sql", return_value={"status": "success", "id": 101}):
            resp = client.post("/admin/vanna/train", json={
                "branch_code": "TST_01",
                "question": "penjualan 2025",
                "sql": "SELECT 1;"
            })
            assert resp.status_code == 200
            assert resp.json()["id"] == 101
    finally:
        app.dependency_overrides.pop(require_admin_role, None)


