from __future__ import annotations
import json
import logging
import re
import time
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


# Patrones que indican que el LLM fabricó datos en vez de extraerlos
_FABRICATION_PATTERNS = [
    r"\bejemplo\b",
    r"\bplantilla\b",
    r"\bpodría ser\b",
    r"\basumiendo\b",
    r"\bgenéric[oa]\b",
    r"\bno se proporcion[aó]\b",
    r"\bno se especific[aó]\b",
    r"\bno se mencion[aó]\b",
    r"\bpara completar\b",
    r"\bnecesitar[ií]amos\b",
    r"\bproporcion[ae]s? más detalles\b",
    r"\bajust[aá][rd][oa]? según\b",
    r"\bcargo similar [A-Z]\b",
]


def _es_respuesta_fabricada(raw_response: str) -> bool:
    """Detecta si el LLM generó un 'ejemplo' en vez de extraer datos reales."""
    texto = raw_response.lower()
    for pattern in _FABRICATION_PATTERNS:
        if re.search(pattern, texto, re.IGNORECASE):
            return True
    return False


def extraer_bloque(block: Block) -> tuple[Optional[dict], dict]:
    """
    Envía un bloque ya clasificado a Qwen y retorna el JSON extraído
    junto con información diagnóstica de la interacción.

    Returns:
        (parsed_result_or_None, diagnostic_info_dict)
    """
    diag = {
        "block_type": block.block_type,
        "page_range": list(block.page_range),
        "pages_included": [p.page_num for p in block.pages],
        "prompt_chars": 0,
        "text_preview": block.text[:2000],
        "raw_response": "",
        "cleaned_response": "",
        "parsed_ok": False,
        "parsed_keys": [],
        "items_extracted": 0,
        "error": "",
    }

    prompt_template = PROMPTS.get(block.block_type)
    if not prompt_template:
        diag["error"] = f"Sin prompt para tipo: {block.block_type}"
        logger.warning(f"[llm] {diag['error']}")
        return None, diag

    prompt = prompt_template.format(texto=block.text)
    diag["prompt_chars"] = len(prompt)

    logger.info(
        f"[llm] Enviando bloque '{block.block_type}' "
        f"págs {block.page_range} ({len(prompt)} chars)"
    )

    try:
        client = _get_client()
        t0 = time.perf_counter()
        response = client.chat.completions.create(
            model=QWEN_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
            max_tokens=QWEN_MAX_TOKENS,
        )
        elapsed = time.perf_counter() - t0
    except Exception as e:
        diag["error"] = f"Qwen falló: {e}"
        logger.warning(f"[llm] {diag['error']}")
        return None, diag

    raw = response.choices[0].message.content.strip()
    diag["raw_response"] = raw

    # ── Métricas de rendimiento ──────────────────────────────────────────
    usage = getattr(response, "usage", None)
    prompt_tokens = getattr(usage, "prompt_tokens", 0) if usage else 0
    completion_tokens = getattr(usage, "completion_tokens", 0) if usage else 0
    total_tokens = prompt_tokens + completion_tokens
    tps = completion_tokens / elapsed if elapsed > 0 and completion_tokens > 0 else 0

    # GPU: ~20-40 tok/s para 14b | CPU/RAM: ~2-5 tok/s
    dispositivo = "GPU" if tps > 10 else "CPU/RAM" if tps > 0 else "?"
    logger.info(
        f"[llm] ✓ '{block.block_type}' págs {block.page_range}: "
        f"{elapsed:.1f}s · {completion_tokens} tokens · "
        f"{tps:.1f} tok/s ({dispositivo}) · "
        f"prompt={prompt_tokens}tok resp={completion_tokens}tok"
    )

    # Detectar respuestas fabricadas ANTES de limpiar/parsear
    if _es_respuesta_fabricada(raw):
        diag["error"] = "Respuesta fabricada detectada (ejemplo/plantilla)"
        logger.warning(
            f"[llm] Bloque '{block.block_type}' págs {block.page_range}: "
            f"respuesta fabricada descartada"
        )
        # Devolver resultado vacío según tipo
        empty = {
            "rtm_postor": {"items_concurso": []},
            "rtm_personal": {"personal_clave": []},
            "factores_evaluacion": {"factores_evaluacion": []},
        }.get(block.block_type, {})
        return empty, diag

    raw = _limpiar_respuesta(raw)
    diag["cleaned_response"] = raw

    try:
        result = json.loads(raw)
        result["_meta"] = {
            "block_type": block.block_type,
            "page_range": list(block.page_range),
        }
        diag["parsed_ok"] = True
        diag["parsed_keys"] = [k for k in result.keys() if not k.startswith("_")]

        # Contar items extraídos según tipo de bloque
        if block.block_type == "rtm_postor":
            diag["items_extracted"] = len(result.get("items_concurso", []))
        elif block.block_type == "rtm_personal":
            diag["items_extracted"] = len(result.get("personal_clave", []))
        elif block.block_type == "factores_evaluacion":
            diag["items_extracted"] = len(result.get("factores_evaluacion", []))

        return result, diag
    except json.JSONDecodeError as e:
        diag["error"] = f"JSON inválido: {e} — raw: {raw[:200]!r}"
        logger.warning(f"[llm] {diag['error']}")
        return None, diag