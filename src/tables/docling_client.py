"""
Cliente Docling para detección y localización de tablas.

Usa Docling SOLO como confirmador: ¿hay tabla en esta página? + bbox.
No se usa el texto extraído por Docling — solo la geometría.

Docling trabaja con imágenes de página, no directamente con el PDF.
Flujo: PyMuPDF extrae imagen → guarda temp PNG → Docling analiza.
"""

from __future__ import annotations
import logging
import tempfile
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class TablaDetectada:
    pagina: int                                     # 1-based
    bbox: tuple[float, float, float, float]         # (x1, y1, x2, y2) en pixeles de la imagen
    num_filas: int
    num_columnas: int
    confianza: float                                # 0.0–1.0


def confirmar_tablas(
    imagenes_pagina: dict[int, "Image.Image"],
) -> list[TablaDetectada]:
    """
    Ejecuta Docling sobre imágenes de páginas específicas.
    Retorna lista de TablaDetectada con bbox en coordenadas de imagen.

    Args:
        imagenes_pagina: Dict {num_pagina: imagen_PIL}

    Returns:
        Lista de tablas confirmadas con su bbox y metadata
    """
    try:
        from docling.document_converter import DocumentConverter
    except ImportError:
        logger.warning(
            "[docling] docling no está instalado. "
            "Saltando confirmación de tablas. "
            "Instalar con: pip install docling"
        )
        return []

    logger.info(f"[docling] Analizando {len(imagenes_pagina)} páginas para tablas")

    converter = DocumentConverter()
    tablas: list[TablaDetectada] = []

    for pag_num, imagen in sorted(imagenes_pagina.items()):
        try:
            # Guardar imagen temporal para Docling
            with tempfile.NamedTemporaryFile(
                suffix=".png", delete=False, prefix=f"docling_pag{pag_num}_"
            ) as tmp:
                imagen.save(tmp.name, "PNG")
                tmp_path = tmp.name

            # Docling analiza la imagen
            result = converter.convert(tmp_path)
            doc_dict = result.document.export_to_dict()

            # Buscar tablas en el dict exportado
            tablas_pagina = _extraer_tablas_de_dict(doc_dict, pag_num)
            tablas.extend(tablas_pagina)

            if tablas_pagina:
                logger.info(
                    f"[docling] Pág {pag_num}: {len(tablas_pagina)} tabla(s) detectada(s)"
                )
            else:
                logger.debug(f"[docling] Pág {pag_num}: sin tablas")

        except Exception as e:
            logger.warning(f"[docling] Error en pág {pag_num}: {e}")
            continue
        finally:
            Path(tmp_path).unlink(missing_ok=True)

    logger.info(
        f"[docling] Total: {len(tablas)} tablas confirmadas "
        f"en {len(imagenes_pagina)} páginas"
    )
    return tablas


def _extraer_tablas_de_dict(
    doc_dict: dict,
    pag_num: int,
) -> list[TablaDetectada]:
    """
    Extrae información de tablas del dict exportado por Docling.

    Busca elementos de tipo 'table' en la estructura del documento
    y extrae su bbox y dimensiones.
    """
    tablas = []

    # Docling estructura: body → items con type "table"
    body = doc_dict.get("body", doc_dict.get("main_text", []))
    if isinstance(body, dict):
        body = body.get("children", [])

    for item in _recorrer_items(doc_dict):
        item_type = item.get("type", "")
        if "table" not in item_type.lower():
            continue

        # Extraer bbox de prov (provenance)
        prov_list = item.get("prov", [])
        bbox = None
        for prov in prov_list:
            bbox_data = prov.get("bbox", {})
            if isinstance(bbox_data, dict):
                bbox = (
                    bbox_data.get("l", bbox_data.get("x", 0)),
                    bbox_data.get("t", bbox_data.get("y", 0)),
                    bbox_data.get("r", bbox_data.get("x", 0) + bbox_data.get("width", 0)),
                    bbox_data.get("b", bbox_data.get("y", 0) + bbox_data.get("height", 0)),
                )
            elif isinstance(bbox_data, (list, tuple)) and len(bbox_data) == 4:
                bbox = tuple(bbox_data)

        if bbox is None:
            bbox = (0, 0, 0, 0)

        # Contar filas y columnas
        data = item.get("data", {})
        grid = data.get("grid", data.get("table_cells", []))
        num_filas = 0
        num_cols = 0
        if isinstance(grid, list) and grid:
            if isinstance(grid[0], list):
                num_filas = len(grid)
                num_cols = max(len(row) for row in grid) if grid else 0
            else:
                # Flat list of cells con row/col info
                rows = set()
                cols = set()
                for cell in grid:
                    if isinstance(cell, dict):
                        rows.add(cell.get("row", cell.get("row_index", 0)))
                        cols.add(cell.get("col", cell.get("col_index", 0)))
                num_filas = len(rows)
                num_cols = len(cols)

        tablas.append(TablaDetectada(
            pagina=pag_num,
            bbox=bbox,
            num_filas=num_filas,
            num_columnas=num_cols,
            confianza=1.0,
        ))

    return tablas


def _recorrer_items(doc_dict: dict) -> list[dict]:
    """Recorre recursivamente la estructura de Docling buscando items."""
    items = []

    # Intentar diferentes claves según versión de Docling
    for key in ("body", "main_text", "furniture", "tables"):
        contenido = doc_dict.get(key, [])
        if isinstance(contenido, list):
            items.extend(contenido)
        elif isinstance(contenido, dict):
            children = contenido.get("children", [])
            if isinstance(children, list):
                items.extend(children)

    # Recursión en children
    resultado = []
    for item in items:
        resultado.append(item)
        children = item.get("children", [])
        if isinstance(children, list):
            for child in children:
                if isinstance(child, dict):
                    resultado.append(child)

    return resultado


def check_docling_available() -> bool:
    """Verifica si Docling está instalado."""
    try:
        from docling.document_converter import DocumentConverter  # noqa: F401
        return True
    except ImportError:
        return False
