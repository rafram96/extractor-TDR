import argparse
import json
import logging
import sys
from pathlib import Path

# --- Logging: consola (INFO) + archivo (DEBUG) ---
_log_fmt = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
_log_file = Path("extractor_tdr.log")

_console = logging.StreamHandler(sys.stdout)
_console.setLevel(logging.INFO)
_console.setFormatter(logging.Formatter(_log_fmt))

_file = logging.FileHandler(_log_file, encoding="utf-8")
_file.setLevel(logging.DEBUG)
_file.setFormatter(logging.Formatter(_log_fmt))

logging.getLogger().setLevel(logging.DEBUG)
logging.getLogger().addHandler(_console)
logging.getLogger().addHandler(_file)

# Silenciar librerías externas
for _lib in ("pdfminer", "pdfplumber", "PIL", "openai", "httpx"):
    logging.getLogger(_lib).setLevel(logging.WARNING)

logger = logging.getLogger(__name__)
logger.info(f"Logs guardados en: {_log_file.absolute()}")

from src.clients.motor_ocr_client import invoke_motor_ocr, check_motor_ocr_available
from src.extractor.parser import parse_full_text
from src.extractor.scorer import score_page, group_into_blocks
from src.extractor.pipeline import extraer_bases
from src.config.settings import OUTPUT_DIR


def _leer_texto_existente(pdf_path: str) -> str | None:
    """
    Busca el _texto_*.md ya generado por motor-OCR para este PDF.
    Retorna su contenido si existe, None si no.
    """
    pdf_stem = Path(pdf_path).stem
    texto_dir = OUTPUT_DIR / pdf_stem
    if not texto_dir.exists():
        return None
    archivos = sorted(texto_dir.glob("*_texto_*.md"))
    if not archivos:
        return None
    texto_md = archivos[-1]
    logger.info(f"[reuse-ocr] Usando texto existente: {texto_md}")
    return texto_md.read_text(encoding="utf-8")


def cmd_extraer(args):
    OUTPUT_DIR.mkdir(exist_ok=True)
    pdf_path = str(Path(args.pdf).absolute())
    logger.info(f"Procesando: {pdf_path}")

    # --reuse-ocr: salta el OCR si el _texto_*.md ya existe
    if getattr(args, "reuse_ocr", False):
        full_text = _leer_texto_existente(pdf_path)
        if full_text is None:
            logger.error(
                f"--reuse-ocr activo pero no se encontró _texto_*.md para "
                f"'{Path(pdf_path).stem}' en {OUTPUT_DIR}. "
                "Corre sin --reuse-ocr para generar el OCR primero."
            )
            sys.exit(1)
    else:
        if not check_motor_ocr_available():
            logger.error("motor-OCR no disponible. Verificar rutas en config/settings.py")
            sys.exit(1)
        full_text = invoke_motor_ocr(pdf_path, output_dir=str(OUTPUT_DIR))

    if args.dry_run:
        # Muestra qué bloques detectaría sin llamar a Qwen
        pages  = parse_full_text(full_text)
        scored = [score_page(p) for p in pages]
        blocks = group_into_blocks(scored)

        print(f"\n{'─'*50}")
        print(f"DRY RUN — {len(pages)} páginas → {len(blocks)} bloques detectados")
        print(f"{'─'*50}")
        for b in blocks:
            avg_conf = sum(p.confidence for p in b.pages) / len(b.pages)
            print(f"  [{b.block_type}]  págs {b.page_range}  conf_avg={avg_conf:.3f}")
            # Mostrar scores de las páginas centrales del bloque
            for p in b.pages:
                dominant = p.dominant_type or "—"
                scores_str = "  ".join(f"{k}={v}" for k, v in sorted(p.scores.items()))
                print(f"    pág {p.page_num:>4}  dominant={dominant:<22} {scores_str}")
        print(f"{'─'*50}\n")
        return

    resultado = extraer_bases(
        full_text,
        nombre_archivo=Path(args.pdf).name,
        pdf_path=pdf_path,
    )

    out_path = OUTPUT_DIR / (Path(args.pdf).stem + "_bases.json")
    out_path.write_text(
        json.dumps(resultado, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    logger.info(f"Resultado guardado en: {out_path}")


def main():
    parser = argparse.ArgumentParser(
        description="Extractor de bases TDR — concursos públicos OSCE"
    )
    sub = parser.add_subparsers(dest="comando")

    p_extraer = sub.add_parser("extraer", help="Extrae RTM y factores de un PDF de bases")
    p_extraer.add_argument("pdf", help="Ruta al PDF de bases")
    p_extraer.add_argument(
        "--dry-run", action="store_true",
        help="Solo muestra los bloques detectados sin llamar a Qwen"
    )
    p_extraer.add_argument(
        "--reuse-ocr", action="store_true",
        help="Usa el _texto_*.md ya existente, salta el OCR (requiere haber corrido antes)"
    )
    p_extraer.add_argument(
        "--verbose", action="store_true",
        help="Activa debug logging en consola"
    )

    args = parser.parse_args()
    if args.comando == "extraer":
        if getattr(args, "verbose", False):
            _console.setLevel(logging.DEBUG)
        cmd_extraer(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()