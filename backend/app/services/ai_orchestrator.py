import httpx
import json
from fastapi import HTTPException
import logging

logger = logging.getLogger(__name__)


def build_chat_url(ai_config: dict) -> str:
    """URL endpoint chat sesuai api_type, dengan base_url ternormalisasi.

    Base_url berakhiran '/' menghasilkan double-slash ('/v1//chat/completions')
    yang ditolak gateway dengan route-matching ketat (mis. B.AI).
    """
    api_type = ai_config.get("api_type", "openai")
    base_url = (ai_config.get("base_url") or "").strip().rstrip("/")

    if api_type == "openai":
        return f"{base_url}/chat/completions" if base_url else "https://api.openai.com/v1/chat/completions"
    if api_type == "anthropic":
        return f"{base_url}/messages" if base_url else "https://api.anthropic.com/v1/messages"
    raise HTTPException(status_code=400, detail="api_type tidak dikenali. Harus 'openai' atau 'anthropic'.")


async def generate_json_filter(user_prompt: str, schema: dict, ai_config: dict):
    """
    Memanggil AI Provider berdasarkan api_type dan base_url yang dikonfigurasi.
    ai_config berisi: provider, model, api_key, temperature, api_type, base_url
    """
    api_type = ai_config.get("api_type", "openai")
    base_url = ai_config.get("base_url", "")
    api_key = ai_config.get("api_key")
    model = ai_config.get("model")
    temperature = ai_config.get("temperature", 0.7)

    # 1. Siapkan headers dan URL berdasarkan api_type
    headers = {"Content-Type": "application/json"}
    url = ""
    payload = {}

    if api_type == "openai":
        # OpenAI Compatible Gateway
        headers["Authorization"] = f"Bearer {api_key}"
        url = build_chat_url(ai_config)
        
        # System Prompt untuk OpenAI
        system_prompt = (
            "Anda adalah AI SQL Expert untuk DMS. Anda HANYA boleh mengembalikan JSON. "
            "JANGAN pernah menulis SQL mentah. Format JSON: { table: string, columns: list, filters: object }."
        )
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"Pertanyaan: {user_prompt}\nSkema Tabel: {schema}"}
            ],
            "temperature": temperature,
            "response_format": {"type": "json_object"}
        }
    elif api_type == "anthropic":
        # Anthropic / Claude Gateway
        headers["x-api-key"] = api_key
        headers["anthropic-version"] = "2023-06-01"
        url = build_chat_url(ai_config)
        
        # System Prompt untuk Anthropic
        system_prompt = (
            "Anda adalah AI SQL Expert untuk DMS. Anda HANYA boleh mengembalikan JSON. "
            "JANGAN pernah menulis SQL mentah. Format JSON: { table: string, columns: list, filters: object }."
        )
        payload = {
            "model": model,
            "system": system_prompt,
            "messages": [{"role": "user", "content": f"Pertanyaan: {user_prompt}\nSkema Tabel: {schema}"}],
            "temperature": temperature,
            "max_tokens": 4096
        }
    else:
        raise HTTPException(status_code=400, detail="api_type tidak dikenali. Harus 'openai' atau 'anthropic'.")

    # 2. Lakukan panggilan HTTP ke AI Gateway
    content = ""  # di-init agar handler JSONDecodeError aman walau resp.json() gagal
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(url, headers=headers, json=payload)
            if resp.status_code != 200:
                logger.error(f"AI API Error: {resp.text}")
                raise HTTPException(status_code=503, detail="Layanan AI sedang tidak tersedia atau quota habis. Silakan hubungi admin.")

            data = resp.json()
            # Ekstrak konten dari response (OpenAI vs Anthropic)
            content = ""
            if api_type == "openai":
                content = data["choices"][0]["message"]["content"]
            elif api_type == "anthropic":
                content = data["content"][0]["text"]

            # Parse JSON yang dikembalikan AI
            return json.loads(content)
    except HTTPException:
        # Jangan telan error yang sengaja kita raise di atas
        # (detail asli seperti "quota habis" harus sampai ke client)
        raise
    except json.JSONDecodeError:
        logger.error(f"AI returned invalid JSON: {content[:500]}")
        raise HTTPException(status_code=500, detail="AI mengembalikan format JSON yang tidak valid.")
    except (httpx.TimeoutException, httpx.ConnectError) as e:
        logger.error(f"AI gateway unreachable: {e}")
        raise HTTPException(status_code=503, detail="Layanan AI tidak dapat dihubungi (timeout/koneksi).")
    except Exception as e:
        logger.error(f"AI Orchestrator Error: {e}")
        raise HTTPException(status_code=503, detail="Layanan AI sedang tidak tersedia.")