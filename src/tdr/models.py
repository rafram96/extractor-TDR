"""
Modelos de datos para TDR (Términos de Referencia).

Define estructuras para profesionales y experiencias extraídas de bases.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional


class Severidad(str, Enum):
    """Nivel de severidad de requisito."""
    OBLIGATORIO = "obligatorio"
    RECOMENDADO = "recomendado"
    CRITICO = "critico"


@dataclass
class TDRCargo:
    """Requisitos para un cargo específico en el concurso."""

    cargo: str
    """Nombre del cargo (ej: "Supervisor de Obra", "Coordinador Técnico")"""

    profesion_requerida: str
    """Profesión requerida (ej: "Ingeniero Civil", "Arquitecto")"""

    anos_minimos_colegiado: int
    """Años mínimos como colegiado"""

    anos_minimos_experiencia: int
    """Años mínimos de experiencia en obras similares"""

    tipos_obra_validos: list[str] = field(default_factory=list)
    """Tipos de obra válidos (ej: ["salud", "vivienda"])"""

    cargos_similares_validos: list[str] = field(default_factory=list)
    """Cargos equivalentes aceptados (ej: ["Jefe de Supervisión", "Jefe de Obra"])"""

    intervenciones_requeridas: list[str] = field(default_factory=list)
    """Intervenciones requeridas (ej: ["supervisión", "coordinación"])"""

    complejidad: str = "media"
    """Nivel de complejidad: alta | media | baja"""

    requisito_minimo_detallado: str = ""
    """Texto exacto del requisito mínimo del documento"""

    puntuacion_experiencia: str = ""
    """Texto sobre puntuación por experiencia adicional (puntaje + máximo)"""

    puntuacion_por_experiencia: dict = field(default_factory=dict)
    """Puntuación por tipo de experiencia {tipo: puntos} (legacy)"""

    capacitacion_solicitada: str = ""
    """Capacitación/formación requerida (ej: "Curso de seguridad")"""

    tiempo_adicional_evaluacion: str = ""
    """Tiempo adicional requerido en los factores de evaluación"""

    pagina_documento: int = 0
    """Página del documento donde aparece el requisito"""

    otros_factores_evaluacion: str = ""
    """Otros factores de evaluación del postor"""

    severidad: Severidad = Severidad.OBLIGATORIO
    """Severidad del requisito"""


@dataclass
class TDRExperience:
    """Requisitos de experiencia solicitados en el concurso."""

    tipo_experiencia: str
    """Tipo de experiencia válida (ej: "Supervisión de obras de salud")"""

    sector_valido: str
    """Sector válido de la experiencia (ej: "Salud", "Vivienda")"""

    descripcion_exacta: str
    """Descripción exacta del documento"""

    experiencia_adicional: str = ""
    """Experiencia adicional que se debe entregar"""

    otros_factores: str = ""
    """Otros factores de evaluación"""

    pagina_documento: int = 0
    """Página donde aparece el requisito"""

    severidad: Severidad = Severidad.OBLIGATORIO
    """Severidad del requisito"""


@dataclass
class TDRExtraction:
    """Resultado completo de extracción TDR."""

    cargos: list[TDRCargo] = field(default_factory=list)
    """Lista de cargos requeridos"""

    experiencias: list[TDRExperience] = field(default_factory=list)
    """Lista de experiencias solicitadas"""

    pdf_name: str = ""
    """Nombre del PDF procesado"""

    total_paginas: int = 0
    """Total de páginas del PDF"""

    fecha_extraccion: datetime = field(default_factory=datetime.now)
    """Timestamp de la extracción"""

    modelo_llm: str = "qwen2.5:14b"
    """Modelo LLM usado para extracción"""

    tiempo_procesamiento: float = 0.0
    """Tiempo total de procesamiento en segundos"""

    notas_extraccion: str = ""
    """Notas sobre la extracción (warnings, issues)"""

    def __post_init__(self):
        """Validación post-inicialización."""
        if not self.cargos and not self.experiencias:
            self.notas_extraccion = "ADVERTENCIA: Extracción vacía (sin cargos ni experiencias)"


@dataclass
class ValidationError:
    """Error en validación de extracción."""

    campo: str
    """Campo que falló"""

    valor: str
    """Valor problemático"""

    razon: str
    """Razón del error"""

    severidad: str = "warning"
    """Severidad: warning | error"""
