"""
Cliente Qwen VL para lectura visual de tablas.

Envía imágenes recortadas de tablas a qwen2.5vl:7b vía Ollama
y recibe markdown estructurado con |col1|col2|...
"""

from __future__ import annotations
import base64
import io
import logging
import time
from typing import Optional

import requests
from PIL import Image

from src.config.settings import (
    QWEN_VL_MODEL,
    QWEN_VL_TIMEOUT,
    OLLAMA_BASE_URL,
    TABLE_VL_MAX_PX,
)

logger = logging.getLogger(__name__)


def _redimensionar(imagen: Image.Image, max_px: int = TABLE_VL_MAX_PX) -> Image.Image:
    """Redimensiona imagen si el lado más largo supera max_px."""
    w, h = imagen.size
    lado_max = max(w, h)
    if lado_max <= max_px:
        return imagen
    escala = max_px / lado_max
    nuevo_w = int(w * escala)
    nuevo_h = int(h * escala)
    return imagen.resize((nuevo_w, nuevo_h), Image.LANCZOS)


def _imagen_a_base64(imagen: Image.Image) -> str:
    """Redimensiona y convierte imagen PIL a base64 JPEG para enviar a Ollama."""
    imagen = _redimensionar(imagen)
    # Convertir a RGB si tiene canal alpha (JPEG no soporta transparencia)
    if imagen.mode in ("RGBA", "LA", "P"):
        imagen = imagen.convert("RGB")
    buffer = io.BytesIO()
    imagen.save(buffer, format="JPEG", quality=85)
    return base64.b64encode(buffer.getvalue()).decode("utf-8")


# Prompt para tabla individual
_PROMPT_TABLA_UNICA = """Extract the table EXACTLY as seen in the image.

Rules:
- Preserve the exact number of columns and rows
- Do NOT merge or split columns
- Do NOT infer or guess missing values — write [UNCLEAR] if text is unreadable
- Ignore watermarks, stamps, dates, and background noise (e.g. "QUISPE", "HERSON", timestamps)
- Output ONLY a markdown table using | format
- Include a header row with | --- | separators
- No explanations before or after the table"""

# Prompt para tabla cross-page (múltiples imágenes)
_PROMPT_TABLA_CROSSPAGE = """The following images are consecutive pages of the SAME table that spans multiple pages.

Rules:
- Merge them into ONE single markdown table
- Preserve row order across pages
- Do NOT repeat header rows — use the header from the first page only
- Do NOT infer or guess missing values — write [UNCLEAR] if text is unreadable
- Ignore watermarks, stamps, dates, and background noise
- Output ONLY a markdown table using | format
- Include a header row with | --- | separators
- No explanations before or after the table"""


def leer_tabla_visual(imagen: Image.Image) -> Optional[str]:
    """
    Envía una imagen recortada de tabla a Qwen VL.

    Args:
        imagen: Imagen PIL de la tabla recortada

    Returns:
        Markdown con |col1|col2|... o None si falla
    """
    return _llamar_qwen_vl([imagen], _PROMPT_TABLA_UNICA)


def leer_tabla_crosspage(imagenes: list[Image.Image]) -> Optional[str]:
    """
    Envía múltiples imágenes de una tabla que cruza páginas a Qwen VL.

    Args:
        imagenes: Lista de imágenes PIL (una por página, en orden)

    Returns:
        Markdown unificado con |col1|col2|... o None si falla
    """
    if len(imagenes) == 1:
        return leer_tabla_visual(imagenes[0])

    return _llamar_qwen_vl(imagenes, _PROMPT_TABLA_CROSSPAGE)


def _llamar_qwen_vl(
    imagenes: list[Image.Image],
    prompt: str,
) -> Optional[str]:
    """
    Llamada directa a Ollama API (no OpenAI compat) para enviar imágenes.

    Ollama /api/chat soporta imágenes como base64 en el campo "images".
    """
    imgs_resized = [_redimensionar(img) for img in imagenes]
    images_b64 = [_imagen_a_base64(img) for img in imagenes]

    px_orig = sum(img.width * img.height for img in imagenes)
    px_resized = sum(img.width * img.height for img in imgs_resized)
    logger.info(
        f"[qwen-vl] Enviando {len(imagenes)} imagen(es) "
        f"({px_orig} px orig → {px_resized} px resized)"
    )

    payload = {
        "model": QWEN_VL_MODEL,
        "messages": [
            {
                "role": "user",
                "content": prompt,
                "images": images_b64,
            }
        ],
        "stream": False,
        "options": {
            "temperature": 0,
            "num_predict": 2048,
            "num_ctx": 8192,
        },
    }

    max_reintentos = 2
    for intento in range(max_reintentos + 1):
        try:
            resp = requests.post(
                f"{OLLAMA_BASE_URL}/api/chat",
                json=payload,
                timeout=QWEN_VL_TIMEOUT,
            )
            resp.raise_for_status()
            data = resp.json()

            contenido = data.get("message", {}).get("content", "").strip()

            # Limpiar bloques markdown (```markdown ... ```)
            if contenido.startswith("```"):
                lineas = contenido.split("\n")
                # Remover primera y última línea si son ```
                if lineas[0].startswith("```"):
                    lineas = lineas[1:]
                if lineas and lineas[-1].strip() == "```":
                    lineas = lineas[:-1]
                contenido = "\n".join(lineas).strip()

            if "|" not in contenido:
                logger.warning("[qwen-vl] Respuesta no contiene tabla markdown")
                return None

            logger.info(f"[qwen-vl] Tabla recibida: {len(contenido)} chars")
            return contenido

        except requests.Timeout:
            logger.error(f"[qwen-vl] Timeout después de {QWEN_VL_TIMEOUT}s")
            return None
        except requests.HTTPError as e:
            if resp.status_code == 500 and intento < max_reintentos:
                wait = 5 * (intento + 1)
                logger.warning(
                    f"[qwen-vl] 500 en intento {intento + 1}/{max_reintentos + 1}, "
                    f"reintentando en {wait}s..."
                )
                time.sleep(wait)
                continue
            logger.error(f"[qwen-vl] Error: {e}")
            return None
        except Exception as e:
            logger.error(f"[qwen-vl] Error: {e}")
            return None

    return None
