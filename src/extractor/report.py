"""
Generador de reporte de diagnóstico (.md) para análisis post-corrida.

Muestra qué páginas se procesaron, qué texto se envió al LLM,
qué devolvió, y de dónde viene cada campo del resultado.
NO es un log de debug — es información para analizar y mejorar la extracción.
"""

from __future__ import annotations
import logging
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from src.extractor.scorer import PageScore, Block

logger = logging.getLogger(__name__)


# ── Tipos auxiliares ─────────────────────────────────────────────────────────

@dataclass
class LLMInteraction:
    """Datos de una interacción con el LLM para un bloque."""
    block_type: str
    page_range: tuple[int, int]
    pages_included: list[int]
    prompt_chars: int
    text_preview: str           # Primeros N chars del texto enviado
    raw_response: str           # Respuesta cruda del LLM
    cleaned_response: str       # Después de _limpiar_respuesta
    parsed_ok: bool
    parsed_keys: list[str] = field(default_factory=list)
    items_extracted: int = 0
    error: str = ""


@dataclass
class DiagnosticData:
    """Colector de datos de diagnóstico a lo largo del pipeline."""
    nombre_archivo: str = ""

    # Scoring
    all_scores: list[PageScore] = field(default_factory=list)

    # Bloques
    blocks: list[Block] = field(default_factory=list)

    # Tablas (enhancer)
    tablas_paginas_heuristicas: list[int] = field(default_factory=list)
    tablas_docling_confirmadas: list[int] = field(default_factory=list)
    tablas_detalles: list[dict] = field(default_factory=list)

    # LLM
    llm_interactions: list[LLMInteraction] = field(default_factory=list)

    # Resultado final
    resultado: dict = field(default_factory=dict)


# ── Generador de reporte ─────────────────────────────────────────────────────

def generar_reporte(diag: DiagnosticData, output_dir: Path) -> Path:
    """Genera el reporte .md de diagnóstico y retorna la ruta del archivo."""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    stem = Path(diag.nombre_archivo).stem if diag.nombre_archivo else "desconocido"
    ruta = output_dir / f"{stem}_diagnostico_{timestamp}.md"

    lines: list[str] = []

    # ── Header ───────────────────────────────────────────────────────────
    lines.append(f"# Diagnóstico de Extracción — {diag.nombre_archivo}")
    lines.append(f"\n**Fecha:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append("")

    # ── 1. Scoring ───────────────────────────────────────────────────────
    _section_scoring(lines, diag)

    # ── 2. Bloques ───────────────────────────────────────────────────────
    _section_bloques(lines, diag)

    # ── 3. Tablas (enhancer) ─────────────────────────────────────────────
    _section_tablas(lines, diag)

    # ── 4. LLM ───────────────────────────────────────────────────────────
    _section_llm(lines, diag)

    # ── 5. Trazabilidad ─────────────────────────────────────────────────
    _section_trazabilidad(lines, diag)

    # ── 6. Cobertura ─────────────────────────────────────────────────────
    _section_cobertura(lines, diag)

    # ── Escribir ─────────────────────────────────────────────────────────
    content = "\n".join(lines)
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_text(content, encoding="utf-8")
    logger.info(f"[report] Diagnóstico guardado en: {ruta}")
    return ruta


# ── Secciones del reporte ────────────────────────────────────────────────────

def _section_scoring(lines: list[str], diag: DiagnosticData):
    lines.append("## 1. Scoring de Páginas")
    lines.append("")
    lines.append("Páginas con score > 0 en al menos una categoría.")
    lines.append("Las marcadas con ✅ fueron seleccionadas (`dominant_type` asignado).")
    lines.append("")
    lines.append(
        "| Pág | Conf | Dominant | rtm_postor | rtm_personal "
        "| factores | blacklist | Seleccionada |"
    )
    lines.append(
        "|-----|------|----------|------------|-------------|"
        "----------|-----------|-------------|"
    )

    total_scored = 0
    total_selected = 0
    for p in diag.all_scores:
        has_score = any(v > 0 for v in p.scores.values())
        if not has_score:
            continue
        total_scored += 1
        dominant = p.dominant_type or "—"
        selected = "✅" if p.dominant_type else "—"
        if p.dominant_type:
            total_selected += 1
        s = p.scores
        lines.append(
            f"| {p.page_num} | {p.confidence:.3f} | {dominant} | "
            f"{s.get('rtm_postor', 0):.1f} | {s.get('rtm_personal', 0):.1f} | "
            f"{s.get('factores_evaluacion', 0):.1f} | {s.get('blacklist', 0):.1f} | "
            f"{selected} |"
        )

    lines.append("")
    lines.append(
        f"> **Resumen:** {len(diag.all_scores)} páginas totales → "
        f"{total_scored} con señales → {total_selected} seleccionadas"
    )
    lines.append("")


def _section_bloques(lines: list[str], diag: DiagnosticData):
    lines.append("## 2. Bloques Formados (enviados al LLM)")
    lines.append("")
    lines.append(
        "Cada bloque incluye las páginas relevantes + "
        "contexto (±1 página). El texto completo de estas páginas "
        "es lo que recibe el LLM."
    )
    lines.append("")

    for i, block in enumerate(diag.blocks, 1):
        page_nums = [p.page_num for p in block.pages]
        lines.append(
            f"### Bloque {i}: `{block.block_type}` — Páginas {block.page_range}"
        )
        lines.append("")
        lines.append(f"- **Páginas incluidas:** {page_nums}")
        lines.append(f"- **Total chars del texto:** {len(block.text):,}")
        lines.append("")

        # Preview del texto de CADA página del bloque
        lines.append("<details>")
        lines.append("<summary>📄 Texto por página (primeras líneas)</summary>")
        lines.append("")
        for page in block.pages:
            preview_lines = page.text.split("\n")[:15]
            preview = "\n".join(preview_lines)
            lines.append(
                f"**Página {page.page_num}** (conf={page.confidence:.3f}, "
                f"{len(page.text):,} chars):"
            )
            lines.append("```")
            lines.append(preview)
            if len(page.text.split("\n")) > 15:
                remaining = len(page.text.split("\n")) - 15
                lines.append(f"... [{remaining} líneas más]")
            lines.append("```")
            lines.append("")
        lines.append("</details>")
        lines.append("")


def _section_tablas(lines: list[str], diag: DiagnosticData):
    lines.append("## 3. Pipeline de Tablas (Enhancer)")
    lines.append("")

    if diag.tablas_paginas_heuristicas:
        lines.append(
            f"- **Heurística detectó tablas en:** {diag.tablas_paginas_heuristicas}"
        )
    else:
        lines.append("- **Heurística:** No detectó tablas en páginas relevantes")

    if diag.tablas_docling_confirmadas:
        lines.append(
            f"- **Docling confirmó tablas en:** {diag.tablas_docling_confirmadas}"
        )
    else:
        lines.append("- **Docling:** No confirmó tablas (o no disponible)")

    lines.append("")

    if diag.tablas_detalles:
        lines.append("### Resultados por grupo de tablas")
        lines.append("")
        for det in diag.tablas_detalles:
            pags = det.get("paginas", "?")
            ok = det.get("validado", False)
            razon = det.get("razon", "")
            preview = det.get("preview", "")
            status = "✅ validado" if ok else f"❌ rechazado ({razon})"
            lines.append(f"- **Págs {pags}:** {status}")
            if preview:
                lines.append("  ```")
                lines.append(f"  {preview}")
                lines.append("  ```")
        lines.append("")
    else:
        lines.append(
            "No se procesaron tablas con QwenVL "
            "(ninguna pasó heurística+Docling, o Docling no disponible)."
        )
        lines.append("")


def _section_llm(lines: list[str], diag: DiagnosticData):
    lines.append("## 4. Interacciones con el LLM (por bloque)")
    lines.append("")

    if not diag.llm_interactions:
        lines.append("No se registraron interacciones con el LLM.")
        lines.append("")
        return

    for i, ix in enumerate(diag.llm_interactions, 1):
        status = "✅" if ix.parsed_ok else "❌"
        lines.append(
            f"### {status} Bloque {i}: `{ix.block_type}` — "
            f"págs {ix.page_range}"
        )
        lines.append("")
        lines.append(f"- **Páginas incluidas:** {ix.pages_included}")
        lines.append(f"- **Prompt enviado:** {ix.prompt_chars:,} chars")

        if ix.parsed_ok:
            lines.append(f"- **Items extraídos:** {ix.items_extracted}")
            lines.append(f"- **Claves del JSON:** {ix.parsed_keys}")
        else:
            lines.append(f"- **Error:** `{ix.error}`")

        lines.append("")

        # Texto que se envió al LLM (preview por página)
        lines.append("<details>")
        lines.append(
            "<summary>📤 Texto enviado al LLM "
            f"({ix.prompt_chars:,} chars)</summary>"
        )
        lines.append("")
        lines.append("```")
        lines.append(ix.text_preview)
        if len(ix.text_preview) >= 2000:
            lines.append("... [truncado]")
        lines.append("```")
        lines.append("</details>")
        lines.append("")

        # Respuesta cruda del LLM
        lines.append("<details>")
        lines.append("<summary>📥 Respuesta cruda del LLM</summary>")
        lines.append("")
        lines.append("```json")
        resp_preview = ix.raw_response[:4000]
        lines.append(resp_preview)
        if len(ix.raw_response) > 4000:
            lines.append(
                f"... [{len(ix.raw_response) - 4000:,} chars truncados]"
            )
        lines.append("```")
        lines.append("</details>")
        lines.append("")

        # Si la respuesta fue limpiada (diferente a la cruda), mostrar
        if ix.cleaned_response != ix.raw_response and ix.cleaned_response:
            lines.append("<details>")
            lines.append("<summary>🧹 Respuesta limpiada (lo que se parsea)</summary>")
            lines.append("")
            lines.append("```json")
            clean_preview = ix.cleaned_response[:3000]
            lines.append(clean_preview)
            if len(ix.cleaned_response) > 3000:
                lines.append("... [truncado]")
            lines.append("```")
            lines.append("</details>")
            lines.append("")


def _section_trazabilidad(lines: list[str], diag: DiagnosticData):
    lines.append("## 5. Trazabilidad del Resultado")
    lines.append("")
    lines.append(
        "De dónde viene cada registro del output. "
        "Los campos marcados con ⚠️ están vacíos (null)."
    )
    lines.append("")

    resultado = diag.resultado

    # ── RTM Postor ───────────────────────────────────────────────────────
    postor = resultado.get("rtm_postor", [])
    lines.append(f"### rtm_postor ({len(postor)} registros)")
    lines.append("")
    for j, item in enumerate(postor, 1):
        tipo = item.get("tipo_experiencia_valida") or "∅ null"
        pag = item.get("pagina") or "?"
        seccion = item.get("seccion") or "?"
        archivo = item.get("archivo") or ""
        lines.append(f"**{j}. {tipo}**")
        lines.append(f"- Página: {pag} | Sección: {seccion}")

        null_fields = [
            k for k, v in item.items()
            if v is None and not k.startswith("_")
        ]
        filled_fields = [
            k for k, v in item.items()
            if v is not None and not k.startswith("_") and k != "archivo"
        ]
        lines.append(f"- ✅ Campos llenos: {', '.join(filled_fields)}")
        if null_fields:
            lines.append(f"- ⚠️ Campos vacíos: {', '.join(null_fields)}")
        lines.append("")

    # ── RTM Personal ─────────────────────────────────────────────────────
    personal = resultado.get("rtm_personal", [])
    lines.append(f"### rtm_personal ({len(personal)} registros)")
    lines.append("")
    for j, item in enumerate(personal, 1):
        cargo = item.get("cargo") or "∅ null"
        profs = item.get("profesiones_aceptadas") or []
        exp = item.get("experiencia_minima") or {}
        cant = exp.get("cantidad", "?")
        unidad = exp.get("unidad", "meses")
        pag = item.get("pagina") or "?"
        cargos_sim = exp.get("cargos_similares_validos") or []

        lines.append(f"**{j}. {cargo}**")
        lines.append(f"- Profesiones: {', '.join(profs) if profs else '∅'}")
        lines.append(f"- Experiencia: {cant} {unidad} | Página: {pag}")
        if cargos_sim:
            lines.append(f"- Cargos similares: {', '.join(cargos_sim)}")

        # Campos vacíos del nivel raíz
        null_root = [
            k for k, v in item.items()
            if v is None and not k.startswith("_")
        ]
        if null_root:
            lines.append(f"- ⚠️ Campos vacíos (raíz): {', '.join(null_root)}")

        # Campos vacíos dentro de experiencia_minima
        if exp:
            null_exp = [k for k, v in exp.items() if v is None]
            if null_exp:
                lines.append(
                    f"- ⚠️ Campos vacíos (experiencia): {', '.join(null_exp)}"
                )

        # Campos vacíos dentro de capacitacion
        cap = item.get("capacitacion") or {}
        if cap:
            null_cap = [k for k, v in cap.items() if v is None]
            if null_cap:
                lines.append(
                    f"- ⚠️ Campos vacíos (capacitación): {', '.join(null_cap)}"
                )
        lines.append("")

    # ── Factores ─────────────────────────────────────────────────────────
    factores = resultado.get("factores_evaluacion", [])
    lines.append(f"### factores_evaluacion ({len(factores)} registros)")
    lines.append("")
    for j, item in enumerate(factores, 1):
        factor = item.get("factor") or "∅ null"
        aplica = item.get("aplica_a") or "?"
        pmax = item.get("puntaje_maximo")
        pag = item.get("pagina") or "?"
        pmax_str = f"{pmax} pts" if pmax else "sin puntaje"
        lines.append(f"{j}. **{factor}** — aplica_a: {aplica} — {pmax_str} — pág {pag}")
    lines.append("")


def _section_cobertura(lines: list[str], diag: DiagnosticData):
    lines.append("## 6. Cobertura de Páginas Clave")
    lines.append("")
    lines.append(
        "¿Se procesaron las páginas donde normalmente está la info importante?"
    )
    lines.append("")

    pages_in_blocks = set()
    for block in diag.blocks:
        for p in block.pages:
            pages_in_blocks.add(p.page_num)

    # Rangos clave según el tipo de documento OSCE
    rangos_clave = [
        ("Sección General + Específica (RTM, Factores)", range(1, 43)),
        ("TDR / Especificaciones Técnicas", range(43, 131)),
        ("RTM + Factores (sección técnica principal)", range(131, 150)),
        ("Anexos y Formularios", range(150, 192)),
    ]

    for nombre, rango in rangos_clave:
        total = len(rango)
        cubiertas = sorted(p for p in rango if p in pages_in_blocks)
        no_cubiertas = sorted(p for p in rango if p not in pages_in_blocks)
        pct = len(cubiertas) / total * 100 if total else 0

        icon = "🟢" if pct > 50 else "🟡" if pct > 20 else "🔴"
        lines.append(
            f"### {icon} {nombre} (págs {rango.start}–{rango.stop - 1})"
        )
        lines.append(
            f"- Cobertura: **{len(cubiertas)}/{total}** ({pct:.0f}%)"
        )
        if cubiertas:
            lines.append(f"- ✅ Procesadas: {cubiertas}")
        if no_cubiertas and len(no_cubiertas) <= 30:
            lines.append(f"- ❌ NO procesadas: {no_cubiertas}")
        elif no_cubiertas:
            lines.append(
                f"- ❌ NO procesadas: {len(no_cubiertas)} páginas "
                f"(primeras: {no_cubiertas[:10]}...)"
            )
        lines.append("")
