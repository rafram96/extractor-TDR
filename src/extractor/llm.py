from __future__ import annotations
import json
import logging
from typing import Optional

from openai import OpenAI

from src.config.settings import (
    QWEN_OLLAMA_BASE_URL, QWEN_OLLAMA_API_KEY,
    QWEN_MODEL, QWEN_MAX_TOKENS, QWEN_TIMEOUT,
)
from src.config.signals import PROMPTS
from src.extractor.scorer import Block

logger = logging.getLogger(__name__)

_client: Optional[OpenAI] = None


def _get_client() -> OpenAI:
    global _client
    if _client is None:
        _client = OpenAI(
            base_url=QWEN_OLLAMA_BASE_URL,
            api_key=QWEN_OLLAMA_API_KEY,
            timeout=QWEN_TIMEOUT,
        )
    return _client


def _limpiar_respuesta(raw: str) -> str:
    """Limpia </think>, texto previo, y bloques markdown."""
    # 1. Quitar bloque <think>...</think>
    if "</think>" in raw:
        raw = raw.split("</think>")[-1].strip()

    # 2. Buscar bloque ```json ... ``` en CUALQUIER parte de la respuesta
    #    (Qwen a veces mete "Basándome en..." antes del JSON)
    import re
    match = re.search(r"```(?:json)?\s*\n?(\{.*?})\s*```", raw, re.DOTALL)
    if match:
        return match.group(1).strip()

    # 3. Buscar el primer { ... } directo (sin bloque markdown)
    brace_start = raw.find("{")
    if brace_start > 0:
        raw = raw[brace_start:]

    # 4. Limpiar backticks sueltos
    raw = raw.strip("`").strip()
    if raw.startswith("json"):
        raw = raw[4:].strip()
    return raw


def extraer_bloque(block: Block) -> Optional[dict]:
    """
    Envía un bloque ya clasificado a Qwen y retorna el JSON extraído.
    Retorna None si Qwen falla o devuelve JSON inválido.
    """
    prompt_template = PROMPTS.get(block.block_type)
    if not prompt_template:
        logger.warning(f"[llm] Sin prompt para tipo: {block.block_type}")
        return None

    prompt = prompt_template.format(texto=block.text)
    logger.info(
        f"[llm] Enviando bloque '{block.block_type}' "
        f"págs {block.page_range} ({len(prompt)} chars)"
    )

    try:
        client = _get_client()
        response = client.chat.completions.create(
            model=QWEN_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
            max_tokens=QWEN_MAX_TOKENS,
        )
    except Exception as e:
        logger.warning(f"[llm] Qwen falló: {e}")
        return None

    raw = response.choices[0].message.content.strip()
    raw = _limpiar_respuesta(raw)

    try:
        result = json.loads(raw)
        result["_meta"] = {
            "block_type": block.block_type,
            "page_range": list(block.page_range),
        }
        return result
    except json.JSONDecodeError as e:
        logger.warning(f"[llm] JSON inválido: {e} — raw: {raw[:200]!r}")
        return None