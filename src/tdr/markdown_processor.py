"""
Procesamiento de archivos Markdown del motor-OCR.

Lee archivos *_texto_*.md generados por motor-OCR y consolida
el texto en bloques lógicos (por secciones/cargos).
"""

import logging
import re
from pathlib import Path
from typing import Dict, Optional

logger = logging.getLogger(__name__)


def process_motor_ocr_output(output_dir: str) -> Dict[str, str]:
    """
    Procesa archivos Markdown del motor-OCR.

    Busca el archivo *_texto_*.md más reciente en output_dir
    y consolida el texto por páginas.

    Args:
        output_dir: Directorio con outputs de motor-OCR

    Returns:
        Dict: {section_name: consolidated_text}
        - "full_text": Texto completo del documento
        - "page_X": Texto de página X (opcional, para debugging)

    Raises:
        FileNotFoundError: Si no hay archivos *_texto_*.md
    """
    output_path = Path(output_dir)
    if not output_path.exists():
        raise FileNotFoundError(f"Directorio no existe: {output_dir}")

    # Buscar archivo *_texto_*.md más reciente
    texto_files = list(output_path.glob("*/*_texto_*.md"))
    if not texto_files:
        raise FileNotFoundError(f"No hay archivos *_texto_*.md en {output_dir}")

    # Usar el más reciente
    texto_file = max(texto_files, key=lambda p: p.stat().st_mtime)
    logger.info(f"[Markdown Processor] Leyendo: {texto_file.relative_to(output_path.parent)}")

    # Parse del archivo
    content = texto_file.read_text(encoding="utf-8", errors="ignore")

    # Consolidar por páginas
    consolidated = _consolidate_pages(content)

    logger.info(f"[Markdown Processor] Consolidadas {len(consolidated)} secciones")

    return consolidated


def _consolidate_pages(content: str) -> Dict[str, str]:
    """
    Consolida páginas del archivo Markdown en un diccionario.

    Busca patrones:
    - ## Página N: inicio de nueva página
    - Acumula texto entre headers

    Returns:
        {page_X: text, full_text: all_text}
    """
    result = {}
    full_text_parts = []

    # Split por "## Página N"
    page_pattern = r"## Página (\d+)"
    pages = re.split(page_pattern, content)

    # pages = [text_before_first_page, page_num_1, text_1, page_num_2, text_2, ...]
    # Saltar elemento 0 (texto antes de primer ## Página)

    for i in range(1, len(pages), 2):
        if i + 1 < len(pages):
            page_num = int(pages[i])
            page_text = pages[i + 1].strip()

            if page_text:
                key = f"page_{page_num:03d}"
                result[key] = page_text
                full_text_parts.append(page_text)

    # Texto completo consolidado
    full_text = "\n\n".join(full_text_parts)
    result["full_text"] = full_text

    logger.debug(f"[Markdown Processor] {len(result) - 1} páginas consolidadas")

    return result


def extract_sections_by_keyword(
    text: str,
    keywords: list[str],
    context_lines: int = 3,
) -> Dict[str, str]:
    """
    Extrae secciones del texto basadas en keywords.

    Útil para identificar secciones de "Cargos", "Experiencias", etc.

    Args:
        text: Texto consolidado
        keywords: Palabras clave a buscar (ej: ["cargo", "profesional"])
        context_lines: Líneas de contexto alrededor de match

    Returns:
        {keyword: extracted_section}
    """
    result = {}
    lines = text.split("\n")

    for keyword in keywords:
        matches = []
        for i, line in enumerate(lines):
            if keyword.lower() in line.lower():
                start = max(0, i - context_lines)
                end = min(len(lines), i + context_lines + 1)
                section = "\n".join(lines[start:end])
                matches.append(section)

        if matches:
            result[keyword] = "\n\n---\n\n".join(matches)

    return result


def clean_markdown_text(text: str) -> str:
    """
    Limpia texto extraído de Markdown.

    Elimina:
    - Saltos de línea excesivos
    - Espacios innecesarios
    - Caracteres de control
    - Líneas vacías múltiples
    """
    # Remove control characters
    text = re.sub(r"[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]", " ", text)

    # Collapse multiple newlines
    text = re.sub(r"\n\n\n+", "\n\n", text)

    # Collapse multiple spaces
    text = re.sub(r"  +", " ", text)

    # Strip leading/trailing whitespace per line
    lines = [line.strip() for line in text.split("\n")]
    text = "\n".join(lines)

    return text.strip()
