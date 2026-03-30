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

    # Solo la primera página recibe el markdown de la tabla completa.
    # Las páginas de continuación NO se tocan — mantienen su texto OCR original
    # para que el LLM pueda extraer datos de columnas que Qwen VL no capturó.
    resultados[grupo[0]] = md

exitosos = len(resultados)
logger.info(f"Completado: {exitosos} grupo(s) exitoso(s) de {len(grupos)}")

with open(output_pkl_path, "wb") as f:
    pickle.dump(resultados, f)

# ── Descargar modelo VL de Ollama antes de salir ─────────────────────────────
# El proceso principal no puede arrancar Qwen 14B hasta que este modelo
# esté fuera de VRAM. Hacemos keep_alive=0 + polling aquí, dentro del worker,
# de modo que cuando subprocess.run() retorna al proceso padre, la VRAM
# está garantizadamente libre.
import time
import requests as _req

_ollama_url   = settings.get("OLLAMA_BASE_URL", "http://localhost:11434")
_vl_model     = settings.get("QWEN_VL_MODEL", "qwen2.5vl:7b")
_poll_timeout = 120
_poll_interval = 2.0

try:
    _req.post(
        f"{_ollama_url}/api/generate",
        json={"model": _vl_model, "keep_alive": 0},
        timeout=10,
    )
    logger.info(f"Solicitud de descarga enviada para '{_vl_model}'")
except Exception as e:
    logger.warning(f"No se pudo solicitar descarga de '{_vl_model}': {e}")

transcurrido = 0.0
while transcurrido < _poll_timeout:
    time.sleep(_poll_interval)
    transcurrido += _poll_interval
    try:
        resp = _req.get(f"{_ollama_url}/api/ps", timeout=5)
        resp.raise_for_status()
        activos = [m.get("name", "") for m in resp.json().get("models", [])]
        if not any(_vl_model in m for m in activos):
            logger.info(
                f"'{_vl_model}' confirmado fuera de VRAM "
                f"({transcurrido:.0f}s) — proceso principal puede cargar 14B"
            )
            break
        logger.debug(f"Esperando descarga VL... ({transcurrido:.0f}s) activos: {activos}")
    except Exception as e:
        logger.debug(f"/api/ps error: {e}")
else:
    logger.warning(
        f"Timeout ({_poll_timeout}s) esperando descarga de '{_vl_model}'. "
        "El proceso principal continúa — puede haber contención de VRAM."
    )

# ── Pre-cargar Qwen 14B en GPU antes de devolver control al proceso principal ──
# Ollama puede retener pools CUDA internos incluso tras descargar VL.
# Si 14B se carga inmediatamente, Ollama a veces lo manda a RAM.
# Forzamos la carga aquí con num_gpu=99 y verificamos que size_vram > 0
# para garantizar que está en GPU, no en RAM/disco.

# Pausa para que CUDA libere los pools internos del modelo VL
time.sleep(5)
logger.info("Pausa de 5s para liberar pools CUDA completada")

_qwen_model = settings.get("QWEN_MODEL", "qwen2.5:14b")
_max_intentos = 3

for _intento in range(1, _max_intentos + 1):
    try:
        logger.info(
            f"Pre-cargando '{_qwen_model}' en GPU (intento {_intento}/{_max_intentos})..."
        )
        # Prompt vacío = solo cargar modelo, sin generar tokens
        resp_warm = _req.post(
            f"{_ollama_url}/api/generate",
            json={
                "model": _qwen_model,
                "prompt": "",
                "keep_alive": "10m",
                "options": {"num_gpu": 99},
            },
            timeout=120,
        )
        resp_warm.raise_for_status()

        # Verificar que 14B está en VRAM (no en RAM)
        # Polleamos /api/ps hasta que el modelo aparezca. Si aparece en GPU → OK.
        # Si aparece en RAM → salir inmediatamente y reintentar (no va a migrar solo).
        _warm_timeout = 60.0
        _warm_elapsed = 0.0
        _en_gpu = False
        _en_ram = False
        while _warm_elapsed < _warm_timeout:
            time.sleep(2)
            _warm_elapsed += 2
            try:
                resp_ps = _req.get(f"{_ollama_url}/api/ps", timeout=5)
                for m in resp_ps.json().get("models", []):
                    if _qwen_model in m.get("name", ""):
                        size_total = m.get("size", 0)
                        size_vram = m.get("size_vram", 0)
                        pct_gpu = (size_vram / size_total * 100) if size_total > 0 else 0

                        if size_vram > 0 and pct_gpu > 90:
                            logger.info(
                                f"'{_qwen_model}' confirmado en GPU: "
                                f"{size_vram / 1e9:.1f}GB VRAM / "
                                f"{size_total / 1e9:.1f}GB total "
                                f"({pct_gpu:.0f}%) — listo"
                            )
                            _en_gpu = True
                        else:
                            logger.warning(
                                f"'{_qwen_model}' cargado pero en RAM: "
                                f"{size_vram / 1e9:.1f}GB VRAM / "
                                f"{size_total / 1e9:.1f}GB total "
                                f"({pct_gpu:.0f}% GPU)"
                            )
                            _en_ram = True
                        break  # modelo encontrado, no seguir buscando en la lista
            except Exception:
                continue

            if _en_gpu or _en_ram:
                break  # modelo detectado — salir del polling

        if _en_gpu:
            break  # éxito — salir del bucle de reintentos

        # Si no está en GPU, descargar y reintentar
        logger.warning(
            f"Intento {_intento}: '{_qwen_model}' no se cargó en GPU. "
            "Descargando para reintentar..."
        )
        _req.post(
            f"{_ollama_url}/api/generate",
            json={"model": _qwen_model, "keep_alive": 0},
            timeout=10,
        )
        time.sleep(5)  # esperar a que Ollama libere VRAM

    except Exception as e:
        logger.warning(
            f"Intento {_intento}: error pre-cargando '{_qwen_model}': {e}"
        )
        if _intento < _max_intentos:
            time.sleep(5)

else:
    logger.error(
        f"FALLO: '{_qwen_model}' no se pudo cargar en GPU tras {_max_intentos} intentos. "
        "Las inferencias serán lentas (RAM/disco)."
    )

logger.info("Worker finalizado.")
