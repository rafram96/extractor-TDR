import argparse
import json
import logging
import sys
from pathlib import Path

from clients.motor_ocr_client import invoke_motor_ocr, check_motor_ocr_available
from extractor.parser import parse_full_text
from extractor.scorer import score_page, group_into_blocks
from extractor.pipeline import extraer_bases
from config.settings import OUTPUT_DIR

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


def cmd_extraer(args):
    if not check_motor_ocr_available():
        logger.error("motor-OCR no disponible. Verificar rutas en config/settings.py")
        sys.exit(1)

    OUTPUT_DIR.mkdir(exist_ok=True)
    pdf_path = str(Path(args.pdf).absolute())

    logger.info(f"Procesando: {pdf_path}")
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

    resultado = extraer_bases(full_text)

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

    args = parser.parse_args()
    if args.comando == "extraer":
        cmd_extraer(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()