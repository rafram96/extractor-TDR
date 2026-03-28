"""
Cliente Ollama para extracción TDR.

Usa OpenAI SDK apuntando a Ollama local.
Temperatura 0 para resultados determinísticos.
"""

import json
import logging
import time

from openai import OpenAI

logger = logging.getLogger(__name__)

# ─── CONFIGURACIÓN ────────────────────────────────────────────────────────────
OLLAMA_BASE_URL = "http://localhost:11434/v1"
OLLAMA_API_KEY  = "ollama"
DEFAULT_MODEL   = "qwen2.5:14b"

RETRY_ATTEMPTS  = 3
RETRY_DELAY     = 5   # segundos entre reintentos
# ──────────────────────────────────────────────────────────────────────────────

client = OpenAI(base_url=OLLAMA_BASE_URL, api_key=OLLAMA_API_KEY)


SYSTEM_PROMPT = """Eres un extractor especializado en criterios técnicos de bases de concursos de obras públicas en Perú.
Tu única tarea es leer el texto de las bases y devolver un JSON estructurado con los datos solicitados.
No expliques nada, no agregues texto fuera del JSON, solo devuelve el JSON solicitado."""


def call_llm(
    prompt: str,
    system_prompt: str = SYSTEM_PROMPT,
    model: str = DEFAULT_MODEL,
    max_retries: int = RETRY_ATTEMPTS,
) -> dict:
    """
    Llama al LLM vía OpenAI SDK (apuntando a Ollama) y retorna JSON parseado.

    Args:
        prompt: Prompt del usuario formateado
        system_prompt: Prompt del sistema (rol)
        model: Modelo Ollama (default: qwen2.5:14b)
        max_retries: Máximo número de intentos

    Returns:
        Dict parseado de JSON

    Raises:
        RuntimeError: Si no puede obtener respuesta válida
    """
    for intento in range(max_retries):
        try:
            logger.debug(f"[Ollama] Intento {intento + 1}/{max_retries}...")

            response = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user",   "content": prompt},
                ],
                temperature=0,
                response_format={"type": "json_object"},
            )

            raw = response.choices[0].message.content.strip()

            # Limpiar tags de pensamiento si el modelo los genera
            if "</think>" in raw:
                raw = raw.split("</think>")[-1].strip()

            if not raw:
                raise ValueError("Respuesta vacía del LLM")

            result = json.loads(raw)
            logger.debug(f"[Ollama] Respuesta válida ({len(raw)} chars)")
            return result

        except json.JSONDecodeError as e:
            logger.error(f"[Ollama] JSON inválido: {raw[:300]}")
            raise RuntimeError(f"LLM no devolvió JSON válido:\n{raw[:500]}") from e

        except Exception as e:
            if intento < max_retries - 1:
                logger.warning(
                    f"[Ollama] Error en intento {intento + 1}/{max_retries}: {e}"
                )
                logger.info(f"[Ollama] Reintentando en {RETRY_DELAY}s...")
                time.sleep(RETRY_DELAY)
            else:
                logger.error(f"[Ollama] Falló tras {max_retries} intentos: {e}")
                raise RuntimeError(
                    f"LLM no respondió tras {max_retries} intentos: {e}"
                )


def check_ollama_available() -> bool:
    """Verifica si Ollama está disponible y tiene el modelo cargado."""
    try:
        models = client.models.list()
        model_ids = [m.id for m in models.data]
        disponible = DEFAULT_MODEL in model_ids
        if not disponible:
            logger.warning(
                f"[Ollama] Modelo {DEFAULT_MODEL} no encontrado. "
                f"Disponibles: {model_ids}"
            )
        return disponible
    except Exception as e:
        logger.warning(f"[Ollama] No disponible: {e}")
        return False
