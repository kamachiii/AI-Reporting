"""F3 — Router chat user: /chat/query + /chat/history.

Guard berlapis (urutan eksekusi):
1. `require_user_role` (app.core.security) — token valid + user role 'user'
   di DB; admin DITOLAK (403) — pola sama dengan require_admin_role.
2. Rate limit in-memory per user_id (pola auth.py; 10 request / 60 dtk).
3. branch_code WAJIB anggota `allowed_branches` pada token — selain itu 403
   (isolasi antar cabang berlapis dengan isolasi koneksi di pipeline).
4. Pipeline (chat_pipeline.proses_pertanyaan) + pemetaan exception -> HTTP:
   TenantTidakAda/SkemaTidakTersedia -> 409, AIConfigError -> 503,
   PlanningError/SqlComposerError -> 502, VerifierDitolak -> 422 (gate+reason),
   QueryCanceledError (statement_timeout) -> 504, ExecutorError/sisanya -> 500.
"""
import logging
import time
from collections import defaultdict, deque

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.core.database import get_core_pool
from app.core.security import require_user_role
from app.services.chat_pipeline import (
    SkemaTidakTersedia, TenantTidakAda, VerifierDitolak, proses_pertanyaan)
from app.services.query_planner import AIConfigError, PlanningError
from app.services.query_executor import ExecutorError
from app.services.sql_composer import SqlComposerError
from app.services.tenant_pool import TenantPoolError, get_tenant_pool_manager

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/chat", tags=["Chat"])

# --- Rate limit in-memory per user (pola auth.py) — cukup untuk dev/PKL
# single-instance; Redis dipindahkan di Fase 6 (docs v2 §6 hardening).
CHAT_MAX_PER_WINDOW = 10
CHAT_WINDOW_SECONDS = 60
_chat_calls: dict[int, deque] = defaultdict(deque)


def cek_rate_limit(user_id: int, *, max_panggilan: int = CHAT_MAX_PER_WINDOW,
                   window_seconds: int = CHAT_WINDOW_SECONDS) -> None:
    """Cek + catat satu panggilan chat user; melebihi kuota -> HTTP 429.

    Fungsi murni-diwaktu (time.monotonic) dengan state module-level agar
    mudah diuji tanpa memicu pipeline. Evict berkala seperti auth.py agar
    dict tidak tumbuh tanpa batas.
    """
    now = time.monotonic()
    if len(_chat_calls) > 1024:
        for k in [k for k, v in _chat_calls.items()
                  if not v or now - v[-1] > window_seconds]:
            _chat_calls.pop(k, None)
    panggilan = _chat_calls[user_id]
    while panggilan and now - panggilan[0] > window_seconds:
        panggilan.popleft()
    if len(panggilan) >= max_panggilan:
        logger.warning("Rate limit chat tercapai untuk user %s", user_id)
        raise HTTPException(
            status_code=429,
            detail=f"Terlalu banyak pertanyaan. Coba lagi dalam "
                   f"{window_seconds} detik.")
    panggilan.append(now)


class ChatQueryRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    branch_code: str = Field(min_length=1, max_length=50)


@router.post("/query")
async def chat_query(payload: ChatQueryRequest,
                     user: dict = Depends(require_user_role)):
    """Satu pertanyaan -> jawaban tabel + SQL + level keyakinan."""
    cek_rate_limit(user["user_id"])

    allowed = user.get("allowed_branches") or []
    if payload.branch_code not in allowed:
        raise HTTPException(
            status_code=403,
            detail=f"Cabang '{payload.branch_code}' bukan penugasan Anda.")

    core_pool = await get_core_pool()
    try:
        return await proses_pertanyaan(
            core_pool, get_tenant_pool_manager(), user, payload.question,
            payload.branch_code)
    except TenantTidakAda as e:
        raise HTTPException(status_code=409, detail=str(e))
    except SkemaTidakTersedia as e:
        raise HTTPException(status_code=409, detail=str(e))
    except TenantPoolError as e:
        raise HTTPException(status_code=503,
                            detail=f"Database tenant tidak tersedia: {e}")
    except AIConfigError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except PlanningError as e:
        raise HTTPException(status_code=502,
                            detail=f"Perencana AI gagal: {e}")
    except SqlComposerError as e:
        raise HTTPException(status_code=502,
                            detail=f"Perencana AI gagal (compose): {e}")
    except VerifierDitolak as e:
        # Alasan verifier diberikan apa adanya ke user (kejujuran docs v2 §4)
        # sekaligus umpan balik merumuskan ulang pertanyaan.
        raise HTTPException(status_code=422, detail={
            "message": "Query tidak lolos verifikasi keamanan",
            "gate": e.verdict.get("gate"),
            "reason": e.verdict.get("reason"),
        })
    except asyncpg.exceptions.QueryCanceledError:
        raise HTTPException(
            status_code=504,
            detail="Query melebihi batas waktu eksekusi (10 detik). "
                   "Coba persempit rentang waktu atau filter.")
    except ExecutorError as e:
        logger.error("chat_query executor invariant: %s", e)
        raise HTTPException(status_code=500,
                            detail="Kesalahan internal executor.")
    except Exception as e:
        logger.error("chat_query error: %s", e)
        raise HTTPException(status_code=500, detail="Terjadi kesalahan internal.")


@router.get("/history")
async def chat_history(branch_code: str = Query(min_length=1, max_length=50),
                       user: dict = Depends(require_user_role)):
    """50 pesan terakhir percakapan user pada satu cabang (lama -> baru)."""
    allowed = user.get("allowed_branches") or []
    if branch_code not in allowed:
        raise HTTPException(
            status_code=403,
            detail=f"Cabang '{branch_code}' bukan penugasan Anda.")

    core_pool = await get_core_pool()
    conv_id = await core_pool.fetchval(
        "SELECT id FROM conversations WHERE user_id = $1 AND branch_code = $2 "
        "ORDER BY id DESC LIMIT 1", user["user_id"], branch_code)
    if conv_id is None:
        return {"conversation_id": None, "messages": []}

    rows = await core_pool.fetch(
        "SELECT role, content, created_at FROM messages "
        "WHERE conversation_id = $1 ORDER BY id DESC LIMIT 50", conv_id)
    messages = [
        {"role": r["role"], "content": r["content"],
         "created_at": r["created_at"].isoformat()}
        for r in rows
    ]
    messages.reverse()  # tampilkan lama -> baru
    return {"conversation_id": conv_id, "messages": messages}
