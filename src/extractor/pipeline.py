from __future__ import annotations
import logging
from typing import Any

from src.extractor.parser import parse_full_text
from src.extractor.scorer import score_page, group_into_blocks
from src.extractor.llm import extraer_bloque

logger = logging.getLogger(__name__)


def _es_nulo(valor: Any) -> bool:
    """True si el valor es None, string vacío o string literal 'null'."""
    if valor is None:
        return True
    if isinstance(valor, str) and valor.strip().lower() in ("null", "none", ""):
        return True
    return False


def _limpiar_nulls(obj: Any) -> Any:
    """Convierte strings 'null'/'none' a None en cualquier estructura anidada."""
    if isinstance(obj, dict):
        return {k: _limpiar_nulls(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_limpiar_nulls(i) for i in obj]
    if isinstance(obj, str) and obj.strip().lower() in ("null", "none"):
        return None
    return obj


def _dedup_personal(lista: list[dict]) -> list[dict]:
    """
    Elimina duplicados de personal clave por cargo.
    Cuando hay dos entradas del mismo cargo, conserva la que tenga
    más campos completos (menos nulls en experiencia_minima).
    """
    por_cargo: dict[str, dict] = {}
    for entrada in lista:
        cargo = entrada.get("cargo")
        if _es_nulo(cargo):
            continue  # descarta entradas sin cargo

        cargo_key = str(cargo).strip().lower()
        if cargo_key not in por_cargo:
            por_cargo[cargo_key] = entrada
        else:
            # Compara completitud de experiencia_minima
            def _completitud(e: dict) -> int:
                em = e.get("experiencia_minima") or {}
                return sum(1 for v in em.values() if not _es_nulo(v))

            if _completitud(entrada) > _completitud(por_cargo[cargo_key]):
                por_cargo[cargo_key] = entrada

    return list(por_cargo.values())


def extraer_bases(
    full_text: str,
    nombre_archivo: str = "",
    pdf_path: str = "",
) -> dict:
    """
    Pipeline completo: full_text del motor OCR → JSON estructurado.

    Args:
        full_text: Texto completo del _texto_*.md
        nombre_archivo: Nombre del PDF (para metadatos)
        pdf_path: Ruta al PDF original (para mejora de tablas)

    Returns:
        {
            "rtm_postor":          [...],
            "rtm_personal":        [...],
            "factores_evaluacion": [...],
            "_bloques_detectados": [...],
            "_tablas_stats":       {...}   # estadísticas de mejora de tablas
        }
    """
    pages  = parse_full_text(full_text)
    scored = [score_page(p) for p in pages]

    # ── Mejora de tablas (antes de agrupar bloques) ──────────────────────
    tablas_stats = None
    if pdf_path:
        try:
            from src.tables.enhancer import mejorar_texto_con_tablas
            paginas_relevantes = [p.page_num for p in scored if p.dominant_type]
            full_text, tablas_stats = mejorar_texto_con_tablas(
                full_text, pdf_path, paginas_relevantes,
            )
            # Re-parsear con el texto mejorado
            pages = parse_full_text(full_text)
            scored = [score_page(p) for p in pages]
        except ImportError as e:
            logger.warning(f"[pipeline] Módulo tables no disponible ({e}), saltando mejora de tablas")
        except Exception as e:
            logger.warning(f"[pipeline] Error en mejora de tablas: {e}")

    blocks = group_into_blocks(scored)

    logger.info(f"[pipeline] {len(pages)} páginas → {len(blocks)} bloques")
    for b in blocks:
        logger.info(f"  [{b.block_type}] págs {b.page_range}")

    resultado: dict = {
        "rtm_postor":          [],
        "rtm_personal":        [],
        "factores_evaluacion": [],
        "_bloques_detectados": [],
        "_tablas_stats":       vars(tablas_stats) if tablas_stats else None,
    }

    for block in blocks:
        resultado["_bloques_detectados"].append({
            "tipo":    block.block_type,
            "paginas": list(block.page_range),
        })
        data = extraer_bloque(block)
        if not data:
            continue
        data = _limpiar_nulls(data)

        if block.block_type == "rtm_postor":
            items = data.get("items_concurso", [])
            for item in items:
                if nombre_archivo:
                    item["archivo"] = nombre_archivo
            resultado["rtm_postor"].extend(items)
        elif block.block_type == "rtm_personal":
            resultado["rtm_personal"].extend(data.get("personal_clave", []))
        elif block.block_type == "factores_evaluacion":
            resultado["factores_evaluacion"].extend(data.get("factores_evaluacion", []))

    # Post-proceso: deduplicar personal y limpiar entradas vacías
    resultado["rtm_personal"] = _dedup_personal(resultado["rtm_personal"])

    logger.info(
        f"[pipeline] Resultado: "
        f"{len(resultado['rtm_postor'])} items postor · "
        f"{len(resultado['rtm_personal'])} profesionales · "
        f"{len(resultado['factores_evaluacion'])} factores"
    )
    return resultado