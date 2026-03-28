"""
Módulo TDR: Extracción de criterios técnicos de bases de concurso.

Paso 1 del pipeline Alpamayo-InfoObras:
- Lee PDF de bases (digital o escaneado)
- Extrae requisitos de profesionales y experiencias
- Genera Excel intermedio con criterios RTM
"""

from .motor_ocr_client import invoke_motor_ocr, check_motor_ocr_available
from .pdf_reader import read_pdf

__all__ = [
    "read_pdf",
    "invoke_motor_ocr",
    "check_motor_ocr_available",
]
