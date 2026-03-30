"""
Orquestador del pipeline de mejora de tablas.

Coordina:
  1. Detección heurística de páginas con tablas
  2. Agrupación de páginas consecutivas (cross-page)
  3. Qwen VL en subproceso independiente (VRAM liberada al terminar)
  4. Reemplazo selectivo en el texto OCR
"""

from __future__ import annotations
import json
import logging
import os
import pickle
import re
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path

from src.tables.detector import detectar_tabla
from src.config.settings import (
    TABLE_DETECT_THRESHOLD,
    TABLE_VALIDATOR_MIN_SCORE,
    TABLE_VL_MAX_BATCH,
    TABLE_VL_MAX_GROUP,
    TABLE_VL_MAX_PX,
    QWEN_VL_MODEL,
    QWEN_VL_TIMEOUT,
    OLLAMA_BASE_URL,
    QWEN_MODEL,
)

logger = logging.getLogger(__name__)

# Directorio raíz del proyecto (dos niveles sobre src/tables/)
_PROJECT_ROOT = str(Path(__file__).parent.parent.parent)
_WORKER_PATH  = str(Path(__file__).parent / "qwen_vl_worker.py")


@dataclass
class EstadisticasTablas:
    paginas_analizadas: int = 0
    paginas_heuristicas: int = 0
    tablas_qwen_vl: int = 0          # grupos enviados al worker
    tablas_validadas: int = 0         # grupos que devolvieron markdown válido
    tablas_fallback: int = 0          # grupos que fallaron
    tiempo_heuristica_s: float = 0.0
    tiempo_qwen_vl_s: float = 0.0
    tiempo_total_s: float = 0.0
    paginas_detectadas_heuristica: list[int] = field(default_factory=list)
    detalles: list[dict] = field(default_factory=list)


def mejorar_texto_con_tablas(
    full_text: str,
    pdf_path: str,
    paginas_relevantes: list[int],
    textos_por_pagina: dict[int, str] | None = None,
) -> tuple[str, EstadisticasTablas]:
    """
    Pipeline de mejora de tablas vía Qwen VL en subproceso.

    1. Detecta páginas con probable tabla (heurística OSCE)
    2. Agrupa páginas consecutivas (cross-page)
    3. Ejecuta qwen_vl_worker.py como subproceso — VRAM liberada al exit
    4. Reemplaza selectivamente el texto OCR con el markdown resultante

    Returns:
        (full_text_mejorado, estadísticas)
    """
    stats = EstadisticasTablas()
    t_inicio = time.time()

    # ── 1. Parsear textos por página ─────────────────────────────────────────
    if textos_por_pagina is None:
        textos_por_pagina = _parsear_textos_pagina(full_text)

    stats.paginas_analizadas = len(paginas_relevantes)

    # ── 2. Detección heurística ───────────────────────────────────────────────
    t_heur = time.time()
    paginas_con_tabla: list[int] = []
    for pag in paginas_relevantes:
        texto = textos_por_pagina.get(pag, "")
        score = detectar_tabla(texto)
        if score >= TABLE_DETECT_THRESHOLD:
            paginas_con_tabla.append(pag)
            logger.debug(f"[enhancer] Pág {pag}: heurística={score:.2f} ✓")

    stats.paginas_heuristicas = len(paginas_con_tabla)
    stats.paginas_detectadas_heuristica = list(paginas_con_tabla)
    stats.tiempo_heuristica_s = round(time.time() - t_heur, 2)

    if not paginas_con_tabla:
        logger.info("[enhancer] No se detectaron tablas por heurística")
        stats.tiempo_total_s = round(time.time() - t_inicio, 2)
        return full_text, stats

    logger.info(
        f"[enhancer] Heurística: {len(paginas_con_tabla)} páginas "
        f"con probable tabla: {paginas_con_tabla}"
    )

    # ── 3. Agrupar páginas consecutivas ──────────────────────────────────────
    grupos = _agrupar_consecutivas(paginas_con_tabla)
    logger.info(
        f"[enhancer] {len(grupos)} grupo(s): "
        + ", ".join(f"[{','.join(str(p) for p in g)}]" for g in grupos)
    )
    stats.tablas_qwen_vl = len(grupos)

    # ── 4. Ejecutar worker Qwen VL como subproceso ────────────────────────────
    t_qwen = time.time()
    reemplazos = _ejecutar_worker(pdf_path, grupos)
    stats.tiempo_qwen_vl_s = round(time.time() - t_qwen, 2)

    # Contabilizar éxitos y fallos por grupo
    for grupo in grupos:
        primera = grupo[0]
        if primera in reemplazos:
            stats.tablas_validadas += 1
            stats.detalles.append({
                "paginas": grupo,
                "validado": True,
                "preview": reemplazos[primera][:200],
            })
        else:
            stats.tablas_fallback += 1
            stats.detalles.append({
                "paginas": grupo,
                "validado": False,
                "preview": "",
            })

    # ── 4b. Guardar debug de tablas VL ─────────────────────────────────────────
    #   Escribe output/vl_tablas_debug.md con el markdown crudo que generó
    #   Qwen VL para cada grupo — permite verificar visualmente si los 12
    #   profesionales están presentes antes de que el LLM los interprete.
    _guardar_debug_vl(reemplazos, grupos, textos_por_pagina)

    # ── 5. Reemplazo selectivo en full_text ───────────────────────────────────
    if reemplazos:
        full_text = _reemplazar_selectivo(full_text, reemplazos, textos_por_pagina)
        logger.info(f"[enhancer] {len(reemplazos)} páginas mejoradas con tablas")

    stats.tiempo_total_s = round(time.time() - t_inicio, 2)
    logger.info(
        f"[enhancer] Estadísticas: "
        f"analizadas={stats.paginas_analizadas} "
        f"heurística={stats.paginas_heuristicas} "
        f"grupos={stats.tablas_qwen_vl} "
        f"validados={stats.tablas_validadas} "
        f"fallback={stats.tablas_fallback} "
        f"tiempo={stats.tiempo_total_s:.1f}s "
        f"(heur={stats.tiempo_heuristica_s:.1f}s "
        f"qwen_vl={stats.tiempo_qwen_vl_s:.1f}s)"
    )
    return full_text, stats


# ── Subprocess ────────────────────────────────────────────────────────────────

def _ejecutar_worker(
    pdf_path: str,
    grupos: list[list[int]],
) -> dict[int, str]:
    """
    Lanza qwen_vl_worker.py como subproceso sincrónico.
    Al terminar, el OS libera VRAM garantizadamente.
    Retorna {num_pagina: markdown} para las páginas exitosas.
    """
    payload = {
        "pdf_path": pdf_path,
        "grupos": grupos,
        "settings": {
            "TABLE_VL_MAX_BATCH":        TABLE_VL_MAX_BATCH,
            "TABLE_VL_MAX_PX":           TABLE_VL_MAX_PX,
            "TABLE_VALIDATOR_MIN_SCORE": TABLE_VALIDATOR_MIN_SCORE,
            "QWEN_VL_MODEL":             QWEN_VL_MODEL,
            "QWEN_VL_TIMEOUT":           QWEN_VL_TIMEOUT,
            "OLLAMA_BASE_URL":           OLLAMA_BASE_URL,
            "QWEN_MODEL":               QWEN_MODEL,
        },
    }

    tmp_json = tmp_pkl = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False, encoding="utf-8"
        ) as fj:
            json.dump(payload, fj)
            tmp_json = fj.name

        with tempfile.NamedTemporaryFile(suffix=".pkl", delete=False) as fp:
            tmp_pkl = fp.name

        logger.info(f"[enhancer] Lanzando worker Qwen VL ({len(grupos)} grupos)...")
        resultado = subprocess.run(
            [sys.executable, _WORKER_PATH, _PROJECT_ROOT, tmp_json, tmp_pkl],
            check=False,           # no lanzar excepción si el worker falla
            capture_output=False,  # los logs del worker van a stdout/stderr directamente
        )

        if resultado.returncode != 0:
            logger.warning(
                f"[enhancer] Worker terminó con código {resultado.returncode}"
            )

        # Leer resultados aunque el returncode sea != 0 (puede haber resultados parciales)
        if os.path.exists(tmp_pkl) and os.path.getsize(tmp_pkl) > 0:
            with open(tmp_pkl, "rb") as f:
                reemplazos: dict[int, str] = pickle.load(f)
            logger.info(
                f"[enhancer] Worker completado — "
                f"{len(reemplazos)} grupo(s) con tabla válida"
            )
            return reemplazos
        else:
            logger.warning("[enhancer] Worker no produjo resultados")
            return {}

    except Exception as e:
        logger.error(f"[enhancer] Error ejecutando worker: {e}")
        return {}
    finally:
        for path in (tmp_json, tmp_pkl):
            if path and os.path.exists(path):
                try:
                    os.unlink(path)
                except OSError:
                    pass


# ── Helpers ───────────────────────────────────────────────────────────────────

def _parsear_textos_pagina(full_text: str) -> dict[int, str]:
    """Extrae el texto de cada página del formato _texto_*.md."""
    paginas = {}
    patron = re.compile(
        r"^## Página (\d+)\s+.*?\n```\n(.*?)```",
        re.MULTILINE | re.DOTALL,
    )
    for m in patron.finditer(full_text):
        paginas[int(m.group(1))] = m.group(2).strip()
    return paginas


def _agrupar_consecutivas(
    paginas: list[int],
    max_size: int = TABLE_VL_MAX_GROUP,
) -> list[list[int]]:
    """
    Agrupa páginas consecutivas en sublistas, con tamaño máximo.

    El límite de tamaño evita que tablas distintas (ej: B.1 en págs 136-139
    y B.2 en págs 140-143) se fusionen en un solo grupo. Cuando eso ocurre,
    el VL solo captura UNA tabla y las demás mantienen OCR garbled.
    """
    if not paginas:
        return []
    ordenadas = sorted(paginas)
    grupos: list[list[int]] = [[ordenadas[0]]]
    for p in ordenadas[1:]:
        if p - grupos[-1][-1] == 1 and len(grupos[-1]) < max_size:
            grupos[-1].append(p)
        else:
            grupos.append([p])
    return grupos


def _reemplazar_selectivo(
    full_text: str,
    reemplazos: dict[int, str],
    textos_por_pagina: dict[int, str],
) -> str:
    """
    Reemplaza SOLO la zona de tabla dentro del texto OCR de cada página.
    El texto fuera de la tabla se preserva.
    """
    for pag_num, nuevo_md in reemplazos.items():
        patron_pagina = re.compile(
            rf"(## Página {pag_num}\s+.*?\n```\n)(.*?)(```)",
            re.DOTALL,
        )
        match = patron_pagina.search(full_text)
        if not match:
            continue

        header         = match.group(1)
        texto_original = match.group(2)
        cierre         = match.group(3)

        texto_mejorado = _insertar_tabla_en_texto(texto_original, nuevo_md)

        full_text = (
            full_text[:match.start()]
            + header + texto_mejorado + "\n" + cierre
            + full_text[match.end():]
        )

    return full_text


def _insertar_tabla_en_texto(texto_original: str, tabla_md: str) -> str:
    """
    Localiza la zona de tabla dentro del texto de una página (líneas cortas
    fragmentadas por el OCR) y la reemplaza con el markdown de Qwen VL.
    Preserva texto antes y después.
    """
    lineas = texto_original.split("\n")
    if len(lineas) < 5:
        return tabla_md

    ventana = 5
    scores  = []
    for i in range(len(lineas)):
        bloque = lineas[i:i + ventana]
        cortas = sum(1 for l in bloque if len(l.strip()) < 40 and l.strip())
        total  = sum(1 for l in bloque if l.strip())
        scores.append(cortas / max(total, 1))

    en_tabla      = [s > 0.6 for s in scores]
    inicio_tabla  = next((i for i, v in enumerate(en_tabla) if v), None)
    if inicio_tabla is None:
        return tabla_md

    fin_tabla = next(
        (i for i in range(inicio_tabla + 1, len(en_tabla)) if not en_tabla[i]),
        len(lineas),
    )

    antes   = "\n".join(lineas[:inicio_tabla]).strip()
    despues = "\n".join(lineas[fin_tabla:]).strip()

    partes = []
    if antes:
        partes.append(antes)
    partes.append(tabla_md)
    if despues:
        partes.append(despues)

    return "\n\n".join(partes)


def _guardar_debug_vl(
    reemplazos: dict[int, str],
    grupos: list[list[int]],
    textos_por_pagina: dict[int, str],
) -> None:
    """
    Escribe output/vl_tablas_debug.md con el markdown crudo de Qwen VL.

    Permite verificar visualmente:
    - Qué tabla generó VL para cada grupo de páginas
    - Si faltan filas (profesionales no capturados)
    - Si el texto OCR original fue reemplazado correctamente
    """
    from datetime import datetime
    from src.config.settings import OUTPUT_DIR

    output_path = OUTPUT_DIR / "vl_tablas_debug.md"
    try:
        lineas = [
            f"# Debug Tablas VL — {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            "",
            f"**Grupos procesados:** {len(grupos)}",
            f"**Grupos con resultado:** {len(reemplazos)}",
            "",
            "---",
            "",
        ]

        for grupo in grupos:
            primera = grupo[0]
            lineas.append(f"## Grupo: páginas {grupo}")
            lineas.append("")

            if primera in reemplazos:
                md = reemplazos[primera]
                # Contar filas de tabla (excluyendo header y separator)
                filas_datos = [
                    l for l in md.strip().split("\n")
                    if l.strip().startswith("|") and "---" not in l
                ]
                # Restar 1 por el header
                n_datos = max(len(filas_datos) - 1, 0)
                lineas.append(f"**Estado:** ✅ Validado — {n_datos} filas de datos")
                lineas.append(f"**Chars:** {len(md)}")
                lineas.append("")
                lineas.append("### Markdown VL (crudo)")
                lineas.append("```")
                lineas.append(md)
                lineas.append("```")
            else:
                lineas.append("**Estado:** ❌ Sin resultado (VL falló o no pasó validación)")

            lineas.append("")

            # Mostrar texto OCR original de cada página del grupo
            lineas.append("### Texto OCR original por página")
            for pag in grupo:
                texto_ocr = textos_por_pagina.get(pag, "(no disponible)")
                preview = texto_ocr[:500] + "..." if len(texto_ocr) > 500 else texto_ocr
                lineas.append(f"#### Página {pag} ({len(texto_ocr)} chars)")
                lineas.append("```")
                lineas.append(preview)
                lineas.append("```")
                lineas.append("")

            lineas.append("---")
            lineas.append("")

        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        output_path.write_text("\n".join(lineas), encoding="utf-8")
        logger.info(f"[enhancer] Debug VL guardado en {output_path}")

    except Exception as e:
        logger.warning(f"[enhancer] Error guardando debug VL: {e}")
