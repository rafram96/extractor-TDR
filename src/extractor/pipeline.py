from __future__ import annotations
import logging
import re
import time
from pathlib import Path
from typing import Any

from src.extractor.parser import parse_full_text
from src.extractor.scorer import score_page, group_into_blocks, Block
from src.extractor.llm import extraer_bloque
from src.extractor.report import (
    DiagnosticData, LLMInteraction, generar_reporte,
)

logger = logging.getLogger(__name__)

# Máximo de caracteres por bloque antes de subdividir
_MAX_BLOCK_CHARS = 15_000
_OVERLAP_PAGES = 1  # páginas de solapamiento entre sub-bloques


def _comprimir_tabla_vl(text: str, max_chars: int = 4000) -> str:
    """
    Comprime tablas markdown grandes generadas por Qwen VL.

    Qwen VL a veces genera dos tablas en una misma página:
      1. Tabla resumen (B.1): Item | Cargo | Profesión | Cant. — celdas cortas, útil
      2. Tabla de descripciones: Cargo | Descripción de actividades — celdas de 500+ chars

    Estrategia: eliminar filas donde ALGUNA celda excede 200 chars
    (son filas de descripción de actividades, no de requisitos).
    """
    if len(text) <= max_chars:
        return text

    # Detectar si el texto tiene tablas markdown (líneas con |)
    lineas = text.split("\n")
    lineas_tabla = [l for l in lineas if "|" in l and l.strip().startswith("|")]
    if len(lineas_tabla) < 3:
        return text  # No es una tabla significativa

    _MAX_CELDA = 200  # celdas de resumen son <100 chars, descripciones >500

    resultado = []
    filas_eliminadas = 0

    for linea in lineas:
        if "|" not in linea or not linea.strip().startswith("|"):
            resultado.append(linea)
            continue

        celdas = [c.strip() for c in linea.split("|")]
        max_celda = max((len(c) for c in celdas), default=0)

        if max_celda > _MAX_CELDA:
            filas_eliminadas += 1
            continue  # Saltar filas con descripciones enormes

        resultado.append(linea)

    texto_comprimido = "\n".join(resultado)

    if filas_eliminadas > 0:
        ahorro = len(text) - len(texto_comprimido)
        logger.info(
            f"[pipeline] Tabla VL comprimida: {len(text)} → {len(texto_comprimido)} chars "
            f"(−{ahorro}, {ahorro*100//len(text)}% reducción, "
            f"{filas_eliminadas} filas de descripción eliminadas)"
        )
    return texto_comprimido


def _es_pagina_tabla_vl(text: str) -> bool:
    """
    Detecta si una página es predominantemente una tabla markdown (VL-enhanced).

    Criterio: >60% de las líneas no-vacías son filas de tabla (empiezan con |)
    y hay al menos 5 filas de tabla.
    """
    lineas = [l for l in text.strip().split("\n") if l.strip()]
    if not lineas:
        return False
    lineas_tabla = [l for l in lineas if l.strip().startswith("|")]
    return len(lineas_tabla) >= 5 and len(lineas_tabla) / len(lineas) > 0.6


def _subdividir_bloque(block: Block) -> list[Block]:
    """
    Si un bloque supera _MAX_BLOCK_CHARS, lo divide en sub-bloques
    más pequeños con _OVERLAP_PAGES de solapamiento.

    Antes de subdividir:
    1. Comprime tablas VL con filas de descripción enormes.
    2. Aísla páginas VL (tablas limpias) en sub-bloques propios para que
       el LLM las lea sin ruido de OCR garbled circundante.
    """
    # Comprimir páginas con tablas VL antes de evaluar tamaño
    from src.extractor.scorer import PageScore
    pages_comprimidas = []
    for p in block.pages:
        if len(p.text) > 4000 and "|" in p.text:
            texto_comprimido = _comprimir_tabla_vl(p.text)
            if texto_comprimido != p.text:
                p = PageScore(
                    page_num=p.page_num,
                    confidence=p.confidence,
                    text=texto_comprimido,
                    scores=p.scores,
                )
        pages_comprimidas.append(p)

    block = Block(block_type=block.block_type, pages=pages_comprimidas)

    if len(block.text) <= _MAX_BLOCK_CHARS:
        return [block]

    # ── Separar páginas VL (tablas limpias) de páginas normales ─────────
    # Las páginas VL van en sub-bloques aislados para que el LLM las lea
    # sin ruido. Las demás se agrupan normalmente por tamaño.
    paginas_vl = []
    paginas_normales = []
    for p in block.pages:
        if _es_pagina_tabla_vl(p.text):
            paginas_vl.append(p)
        else:
            paginas_normales.append(p)

    sub_bloques = []

    # Sub-bloques aislados para cada página VL
    for p in paginas_vl:
        sub_bloques.append(Block(block_type=block.block_type, pages=[p]))
        logger.info(
            f"[pipeline] Pág {p.page_num} aislada como sub-bloque VL "
            f"({len(p.text)} chars, tabla markdown)"
        )

    # Sub-bloques normales con las páginas restantes
    pages = paginas_normales
    i = 0

    while i < len(pages):
        # Acumular páginas hasta llegar al límite
        sub_pages = []
        chars = 0
        while i < len(pages) and (chars + len(pages[i].text)) <= _MAX_BLOCK_CHARS:
            sub_pages.append(pages[i])
            chars += len(pages[i].text)
            i += 1

        # Si no pudimos agregar ni una página (página individual > límite), agregarla sola
        if not sub_pages and i < len(pages):
            sub_pages.append(pages[i])
            i += 1

        if sub_pages:
            sub_bloques.append(Block(block_type=block.block_type, pages=sub_pages))
            # Retroceder para solapamiento, pero solo si avanzamos más de
            # _OVERLAP_PAGES páginas — sino es loop infinito
            if len(sub_pages) > _OVERLAP_PAGES:
                i -= _OVERLAP_PAGES

    # Ordenar sub-bloques por página inicial para mantener orden lógico
    sub_bloques.sort(key=lambda sb: sb.pages[0].page_num)

    if sub_bloques:
        n_pages = [len(sb.pages) for sb in sub_bloques]
        logger.info(
            f"[pipeline] Bloque '{block.block_type}' págs {block.page_range} "
            f"({len(block.text)} chars) → {len(sub_bloques)} sub-bloques "
            f"({n_pages} págs)"
        )

    return sub_bloques




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


def _contar_campos(obj: Any) -> tuple[int, int]:
    """
    Cuenta (total_campos, campos_nulos) de forma recursiva.
    Para dicts anidados, cuenta sus campos internos en vez del dict como 1 campo.
    Para listas, cuenta como nulo si está vacía.
    """
    if isinstance(obj, dict):
        total = 0
        nulos = 0
        for v in obj.values():
            t, n = _contar_campos(v)
            total += t
            nulos += n
        return total, nulos
    # Un campo hoja
    es_nulo = _es_nulo(obj) or (isinstance(obj, list) and len(obj) == 0)
    return 1, (1 if es_nulo else 0)


def _filtrar_registros_vacios(
    lista: list[dict],
    nombre_seccion: str,
    umbral: float = 0.80,
) -> list[dict]:
    """
    Elimina registros donde el porcentaje de campos nulos >= umbral.
    Por defecto elimina registros con 80% o más de campos nulos.
    """
    filtrados = []
    for registro in lista:
        total, nulos = _contar_campos(registro)
        if total == 0:
            logger.debug(f"[validador] {nombre_seccion}: descartado registro sin campos")
            continue
        ratio = nulos / total
        if ratio >= umbral:
            # Vista previa del registro para el log
            preview = {k: v for k, v in registro.items()
                       if not _es_nulo(v) and k != "archivo"}
            logger.info(
                f"[validador] {nombre_seccion}: descartado registro "
                f"({nulos}/{total} campos nulos = {ratio:.0%}): {preview}"
            )
            continue
        filtrados.append(registro)
    descartados = len(lista) - len(filtrados)
    if descartados:
        logger.info(
            f"[validador] {nombre_seccion}: {descartados} registro(s) descartado(s) "
            f"por tener ≥{umbral:.0%} campos nulos"
        )
    return filtrados


def _merge_deep(base: dict, nuevo: dict) -> dict:
    """
    Fusiona dos dicts: campos no-nulos de 'nuevo' rellenan los nulos de 'base'.
    Para sub-dicts (experiencia_minima, capacitacion), fusiona recursivamente.
    Para listas, conserva la más larga.
    Para strings, si ambos son no-nulos conserva el más largo (más informativo).
    """
    resultado = dict(base)
    for k, v in nuevo.items():
        if k.startswith("_"):
            continue
        base_v = resultado.get(k)
        if isinstance(base_v, dict) and isinstance(v, dict):
            resultado[k] = _merge_deep(base_v, v)
        elif isinstance(base_v, list) and isinstance(v, list):
            if len(v) > len(base_v):
                resultado[k] = v
        elif _es_nulo(base_v) and not _es_nulo(v):
            resultado[k] = v
        elif (isinstance(base_v, str) and isinstance(v, str)
              and not _es_nulo(base_v) and not _es_nulo(v)):
            # Preferir string más largo (más informativo)
            if len(v) > len(base_v):
                resultado[k] = v
    return resultado


def _normalizar_cargo(cargo: str) -> str:
    """
    Normaliza nombre de cargo para dedup fuzzy.

    Ejemplos:
      "Jefe de elaboración del expediente técnico"
        → "jefe"
      "Jefe y/o Gerente y/o Director y/o Gestor y/o Coordinador"
        → "jefe"
      "Gestor BIM y/o líder BIM y/o Supervisor BIM..."
        → "gestor bim"
      "Gestor BIM"
        → "gestor bim"
      "Especialista en Arquitectura"
        → "especialista en arquitectura"
      "Especialista en desarrollo y/o elaboración y/o ... en la especialidad de Estructuras"
        → "especialista en estructuras"
      "Especialista en desarrollo y/o ... en la especialidad de Instalaciones Eléctricas"
        → "especialista en instalaciones eléctricas"
    """
    texto = cargo.strip()

    # 0. Caso especial: cargos con "en la especialidad de X"
    #    El LLM a veces genera cargos largos tipo:
    #    "Especialista en desarrollo y/o elaboración y/o supervisión y/o
    #     diseño en la especialidad de Instalaciones Eléctricas"
    #    La identidad real del cargo es la especialidad final.
    m_esp = re.search(
        r"especialidad\s+de\s+(.+)$", texto, re.IGNORECASE,
    )
    if m_esp:
        especialidad = m_esp.group(1).strip().lower()
        return f"especialista en {especialidad}"

    # 1. Tomar primera alternativa de "X y/o Y y/o Z"
    base = re.split(r"\s+y/o\s+", texto, maxsplit=1)[0].strip()

    # 2. Quitar frases de acción tras el cargo base:
    #    "de elaboración del expediente técnico" → ""
    #    "en la elaboración de expedientes" → ""
    #    Pero NO quitar "en Arquitectura", "en Estructuras", etc.
    base = re.sub(
        r"\s+(?:de|en)\s+(?:la\s+)?(?:elaboración|desarrollo|supervisión|diseño)"
        r"(?:\s+\S+)*$",
        "", base, flags=re.IGNORECASE,
    )

    return base.strip().lower()


def _dedup_personal(lista: list[dict]) -> list[dict]:
    """
    Fusiona duplicados de personal clave por cargo normalizado.
    Cuando hay dos entradas del mismo cargo (ej. "Gestor BIM" y
    "Gestor BIM y/o líder BIM..."), combina sus campos:
    los no-nulos de cada entrada se complementan mutuamente.
    """
    por_cargo: dict[str, dict] = {}
    for entrada in lista:
        cargo = entrada.get("cargo")
        if _es_nulo(cargo):
            continue

        cargo_key = _normalizar_cargo(str(cargo))
        if cargo_key not in por_cargo:
            por_cargo[cargo_key] = entrada
        else:
            por_cargo[cargo_key] = _merge_deep(por_cargo[cargo_key], entrada)
            logger.debug(
                f"[dedup] Fusionado cargo '{cargo}' → key '{cargo_key}'"
            )

    return list(por_cargo.values())


def _extraer_especialidad(cargo: str) -> str | None:
    """
    Extrae la especialidad base de un cargo, independientemente de si es
    "Asistente de X", "Asistente en X", o "Especialista en X".

    Ejemplos:
      "Asistente de Arquitectura"              → "arquitectura"
      "Asistente en Ingeniería Sanitaria"      → "ingeniería sanitaria"
      "Asistente en Instalaciones Eléctricas"   → "instalaciones eléctricas"
      "Especialista en Arquitectura"            → "arquitectura"
      "Especialista en Inst. Mecánicas"         → "instalaciones mecánicas"
      "Jefe de elaboración..."                  → None (no aplica)
    """
    m = re.match(
        r"(?:asistente|especialista)\s+(?:de|en)\s+(.+)$",
        cargo.strip(), re.IGNORECASE,
    )
    return m.group(1).strip().lower() if m else None


def _filtrar_asistentes(lista: list[dict]) -> list[dict]:
    """
    Elimina roles de "Asistente" cuando existe un "Especialista" para la
    misma especialidad. Las secciones TDR/Anexo generan roles de soporte
    que no son personal clave del concurso.
    """
    # Recopilar especialidades cubiertas por Especialistas (no Asistentes)
    especialidades_cubiertas: set[str] = set()
    for entrada in lista:
        cargo = str(entrada.get("cargo", ""))
        if re.match(r"especialista\b", cargo.strip(), re.IGNORECASE):
            esp = _extraer_especialidad(cargo)
            if esp:
                especialidades_cubiertas.add(esp)

    if not especialidades_cubiertas:
        return lista

    resultado = []
    for entrada in lista:
        cargo = str(entrada.get("cargo", ""))
        if re.match(r"asistente\b", cargo.strip(), re.IGNORECASE):
            esp = _extraer_especialidad(cargo)
            if esp and esp in especialidades_cubiertas:
                logger.info(
                    f"[filtro] Descartado '{cargo}' — existe Especialista "
                    f"en '{esp}'"
                )
                continue
        resultado.append(entrada)

    descartados = len(lista) - len(resultado)
    if descartados:
        logger.info(
            f"[filtro] {descartados} Asistente(s) descartado(s) por tener "
            f"Especialista equivalente"
        )
    return resultado


def extraer_bases(
    full_text: str,
    nombre_archivo: str = "",
    pdf_path: str = "",
    output_dir: Path | None = None,
) -> dict:
    """
    Pipeline completo: full_text del motor OCR → JSON estructurado.

    Args:
        full_text: Texto completo del _texto_*.md
        nombre_archivo: Nombre del PDF (para metadatos)
        pdf_path: Ruta al PDF original (para mejora de tablas)
        output_dir: Directorio de salida (para generar reporte diagnóstico)

    Returns:
        {
            "rtm_postor":          [...],
            "rtm_personal":        [...],
            "factores_evaluacion": [...],
            "_bloques_detectados": [...],
            "_tablas_stats":       {...}   # estadísticas de mejora de tablas
        }
    """
    # ── Inicializar datos de diagnóstico ──────────────────────────────────
    diag = DiagnosticData(nombre_archivo=nombre_archivo)

    pages  = parse_full_text(full_text)
    scored = [score_page(p) for p in pages]

    # ── Mejora de tablas (antes de agrupar bloques) ──────────────────────
    #    FASE VL: usa Qwen VL para leer tablas visualmente.
    #    Al terminar, descarga VL de Ollama para liberar VRAM antes de Qwen 14B.
    tablas_stats = None
    if pdf_path:
        try:
            from src.tables.enhancer import mejorar_texto_con_tablas
            # Usar todas las páginas de los bloques (incluye gap pages como 39,40
            # y páginas con heurística baja que sí están dentro de bloques importantes)
            _bloques_pre = group_into_blocks(scored)
            paginas_relevantes = sorted({
                p.page_num for b in _bloques_pre for p in b.pages
            })
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

    # Guardar scores para diagnóstico
    diag.all_scores = list(scored)

    # Capturar datos de tablas si existen
    if tablas_stats:
        diag.tablas_paginas_heuristicas = getattr(
            tablas_stats, "paginas_detectadas_heuristica", []
        )
        diag.tablas_docling_confirmadas = getattr(
            tablas_stats, "paginas_confirmadas_docling", []
        )
        diag.tablas_detalles = getattr(tablas_stats, "detalles", [])

    blocks = group_into_blocks(scored)
    diag.blocks = list(blocks)

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

    t_llm_total = time.perf_counter()
    for i_block, block in enumerate(blocks, 1):
        resultado["_bloques_detectados"].append({
            "tipo":    block.block_type,
            "paginas": list(block.page_range),
        })

        logger.info(
            f"[pipeline] Bloque {i_block}/{len(blocks)}: "
            f"'{block.block_type}' págs {block.page_range} "
            f"({len(block.text)} chars)"
        )

        # Subdividir bloques grandes para que el LLM no pierda contexto
        sub_blocks = _subdividir_bloque(block)

        for i_sub, sub_block in enumerate(sub_blocks, 1):
            if len(sub_blocks) > 1:
                logger.info(
                    f"[pipeline]   Sub-bloque {i_sub}/{len(sub_blocks)} "
                    f"págs {sub_block.page_range} ({len(sub_block.text)} chars)"
                )
            t_bloque = time.perf_counter()
            data, llm_diag = extraer_bloque(sub_block)
            dt = time.perf_counter() - t_bloque
            logger.info(
                f"[pipeline]   → {sub_block.block_type} págs {sub_block.page_range}: "
                f"{'OK' if data else 'VACÍO'} en {dt:.1f}s"
            )

            # Registrar interacción LLM para diagnóstico
            diag.llm_interactions.append(LLMInteraction(
                block_type=llm_diag["block_type"],
                page_range=tuple(llm_diag["page_range"]),
                pages_included=llm_diag["pages_included"],
                prompt_chars=llm_diag["prompt_chars"],
                text_preview=llm_diag["text_preview"],
                raw_response=llm_diag["raw_response"],
                cleaned_response=llm_diag["cleaned_response"],
                parsed_ok=llm_diag["parsed_ok"],
                parsed_keys=llm_diag["parsed_keys"],
                items_extracted=llm_diag["items_extracted"],
                error=llm_diag["error"],
            ))

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

    # Filtrar "Asistentes" espurios cuando existe un "Especialista" equivalente.
    # Páginas de TDR/Anexo (ej: 36-42) generan roles de soporte ("Asistente de
    # Arquitectura") que no son personal clave del concurso. Si existe un
    # "Especialista en Arquitectura" de la sección de calificación, el Asistente
    # es redundante.
    resultado["rtm_personal"] = _filtrar_asistentes(resultado["rtm_personal"])

    # Validación final: eliminar registros con ≥80% de campos nulos
    resultado["rtm_postor"] = _filtrar_registros_vacios(
        resultado["rtm_postor"], "rtm_postor",
    )
    resultado["rtm_personal"] = _filtrar_registros_vacios(
        resultado["rtm_personal"], "rtm_personal",
    )
    resultado["factores_evaluacion"] = _filtrar_registros_vacios(
        resultado["factores_evaluacion"], "factores_evaluacion",
    )

    dt_llm_total = time.perf_counter() - t_llm_total
    logger.info(
        f"[pipeline] Resultado: "
        f"{len(resultado['rtm_postor'])} items postor · "
        f"{len(resultado['rtm_personal'])} profesionales · "
        f"{len(resultado['factores_evaluacion'])} factores · "
        f"LLM total: {dt_llm_total:.1f}s"
    )

    # ── Generar reporte de diagnóstico ────────────────────────────────────
    diag.resultado = resultado
    if output_dir:
        try:
            generar_reporte(diag, output_dir)
        except Exception as e:
            logger.warning(f"[pipeline] Error generando reporte diagnóstico: {e}")

    return resultado