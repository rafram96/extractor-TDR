"""
Detector heurístico de tablas en texto OCR de bases OSCE.

Analiza el texto de PaddleOCR de una página y estima la probabilidad
de que contenga una tabla. Específico para documentos de concursos
públicos peruanos (OSCE).
"""

from __future__ import annotations
import re
import logging

logger = logging.getLogger(__name__)


def detectar_tabla(texto: str) -> float:
    """
    Score 0.0–1.0 de probabilidad de tabla en una página.

    Señales OSCE que indican tabla:
    - Fragmentación: muchas líneas cortas (celdas OCR linearizadas)
    - Repetición estructural: misma frase N veces (filas de tabla)
    - Patrones temporales: "N meses en el cargo"
    - Patrones profesionales: "Ingeniero", "Bachiller", "Arquitecto" 3+ veces
    - Ítems secuenciales: números sueltos
    - Headers de tabla OSCE: "Ítem", "Cant.", "Cargo", "Formación"
    """
    if not texto or len(texto.strip()) < 100:
        return 0.0

    lineas = texto.strip().splitlines()
    lineas_no_vacias = [l for l in lineas if l.strip()]
    if not lineas_no_vacias:
        return 0.0

    score = 0.0
    señales = {}

    # ── 1. Fragmentación: ratio de líneas cortas (<30 chars) ─────────────
    cortas = sum(1 for l in lineas_no_vacias if len(l.strip()) < 30)
    ratio_cortas = cortas / len(lineas_no_vacias)
    if ratio_cortas > 0.5:
        score += 0.15
        señales["fragmentacion"] = f"{ratio_cortas:.2f}"

    # ── 2. Líneas cortas + muchas líneas (señal visual indirecta) ────────
    avg_len = sum(len(l.strip()) for l in lineas_no_vacias) / len(lineas_no_vacias)
    if avg_len < 40 and len(lineas_no_vacias) > 20:
        score += 0.15
        señales["lineas_cortas_densas"] = f"avg={avg_len:.0f}, n={len(lineas_no_vacias)}"

    # ── 3. Repetición estructural ────────────────────────────────────────
    frases = [l.strip().lower() for l in lineas_no_vacias if len(l.strip()) > 15]
    repetidas = len(frases) - len(set(frases))
    if repetidas >= 3:
        score += 0.15
        señales["repeticion"] = repetidas

    # ── 4. Patrón "N meses en" (tabla B.2 experiencia) ──────────────────
    patron_meses = len(re.findall(r"\d+\s*meses\s+en", texto, re.IGNORECASE))
    if patron_meses >= 2:
        score += 0.20
        señales["patron_meses"] = patron_meses

    # ── 5. Patrón profesional: "Ingeniero", "Bachiller", "Arquitecto" ───
    texto_lower = texto.lower()
    profesiones = (
        texto_lower.count("ingeniero")
        + texto_lower.count("bachiller")
        + texto_lower.count("arquitecto")
    )
    if profesiones >= 3:
        score += 0.10
        señales["profesiones"] = profesiones

    # ── 6. Ítems secuenciales (números sueltos como tokens aislados) ────
    nums_sueltos = re.findall(r"(?:^|\n)\s*(\d{1,2})\s*(?:\n|$)", texto)
    if len(nums_sueltos) >= 3:
        # Verificar que son secuenciales
        nums = [int(n) for n in nums_sueltos]
        secuencial = sum(
            1 for i in range(1, len(nums)) if nums[i] == nums[i - 1] + 1
        )
        if secuencial >= 2:
            score += 0.10
            señales["items_secuenciales"] = nums

    # ── 7. Headers de tabla OSCE ─────────────────────────────────────────
    headers_osce = [
        r"\bítem\b", r"\bcant\b", r"\bcargo\b", r"\bformaci[oó]n\b",
        r"\bexperiencia\b", r"\bpuesto\b", r"\bdenominaci[oó]n\b",
        r"\bt[ií]tulo profesional\b", r"\bgrado\b",
    ]
    headers_encontrados = sum(
        1 for h in headers_osce if re.search(h, texto_lower)
    )
    if headers_encontrados >= 3:
        score += 0.15
        señales["headers_osce"] = headers_encontrados

    score = min(score, 1.0)
    if score >= 0.3:
        logger.debug(
            f"[detector] score={score:.2f} señales={señales}"
        )

    return round(score, 2)


# Threshold configurable desde settings.py
DEFAULT_THRESHOLD = 0.4
