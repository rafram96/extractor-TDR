"""
Worker de Qwen VL — se ejecuta como subproceso independiente.

Recibe grupos de páginas del PDF, extrae imágenes, llama Qwen VL,
valida y guarda los resultados en un pickle.
Al terminar el proceso, el OS libera toda la VRAM automáticamente.

Uso (invocado por enhancer.py):
    python qwen_vl_worker.py <project_root> <input_json> <output_pkl>

input_json:
    {
        "pdf_path": "...",
        "grupos": [[37, 38, 39], [40], [136, 137, 138], ...],
        "settings": { "QWEN_VL_MODEL": ..., "TABLE_VL_MAX_BATCH": ..., ... }
    }

output_pkl:
    dict[int, str] — {num_pagina: markdown_tabla}
    La primera página de cada grupo tiene el markdown completo.
    Las páginas de continuación tienen "[Tabla continúa desde página N]".
"""
from __future__ import annotations
import sys
import json
import pickle
import logging

# ── Configurar sys.path antes de cualquier import del proyecto ────────────────
project_root = sys.argv[1]
input_json_path = sys.argv[2]
output_pkl_path = sys.argv[3]

sys.path.insert(0, project_root)

# ── Leer parámetros ───────────────────────────────────────────────────────────
with open(input_json_path, "r", encoding="utf-8") as f:
    datos = json.load(f)

pdf_path: str = datos["pdf_path"]
grupos: list[list[int]] = datos["grupos"]
settings: dict = datos.get("settings", {})

# ── Aplicar settings recibidos del proceso padre ──────────────────────────────
import src.config.settings as _cfg
for k, v in settings.items():
    if hasattr(_cfg, k):
        setattr(_cfg, k, v)

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("qwen_vl_worker")

# ── Imports del proyecto (después de configurar sys.path y settings) ──────────
from src.tables.image_utils import extraer_multiples_paginas
from src.tables.vision import leer_tabla_visual, leer_tabla_crosspage
from src.tables.validator import validar_tabla_markdown
from src.config.settings import TABLE_VL_MAX_BATCH, TABLE_VALIDATOR_MIN_SCORE


def _procesar_grupo(
    imagenes: list,
    paginas_grupo: list[int],
) -> str | None:
    """
    Procesa un grupo de imágenes con Qwen VL, con sub-batching si es necesario.
    Valida cada sub-batch individualmente antes de fusionar.
    Retorna el markdown fusionado, o None si nada pasa validación.
    """
    if len(imagenes) <= TABLE_VL_MAX_BATCH:
        if len(imagenes) == 1:
            md = leer_tabla_visual(imagenes[0])
        else:
            md = leer_tabla_crosspage(imagenes)

        if not md or "|" not in md:
            logger.warning(f"Grupo págs {paginas_grupo}: Qwen VL no devolvió tabla")
            return None

        val = validar_tabla_markdown(md, min_score=TABLE_VALIDATOR_MIN_SCORE)
        if not val.valido:
            logger.warning(f"Grupo págs {paginas_grupo} no pasó validación: {val.razon}")
            return None

        return md

    # Grupo grande → sub-batches
    logger.info(
        f"Grupo de {len(imagenes)} imgs → "
        f"sub-batches de {TABLE_VL_MAX_BATCH}"
    )
    sub_resultados: list[str] = []

    for i in range(0, len(imagenes), TABLE_VL_MAX_BATCH):
        sub_imgs = imagenes[i:i + TABLE_VL_MAX_BATCH]
        sub_pags = paginas_grupo[i:i + TABLE_VL_MAX_BATCH]

        logger.info(f"Sub-batch págs {sub_pags}")

        if len(sub_imgs) == 1:
            md = leer_tabla_visual(sub_imgs[0])
        else:
            md = leer_tabla_crosspage(sub_imgs)

        if not md or "|" not in md:
            logger.warning(f"Sub-batch págs {sub_pags}: no devolvió tabla")
            continue

        val = validar_tabla_markdown(md, min_score=TABLE_VALIDATOR_MIN_SCORE)
        if not val.valido:
            logger.warning(f"Sub-batch págs {sub_pags} descartado: {val.razon}")
            continue

        sub_resultados.append(md)

    if not sub_resultados:
        return None

    if len(sub_resultados) == 1:
        return sub_resultados[0]

    # Fusionar: header del primero, filas de los demás
    lineas_finales: list[str] = []
    for idx, md in enumerate(sub_resultados):
        lineas = [l for l in md.strip().split("\n") if l.strip()]
        if idx == 0:
            lineas_finales.extend(lineas)
        else:
            for linea in lineas:
                if linea.strip().startswith("|") and "---" not in linea:
                    lineas_finales.append(linea)

    merged = "\n".join(lineas_finales)

    val_merged = validar_tabla_markdown(merged, min_score=TABLE_VALIDATOR_MIN_SCORE)
    if not val_merged.valido:
        logger.warning(
            f"Resultado fusionado págs {paginas_grupo} no pasó validación: "
            f"{val_merged.razon}"
        )
        return None

    return merged


# ── Main ──────────────────────────────────────────────────────────────────────

todas_paginas = sorted({p for grupo in grupos for p in grupo})
logger.info(
    f"Iniciado: {len(grupos)} grupo(s), "
    f"{len(todas_paginas)} páginas únicas del PDF"
)

# Extraer todas las imágenes necesarias de una vez
try:
    paginas_img = extraer_multiples_paginas(pdf_path, todas_paginas)
    img_por_pagina = {pi.pagina: pi.imagen for pi in paginas_img}
    logger.info(f"{len(img_por_pagina)} imágenes extraídas del PDF")
except Exception as e:
    logger.error(f"Error extrayendo imágenes: {e}")
    with open(output_pkl_path, "wb") as f:
        pickle.dump({}, f)
    sys.exit(0)

resultados: dict[int, str] = {}

for grupo in grupos:
    imagenes = [img_por_pagina[p] for p in grupo if p in img_por_pagina]
    if not imagenes:
        logger.warning(f"Grupo {grupo}: ninguna imagen disponible")
        continue

    md = _procesar_grupo(imagenes, grupo)
    if md is None:
        continue

    # Primera página: markdown completo; resto: marcador de continuación
    resultados[grupo[0]] = md
    for pag_extra in grupo[1:]:
        resultados[pag_extra] = f"[Tabla continúa desde página {grupo[0]}]"

exitosos = sum(1 for v in resultados.values() if not v.startswith("[Tabla continúa"))
logger.info(f"Completado: {exitosos} grupo(s) exitoso(s) de {len(grupos)}")

with open(output_pkl_path, "wb") as f:
    pickle.dump(resultados, f)

logger.info("Worker finalizado.")
