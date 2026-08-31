"""Endpoints admin untuk Knowledge Base tenant (F2.0).

KB adalah lapisan semantik per tenant (docs/PERANCANGAN-PIPELINE-AI.md §3)
yang disimpan di kolom JSONB tenants.knowledge_base. Validasi bentuk data
didelegasikan penuh ke app/services/knowledge_base.py; endpoint ini hanya
mengatur akses + penyimpanan (UPDATE parameterized).
"""
import json
import logging

from fastapi import APIRouter, Depends, HTTPException

from app.core.database import get_core_pool
from app.core.security import require_admin_role
from app.services.knowledge_base import validate_kb, parse_stored_kb

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/admin", tags=["Admin - Knowledge Base"])


async def _get_tenant_row(pool, branch_code: str):
    """Ambil baris tenant; 404 dengan pesan jelas bila cabang/belum terhubung."""
    row = await pool.fetchrow(
        "SELECT knowledge_base, updated_at FROM tenants WHERE branch_code = $1", branch_code)
    if row:
        return row
    # Bedakan pesan: cabang tak ada vs cabang ada tapi belum jadi tenant.
    branch_exists = await pool.fetchval(
        "SELECT 1 FROM branches WHERE code = $1", branch_code)
    if not branch_exists:
        raise HTTPException(status_code=404,
                            detail=f"Cabang '{branch_code}' tidak ditemukan.")
    raise HTTPException(
        status_code=404,
        detail=f"Cabang '{branch_code}' belum terhubung database (belum jadi tenant) — "
               "hubungkan database dulu di menu Koneksi.")
    # Catatan: cabang aktif/nonaktif tidak dibedakan di sini — KB tetap bisa
    # dilihat/diubah untuk cabang nonaktif (tak berpengaruh ke DB tenant).


def _ringkas_kb(kb: dict) -> dict:
    """Ringkasan jumlah entri per bagian — untuk metadata 'perubahan'."""
    return {
        "glossary": len(kb.get("glossary", [])),
        "catatan_kolom": len(kb.get("catatan_kolom", {})),
        "nilai_map": len(kb.get("nilai_map", {})),
        "contoh_tanya": len(kb.get("contoh_tanya", [])),
        "tabel_dilarang": len(kb.get("tabel_dilarang", [])),
    }


@router.get("/tenants/{branch_code}/knowledge-base")
async def get_knowledge_base(branch_code: str, user: dict = Depends(require_admin_role)):
    """KB saat ini milik tenant (atau struktur kosong bila belum diisi) + metadata."""
    try:
        pool = await get_core_pool()
        row = await _get_tenant_row(pool, branch_code)
        kb = parse_stored_kb(row["knowledge_base"])
        updated_at = row["updated_at"]
        return {
            "branch_code": branch_code,
            "knowledge_base": kb,
            # updated_at menyatu dengan perubahan DB tenant lain — bila kolom
            # belum pernah disentuh, tetap tampil sebagai waktu update terakhir.
            "updated_at": updated_at.isoformat() if updated_at else None,
            "sumber": "tersimpan" if row["knowledge_base"] is not None else "default",
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching knowledge base {branch_code}: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.put("/tenants/{branch_code}/knowledge-base")
async def put_knowledge_base(branch_code: str, payload: dict,
                             user: dict = Depends(require_admin_role)):
    """Simpan KB tenant: validate -> UPDATE parameterized -> kembalikan hasil."""
    clean, errors = validate_kb(payload)
    if errors:
        raise HTTPException(status_code=422, detail={
            "message": "Knowledge base tidak valid",
            "errors": errors,
        })
    try:
        pool = await get_core_pool()
        old_row = await _get_tenant_row(pool, branch_code)
        lama = parse_stored_kb(old_row["knowledge_base"])

        await pool.execute(
            "UPDATE tenants SET knowledge_base = $2::jsonb, "
            "updated_at = CURRENT_TIMESTAMP WHERE branch_code = $1",
            branch_code, json.dumps(clean))

        # Ringkasan perubahan: bagian mana yang berisi + jumlah entri lama -> baru.
        ringkas_lama, ringkas_baru = _ringkas_kb(lama), _ringkas_kb(clean)
        sections_berubah = [k for k in ringkas_baru if ringkas_lama[k] != ringkas_baru[k]]
        return {
            "message": f"Knowledge base cabang {branch_code} berhasil disimpan",
            "knowledge_base": clean,
            "perubahan": {
                "sections_berubah": sections_berubah,
                "sebelum": ringkas_lama,
                "sesudah": ringkas_baru,
            },
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error saving knowledge base {branch_code}: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/tenants/{branch_code}/knowledge-base/validate")
async def validate_knowledge_base(branch_code: str, payload: dict,
                                  user: dict = Depends(require_admin_role)):
    """Dry-run validasi KB: TIDAK menyimpan apa pun, TIDAK menyentuh DB tenant.

    Dipakai tombol 'Validasi' di form admin; juga berguna untuk pemeriksaan
    massal via API. Return {ok, errors} — errors kosong berarti valid.
    """
    _, errors = validate_kb(payload)
    return {"ok": len(errors) == 0, "errors": errors}
