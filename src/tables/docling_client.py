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
        tmp_path = None
        try:
            # Guardar imagen temporal para Docling
            with tempfile.NamedTemporaryFile(
                suffix=".png", delete=False, prefix=f"docling_pag{pag_num}_"
            ) as tmp:
                imagen.save(tmp.name, "PNG")
                tmp_path = tmp.name

            # Docling analiza la imagen
            result = converter.convert(tmp_path)

            # ── Estrategia 1: API directa (Docling v2+) ──
            tablas_pagina = _extraer_via_api(result, pag_num)

            # ── Estrategia 2: fallback al dict si la API no devolvió nada ──
            if not tablas_pagina:
                doc_dict = result.document.export_to_dict()
                tablas_pagina = _extraer_de_dict(doc_dict, pag_num)

                # Debug: si aún no encontramos tablas, log de la estructura
                if not tablas_pagina:
                    _debug_estructura(result, doc_dict, pag_num)

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
            if tmp_path:
                Path(tmp_path).unlink(missing_ok=True)

    logger.info(
        f"[docling] Total: {len(tablas)} tablas confirmadas "
        f"en {len(imagenes_pagina)} páginas"
    )
    return tablas


def _extraer_via_api(result, pag_num: int) -> list[TablaDetectada]:
    """
    Extrae tablas usando la API directa de Docling v2+.
    Accede a result.document.tables si existe.
    """
    tablas = []
    doc = result.document

    # Intentar acceder a la propiedad .tables del documento
    doc_tables = None
    if hasattr(doc, "tables"):
        try:
            doc_tables = list(doc.tables)
        except Exception:
            doc_tables = None

    if not doc_tables:
        return []

    for table in doc_tables:
        # Extraer bbox de provenance
        bbox = (0, 0, 0, 0)
        if hasattr(table, "prov") and table.prov:
            for prov in table.prov:
                if hasattr(prov, "bbox"):
                    bb = prov.bbox
                    if hasattr(bb, "l"):
                        bbox = (bb.l, bb.t, bb.r, bb.b)
                    elif hasattr(bb, "x"):
                        bbox = (bb.x, bb.y, bb.x + bb.width, bb.y + bb.height)
                    elif isinstance(bb, (list, tuple)) and len(bb) == 4:
                        bbox = tuple(bb)

        # Contar filas/columnas
        num_filas, num_cols = 0, 0
        if hasattr(table, "data") and table.data:
            data = table.data
            if hasattr(data, "grid") and data.grid:
                num_filas = len(data.grid)
                num_cols = max(len(row) for row in data.grid) if data.grid else 0
            elif hasattr(data, "table_cells") and data.table_cells:
                rows, cols = set(), set()
                for cell in data.table_cells:
                    if hasattr(cell, "row"):
                        rows.add(cell.row)
                    if hasattr(cell, "col"):
                        cols.add(cell.col)
                num_filas = len(rows)
                num_cols = len(cols)
            elif hasattr(data, "num_rows"):
                num_filas = data.num_rows
                num_cols = getattr(data, "num_cols", 0)

        tablas.append(TablaDetectada(
            pagina=pag_num,
            bbox=bbox,
            num_filas=num_filas,
            num_columnas=num_cols,
            confianza=1.0,
        ))

    return tablas


def _extraer_de_dict(doc_dict: dict, pag_num: int) -> list[TablaDetectada]:
    """
    Fallback: extrae tablas del dict exportado por Docling.
    Busca recursivamente cualquier item con 'table' en su tipo/label.
    """
    tablas = []

    for item in _recorrer_items_profundo(doc_dict):
        # Buscar items de tipo tabla por diferentes claves
        item_type = ""
        for key in ("type", "label", "content_type", "doc_item_label"):
            val = item.get(key, "")
            if isinstance(val, str) and "table" in val.lower():
                item_type = val
                break

        if not item_type:
            continue

        # Extraer bbox
        bbox = _extraer_bbox(item)

        # Contar filas/columnas
        num_filas, num_cols = _contar_grid(item)

        tablas.append(TablaDetectada(
            pagina=pag_num,
            bbox=bbox,
            num_filas=num_filas,
            num_columnas=num_cols,
            confianza=1.0,
        ))

    return tablas


def _extraer_bbox(item: dict) -> tuple[float, float, float, float]:
    """Extrae bbox de un item, buscando en varias ubicaciones posibles."""
    for prov_key in ("prov", "provenance"):
        prov_list = item.get(prov_key, [])
        if isinstance(prov_list, dict):
            prov_list = [prov_list]
        for prov in prov_list:
            bbox_data = prov.get("bbox", {})
            if isinstance(bbox_data, dict) and bbox_data:
                return (
                    bbox_data.get("l", bbox_data.get("x", 0)),
                    bbox_data.get("t", bbox_data.get("y", 0)),
                    bbox_data.get("r", bbox_data.get("x", 0) + bbox_data.get("width", 0)),
                    bbox_data.get("b", bbox_data.get("y", 0) + bbox_data.get("height", 0)),
                )
            elif isinstance(bbox_data, (list, tuple)) and len(bbox_data) == 4:
                return tuple(bbox_data)

    # Buscar bbox directamente en el item
    bbox_data = item.get("bbox", {})
    if isinstance(bbox_data, dict) and bbox_data:
        return (
            bbox_data.get("l", bbox_data.get("x", 0)),
            bbox_data.get("t", bbox_data.get("y", 0)),
            bbox_data.get("r", bbox_data.get("x", 0) + bbox_data.get("width", 0)),
            bbox_data.get("b", bbox_data.get("y", 0) + bbox_data.get("height", 0)),
        )

    return (0, 0, 0, 0)


def _contar_grid(item: dict) -> tuple[int, int]:
    """Cuenta filas y columnas de una tabla."""
    for data_key in ("data", "table_data"):
        data = item.get(data_key, {})
        if not isinstance(data, dict):
            continue

        for grid_key in ("grid", "table_cells", "cells"):
            grid = data.get(grid_key, [])
            if not isinstance(grid, list) or not grid:
                continue

            if isinstance(grid[0], list):
                return len(grid), max(len(row) for row in grid)
            else:
                rows, cols = set(), set()
                for cell in grid:
                    if isinstance(cell, dict):
                        rows.add(cell.get("row", cell.get("row_index", 0)))
                        cols.add(cell.get("col", cell.get("col_index", 0)))
                if rows:
                    return len(rows), len(cols)

    return 0, 0


def _recorrer_items_profundo(obj, depth=0, max_depth=10) -> list[dict]:
    """Recorre recursivamente toda la estructura buscando items de cualquier tipo."""
    if depth > max_depth:
        return []

    items = []

    if isinstance(obj, dict):
        items.append(obj)
        for key, val in obj.items():
            if isinstance(val, (dict, list)):
                items.extend(_recorrer_items_profundo(val, depth + 1, max_depth))
    elif isinstance(obj, list):
        for item in obj:
            if isinstance(item, (dict, list)):
                items.extend(_recorrer_items_profundo(item, depth + 1, max_depth))

    return items


def _debug_estructura(result, doc_dict: dict, pag_num: int):
    """Log de debug para entender por qué no se encontraron tablas."""
    # Mostrar las claves top-level del dict
    logger.debug(
        f"[docling] Pág {pag_num} — dict keys: {list(doc_dict.keys())}"
    )

    # Mostrar atributos del documento
    doc = result.document
    attrs = [a for a in dir(doc) if not a.startswith("_")]
    logger.debug(
        f"[docling] Pág {pag_num} — document attrs: {attrs[:20]}"
    )

    # Buscar cualquier clave que contenga "table" en el dict completo
    table_keys = _buscar_claves_tabla(doc_dict)
    if table_keys:
        logger.debug(
            f"[docling] Pág {pag_num} — claves con 'table': {table_keys[:10]}"
        )

    # Contar items por tipo en el dict
    tipos = {}
    for item in _recorrer_items_profundo(doc_dict, max_depth=5):
        for key in ("type", "label", "content_type", "doc_item_label"):
            val = item.get(key, "")
            if val:
                tipos[f"{key}={val}"] = tipos.get(f"{key}={val}", 0) + 1
    if tipos:
        logger.debug(
            f"[docling] Pág {pag_num} — tipos encontrados: {tipos}"
        )


def _buscar_claves_tabla(obj, prefix="", depth=0) -> list[str]:
    """Busca recursivamente claves que contengan 'table'."""
    if depth > 5:
        return []

    results = []
    if isinstance(obj, dict):
        for key, val in obj.items():
            path = f"{prefix}.{key}" if prefix else key
            if "table" in str(key).lower():
                results.append(path)
            if isinstance(val, str) and "table" in val.lower():
                results.append(f"{path}={val}")
            results.extend(_buscar_claves_tabla(val, path, depth + 1))
    elif isinstance(obj, list) and obj and depth < 3:
        results.extend(_buscar_claves_tabla(obj[0], f"{prefix}[0]", depth + 1))

    return results


def check_docling_available() -> bool:
    """Verifica si Docling está instalado."""
    try:
        from docling.document_converter import DocumentConverter  # noqa: F401
        return True
    except ImportError:
        return False
