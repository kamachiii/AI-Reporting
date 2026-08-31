"""Endpoints admin untuk konfigurasi AI provider & model."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
import asyncio
import asyncpg
import httpx
import logging

from app.core.database import get_core_pool
from app.core.security import require_admin_role, encrypt_credential, decrypt_credential

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/admin", tags=["Admin - AI Configs"])


class AIConfigCreate(BaseModel):
    scope: str
    target_id: str = ""
    provider: str
    api_key: str
    model: str
    temperature: float = 0.7
    api_type: str = "openai"
    base_url: str = ""

class AIConfigUpdate(BaseModel):
    scope: str
    target_id: str = ""
    provider: str
    api_key: str = ""
    model: str
    temperature: float = 0.7
    api_type: str = "openai"
    base_url: str = ""

class AIConfigTestDraft(BaseModel):
    api_type: str
    base_url: str
    api_key: str = ""
    config_id: int | None = None

class FetchModelsRequest(BaseModel):
    provider: str
    api_key: str = ""
    api_type: str = "openai"
    base_url: str = ""
    config_id: int | None = None


def _normalize_base(base_url: str | None) -> str:
    """Rapikan base_url provider: buang whitespace & trailing slash.

    Gateway inference dengan route-matching ketat (mis. B.AI) menolak
    '/v1//models' (double slash akibat base_url berakhiran '/').
    """
    if not base_url:
        return ""
    return base_url.strip().rstrip("/")


def build_models_url(base_url: str | None, api_type: str) -> str:
    """URL /models untuk api_type openai; default ke api.openai.com bila kosong."""
    base = _normalize_base(base_url) or "https://api.openai.com/v1"
    return f"{base}/models"


def get_provider_label(model_id: str, user_provider: str) -> str:
    """Menentukan provider label berdasarkan nama model."""
    first_part = model_id.split('-')[0] if '-' in model_id else model_id
    mapping = {
        "deepseek": "DeepSeek",
        "qwen": "Qwen",
        "mistral": "Mistral",
        "claude": "Claude",
        "gpt": "OpenAI",
        "llama": "Meta Llama",
        "gemini": "Google Gemini",
        "stepfun": "StepFun"
    }
    return mapping.get(first_part.lower(), user_provider)


@router.get("/ai-configs")
async def get_ai_configs(user: dict = Depends(require_admin_role)):
    try:
        pool = await get_core_pool()
        rows = await pool.fetch("""
            SELECT id, scope, target_id, provider, model, temperature, api_type, base_url
            FROM ai_configs
        """)
        return [
            {
                "id": r["id"],
                "scope": r["scope"],
                "target_id": r["target_id"],
                "provider": r["provider"],
                "model": r["model"],
                "temperature": r["temperature"],
                "api_type": r["api_type"],
                "base_url": r["base_url"]
            } for r in rows
        ]
    except Exception as e:
        logger.error(f"Error fetching AI configs: {e}")
        return []

@router.post("/ai-configs")
async def create_ai_config(payload: AIConfigCreate, user: dict = Depends(require_admin_role)):
    try:
        # Validasi: scope selain global wajib punya target_id
        if payload.scope != "global" and not (payload.target_id and payload.target_id.strip()):
            raise HTTPException(status_code=400, detail="Target ID wajib diisi untuk scope tenant/user")
        pool = await get_core_pool()
        encrypted_key = encrypt_credential(payload.api_key)
        target_id_val = payload.target_id if payload.target_id else None
        await pool.execute("""
            INSERT INTO ai_configs (scope, target_id, provider, model, api_key, temperature, api_type, base_url)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
        """, payload.scope, target_id_val, payload.provider, payload.model, encrypted_key, payload.temperature, payload.api_type, payload.base_url)
        return {"message": "Konfigurasi AI berhasil disimpan"}
    except HTTPException:
        raise
    except asyncpg.exceptions.UniqueViolationError:
        raise HTTPException(status_code=400, detail="Konfigurasi dengan scope & target ini sudah ada")
    except Exception as e:
        logger.error(f"Error creating AI config: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")

@router.put("/ai-configs/{config_id}")
async def update_ai_config(config_id: int, payload: AIConfigUpdate, user: dict = Depends(require_admin_role)):
    try:
        if payload.scope != "global" and not (payload.target_id and payload.target_id.strip()):
            raise HTTPException(status_code=400, detail="Target ID wajib diisi untuk scope tenant/user")
        pool = await get_core_pool()
        target_id_val = payload.target_id if payload.target_id else None

        if payload.api_key and payload.api_key.strip():
            encrypted_key = encrypt_credential(payload.api_key)
            await pool.execute("""
                UPDATE ai_configs
                SET scope = $1, target_id = $2, provider = $3, model = $4,
                    temperature = $5, api_type = $6, base_url = $7, api_key = $8
                WHERE id = $9
            """, payload.scope, target_id_val, payload.provider, payload.model,
                payload.temperature, payload.api_type, payload.base_url, encrypted_key, config_id)
        else:
            # Update tanpa API Key
            await pool.execute("""
                UPDATE ai_configs
                SET scope = $1, target_id = $2, provider = $3, model = $4,
                    temperature = $5, api_type = $6, base_url = $7
                WHERE id = $8
            """, payload.scope, target_id_val, payload.provider, payload.model,
                payload.temperature, payload.api_type, payload.base_url, config_id)
        return {"message": "Konfigurasi berhasil diperbarui"}
    except HTTPException:
        raise
    except asyncpg.exceptions.UniqueViolationError:
        raise HTTPException(status_code=400, detail="Konfigurasi dengan scope & target ini sudah ada")
    except Exception as e:
        logger.error(f"Error updating AI config {config_id}: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")

@router.delete("/ai-configs/{config_id}")
async def delete_ai_config(config_id: int, user: dict = Depends(require_admin_role)):
    try:
        pool = await get_core_pool()
        await pool.execute("DELETE FROM ai_configs WHERE id = $1", config_id)
        return {"message": "Konfigurasi berhasil dihapus"}
    except Exception as e:
        logger.error(f"Error deleting AI config: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")

@router.post("/ai-configs/{config_id}/test")
async def test_ai_config(config_id: int, user: dict = Depends(require_admin_role)):
    pool = await get_core_pool()
    row = await pool.fetchrow("SELECT api_type, base_url, api_key FROM ai_configs WHERE id = $1", config_id)
    if not row:
        raise HTTPException(status_code=404, detail="Config tidak ditemukan")

    api_type = row["api_type"]
    base_url = row["base_url"]
    decrypted_key = decrypt_credential(row["api_key"])

    if api_type == "anthropic":
        return {"status": "connected", "message": "Anthropic tidak mendukung test otomatis"}

    url = build_models_url(row["base_url"], api_type="openai")
    headers = {"Authorization": f"Bearer {decrypted_key}"}
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(url, headers=headers)
            if resp.status_code == 200:
                return {"status": "connected", "message": "Koneksi berhasil"}
            return {"status": "disconnected", "message": f"Gagal: {resp.status_code}"}
    except Exception as e:
        return {"status": "disconnected", "message": str(e)}

@router.post("/ai-providers/models")
async def fetch_models_from_provider(payload: FetchModelsRequest, user: dict = Depends(require_admin_role)):
    pool = await get_core_pool()
    final_api_key = payload.api_key
    if not final_api_key and payload.config_id:
        row = await pool.fetchrow("SELECT api_key FROM ai_configs WHERE id = $1", payload.config_id)
        if row:
            final_api_key = decrypt_credential(row["api_key"])
        else:
            raise HTTPException(status_code=404, detail="Konfigurasi tidak ditemukan")
    elif not final_api_key and not payload.config_id:
        raise HTTPException(status_code=400, detail="API Key wajib diisi untuk mode tambah baru")

    headers = {}
    url = ""
    if payload.api_type == "openai":
        headers = {"Authorization": f"Bearer {final_api_key}"}
        url = build_models_url(payload.base_url, api_type="openai")
    elif payload.api_type == "anthropic":
        return {"provider": payload.provider, "models": []}
    else:
        raise HTTPException(status_code=400, detail="api_type tidak dikenali")

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(url, headers=headers)
            if resp.status_code != 200:
                raise HTTPException(status_code=resp.status_code, detail=f"Gagal fetch dari provider: {resp.text}")
            data = resp.json()
            raw_models = [item["id"] for item in data.get("data", [])]

            formatted_models = [
                {
                    "id": m,
                    "label": m.replace("-", " ").title(),
                    "provider": get_provider_label(m, payload.provider)
                }
                for m in raw_models
            ]
            return {"provider": payload.provider, "models": formatted_models}
    except Exception as e:
        logger.error(f"Error fetching models: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/ai-configs/test-draft")
async def test_ai_config_draft(payload: AIConfigTestDraft, user: dict = Depends(require_admin_role)):
    pool = await get_core_pool()
    final_api_key = payload.api_key
    if not final_api_key and payload.config_id:
        row = await pool.fetchrow("SELECT api_key FROM ai_configs WHERE id = $1", payload.config_id)
        if row:
            final_api_key = decrypt_credential(row["api_key"])
        else:
            raise HTTPException(status_code=404, detail="Konfigurasi tidak ditemukan")
    elif not final_api_key and not payload.config_id:
        raise HTTPException(status_code=400, detail="API Key wajib diisi untuk mode tambah baru")

    try:
        if payload.api_type == "openai":
            url = build_models_url(payload.base_url, api_type="openai")
            headers = {"Authorization": f"Bearer {final_api_key}"}
        elif payload.api_type == "anthropic":
            return {"status": "connected", "message": "Koneksi diasumsikan berhasil (manual model)."}
        else:
            return {"status": "disconnected", "message": "Tipe API tidak didukung"}

        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(url, headers=headers)
            if resp.status_code == 200:
                return {"status": "connected", "message": "Koneksi berhasil!"}
            return {"status": "disconnected", "message": f"Gagal: {resp.status_code}"}
    except Exception as e:
        return {"status": "disconnected", "message": f"Error: {str(e)}"}


async def _probe(row) -> tuple[int, dict]:
    """Tes satu config AI; tidak pernah raise — selalu return hasil."""
    try:
        api_key = decrypt_credential(row["api_key"]) if row["api_key"] else ""
        if row["api_type"] == "anthropic":
            return row["id"], {"status": "connected", "message": "Anthropic: test otomatis tidak didukung"}
        base = _normalize_base(row["base_url"]) or "https://api.openai.com/v1"
        url = f"{base}/models"
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(url, headers={"Authorization": f"Bearer {api_key}"})
        if resp.status_code == 200:
            return row["id"], {"status": "connected", "message": "Koneksi berhasil"}
        return row["id"], {"status": "disconnected", "message": f"Gagal: {resp.status_code}"}
    except Exception as e:
        return row["id"], {"status": "disconnected", "message": str(e).split("\n")[0][:120]}


@router.post("/ai-configs/test-all")
async def test_all_ai_configs(user: dict = Depends(require_admin_role)):
    """
    Tes koneksi SEMUA config AI secara paralel.
    Return: { "<config_id>": {status, message}, ... }
    """
    try:
        pool = await get_core_pool()
        rows = await pool.fetch("SELECT id, api_type, base_url, api_key FROM ai_configs")
        if not rows:
            return {}
        results = await asyncio.gather(*(_probe(r) for r in rows))
        return {str(cid): payload for cid, payload in results}
    except Exception as e:
        logger.error(f"ai-configs test-all failed: {e}")
        return {}
