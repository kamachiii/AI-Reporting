"""Test fewshot_provider (F3) — penyedia contoh few-shot dari sql_memory & global_kb.

Memastikan:
- ambil_fewshot_memory: hanya approved, terurut times_used DESC, parse plan_json
- ambil_fewshot_global: hanya kind='example', terurut updated_at DESC
- ambil_fewshot: gabungan memory + global sesuai limit total
- Fallback jika query error / tabel belum ada.
"""
import asyncio
import json
import pytest

from app.services.fewshot_provider import (
    ambil_fewshot_memory,
    ambil_fewshot_global,
    ambil_fewshot,
)


def _run(coro):
    return asyncio.run(coro)


class _StubPool:
    def __init__(self, fetch_fn=None):
        self.fetch_fn = fetch_fn

    async def fetch(self, sql, *args):
        if self.fetch_fn:
            return await self.fetch_fn(sql, *args)
        return []


class TestFewshotProvider:
    def test_ambil_fewshot_memory(self):
        async def fake_fetch(sql, *args):
            assert "WHERE tenant_id = $1 AND status = 'approved'" in sql
            return [
                {
                    "pertanyaan_ternormalisasi": "omzet bulan ini",
                    "plan_json": json.dumps({"tables": ["penjualan"]}),
                    "sql": "SELECT SUM(harga_deal) FROM penjualan",
                    "sumber": "tier1"
                },
                {
                    "pertanyaan_ternormalisasi": "total unit",
                    "plan_json": {"tables": ["kendaraan"]},  # dict langsung
                    "sql": "SELECT COUNT(*) FROM kendaraan",
                    "sumber": "tier1"
                }
            ]

        pool = _StubPool(fetch_fn=fake_fetch)
        res = _run(ambil_fewshot_memory(pool, tenant_id=1, limit=3))
        assert len(res) == 2
        assert res[0]["pertanyaan"] == "omzet bulan ini"
        assert res[0]["plan_json"] == {"tables": ["penjualan"]}
        assert res[1]["plan_json"] == {"tables": ["kendaraan"]}

    def test_ambil_fewshot_global(self):
        async def fake_fetch(sql, *args):
            assert "WHERE kind = 'example'" in sql
            return [
                {
                    "question": "penjualan 2026",
                    "sql_example": "SELECT * FROM untt_penjualan WHERE thn = '2026'"
                }
            ]

        pool = _StubPool(fetch_fn=fake_fetch)
        res = _run(ambil_fewshot_global(pool, limit=2))
        assert len(res) == 1
        assert res[0]["pertanyaan"] == "penjualan 2026"
        assert res[0]["sql"] == "SELECT * FROM untt_penjualan WHERE thn = '2026'"

    def test_ambil_fewshot_gabungan_prioritas_memory(self):
        async def fake_fetch(sql, *args):
            if "sql_memory" in sql:
                limit = args[1] if len(args) > 1 else 3
                return [
                    {
                        "pertanyaan_ternormalisasi": "q1 memory",
                        "plan_json": None,
                        "sql": "SELECT 1",
                        "sumber": "tier1"
                    },
                    {
                        "pertanyaan_ternormalisasi": "q2 memory",
                        "plan_json": None,
                        "sql": "SELECT 2",
                        "sumber": "tier1"
                    }
                ][:limit]
            elif "global_knowledge_base" in sql:
                limit = args[0] if len(args) > 0 else 2
                return [
                    {
                        "question": "q3 global",
                        "sql_example": "SELECT 3"
                    },
                    {
                        "question": "q4 global",
                        "sql_example": "SELECT 4"
                    }
                ][:limit]
            return []

        pool = _StubPool(fetch_fn=fake_fetch)
        # Total limit 3: 2 dari memory (max 3), 1 dari global
        res = _run(ambil_fewshot(pool, tenant_id=1, max_total=3))
        assert len(res) == 3
        assert res[0]["pertanyaan"] == "q1 memory"
        assert res[1]["pertanyaan"] == "q2 memory"
        assert res[2]["pertanyaan"] == "q3 global"

    def test_error_handling_graceful(self):
        async def failing_fetch(sql, *args):
            raise Exception("DB Error")

        pool = _StubPool(fetch_fn=failing_fetch)
        res = _run(ambil_fewshot(pool, tenant_id=1, max_total=5))
        assert res == []
