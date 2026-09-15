"""Audit aksi admin (QA1-01): decorator satu-baris per endpoint mutasi.

Pola: @audit_admin("company-create", target="payload.code")
  - target: literal, nama kwarg, atau path "payload.code" / "branch_code".
  - branch: opsional (default "" — kolom audit_logs.branch_code NOT NULL).
  - Sukses maupun gagal (HTTPException & Exception) tercatat; audit TIDAK
    PERNAH mengubah respons atau menggagalkan operasi (pola eval.py).
  - Endpoint yang sudah mengaudit sendiri (tenants mode/tier2, eval,
    memories) JANGAN didekorasi agar tidak dobel.
"""
import functools
import inspect
import logging

from fastapi import HTTPException

from app.core.database import get_core_pool
from app.services.chat_pipeline import tulis_audit

logger = logging.getLogger(__name__)


def _nilai_target(kwargs: dict, target: str):
    if not target:
        return "?"
    if "." in target:
        nama, _, attrs = target.partition(".")
        if nama == "result":
            return ("result", attrs)
        cur = kwargs.get(nama)
        for bagian in attrs.split("."):
            if cur is None:
                return None
            cur = cur.get(bagian) if isinstance(cur, dict) else getattr(
                cur, bagian, None)
        return cur
    if target in kwargs:
        return kwargs[target]
    return target


def _nilai_hasil(hasil, attrs: str):
    cur = hasil
    for bagian in attrs.split("."):
        if cur is None:
            return None
        cur = cur.get(bagian) if isinstance(cur, dict) else getattr(
            cur, bagian, None)
    return cur


async def _catat(pool, user, branch: str, aksi: str, target: str,
                 status: str, detail: str | None = None) -> None:
    try:
        await tulis_audit(
            pool, user_id=(user or {}).get("user_id"),
            branch_code=branch or "",
            prompt_text=f"[{aksi}] {target}",
            ai_json_filter={"category": "admin", "aksi": aksi},
            generated_sql=None, execution_time_ms=None,
            status=status, error_message=detail)
    except Exception as e:
        logger.error("audit %s gagal: %s", aksi, e)


def audit_admin(aksi: str, target: str = "?", branch: str | None = None):
    """Dekorator audit untuk endpoint admin. Lihat docstring modul."""
    def deco(fn):
        @functools.wraps(fn)
        async def bungkus(*args, **kwargs):
            pool = await get_core_pool()
            try:
                semua = inspect.signature(fn).bind_partial(*args, **kwargs)
                semua.apply_defaults()
                named = dict(semua.arguments)
            except (TypeError, ValueError):
                named = dict(kwargs)
            user = named.get("user")
            cabang = _nilai_target(named, branch) if branch else ""
            mentah = _nilai_target(named, target)
            dari_hasil = isinstance(mentah, tuple) and mentah[0] == "result"
            target_awal = None if dari_hasil else mentah
            try:
                hasil = await fn(*args, **kwargs)
            except HTTPException as e:
                detail = e.detail if isinstance(e.detail, str) else str(e.detail)
                await _catat(pool, user, cabang or "", aksi,
                             str(target_awal or "?"), "error", detail)
                raise
            except Exception as e:
                await _catat(pool, user, cabang or "", aksi,
                             str(target_awal or "?"), "error", str(e))
                raise
            if dari_hasil:
                target_awal = _nilai_hasil(hasil, mentah[1])
            await _catat(pool, user, cabang or "", aksi,
                         str(target_awal or "?"), "success")
            return hasil
        return bungkus
    return deco
