"""
F1.1 — Introspeksi skema database tenant.

Membaca information_schema dari koneksi tenant DB dan menghasilkan struktur
JSON ketat yang menjadi konteks AI di Fase 2 (query planner) sekaligus
dokumentasi skema yang tersimpan di tenants.schema_config_json:

{
  "introspected_at": "2026-08-29T12:00:00+00:00",
  "tables": {
    "penjualan": {
      "columns":   [{"name", "type", "nullable", "default"}],
      "primary_key": ["id"],
      "foreign_keys": [{"column", "references_table", "references_column"}],
      "sample_rows": [ {kolom: nilai}, ... ]   # maksimal 2 baris
    }
  }
}

Semua nilai sample dikonversi JSON-safe (date/datetime -> ISO, Decimal -> float).
"""
import json
import logging
import uuid
from datetime import date, datetime, time, timezone
from decimal import Decimal

import asyncpg

logger = logging.getLogger(__name__)

_SAMPLE_ROWS = 2
# Skema yang diperiksa: 'public' saja — tenant DB milik aplikasi, bukan katalog sistem
_SCHEMA = "public"


def _json_safe(v):
    if v is None or isinstance(v, (str, int, float, bool)):
        return v
    if isinstance(v, (date, datetime, time)):
        return v.isoformat()
    if isinstance(v, Decimal):
        return float(v)
    if isinstance(v, uuid.UUID):
        return str(v)
    if isinstance(v, bytes):
        return v.decode("utf-8", "replace")
    return str(v)


def _nama_tabel_aman(nama: str) -> bool:
    # identifer dibungkus kutip-ganda; tolak nama yang bisa memecah quoting
    return bool(nama) and '"' not in nama and "\x00" not in nama


async def introspect_schema(conn: asyncpg.Connection) -> dict:
    """Baca struktur + sample dari seluruh tabel public pada koneksi tenant."""
    kolom_rows = await conn.fetch(
        """
        SELECT table_name, column_name, data_type, is_nullable, column_default
        FROM information_schema.columns
        WHERE table_schema = $1
        ORDER BY table_name, ordinal_position
        """,
        _SCHEMA,
    )
    pk_rows = await conn.fetch(
        """
        SELECT tc.table_name, kcu.column_name
        FROM information_schema.table_constraints tc
        JOIN information_schema.key_column_usage kcu
          ON tc.constraint_name = kcu.constraint_name
         AND tc.table_schema = kcu.table_schema
        WHERE tc.constraint_type = 'PRIMARY KEY' AND tc.table_schema = $1
        ORDER BY tc.table_name, kcu.ordinal_position
        """,
        _SCHEMA,
    )
    fk_rows = await conn.fetch(
        """
        SELECT tc.table_name, kcu.column_name,
               ccu.table_name  AS ref_table,
               ccu.column_name AS ref_column
        FROM information_schema.table_constraints tc
        JOIN information_schema.key_column_usage kcu
          ON tc.constraint_name = kcu.constraint_name
         AND tc.table_schema = kcu.table_schema
        JOIN information_schema.constraint_column_usage ccu
          ON ccu.constraint_name = tc.constraint_name
        WHERE tc.constraint_type = 'FOREIGN KEY' AND tc.table_schema = $1
        """,
        _SCHEMA,
    )

    tables: dict = {}
    for r in kolom_rows:
        t = r["table_name"]
        if not _nama_tabel_aman(t):
            continue
        tables.setdefault(t, {
            "columns": [], "primary_key": [], "foreign_keys": [], "sample_rows": [],
        })
        tables[t]["columns"].append({
            "name": r["column_name"],
            "type": r["data_type"],
            "nullable": r["is_nullable"] == "YES",
            "default": r["column_default"],
        })
    for r in pk_rows:
        if r["table_name"] in tables:
            tables[r["table_name"]]["primary_key"].append(r["column_name"])
    for r in fk_rows:
        if r["table_name"] in tables:
            tables[r["table_name"]]["foreign_keys"].append({
                "column": r["column_name"],
                "references_table": r["ref_table"],
                "references_column": r["ref_column"],
            })

    # sample rows: 2 baris per tabel, nilai JSON-safe
    for t, info in tables.items():
        try:
            rows = await conn.fetch(f'SELECT * FROM "{t}" LIMIT {_SAMPLE_ROWS}')
            info["sample_rows"] = [
                {k: _json_safe(v) for k, v in dict(row).items()} for row in rows
            ]
        except Exception as e:
            logger.warning(f"Sample rows tabel '{t}' gagal: {e}")
            info["sample_rows"] = []

    return {
        "introspected_at": datetime.now(timezone.utc).isoformat(),
        "tables": tables,
    }


def ringkas_skema(skema: dict) -> str:
    """Ringkasan skema (nama tabel + kolom saja) — bentuk ringan untuk prompt AI
    bila skema besar; detail penuh tetap tersedia di schema_config_json."""
    bagian = []
    for t, info in skema.get("tables", {}).items():
        kolom = ", ".join(c["name"] for c in info.get("columns", []))
        bagian.append(f"{t}({kolom})")
    return "; ".join(bagian)
