from __future__ import annotations
import logging

from extractor.parser import parse_full_text
from extractor.scorer import score_page, group_into_blocks
from extractor.llm import extraer_bloque

logger = logging.getLogger(__name__)


def extraer_bases(full_text: str) -> dict:
    """
    Pipeline completo: full_text del motor OCR → JSON estructurado.

    Returns:
        {
            "rtm_postor":          [...],
            "rtm_personal":        [...],
            "factores_evaluacion": [...],
            "_bloques_detectados": [...]   # trazabilidad
        }
    """
    pages  = parse_full_text(full_text)
    scored = [score_page(p) for p in pages]
    blocks = group_into_blocks(scored)

    logger.info(f"[pipeline] {len(pages)} páginas → {len(blocks)} bloques")
    for b in blocks:
        logger.info(f"  [{b.block_type}] págs {b.page_range}")

    resultado: dict = {
        "rtm_postor":          [],
        "rtm_personal":        [],
        "factores_evaluacion": [],
        "_bloques_detectados": [],
    }

    for block in blocks:
        resultado["_bloques_detectados"].append({
            "tipo":    block.block_type,
            "paginas": list(block.page_range),
        })
        data = extraer_bloque(block)
        if not data:
            continue

        if block.block_type == "rtm_postor":
            resultado["rtm_postor"].extend(data.get("items_concurso", []))
        elif block.block_type == "rtm_personal":
            resultado["rtm_personal"].extend(data.get("personal_clave", []))
        elif block.block_type == "factores_evaluacion":
            resultado["factores_evaluacion"].extend(data.get("factores_evaluacion", []))

    logger.info(
        f"[pipeline] Resultado: "
        f"{len(resultado['rtm_postor'])} items postor · "
        f"{len(resultado['rtm_personal'])} profesionales · "
        f"{len(resultado['factores_evaluacion'])} factores"
    )
    return resultado