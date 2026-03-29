"""
Orquestador de extracción TDR.

Coordina:
1. Lectura y consolidación de texto
2. Llamadas a LLM para extraer criterios
3. Validación de resultados
4. Retorno de modelos estructurados
"""

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

from .markdown_processor import clean_markdown_text
from .models import TDRCargo, TDRExperience, TDRExtraction
from .ollama_client import call_llm, check_ollama_available
from .prompts import format_prompt_cargos, format_prompt_experiencias

logger = logging.getLogger(__name__)


class TDRExtractor:
    """Extractor de criterios TDR de bases de concurso."""

    def __init__(self):
        """Inicializa el extractor."""
        self.modelo_llm = "qwen2.5:14b"

    def extract(
        self,
        texto: str,
        pdf_name: str = "bases.pdf",
        total_paginas: int = 0,
        max_retries: int = 3,
    ) -> TDRExtraction:
        """
        Extrae criterios TDR del texto de bases.

        Args:
            texto: Texto consolidado de las bases
            pdf_name: Nombre del PDF procesado
            total_paginas: Total de páginas del PDF
            max_retries: Máximo número de reintentos por paso

        Returns:
            TDRExtraction con cargos y experiencias

        Raises:
            RuntimeError: Si no puede extraer datos válidos
        """
        inicio = datetime.now()

        logger.info("[TDR Extractor] Iniciando extracción...")

        # Validar Ollama disponible
        if not check_ollama_available():
            raise RuntimeError(
                "Ollama no disponible. Verificar: http://localhost:11434"
            )

        # Limpiar texto
        texto_limpio = clean_markdown_text(texto)
        logger.info(f"[TDR Extractor] Texto consolidado: {len(texto_limpio)} caracteres")

        # Extraer cargos
        logger.info("[TDR Extractor] Paso 1: Extrayendo CARGOS...")
        cargos = self._extract_cargos(texto_limpio, max_retries)
        logger.info(f"[TDR Extractor] ✓ {len(cargos)} cargos extraídos")

        # Extraer experiencias
        logger.info("[TDR Extractor] Paso 2: Extrayendo EXPERIENCIAS...")
        experiencias = self._extract_experiencias(texto_limpio, max_retries)
        logger.info(f"[TDR Extractor] ✓ {len(experiencias)} experiencias extraídas")

        # Validar resultados
        self._validate_extraction(cargos, experiencias)

        # Crear resultado
        tiempo_total = (datetime.now() - inicio).total_seconds()

        resultado = TDRExtraction(
            cargos=cargos,
            experiencias=experiencias,
            pdf_name=pdf_name,
            total_paginas=total_paginas,
            fecha_extraccion=datetime.now(),
            modelo_llm=self.modelo_llm,
            tiempo_procesamiento=tiempo_total,
        )

        logger.info(f"[TDR Extractor] ✓ Extracción completada en {tiempo_total:.1f}s")

        return resultado

    def _extract_cargos(self, texto: str, max_retries: int) -> list[TDRCargo]:
        """Extrae cargos del texto."""
        prompt = format_prompt_cargos(texto)

        for intento in range(1, max_retries + 1):
            try:
                logger.debug(f"[TDR Extractor] Extrayendo cargos (intento {intento}/{max_retries})...")

                response = call_llm(prompt, max_retries=2)

                # Log respuesta cruda para debug
                logger.debug(f"[TDR Extractor] Respuesta LLM cruda: {json.dumps(response, indent=2, ensure_ascii=False)}")

                # Parse response
                cargos_data = response.get("cargos", [])

                if not cargos_data:
                    logger.warning(f"[TDR Extractor] LLM retornó lista vacía de cargos. Response: {response}")
                    if intento < max_retries:
                        logger.info("[TDR Extractor] Reintentando...")
                        continue
                    raise RuntimeError("No se pudieron extraer cargos")

                # Convertir a modelos
                cargos = []
                for cargo_dict in cargos_data:
                    try:
                        cargo = TDRCargo(
                            cargo=cargo_dict.get("cargo", ""),
                            profesion_requerida=cargo_dict.get("profesion_requerida", ""),
                            anos_minimos_colegiado=int(
                                cargo_dict.get("anos_minimos_colegiado", 0) or 0
                            ),
                            anos_minimos_experiencia=int(
                                cargo_dict.get("anos_minimos_experiencia", 0) or 0
                            ),
                            tipos_obra_validos=cargo_dict.get("tipos_obra_validos", []),
                            cargos_similares_validos=cargo_dict.get(
                                "cargos_similares_validos", []
                            ),
                            requisito_minimo_detallado=cargo_dict.get(
                                "requisito_minimo_detallado", ""
                            ),
                            puntuacion_experiencia=cargo_dict.get(
                                "puntuacion_experiencia", ""
                            ),
                            capacitacion_solicitada=cargo_dict.get(
                                "capacitacion_solicitada", ""
                            ),
                            tiempo_adicional_evaluacion=cargo_dict.get(
                                "tiempo_adicional_evaluacion", ""
                            ),
                            otros_factores_evaluacion=cargo_dict.get(
                                "otros_factores_evaluacion", ""
                            ),
                        )
                        cargos.append(cargo)
                    except Exception as e:
                        logger.warning(f"[TDR Extractor] Error parsing cargo: {e}")
                        continue

                if cargos:
                    return cargos

            except Exception as e:
                logger.warning(f"[TDR Extractor] Error en intento {intento}: {e}")
                if intento < max_retries:
                    continue
                raise

        raise RuntimeError("No se pudieron extraer cargos válidos")

    def _extract_experiencias(self, texto: str, max_retries: int) -> list[TDRExperience]:
        """Extrae experiencias del texto."""
        prompt = format_prompt_experiencias(texto)

        for intento in range(1, max_retries + 1):
            try:
                logger.debug(
                    f"[TDR Extractor] Extrayendo experiencias (intento {intento}/{max_retries})..."
                )

                response = call_llm(prompt, max_retries=2)

                # Parse response
                exp_data = response.get("experiencias", [])

                if not exp_data:
                    logger.warning("[TDR Extractor] LLM retornó lista vacía de experiencias")
                    if intento < max_retries:
                        logger.info("[TDR Extractor] Reintentando...")
                        continue
                    raise RuntimeError("No se pudieron extraer experiencias")

                # Convertir a modelos
                experiencias = []
                for exp_dict in exp_data:
                    try:
                        exp = TDRExperience(
                            tipo_experiencia=exp_dict.get("tipo_experiencia", ""),
                            sector_valido=exp_dict.get("sector_valido", ""),
                            descripcion_exacta=exp_dict.get("descripcion_exacta", ""),
                            experiencia_adicional=exp_dict.get("experiencia_adicional", ""),
                            otros_factores=exp_dict.get("otros_factores", ""),
                            pagina_documento=int(exp_dict.get("pagina_documento", 0)),
                        )
                        experiencias.append(exp)
                    except Exception as e:
                        logger.warning(f"[TDR Extractor] Error parsing experiencia: {e}")
                        continue

                if experiencias:
                    return experiencias

            except Exception as e:
                logger.warning(f"[TDR Extractor] Error en intento {intento}: {e}")
                if intento < max_retries:
                    continue
                raise

        raise RuntimeError("No se pudieron extraer experiencias válidas")

    def _validate_extraction(
        self,
        cargos: list[TDRCargo],
        experiencias: list[TDRExperience],
    ) -> None:
        """
        Valida que la extracción sea razonablemente completa.

        Levanta RuntimeError si hay issues críticos.
        """
        errors = []

        # Validación básica
        if not cargos:
            errors.append("No se encontraron cargos")

        if not experiencias:
            errors.append("No se encontraron experiencias")

        # Validación de campos obligatorios
        for i, cargo in enumerate(cargos):
            if not cargo.cargo:
                errors.append(f"Cargo {i}: nombre vacío")
            if not cargo.profesion_requerida:
                errors.append(f"Cargo {i}: profesión vacía")

        for i, exp in enumerate(experiencias):
            if not exp.tipo_experiencia:
                errors.append(f"Experiencia {i}: tipo vacío")

        # Warnings (no son errores críticos)
        if len(cargos) < 2:
            logger.warning("[TDR Extractor] ⚠ Solo se encontró 1 cargo (esperado ≥2)")

        if len(experiencias) < 2:
            logger.warning("[TDR Extractor] ⚠ Solo se encontró 1 experiencia (esperado ≥2)")

        if errors:
            logger.error(f"[TDR Extractor] Validación fallida:\n" + "\n".join(errors))
            raise RuntimeError(f"Validación fallida: {'; '.join(errors)}")

        logger.info("[TDR Extractor] ✓ Validación pasada")
