# Plan: Pipeline híbrido de detección y lectura de tablas

## Problema
PaddleOCR lineariza tablas multi-columna mezclando las columnas. El texto resultante es ilegible para Qwen 14B (experiencia del personal sale toda null). Necesitamos detectar páginas con tablas y leerlas visualmente.

## Flujo propuesto

```
motor-OCR (PaddleOCR) → _texto_*.md completo (ya existe, no se toca)
    ↓
Scorer → ~30 páginas relevantes (ya existe)
    ↓
[NUEVO] Detector heurístico → pre-filtra páginas con probable tabla
    ↓
[NUEVO] Docling (solo esas páginas) → confirma tabla + bbox
    ↓
[NUEVO] Agrupa páginas consecutivas con tabla (cross-page)
    ↓
[NUEVO] Extrae imagen del PDF → crop por bbox
    ↓
[NUEVO] Qwen VL (qwen2.5vl:7b) → lee imagen → markdown con |col1|col2|
    ↓
[NUEVO] Validador → verifica columnas consistentes
    ├─ ✅ → reemplaza texto de esa página en _texto_*.md
    └─ ❌ → mantiene texto PaddleOCR original
    ↓
Pipeline extracción (Qwen 14B) → JSON final (ya existe)
```

## Archivos nuevos a crear

```
src/
  tables/
    __init__.py
    detector.py        ← heurística OSCE para detectar tablas en texto OCR
    docling_client.py  ← confirma tabla + extrae bbox
    vision.py          ← cliente Qwen VL vía Ollama (lectura visual)
    validator.py       ← valida markdown de tabla (columnas consistentes)
    image_utils.py     ← extrae imagen de página del PDF (PyMuPDF), crop por bbox
    enhancer.py        ← orquesta: detectar → confirmar → leer → reemplazar
```

## Archivos existentes a modificar

- `src/config/settings.py` → agregar config de Qwen VL y Docling
- `src/extractor/pipeline.py` → llamar al enhancer ANTES de la extracción
- `requirements.txt` → agregar PyMuPDF y docling

## Detalle por componente

### 1. detector.py — Heurística OSCE

Detecta tablas en texto PaddleOCR usando patrones del dominio OSCE.
NO es genérico — es específico para bases de concurso.

```python
def detectar_tablas_en_pagina(texto: str) -> float:
    """Score 0-1 de probabilidad de tabla en esta página."""
```

Señales (cada una suma al score):
- **Fragmentación**: ratio de líneas cortas (< 30 chars) > 0.5
- **Repetición estructural**: misma frase 3+ veces (filas de tabla)
- **Patrón "N meses en el cargo"**: indica tabla B.2 experiencia
- **Patrón "Bachiller en" / "Ingeniero" / "Arquitecto"**: 3+ veces
- **Ítems secuenciales**: números sueltos (1, 2, 3...) como tokens aislados
- **Patrones OSCE**: "Cant.", "Ítem", "Puesto, Cargo", "Formación académica"

Threshold: score > 0.6 → probable tabla.

### 2. docling_client.py — Confirmación + bbox

```python
def confirmar_tablas(pdf_path: str, paginas: list[int]) -> list[TablaDetectada]:
    """
    Corre Docling solo en las páginas indicadas.
    Retorna lista de TablaDetectada(pagina, bbox, num_columnas).
    Si Docling no detecta tabla → la página se descarta.
    """
```

Docling solo se usa como confirmador binario + bbox. No se usa su texto.

### 3. image_utils.py — Extracción de imagen

```python
def extraer_imagen_pagina(pdf_path: str, pagina: int, dpi: int = 200) -> Image:
    """Extrae imagen de una página del PDF usando PyMuPDF."""

def crop_tabla(imagen: Image, bbox: tuple) -> Image:
    """Recorta solo la región de la tabla usando el bbox de Docling."""
```

Usa PyMuPDF (fitz) — rápido, sin GPU, sin dependencias pesadas.

### 4. vision.py — Lectura visual con Qwen VL

```python
def leer_tabla_visual(imagen: Image) -> str | None:
    """
    Envía imagen recortada a qwen2.5vl:7b vía Ollama.
    Retorna markdown con |col1|col2|... o None si falla.
    """
```

Prompt estricto:
```
Extract the table EXACTLY as seen in the image.
Rules:
- Preserve exact number of columns and rows
- Do NOT merge or split columns
- Do NOT infer missing values — write [UNCLEAR] if unreadable
- Ignore watermarks, stamps, and background noise
- Output ONLY a markdown table using | format
- No explanations before or after
```

Usa Ollama API directamente (no OpenAI compat) para poder enviar imágenes.

### 5. validator.py — Validación de markdown

```python
def validar_tabla_markdown(md: str) -> bool:
    """
    Verifica que el markdown de tabla sea válido:
    - Tiene al menos 2 filas de datos
    - Columnas consistentes (mismo count de | por fila, tolerancia ±1)
    """
```

Si falla → se mantiene el texto PaddleOCR original para esa página.

### 6. enhancer.py — Orquestador

```python
def mejorar_texto_con_tablas(
    full_text: str,
    pdf_path: str,
    paginas_relevantes: list[int],
) -> str:
    """
    Pipeline completo de mejora de tablas:
    1. Detecta páginas con probable tabla (heurística)
    2. Confirma con Docling (bbox)
    3. Agrupa páginas consecutivas (cross-page)
    4. Extrae + cropea imágenes
    5. Lee con Qwen VL
    6. Valida markdown
    7. Reemplaza en full_text
    Retorna full_text mejorado.
    """
```

Cross-page: si páginas 140, 141, 142 todas tienen tabla confirmada por Docling,
se envían como grupo a Qwen VL (múltiples imágenes en un solo prompt).

### 7. Cambios en pipeline.py

```python
def extraer_bases(full_text: str, nombre_archivo: str = "", pdf_path: str = "") -> dict:
    # NUEVO: mejorar texto con tablas antes de extracción
    if pdf_path:
        pages = parse_full_text(full_text)
        scored = [score_page(p) for p in pages]
        paginas_relevantes = [p.page_num for p in scored if p.dominant_type]
        full_text = mejorar_texto_con_tablas(full_text, pdf_path, paginas_relevantes)

    # ... resto del pipeline igual
```

### 8. Cambios en settings.py

```python
# Qwen VL (visión)
QWEN_VL_MODEL    = "qwen2.5vl:7b"
QWEN_VL_TIMEOUT  = 120

# Tablas
TABLE_DETECT_THRESHOLD = 0.6   # score mínimo para heurística
TABLE_DOCLING_DPI      = 200   # resolución para extracción de imágenes
```

### 9. Cambios en requirements.txt

```
PyMuPDF>=1.24.0             # Extracción de imágenes de PDF
docling>=2.0.0              # Detección de tablas (confirmación + bbox)
Pillow>=10.0.0              # Manipulación de imágenes (crop)
```

## Dependencias y secuencia de ejecución

```
motor-OCR termina (GPU libre)
    ↓
Docling corre (puede usar GPU o CPU) — NO compite con PaddleOCR
    ↓
Qwen VL corre en Ollama — mismo servidor, ya cargado
    ↓
Qwen 14B corre en Ollama — extracción final
```

No hay conflicto de GPU porque todo es secuencial.

## Qué NO cambia

- motor-OCR (caja negra, no se toca)
- scorer.py (detección de bloques)
- signals.py (señales y prompts)
- parser.py (parseo del markdown)
- llm.py (cliente Qwen 14B)

## Riesgos y mitigaciones

| Riesgo | Mitigación |
|--------|------------|
| Docling no disponible en servidor | Fallback: skip tablas, usar texto PaddleOCR |
| Qwen VL alucina estructura | Validador rechaza → fallback a PaddleOCR |
| Tabla cruza 3+ páginas | Agrupar todas las consecutivas, enviar como grupo |
| Docling pesado en RAM/GPU | Solo corre en ~10 páginas pre-filtradas, no en 192 |
| PyMuPDF no abre el PDF | Try/except → skip mejora, log warning |
