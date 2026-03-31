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


def _reparar_json(raw: str) -> Optional[dict]:
    """
    Intenta reparar JSON malformado del LLM.

    Reparaciones (en orden):
    1. Coma faltante entre objetos: }{ → },{
    2. Coma faltante entre valor y llave: "valor"  "llave" → "valor", "llave"
    3. Comas trailing antes de cierre: ,} → }  ,] → ]
    4. Cerrar brackets/braces sin cerrar
    """
    # 1. Coma faltante entre objetos en arrays: } { o }\n{
    fixed = re.sub(r"\}\s*\{", "},{", raw)

    # 2. Coma faltante entre string/number y nueva key:
    #    "valor"  "key"  →  "valor", "key"
    #    123  "key"      →  123, "key"
    #    null  "key"     →  null, "key"
    #    true  "key"     →  true, "key"
    fixed = re.sub(
        r'("|\d|null|true|false)\s*\n\s*"', r'\1,\n"', fixed
    )

    # 3. Trailing commas
    fixed = re.sub(r",\s*([}\]])", r"\1", fixed)

    # 4. Cerrar brackets/braces sin cerrar
    open_braces = fixed.count("{") - fixed.count("}")
    open_brackets = fixed.count("[") - fixed.count("]")
    if open_braces > 0:
        fixed = fixed.rstrip() + "}" * open_braces
    if open_brackets > 0:
        fixed = fixed.rstrip() + "]" * open_brackets

    try:
        return json.loads(fixed)
    except json.JSONDecodeError:
        return None


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
            extra_body={
                "keep_alive": "10m",
                "options": {"num_gpu": 99},
            },
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

    # Velocidad de prefill (prompt processing) — indicador real de GPU vs CPU
    # GPU 14b: ~300-1000 tok/s prefill | CPU/RAM: ~30-100 tok/s
    prefill_tps = prompt_tokens / elapsed if elapsed > 0 and prompt_tokens > 0 else 0
    dispositivo = "GPU" if prefill_tps > 200 else "CPU/RAM" if prefill_tps > 0 else "?"
    logger.info(
        f"[llm] ✓ '{block.block_type}' págs {block.page_range}: "
        f"{elapsed:.1f}s · prefill={prefill_tps:.0f} tok/s ({dispositivo}) · "
        f"prompt={prompt_tokens}tok resp={completion_tokens}tok"
    )

    # Detectar respuestas fabricadas en el preámbulo (texto ANTES del JSON).
    # No se verifica el JSON completo porque los valores extraídos del documento
    # pueden contener legítimamente palabras como "ejemplo" en las descripciones.
    # El LLM a veces añade un párrafo meta-comentario DESPUÉS del JSON válido
    # ("Este es un ejemplo para el primer cargo...") que no debe descartar el resultado.
    _pre_json = raw[: raw.find("{")] if "{" in raw else raw
    if _es_respuesta_fabricada(_pre_json):
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
        logger.warning(
            f"[llm] JSON inválido en '{block.block_type}' págs {block.page_range}: {e}"
        )
        # Intentar reparación automática
        repaired = _reparar_json(raw)
        if repaired is not None:
            logger.info(
                f"[llm] ✓ JSON reparado para '{block.block_type}' págs {block.page_range}"
            )
            repaired["_meta"] = {
                "block_type": block.block_type,
                "page_range": list(block.page_range),
            }
            diag["parsed_ok"] = True
            diag["parsed_keys"] = [k for k in repaired.keys() if not k.startswith("_")]
            diag["error"] = f"JSON reparado (error original: {e})"

            if block.block_type == "rtm_postor":
                diag["items_extracted"] = len(repaired.get("items_concurso", []))
            elif block.block_type == "rtm_personal":
                diag["items_extracted"] = len(repaired.get("personal_clave", []))
            elif block.block_type == "factores_evaluacion":
                diag["items_extracted"] = len(repaired.get("factores_evaluacion", []))

            return repaired, diag

        diag["error"] = f"JSON inválido (reparación falló): {e} — raw: {raw[:200]!r}"
        logger.warning(f"[llm] {diag['error']}")
        return None, diag