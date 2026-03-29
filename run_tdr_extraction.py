#!/usr/bin/env python3
"""
CLI para extracción de criterios TDR de bases de concurso.

Uso:
    python run_tdr_extraction.py \\
        --pdf "ruta/del/pdf" \\
        --output "ruta/del/output.xlsx"
"""

import argparse
import logging
import sys
from datetime import datetime
from pathlib import Path

# Setup logging a consola y archivo
log_file = Path("extractor_tdr.log")

# Handlers: consola + archivo
console_handler = logging.StreamHandler(sys.stdout)
console_handler.setLevel(logging.INFO)
console_formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
console_handler.setFormatter(console_formatter)

file_handler = logging.FileHandler(log_file, encoding="utf-8")
file_handler.setLevel(logging.DEBUG)  # Archivo captura todo
file_formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
file_handler.setFormatter(file_formatter)

# Configurar root logger
root_logger = logging.getLogger()
root_logger.setLevel(logging.DEBUG)
root_logger.addHandler(console_handler)
root_logger.addHandler(file_handler)

logger = logging.getLogger(__name__)

# Silenciar logs verbosos de librerías externas
logging.getLogger("pdfminer").setLevel(logging.WARNING)
logging.getLogger("pdfplumber").setLevel(logging.WARNING)
logging.getLogger("PIL").setLevel(logging.WARNING)
logging.getLogger("openai").setLevel(logging.WARNING)
logging.getLogger("httpx").setLevel(logging.WARNING)

logger.info(f"Logs guardados en: {log_file.absolute()}")

# Agregar src al path
sys.path.insert(0, str(Path(__file__).parent))

from src.tdr.excel_writer import TDRExcelWriter
from src.tdr.markdown_processor import process_motor_ocr_output
from src.tdr.motor_ocr_client import check_motor_ocr_available
from src.tdr.pdf_reader import read_pdf
from src.tdr.tdr_extractor import TDRExtractor


def main():
    """Función principal."""
    parser = argparse.ArgumentParser(
        description="Extrae criterios TDR de bases de concurso escaneadas",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Ejemplos:
  # Procesamiento completo PDF -> Excel
  python run_tdr_extraction.py \\
    --pdf "C:\\Users\\Holbi\\Downloads\\BASES.pdf" \\
    --output "data/BASES_TDR.xlsx"

  # Solo extrae y consolida texto (sin LLM)
  python run_tdr_extraction.py --pdf "bases.pdf" --text-only

  # Solo parsea markdown (si ya existe)
  python run_tdr_extraction.py --pdf "bases.pdf" --parse-only
        """,
    )

    parser.add_argument(
        "--pdf",
        required=True,
        help="Ruta absoluta del PDF bases (digital o escaneado)",
    )

    parser.add_argument(
        "--output",
        default="data/BASES_TDR_CRITERIOS.xlsx",
        help="Ruta del Excel output (default: data/BASES_TDR_CRITERIOS.xlsx)",
    )

    parser.add_argument(
        "--text-only",
        action="store_true",
        help="Solo extrae texto, no genera Excel",
    )

    parser.add_argument(
        "--parse-only",
        action="store_true",
        help="Solo parsea markdown, no llama a LLM",
    )

    parser.add_argument(
        "--ocr-output",
        default=r"D:\proyectos\infoobras\ocr_output",
        help="Directorio para outputs motor-OCR (default: D:\\proyectos\\infoobras\\ocr_output)",
    )

    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Output detallado (debug logging)",
    )

    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    logger.info("=" * 70)
    logger.info("TDR EXTRACTOR - Extracción de Criterios de Bases de Concurso")
    logger.info("=" * 70)

    try:
        # Validar entrada
        pdf_path = Path(args.pdf)
        if not pdf_path.exists():
            logger.error(f"❌ PDF no existe: {pdf_path}")
            return 1

        logger.info(f"PDF: {pdf_path.name} ({pdf_path.stat().st_size / 1024 / 1024:.1f} MB)")

        # Verificar motor-OCR disponible
        if not check_motor_ocr_available():
            logger.warning(
                "[motor-OCR] Wrapper no encontrado. "
                "Si el PDF es escaneado, fallará. "
                "Verificar: motor-OCR/subprocess_wrapper.py"
            )

        # PASO 1: Leer PDF
        logger.info("[PASO 1/4] Leyendo PDF...")
        texto = read_pdf(str(pdf_path), args.ocr_output)

        if args.text_only:
            # Solo texto, terminar aquí
            texto_path = Path(args.output).parent / f"{pdf_path.stem}_texto.txt"
            texto_path.write_text(texto, encoding="utf-8")
            logger.info(f"✓ Texto guardado en {texto_path}")
            return 0

        # PASO 2: Procesar Markdown (si motor-OCR fue invocado)
        logger.info("[PASO 2/4] Procesando Markdown...")
        try:
            sections = process_motor_ocr_output(args.ocr_output)
            texto = sections.get("full_text", texto)
        except Exception as e:
            logger.warning(f"No se pudo procesar Markdown: {e}. Usando texto directo.")

        if args.parse_only:
            logger.info("✓ --parse-only activado, terminando aquí")
            return 0

        # PASO 3: Extraer con LLM
        logger.info("[PASO 3/4] Extrayendo criterios con LLM...")
        extractor = TDRExtractor()
        extraction = extractor.extract(
            texto,
            pdf_name=pdf_path.name,
            total_paginas=0,  # TODO: obtener de pdfplumber
        )

        logger.info(f"✓ Extracción completada:")
        logger.info(f"  - {len(extraction.cargos)} cargos")
        logger.info(f"  - {len(extraction.experiencias)} experiencias")

        # PASO 4: Generar Excel
        logger.info("[PASO 4/4] Generando Excel...")
        output_path = Path(args.output)
        TDRExcelWriter.write(extraction, output_path)

        logger.info("=" * 70)
        logger.info(f"✓ ÉXITO: Excel generado en {output_path}")
        logger.info("=" * 70)

        return 0

    except KeyboardInterrupt:
        logger.error("\n❌ Cancelado por usuario")
        return 130

    except Exception as e:
        logger.error(f"❌ Error: {e}")
        if args.verbose:
            import traceback
            traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
