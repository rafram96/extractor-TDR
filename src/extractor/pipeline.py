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

    Orden de operaciones:
    1. Detecta páginas VL (tablas limpias) ANTES de comprimir — estas se
       aíslan intactas en sub-bloques propios.
    2. Comprime solo las páginas NO-VL que tengan tablas de descripción.
    3. Agrupa las páginas normales por tamaño.

    Esto garantiza que la tabla B.2 (experiencia, meses) llegue intacta
    al LLM, mientras que las tablas B.1 (descripciones enormes de 500+
    chars por celda) se comprimen para no reventar el contexto.
    """
    from src.extractor.scorer import PageScore

    # ── 1. Detectar páginas VL ANTES de cualquier compresión ────────────
    paginas_vl = []
    paginas_normales = []
    for p in block.pages:
        if _es_pagina_tabla_vl(p.text):
            paginas_vl.append(p)
            logger.debug(
                f"[pipeline] Pág {p.page_num}: detectada como tabla VL "
                f"({len(p.text)} chars)"
            )
        else:
            paginas_normales.append(p)

    # ── 2. Comprimir solo páginas normales con tablas grandes ───────────
    pages_comprimidas = []
    for p in paginas_normales:
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

    # ── 3. Si no hay páginas VL y el bloque cabe, devolver directo ──────
    if not paginas_vl:
        block_comprimido = Block(
            block_type=block.block_type, pages=pages_comprimidas,
        )
        if len(block_comprimido.text) <= _MAX_BLOCK_CHARS:
            return [block_comprimido]

    # ── 4. Construir sub-bloques ────────────────────────────────────────
    sub_bloques = []

    # 4a. Sub-bloques aislados para cada página VL (intactas, sin comprimir)
    for p in paginas_vl:
        sub_bloques.append(Block(block_type=block.block_type, pages=[p]))
        logger.info(
            f"[pipeline] Pág {p.page_num} aislada como sub-bloque VL "
            f"({len(p.text)} chars, tabla markdown)"
        )

    # 4b. Sub-bloques normales con las páginas comprimidas restantes
    pages = pages_comprimidas
    total_normal_chars = sum(len(p.text) for p in pages)

    if pages and total_normal_chars <= _MAX_BLOCK_CHARS:
        # Todas las normales caben en un solo sub-bloque
        sub_bloques.append(Block(block_type=block.block_type, pages=pages))
    elif pages:
        # Subdividir por tamaño
        i = 0
        while i < len(pages):
            sub_pages = []
            chars = 0
            while i < len(pages) and (chars + len(pages[i].text)) <= _MAX_BLOCK_CHARS:
                sub_pages.append(pages[i])
                chars += len(pages[i].text)
                i += 1

            if not sub_pages and i < len(pages):
                sub_pages.append(pages[i])
                i += 1

            if sub_pages:
                sub_bloques.append(Block(
                    block_type=block.block_type, pages=sub_pages,
                ))
                if len(sub_pages) > _OVERLAP_PAGES:
                    i -= _OVERLAP_PAGES

    # Ordenar sub-bloques por página inicial para mantener orden lógico
    sub_bloques.sort(key=lambda sb: sb.pages[0].page_num)

    if len(sub_bloques) > 1:
        n_pages = [len(sb.pages) for sb in sub_bloques]
        total_chars = sum(len(p.text) for sb in sub_bloques for p in sb.pages)
        logger.info(
            f"[pipeline] Bloque '{block.block_type}' págs {block.page_range} "
            f"({total_chars} chars) → {len(sub_bloques)} sub-bloques "
            f"({n_pages} págs)"
        )

    return sub_bloques if sub_bloques else [block]




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


def _extraer_numero_de_string(s: str) -> int | None:
    """
    Extrae el primer número entero de un string como "48 meses" → 48.
    Retorna None si no hay número o si el string es demasiado largo
    (no es un campo de cantidad, sino texto libre).
    """
    if len(s) > 30:  # textos largos no son cantidades
        return None
    m = re.match(r"(\d+)", s.strip())
    return int(m.group(1)) if m else None


def _merge_deep(base: dict, nuevo: dict, base_es_vl: bool = False) -> dict:
    """
    Fusiona dos dicts: campos no-nulos de 'nuevo' rellenan los nulos de 'base'.
    Para sub-dicts (experiencia_minima, capacitacion), fusiona recursivamente.
    Para listas, conserva la más larga.
    Para strings, si ambos son no-nulos conserva el más largo (más informativo).
    Para numéricos, conserva el mayor — EXCEPTO cuando base proviene de una
    tabla VL validada (base_es_vl=True): en ese caso se confía en el valor
    de la tabla limpia y no se sobreescribe con el OCR fragmentado.
    """
    resultado = dict(base)
    for k, v in nuevo.items():
        if k.startswith("_"):
            continue
        base_v = resultado.get(k)
        if isinstance(base_v, dict) and isinstance(v, dict):
            resultado[k] = _merge_deep(base_v, v, base_es_vl)
        elif isinstance(base_v, list) and isinstance(v, list):
            # Si base proviene de una tabla VL, confiar en su lista —
            # no sobreescribir aunque la nueva sea más larga (puede haber
            # confundido columnas adyacentes, como ocurre en tablas densas).
            if not base_es_vl and len(v) > len(base_v):
                resultado[k] = v
        elif _es_nulo(base_v) and not _es_nulo(v):
            resultado[k] = v
        elif (isinstance(base_v, (int, float)) and isinstance(v, (int, float))
              and not _es_nulo(base_v) and not _es_nulo(v)):
            # Si base es VL, sus valores numéricos son los correctos — no sobreescribir
            if not base_es_vl and v > base_v:
                resultado[k] = v
        elif (isinstance(base_v, str) and isinstance(v, str)
              and not _es_nulo(base_v) and not _es_nulo(v)):
            num_base = _extraer_numero_de_string(base_v)
            num_nuevo = _extraer_numero_de_string(v)
            if num_base is not None and num_nuevo is not None:
                # Si base es VL, respetar su número aunque sea menor
                if not base_es_vl and num_nuevo > num_base:
                    resultado[k] = v
            elif len(v) > len(base_v):
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

    # 1b. Strip "de"/"del" that connects a role word to a specialty name
    #     "Gestor de BIM" → "Gestor BIM"
    #     "Director del Proyecto" is also stripped, which is fine for dedup purposes.
    #     Aplica solo a palabras de rol OSCE estándar para no alterar "Especialista en X".
    base = re.sub(
        r"^(Gestor|Director|Gerente|Coordinador|Jefe|L[ií]der|Supervisor"
        r"|Responsable|Encargado|Administrador|Representante)\s+de(?:l)?\s+",
        r"\1 ", base, flags=re.IGNORECASE,
    )

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

    Prioridad VL: si una entrada viene de un sub-bloque VL (tabla validada
    visualmente), se usa como base en el merge para que sus valores numéricos
    exactos no sean sobreescritos por el OCR fragmentado.
    """
    por_cargo: dict[str, dict] = {}
    for entrada in lista:
        cargo = entrada.get("cargo")
        if _es_nulo(cargo):
            continue

        cargo_key = _normalizar_cargo(str(cargo))
        es_vl = bool(entrada.get("_vl_source"))

        if cargo_key not in por_cargo:
            por_cargo[cargo_key] = entrada
        else:
            existente = por_cargo[cargo_key]
            existente_es_vl = bool(existente.get("_vl_source"))

            if es_vl and not existente_es_vl:
                # Nueva entrada es VL: usarla como base (sus valores son correctos)
                por_cargo[cargo_key] = _merge_deep(entrada, existente, base_es_vl=True)
                logger.debug(f"[dedup] Fusionado '{cargo}' → '{cargo_key}' (VL base)")
            else:
                por_cargo[cargo_key] = _merge_deep(existente, entrada, base_es_vl=existente_es_vl)
                logger.debug(f"[dedup] Fusionado '{cargo}' → '{cargo_key}'")

    # Quitar campo interno _vl_source antes de devolver
    resultado = []
    for entrada in por_cargo.values():
        entrada.pop("_vl_source", None)
        resultado.append(entrada)
    return resultado


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
    Elimina roles de "Asistente" cuando existen "Especialistas" en los
    resultados. En documentos OSCE, los Asistentes aparecen en la sección
    TDR/Funciones (págs 36-42) y son roles de soporte, NO personal clave
    del concurso (que son los Especialistas de las tablas B.1/B.2).

    Estrategia:
    1. Si hay al menos un Especialista, activar filtro.
    2. Recopilar especialidades normalizadas de Especialistas
       (usa _normalizar_cargo para "en la especialidad de X" → "x").
    3. Para cada Asistente, normalizar su especialidad y comparar.
    4. Si hay match directo → descartar.
    5. Si no hay match pero hay Especialistas → descartar también
       (ej: "Asistente en Ingeniería Civil" no matchea ningún
       Especialista porque el equivalente es "Estructuras", pero
       sigue siendo un rol TDR, no personal clave).
    """
    # Recopilar especialidades normalizadas de Especialistas
    especialidades_cubiertas: set[str] = set()
    tiene_especialistas = False
    for entrada in lista:
        cargo = str(entrada.get("cargo", ""))
        normalizado = _normalizar_cargo(cargo)
        if normalizado.startswith("especialista"):
            tiene_especialistas = True
            # Extraer la parte después de "especialista en "
            m = re.match(r"especialista\s+(?:de|en)\s+(.+)$", normalizado)
            if m:
                especialidades_cubiertas.add(m.group(1).strip())

    if not tiene_especialistas:
        return lista

    resultado = []
    for entrada in lista:
        cargo = str(entrada.get("cargo", ""))
        normalizado = _normalizar_cargo(cargo)
        if normalizado.startswith("asistente"):
            # Extraer especialidad del asistente normalizado
            m = re.match(r"asistente\s+(?:de|en)\s+(.+)$", normalizado)
            esp_asist = m.group(1).strip() if m else None

            if esp_asist and esp_asist in especialidades_cubiertas:
                logger.info(
                    f"[filtro] Descartado '{cargo}' — match directo con "
                    f"Especialista en '{esp_asist}'"
                )
            else:
                # No hay match directo, pero es un Asistente de sección TDR
                # y existen Especialistas → descartar igualmente
                logger.info(
                    f"[filtro] Descartado '{cargo}' — rol de soporte TDR, "
                    f"no es personal clave del concurso"
                )
            continue
        resultado.append(entrada)

    descartados = len(lista) - len(resultado)
    if descartados:
        logger.info(
            f"[filtro] {descartados} Asistente(s) descartado(s) "
            f"(sección TDR, no personal clave)"
        )
    return resultado


def _limpiar_anos_colegiado(valor: Any) -> Any:
    """
    Elimina sufijos y prefijos OSCE estándar del campo anos_colegiado.

    Ejemplos:
      "24 meses (Computada desde la fecha de la colegiatura)"
        → "24 meses"
      "Título profesional, 36 meses"
        → "36 meses"
      "48 meses (contabilizada desde la emisión del grado o título)"
        → "48 meses"
    """
    if not isinstance(valor, str):
        return valor
    s = valor
    # Quitar prefijo "Título profesional[,] "
    s = re.sub(r"^[Tt][ií]tulo\s+profesional,?\s*", "", s)
    # Quitar paréntesis que contengan términos OSCE sobre cómputo de plazos
    s = re.sub(
        r"\s*\([^)]*(?:colegiatura|grado\s+o\s+t[ií]tulo|t[ií]tulo\s+profesional"
        r"|computada|contabilizada)[^)]*\)",
        "", s, flags=re.IGNORECASE,
    )
    return s.strip()


def _similarity_cargo(a: str, b: str) -> float:
    """Overlap de palabras entre dos strings de cargo normalizados."""
    words_a = set(a.split())
    words_b = set(b.split())
    if not words_a or not words_b:
        return 0.0
    return len(words_a & words_b) / max(len(words_a), len(words_b))


def _cruzar_personal_con_factores(
    personal: list[dict],
    factores: list[dict],
) -> list[dict]:
    """
    Popula tiempo_adicional_factores en cada cargo de rtm_personal buscando
    si existe un factor de evaluación de experiencia que lo mencione.

    Estrategia en dos pasadas:
    1. Matching específico: cargo_personal del factor coincide con algún cargo.
    2. Fallback genérico: factores cuyo cargo_personal no coincide con ningún
       cargo específico (ej: "Consultoría de Obra") se aplican a todos los
       cargos que aún no tengan tiempo_adicional_factores.
    """
    factores_personal = [
        f for f in factores
        if f.get("aplica_a") == "personal" and not _es_nulo(f.get("cargo_personal"))
    ]
    if not factores_personal:
        return personal

    personal_norms = [
        _normalizar_cargo(str(e.get("cargo", ""))) for e in personal
    ]

    # ── Pasada 1: matching específico ────────────────────────────────────
    factores_matched: set[int] = set()
    for cargo_entry in personal:
        cargo = cargo_entry.get("cargo")
        if _es_nulo(cargo) or not _es_nulo(cargo_entry.get("tiempo_adicional_factores")):
            continue
        cargo_norm = _normalizar_cargo(str(cargo))

        for i_f, factor in enumerate(factores_personal):
            cargo_factor_norm = _normalizar_cargo(str(factor.get("cargo_personal", "")))
            if (cargo_norm == cargo_factor_norm
                    or cargo_norm in cargo_factor_norm
                    or cargo_factor_norm in cargo_norm
                    or _similarity_cargo(cargo_norm, cargo_factor_norm) >= 0.6):
                puntaje = factor.get("puntaje_maximo")
                metodologia = factor.get("metodologia", "")
                cargo_entry["tiempo_adicional_factores"] = (
                    metodologia[:300] if metodologia
                    else (f"Hasta {puntaje} puntos" if puntaje else "Sí evalúa")
                )
                factores_matched.add(i_f)
                logger.debug(
                    f"[cruce] '{cargo}' → factor '{factor.get('factor')}' (específico)"
                )
                break

    # ── Pasada 2: fallback genérico ───────────────────────────────────────
    # Un factor es "genérico" si su cargo_personal no coincide con ningún
    # cargo del personal clave con similaridad ≥ 0.5.
    factores_genericos = [
        factores_personal[i] for i in range(len(factores_personal))
        if i not in factores_matched
        and all(
            _similarity_cargo(
                _normalizar_cargo(str(factores_personal[i].get("cargo_personal", ""))),
                pn,
            ) < 0.5
            for pn in personal_norms
        )
    ]

    if factores_genericos:
        factor_gen = factores_genericos[0]
        puntaje = factor_gen.get("puntaje_maximo")
        metodologia = factor_gen.get("metodologia", "")
        texto_gen = (
            metodologia[:300] if metodologia
            else (f"Hasta {puntaje} puntos" if puntaje else "Sí evalúa")
        )
        for cargo_entry in personal:
            if _es_nulo(cargo_entry.get("tiempo_adicional_factores")):
                cargo_entry["tiempo_adicional_factores"] = texto_gen
                logger.debug(
                    f"[cruce] '{cargo_entry.get('cargo')}' → "
                    f"factor genérico '{factor_gen.get('factor')}'"
                )

    return personal


def _cruzar_postor_con_factores(
    postor: list[dict],
    factores: list[dict],
) -> list[dict]:
    """
    Popula otros_factores_postor en rtm_postor con los factores de evaluación
    que aplican al postor (excluye oferta económica).
    """
    factores_postor = [
        f for f in factores
        if f.get("aplica_a") == "postor"
        and not re.search(
            r"oferta econ[oó]mica|propuesta econ[oó]mica",
            str(f.get("factor", "")), re.IGNORECASE,
        )
    ]
    if not postor or not factores_postor:
        return postor

    factores_text = "; ".join(
        f"{f.get('factor', '')} ({f.get('puntaje_maximo', '')} pts)"
        for f in factores_postor
    )
    for entry in postor:
        if _es_nulo(entry.get("otros_factores_postor")):
            entry["otros_factores_postor"] = factores_text

    return postor


def _guardar_debug_bloques(
    blocks: list[Block],
    output_dir: Path,
) -> None:
    """
    Escribe output/bloques_debug.md con el texto exacto que cada sub-bloque
    envía al LLM. Permite verificar:
    - Si las páginas VL (tablas markdown) están aisladas
    - Si la compresión destruyó datos útiles
    - Qué texto ve el LLM para cada rango de páginas
    """
    from datetime import datetime

    lineas = [
        f"# Debug Sub-bloques → LLM — {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "",
        f"**Bloques detectados:** {len(blocks)}",
        "",
        "---",
        "",
    ]

    bloque_num = 0
    for block in blocks:
        sub_blocks = _subdividir_bloque(block)
        for i_sub, sb in enumerate(sub_blocks, 1):
            bloque_num += 1
            es_vl = any(
                _es_pagina_tabla_vl(p.text) for p in sb.pages
            )
            tag = " 🟢 VL AISLADO" if es_vl and len(sb.pages) == 1 else ""

            lineas.append(
                f"## Bloque {bloque_num}: [{block.block_type}] "
                f"págs {sb.page_range} "
                f"({len(sb.text)} chars){tag}"
            )
            lineas.append("")

            if len(sub_blocks) > 1:
                lineas.append(
                    f"*Sub-bloque {i_sub}/{len(sub_blocks)} "
                    f"del bloque original págs {block.page_range}*"
                )
                lineas.append("")

            # Texto por página
            for p in sb.pages:
                es_tabla = _es_pagina_tabla_vl(p.text)
                tag_pag = " 📊 TABLA VL" if es_tabla else ""
                lineas.append(
                    f"### Página {p.page_num} ({len(p.text)} chars){tag_pag}"
                )
                lineas.append("```")
                # Mostrar completo si es tabla VL (son los datos clave),
                # truncar si es texto normal largo
                if es_tabla or len(p.text) <= 2000:
                    lineas.append(p.text)
                else:
                    lineas.append(p.text[:1000])
                    lineas.append(f"\n... ({len(p.text) - 1000} chars más) ...")
                    lineas.append(p.text[-500:])
                lineas.append("```")
                lineas.append("")

            lineas.append("---")
            lineas.append("")

    output_path = Path(output_dir) / "bloques_debug.md"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(lineas), encoding="utf-8")
    logger.info(f"[pipeline] Debug bloques guardado en {output_path}")


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

    # ── Debug: guardar texto de sub-bloques para inspección ──────────────
    if output_dir:
        try:
            _guardar_debug_bloques(blocks, output_dir)
        except Exception as e:
            logger.warning(f"[pipeline] Error guardando debug bloques: {e}")

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
            # Detectar si este sub-bloque es una tabla VL validada (página única
            # con markdown estructurado). Sus valores numéricos son más fiables
            # que el OCR fragmentado y no deben ser sobreescritos en el merge.
            es_sub_vl = (
                len(sub_block.pages) == 1
                and _es_pagina_tabla_vl(sub_block.pages[0].text)
            )

            if len(sub_blocks) > 1:
                tag_vl = " [VL]" if es_sub_vl else ""
                logger.info(
                    f"[pipeline]   Sub-bloque {i_sub}/{len(sub_blocks)} "
                    f"págs {sub_block.page_range} ({len(sub_block.text)} chars){tag_vl}"
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
                items = data.get("personal_clave", [])
                if es_sub_vl:
                    for item in items:
                        item["_vl_source"] = True
                resultado["rtm_personal"].extend(items)
            elif block.block_type == "factores_evaluacion":
                resultado["factores_evaluacion"].extend(data.get("factores_evaluacion", []))

    # Post-proceso: deduplicar personal y limpiar entradas vacías
    resultado["rtm_personal"] = _dedup_personal(resultado["rtm_personal"])

    # Limpiar sufijos OSCE estándar en anos_colegiado
    for entry in resultado["rtm_personal"]:
        if not _es_nulo(entry.get("anos_colegiado")):
            entry["anos_colegiado"] = _limpiar_anos_colegiado(entry["anos_colegiado"])

    # Filtrar "Asistentes" espurios cuando existe un "Especialista" equivalente.
    resultado["rtm_personal"] = _filtrar_asistentes(resultado["rtm_personal"])

    # Cruce personal ↔ factores: popula tiempo_adicional_factores
    resultado["rtm_personal"] = _cruzar_personal_con_factores(
        resultado["rtm_personal"], resultado["factores_evaluacion"],
    )

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

    # Cruce postor ↔ factores: popula otros_factores_postor
    resultado["rtm_postor"] = _cruzar_postor_con_factores(
        resultado["rtm_postor"], resultado["factores_evaluacion"],
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