from pathlib import Path

# ── Motor OCR ─────────────────────────────────────────────────────────────────
MOTOR_OCR_REPO    = Path(r"D:\proyectos\motor-OCR")
MOTOR_OCR_TIMEOUT = 7200  # segundos

# ── Qwen / Ollama ─────────────────────────────────────────────────────────────
QWEN_OLLAMA_BASE_URL = "http://localhost:11434/v1"
QWEN_OLLAMA_API_KEY  = "ollama"
QWEN_MODEL           = "qwen2.5:14b"
QWEN_MAX_TOKENS      = 4096
QWEN_TIMEOUT         = 300

# ── Scorer ────────────────────────────────────────────────────────────────────
SCORER_MIN_SCORE  = 2.0   # score mínimo para considerar una página relevante
SCORER_MAX_GAP    = 3     # páginas de gap toleradas dentro de un bloque
SCORER_CONTEXT    = 1     # páginas de contexto antes/después de cada bloque

# ── Paths de salida ───────────────────────────────────────────────────────────
OUTPUT_DIR = Path("output")