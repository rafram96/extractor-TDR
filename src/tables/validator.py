"""
Validador de tablas markdown generadas por Qwen VL.

Usa un confidence score en vez de binario para decidir
si reemplazar el texto PaddleOCR.
"""

from __future__ import annotations
import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class ResultadoValidacion:
    valido: bool
    score: float          # 0.0–1.0
    num_filas: int
    num_columnas: int
    razon: str            # descripción si falla


def validar_tabla_markdown(md: str, min_score: float = 0.5) -> ResultadoValidacion:
    """
    Valida una tabla markdown y calcula un confidence score.

    Criterios:
    - Mínimo 3 filas con |
    - Mínimo 3 columnas (| count >= 4 por fila)
    - Columnas consistentes (max - min <= 1)
    - Presencia de header separator (---)
    - Longitud promedio de celdas razonable

    Args:
        md: Markdown de la tabla
        min_score: Score mínimo para considerar válido

    Returns:
        ResultadoValidacion con score y metadata
    """
    if not md or "|" not in md:
        return ResultadoValidacion(
            valido=False, score=0.0,
            num_filas=0, num_columnas=0,
            razon="No contiene tabla markdown"
        )

    lineas = [l.strip() for l in md.strip().split("\n") if "|" in l]

    # ── Mínimo 3 filas ──────────────────────────────────────────────────
    if len(lineas) < 3:
        return ResultadoValidacion(
            valido=False, score=0.1,
            num_filas=len(lineas), num_columnas=0,
            razon=f"Solo {len(lineas)} filas (mínimo 3)"
        )

    # ── Contar columnas por fila ─────────────────────────────────────────
    col_counts = [l.count("|") for l in lineas]

    # ── Mínimo 3 columnas (4 pipes = 3 columnas: |c1|c2|c3|) ───────────
    max_cols = max(col_counts)
    if max_cols < 4:
        return ResultadoValidacion(
            valido=False, score=0.15,
            num_filas=len(lineas), num_columnas=max_cols - 1,
            razon=f"Solo {max_cols - 1} columnas (mínimo 3)"
        )

    # ── Consistencia de columnas ─────────────────────────────────────────
    # Excluir líneas separator (---) del conteo de varianza
    data_counts = [c for l, c in zip(lineas, col_counts) if "---" not in l]
    if data_counts:
        varianza = max(data_counts) - min(data_counts)
    else:
        varianza = max(col_counts) - min(col_counts)

    # ── Rechazos duros ───────────────────────────────────────────────────
    # Tablas grandes (≥8 filas) toleran más varianza: fusión de celdas en OCR
    # es frecuente pero no invalida las demás filas.
    max_varianza = 5 if len(data_counts) >= 8 else 3
    if varianza > max_varianza:
        return ResultadoValidacion(
            valido=False, score=0.1,
            num_filas=len(lineas), num_columnas=max_cols - 1,
            razon=f"Columnas inconsistentes (varianza={varianza}, max tolerable={max_varianza})"
        )

    # Densidad mínima: menos de 4 chars por fila → respuesta vacía/garbage
    chars_por_fila = len(md) / len(lineas) if lineas else 0
    if chars_por_fila < 4:
        return ResultadoValidacion(
            valido=False, score=0.05,
            num_filas=len(lineas), num_columnas=max_cols - 1,
            razon=f"Respuesta demasiado corta ({len(md)} chars / {len(lineas)} filas = {chars_por_fila:.1f} chars/fila)"
        )

    # ── Score compuesto ──────────────────────────────────────────────────
    score = 0.0

    # Consistencia de columnas (peso: 0.35)
    if varianza == 0:
        score += 0.35
    elif varianza == 1:
        score += 0.20
    else:
        score += 0.0  # columnas muy inconsistentes

    # Número de filas de datos (peso: 0.25)
    filas_datos = len([l for l in lineas if "---" not in l])
    if filas_datos >= 10:
        score += 0.25
    elif filas_datos >= 5:
        score += 0.20
    elif filas_datos >= 3:
        score += 0.15
    else:
        score += 0.05

    # Presencia de header separator (peso: 0.15)
    tiene_separator = any("---" in l for l in lineas)
    if tiene_separator:
        score += 0.15

    # Longitud promedio de celdas razonable (peso: 0.15)
    # Celdas muy cortas (<3 chars) o muy largas (>200) son sospechosas
    celdas = []
    for l in lineas:
        if "---" in l:
            continue
        partes = [p.strip() for p in l.split("|") if p.strip()]
        celdas.extend(partes)
    if celdas:
        avg_len = sum(len(c) for c in celdas) / len(celdas)
        if 3 <= avg_len <= 200:
            score += 0.15
        elif avg_len > 200:
            score += 0.05  # celdas muy largas → posible alucinación

    # Número de columnas (peso: 0.10)
    num_cols = max_cols - 1
    if num_cols >= 3:
        score += 0.10

    score = round(min(score, 1.0), 2)
    valido = score >= min_score

    num_filas_final = filas_datos
    resultado = ResultadoValidacion(
        valido=valido,
        score=score,
        num_filas=num_filas_final,
        num_columnas=num_cols,
        razon="OK" if valido else f"Score {score:.2f} < {min_score}",
    )

    logger.info(
        f"[validator] score={score:.2f} filas={num_filas_final} "
        f"cols={num_cols} varianza={varianza} "
        f"{'✅' if valido else '❌'} {resultado.razon}"
    )
    return resultado
