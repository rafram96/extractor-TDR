"""
Motor-OCR subprocess client para procesamiento de PDFs escaneados.

Usa mode="ocr_only" — solo extrae texto, sin segmentación por profesionales.
Más rápido (~50 min vs ~100 min para documentos grandes).
"""

import json
import logging
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Rutas
# En servidor: D:\proyectos\motor-OCR
# En laptop: C:\Users\Holbi\Documents\Freelance\proyectos\motor-OCR
MOTOR_OCR_REPO = Path(r"D:\proyectos\motor-OCR")
MOTOR_OCR_WRAPPER = MOTOR_OCR_REPO / "subprocess_wrapper.py"
MOTOR_OCR_PYTHON = MOTOR_OCR_REPO / "venv" / "Scripts" / "python.exe"


def invoke_motor_ocr(
    pdf_path: str,
    output_dir: str,
    pages: Optional[list] = None,
    timeout: int = 7200,
) -> str:
    """
    Invoca motor-OCR como subprocess en mode="ocr_only".

    Solo extrae texto (sin segmentación por profesionales).
    Retorna DocumentResult.full_text.

    Args:
        pdf_path: Ruta absoluta del PDF a procesar
        output_dir: Directorio donde guardar archivos .md
        pages: Lista de números de página (1-based). None = todas.
        timeout: Timeout en segundos (default 7200 = 2 horas)

    Returns:
        Texto extraído consolidado

    Raises:
        RuntimeError: Si motor-OCR falla o timeout
    """
    pdf_name = Path(pdf_path).name
    logger.info(f"[motor-OCR] Iniciando OCR (mode=ocr_only) de {pdf_name}")

    pdf_path = str(Path(pdf_path).absolute())
    output_dir = str(Path(output_dir).absolute())

    Path(output_dir).mkdir(parents=True, exist_ok=True)

    # mode="ocr_only" → solo process_document(), sin segmentación
    args = {
        "mode": "ocr_only",
        "pdf_path": pdf_path,
        "output_dir": output_dir,
        "pages": pages,
        "keep_images": False,
    }

    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump(args, f)
        args_file = f.name

    results_file = tempfile.mktemp(suffix=".json")

    # Log file para capturar output del subprocess
    log_file = Path("motor_ocr.log")

    try:
        python_exe = str(MOTOR_OCR_PYTHON) if MOTOR_OCR_PYTHON.exists() else sys.executable
        logger.info(f"[motor-OCR] Ejecutando wrapper: {MOTOR_OCR_WRAPPER}")
        logger.info(f"[motor-OCR] Python: {python_exe}")
        logger.info(f"[motor-OCR] Logs en: {log_file.absolute()}")

        with open(log_file, "w") as logf:
            result = subprocess.run(
                [python_exe, str(MOTOR_OCR_WRAPPER), args_file, results_file],
                stdout=logf,
                stderr=subprocess.STDOUT,
                text=True,
                timeout=timeout,
                check=False,
            )

        # Lee los últimos logs
        with open(log_file, "r") as logf:
            last_lines = logf.readlines()[-20:]

        if result.returncode != 0:
            error_msg = "".join(last_lines) or "Error desconocido"
            logger.error(f"[motor-OCR] Fallo con código {result.returncode}")
            logger.error(f"[motor-OCR] Últimos logs:\n{error_msg}")
            raise RuntimeError(f"motor-OCR falló: {error_msg}")


        # mode="ocr_only" retorna JSON con DocumentResult
        with open(results_file, "r", encoding="utf-8") as f:
            result_data = json.load(f)

        total_pages = result_data["total_pages"]
        pages_paddle = result_data["pages_paddle"]
        pages_qwen = result_data["pages_qwen"]
        pages_error = result_data["pages_error"]
        conf_promedio = result_data["conf_promedio_documento"]
        tiempo_total = result_data["tiempo_total"]

        logger.info(
            f"[motor-OCR] {total_pages} páginas procesadas "
            f"(Paddle: {pages_paddle}, "
            f"Qwen: {pages_qwen}, "
            f"Error: {pages_error})"
        )
        logger.info(f"[motor-OCR] Confianza promedio: {conf_promedio:.3f}")
        logger.info(f"[motor-OCR] Tiempo: {tiempo_total:.1f}s")

        # El _texto_*.md tiene el formato markdown que espera el parser.
        # result_data["full_text"] es texto plano — no sirve para el parser.
        pdf_stem = Path(pdf_path).stem
        texto_dir = Path(output_dir) / pdf_stem
        texto_files = sorted(texto_dir.glob("*_texto_*.md"))

        if not texto_files:
            raise RuntimeError(
                f"No se encontró _texto_*.md en {texto_dir}. "
                "Verificar que motor-OCR generó el archivo."
            )

        texto_md = texto_files[-1]  # el más reciente si hubiera varios
        full_text = texto_md.read_text(encoding="utf-8")
        logger.info(f"[motor-OCR] Leyendo texto desde: {texto_md.name}")

        if len(full_text.strip()) < 500:
            raise RuntimeError(
                f"motor-OCR extrajo muy poco texto ({len(full_text)} chars). "
                "Verificar calidad del PDF."
            )

        logger.info(f"[motor-OCR] Texto extraído: {len(full_text)} caracteres")
        return full_text

    except subprocess.TimeoutExpired:
        logger.error(f"[motor-OCR] Timeout después de {timeout}s")
        raise RuntimeError(f"motor-OCR timeout después de {timeout} segundos")
    except RuntimeError:
        raise
    except Exception as e:
        logger.error(f"[motor-OCR] Error inesperado: {e}")
        raise
    finally:
        Path(args_file).unlink(missing_ok=True)
        Path(results_file).unlink(missing_ok=True)


def check_motor_ocr_available() -> bool:
    """Verifica si motor-OCR está disponible (repo + wrapper + venv)."""
    available = MOTOR_OCR_WRAPPER.exists() and MOTOR_OCR_REPO.exists()
    if available and not MOTOR_OCR_PYTHON.exists():
        logger.warning(
            f"[motor-OCR] venv no encontrado en {MOTOR_OCR_PYTHON}. "
            "Se usará sys.executable como fallback."
        )
    return available
