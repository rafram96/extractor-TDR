"""
Orquestador del pipeline de mejora de tablas.

Coordina: detección heurística → confirmación Docling → lectura Qwen VL
→ validación → reemplazo selectivo en el texto.
"""

from __future__ import annotations
import logging
import re
import time
from dataclasses import dataclass

from src.tables.detector import detectar_tabla
from src.tables.docling_client import confirmar_tablas, check_docling_available, TablaDetectada
from src.tables.image_utils import extraer_multiples_paginas, crop_tabla, PaginaImagen
from src.tables.vision import leer_tabla_visual, leer_tabla_crosspage
from src.tables.validator import validar_tabla_markdown
from src.config.settings import TABLE_DETECT_THRESHOLD, TABLE_VALIDATOR_MIN_SCORE

logger = logging.getLogger(__name__)


@dataclass
class EstadisticasTablas:
    paginas_analizadas: int = 0
    paginas_heuristicas: int = 0
    tablas_docling: int = 0
    tablas_qwen_vl: int = 0
    tablas_validadas: int = 0
    tablas_fallback: int = 0
    tiempo_heuristica_s: float = 0.0
    tiempo_docling_s: float = 0.0
    tiempo_qwen_vl_s: float = 0.0
    tiempo_total_s: float = 0.0


def mejorar_texto_con_tablas(
    full_text: str,
    pdf_path: str,
    paginas_relevantes: list[int],
    textos_por_pagina: dict[int, str] | None = None,
) -> tuple[str, EstadisticasTablas]:
    """
    Pipeline completo de mejora de tablas.

    1. Detecta páginas con probable tabla (heurística OSCE)
    2. Confirma con Docling (bbox)
    3. Agrupa páginas consecutivas (cross-page)
    4. Extrae + cropea imágenes del PDF
    5. Lee con Qwen VL
    6. Valida markdown
    7. Reemplaza selectivamente en full_text

    Args:
        full_text: Texto completo del _texto_*.md
        pdf_path: Ruta al PDF original
        paginas_relevantes: Páginas que el scorer marcó como relevantes
        textos_por_pagina: Dict {num_pagina: texto} para acceso rápido.
                          Si None, se parsea del full_text.

    Returns:
        (full_text_mejorado, estadísticas)
    """
    stats = EstadisticasTablas()
    t_inicio = time.time()

    # ── 1. Parsear textos por página si no se proporcionaron ─────────────
    if textos_por_pagina is None:
        textos_por_pagina = _parsear_textos_pagina(full_text)

    stats.paginas_analizadas = len(paginas_relevantes)

    # ── 2. Detección heurística ──────────────────────────────────────────
    t_heur = time.time()
    paginas_con_tabla: list[int] = []
    for pag in paginas_relevantes:
        texto = textos_por_pagina.get(pag, "")
        score = detectar_tabla(texto)
        if score >= TABLE_DETECT_THRESHOLD:
            paginas_con_tabla.append(pag)
            logger.debug(f"[enhancer] Pág {pag}: heurística={score:.2f} ✓")

    stats.paginas_heuristicas = len(paginas_con_tabla)
    stats.tiempo_heuristica_s = round(time.time() - t_heur, 2)

    if not paginas_con_tabla:
        logger.info("[enhancer] No se detectaron tablas por heurística")
        stats.tiempo_total_s = round(time.time() - t_inicio, 2)
        return full_text, stats

    logger.info(
        f"[enhancer] Heurística: {len(paginas_con_tabla)} páginas "
        f"con probable tabla: {paginas_con_tabla}"
    )

    # ── 3. Extraer imágenes para páginas candidatas ────────────────────
    #    Se extraen ANTES de Docling para pasar las imágenes PIL
    #    directamente (Docling trabaja con imágenes, no con el PDF).
    try:
        paginas_img = extraer_multiples_paginas(pdf_path, paginas_con_tabla)
        img_por_pagina = {pi.pagina: pi for pi in paginas_img}
    except Exception as e:
        logger.error(f"[enhancer] Error extrayendo imágenes: {e}")
        stats.tiempo_total_s = round(time.time() - t_inicio, 2)
        return full_text, stats

    # ── 4. Confirmación con Docling ──────────────────────────────────────
    t_docling = time.time()
    if not check_docling_available():
        logger.warning(
            "[enhancer] Docling no disponible — usando heurística pura "
            "(sin bbox, se manda página completa a Qwen VL)"
        )
        tablas_confirmadas = [
            TablaDetectada(pagina=p, bbox=(0, 0, 0, 0), num_filas=0, num_columnas=0, confianza=0.5)
            for p in paginas_con_tabla
        ]
    else:
        imagenes_para_docling = {pag: pi.imagen for pag, pi in img_por_pagina.items()}
        tablas_confirmadas = confirmar_tablas(imagenes_para_docling)

    stats.tablas_docling = len(tablas_confirmadas)
    stats.tiempo_docling_s = round(time.time() - t_docling, 2)

    if not tablas_confirmadas:
        logger.info("[enhancer] Docling no confirmó tablas")
        stats.tiempo_total_s = round(time.time() - t_inicio, 2)
        return full_text, stats

    # ── 5. Agrupar páginas consecutivas (cross-page) ────────────────────
    grupos = _agrupar_crosspage(tablas_confirmadas)
    logger.info(
        f"[enhancer] {len(grupos)} grupo(s) de tablas: "
        + ", ".join(
            f"[{','.join(str(t.pagina) for t in g)}]" for g in grupos
        )
    )

    # ── 6. Por cada grupo: crop → Qwen VL → validar → reemplazar ────────
    t_qwen = time.time()
    reemplazos: dict[int, str] = {}  # {pagina: markdown_tabla}

    for grupo in grupos:
        imagenes_crop = []
        paginas_grupo = []

        for tabla in grupo:
            pi = img_por_pagina.get(tabla.pagina)
            if pi is None:
                continue

            # Si tenemos bbox real de Docling, cropear
            if tabla.bbox != (0, 0, 0, 0):
                img_crop = crop_tabla(pi, tabla.bbox)
            else:
                # Sin Docling: mandar página completa
                img_crop = pi.imagen

            imagenes_crop.append(img_crop)
            paginas_grupo.append(tabla.pagina)

        if not imagenes_crop:
            continue

        # Llamar a Qwen VL
        stats.tablas_qwen_vl += 1
        if len(imagenes_crop) == 1:
            md_tabla = leer_tabla_visual(imagenes_crop[0])
        else:
            md_tabla = leer_tabla_crosspage(imagenes_crop)

        if md_tabla is None:
            logger.warning(
                f"[enhancer] Qwen VL falló para págs {paginas_grupo}"
            )
            stats.tablas_fallback += 1
            continue

        # Validar
        resultado = validar_tabla_markdown(md_tabla, min_score=TABLE_VALIDATOR_MIN_SCORE)
        if not resultado.valido:
            logger.warning(
                f"[enhancer] Tabla págs {paginas_grupo} no pasó validación: "
                f"{resultado.razon}"
            )
            stats.tablas_fallback += 1
            continue

        stats.tablas_validadas += 1

        # Asignar el markdown a cada página del grupo
        # Para cross-page: el markdown completo va en la primera página,
        # las siguientes se marcan como "continuación" para no duplicar
        reemplazos[paginas_grupo[0]] = md_tabla
        for pag_extra in paginas_grupo[1:]:
            reemplazos[pag_extra] = f"[Tabla continúa desde página {paginas_grupo[0]}]"

    stats.tiempo_qwen_vl_s = round(time.time() - t_qwen, 2)

    # ── 7. Reemplazo selectivo en full_text ──────────────────────────────
    if reemplazos:
        full_text = _reemplazar_selectivo(full_text, reemplazos, textos_por_pagina)
        logger.info(
            f"[enhancer] {len(reemplazos)} páginas mejoradas con tablas"
        )

    stats.tiempo_total_s = round(time.time() - t_inicio, 2)
    logger.info(
        f"[enhancer] Estadísticas: "
        f"analizadas={stats.paginas_analizadas} "
        f"heurística={stats.paginas_heuristicas} "
        f"docling={stats.tablas_docling} "
        f"qwen_vl={stats.tablas_qwen_vl} "
        f"validadas={stats.tablas_validadas} "
        f"fallback={stats.tablas_fallback} "
        f"tiempo={stats.tiempo_total_s:.1f}s "
        f"(heur={stats.tiempo_heuristica_s:.1f}s "
        f"docling={stats.tiempo_docling_s:.1f}s "
        f"qwen_vl={stats.tiempo_qwen_vl_s:.1f}s)"
    )
    return full_text, stats


def _parsear_textos_pagina(full_text: str) -> dict[int, str]:
    """Extrae el texto de cada página del formato _texto_*.md."""
    paginas = {}
    patron = re.compile(
        r"^## Página (\d+)\s+.*?\n```\n(.*?)```",
        re.MULTILINE | re.DOTALL,
    )
    for m in patron.finditer(full_text):
        num = int(m.group(1))
        texto = m.group(2).strip()
        paginas[num] = texto
    return paginas


def _agrupar_crosspage(
    tablas: list[TablaDetectada],
) -> list[list[TablaDetectada]]:
    """
    Agrupa tablas en páginas consecutivas como un solo grupo cross-page.
    Páginas 140, 141, 142 → un grupo. Página 135 sola → otro grupo.
    """
    if not tablas:
        return []

    # Ordenar por página
    tablas_ord = sorted(tablas, key=lambda t: t.pagina)
    grupos: list[list[TablaDetectada]] = [[tablas_ord[0]]]

    for tabla in tablas_ord[1:]:
        ultimo_grupo = grupos[-1]
        ultima_pagina = ultimo_grupo[-1].pagina
        # Consecutiva = diferencia de 1
        if tabla.pagina - ultima_pagina == 1:
            ultimo_grupo.append(tabla)
        else:
            grupos.append([tabla])

    return grupos


def _reemplazar_selectivo(
    full_text: str,
    reemplazos: dict[int, str],
    textos_por_pagina: dict[int, str],
) -> str:
    """
    Reemplaza SOLO el bloque de tabla dentro del texto de cada página.

    No reemplaza toda la página — busca la sección que parece tabla
    (líneas fragmentadas, cortas) y la sustituye por el markdown.
    El texto fuera de la tabla se preserva.
    """
    for pag_num, nuevo_md in reemplazos.items():
        # Buscar el bloque de esta página en full_text
        patron_pagina = re.compile(
            rf"(## Página {pag_num}\s+.*?\n```\n)(.*?)(```)",
            re.DOTALL,
        )
        match = patron_pagina.search(full_text)
        if not match:
            continue

        header = match.group(1)
        texto_original = match.group(2)
        cierre = match.group(3)

        # Identificar la zona de tabla dentro del texto
        texto_mejorado = _insertar_tabla_en_texto(texto_original, nuevo_md)

        full_text = (
            full_text[:match.start()]
            + header + texto_mejorado + "\n" + cierre
            + full_text[match.end():]
        )

    return full_text


def _insertar_tabla_en_texto(texto_original: str, tabla_md: str) -> str:
    """
    Reemplaza la zona de tabla dentro del texto de una página.

    Estrategia: busca la sección con mayor densidad de líneas cortas
    (< 40 chars) que es la zona de tabla linearizada por OCR.
    Reemplaza esa zona con el markdown de la tabla.
    Preserva texto antes y después.
    """
    lineas = texto_original.split("\n")
    if len(lineas) < 5:
        # Página muy corta, reemplazar todo
        return tabla_md

    # Calcular "densidad de tabla" por ventana deslizante
    ventana = 5
    mejor_inicio = 0
    mejor_score = 0
    scores = []

    for i in range(len(lineas)):
        fin = min(i + ventana, len(lineas))
        bloque = lineas[i:fin]
        cortas = sum(1 for l in bloque if len(l.strip()) < 40 and l.strip())
        total = sum(1 for l in bloque if l.strip())
        score = cortas / max(total, 1)
        scores.append(score)

    # Encontrar la región continua con mayor score
    en_tabla = [s > 0.6 for s in scores]
    inicio_tabla = None
    fin_tabla = None

    for i, es_tabla in enumerate(en_tabla):
        if es_tabla and inicio_tabla is None:
            inicio_tabla = i
        if not es_tabla and inicio_tabla is not None:
            fin_tabla = i
            break

    if inicio_tabla is None:
        # No se encontró zona clara de tabla, reemplazar todo
        return tabla_md

    if fin_tabla is None:
        fin_tabla = len(lineas)

    # Preservar texto antes y después de la tabla
    antes = "\n".join(lineas[:inicio_tabla]).strip()
    despues = "\n".join(lineas[fin_tabla:]).strip()

    partes = []
    if antes:
        partes.append(antes)
    partes.append(tabla_md)
    if despues:
        partes.append(despues)

    return "\n\n".join(partes)
