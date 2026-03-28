"""
Lectura de PDFs: intenta pdfplumber primero, fallback a motor-OCR para escaneados.
"""

import logging
from pathlib import Path
from typing import Optional

import pdfplumber

from .motor_ocr_client import check_motor_ocr_available, invoke_motor_ocr

logger = logging.getLogger(__name__)


def read_pdf(
    pdf_path: str,
    output_dir: Optional[str] = None,
    min_chars_per_page: int = 200,
) -> str:
    """
    Lee PDF (digital o escaneado) y retorna texto consolidado.

    Estrategia:
    1. Intenta pdfplumber (PDF digital con texto)
    2. Si texto < min_chars_per_page * num_páginas → motor-OCR (PDF escaneado)
    3. Return: Texto consolidado

    Args:
        pdf_path: Ruta absoluta del PDF
        output_dir: Directorio para motor-OCR output. Default: D:\proyectos\infoobras\ocr_output
        min_chars_per_page: Umbral para decidir si es escaneado (default 200)

    Returns:
        Texto extraído consolidado

    Raises:
        FileNotFoundError: Si PDF no existe
        RuntimeError: Si ambas estrategias fallan
    """
    pdf_path = Path(pdf_path)
    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF no existe: {pdf_path}")

    logger.info(f"[PDF Reader] Procesando {pdf_path.name}")

    # Estrategia 1: pdfplumber
    text = _read_with_pdfplumber(str(pdf_path))

    if _is_sufficient_text(text, pdf_path):
        logger.info("[PDF Reader] ✓ Texto suficiente extraído con pdfplumber")
        return text

    # Estrategia 2: motor-OCR fallback
    logger.info("[PDF Reader] ⊘ Texto insuficiente, activando motor-OCR...")

    if not check_motor_ocr_available():
        raise RuntimeError(
            "motor-OCR no disponible y pdfplumber insuficiente. "
            "Verificar motor-OCR repo."
        )

    if output_dir is None:
        output_dir = r"D:\proyectos\infoobras\ocr_output"

    text = invoke_motor_ocr(str(pdf_path), output_dir)

    logger.info(f"[PDF Reader] ✓ Texto extraído con motor-OCR ({len(text)} chars)")

    return text


def _read_with_pdfplumber(pdf_path: str) -> str:
    """Lee PDF con pdfplumber (texto digital)."""
    try:
        with pdfplumber.open(pdf_path) as pdf:
            pages = pdf.pages
            total_pages = len(pages)

            # Extrae texto de cada página
            texts = []
            for i, page in enumerate(pages, 1):
                try:
                    page_text = page.extract_text() or ""
                    texts.append(page_text)
                except Exception as e:
                    logger.warning(f"[pdfplumber] Error en página {i}: {e}")
                    texts.append("")

        full_text = "\n".join(texts)
        logger.debug(
            f"[pdfplumber] Extraído: {total_pages} páginas, {len(full_text)} chars"
        )

        return full_text

    except Exception as e:
        logger.warning(f"[pdfplumber] No pudo abrir PDF: {e}")
        return ""


def _is_sufficient_text(text: str, pdf_path: Path, min_chars_per_page: int = 200) -> bool:
    """
    Verifica si el texto extraído es suficiente (no es escaneado).

    Heurística: si promedio de chars por página > min_chars_per_page,
    probablemente es PDF digital con texto.
    """
    if not text or not text.strip():
        return False

    try:
        with pdfplumber.open(str(pdf_path)) as pdf:
            num_pages = len(pdf.pages)
    except Exception:
        return len(text) > min_chars_per_page * 5  # fallback estimate

    chars_per_page = len(text) / num_pages if num_pages > 0 else 0

    is_sufficient = chars_per_page >= min_chars_per_page

    logger.debug(
        f"[PDF Analysis] {num_pages} páginas, "
        f"{len(text)} chars total, "
        f"{chars_per_page:.0f} chars/página "
        f"(umbral: {min_chars_per_page}) → {'✓ Suficiente' if is_sufficient else '⊘ Insuficiente'}"
    )

    return is_sufficient
