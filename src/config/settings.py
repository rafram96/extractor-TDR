from pathlib import Path

# ── Motor OCR ─────────────────────────────────────────────────────────────────
MOTOR_OCR_REPO    = Path(r"D:\proyectos\motor-OCR")
MOTOR_OCR_TIMEOUT = 7200  # segundos

# ── Ollama ───────────────────────────────────────────────────────────────────
OLLAMA_BASE_URL      = "http://localhost:11434"

# ── Qwen 14B (extracción semántica) ─────────────────────────────────────────
QWEN_OLLAMA_BASE_URL = f"{OLLAMA_BASE_URL}/v1"
QWEN_OLLAMA_API_KEY  = "ollama"
QWEN_MODEL           = "qwen2.5:14b"
QWEN_MAX_TOKENS      = 4096
QWEN_TIMEOUT         = 300

# ── Qwen VL (lectura visual de tablas) ──────────────────────────────────────
QWEN_VL_MODEL   = "qwen2.5vl:7b"
QWEN_VL_TIMEOUT = 120   # segundos por imagen

# ── Scorer ────────────────────────────────────────────────────────────────────
SCORER_MIN_SCORE  = 2.0   # score mínimo para considerar una página relevante
SCORER_MAX_GAP    = 3     # páginas de gap toleradas dentro de un bloque
SCORER_CONTEXT    = 1     # páginas de contexto antes/después de cada bloque

# ── Tablas (pipeline híbrido) ────────────────────────────────────────────────
TABLE_DETECT_THRESHOLD   = 0.4   # score mínimo heurística para pre-filtro
TABLE_DOCLING_DPI        = 200   # resolución para extracción de imágenes
TABLE_VALIDATOR_MIN_SCORE = 0.5  # score mínimo para aceptar tabla de Qwen VL

# ── Paths de salida ───────────────────────────────────────────────────────────
OUTPUT_DIR = Path("output")