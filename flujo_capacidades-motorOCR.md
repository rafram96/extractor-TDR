# Motor OCR — Flujo de Procesamiento y Capacidades

## Flujo completo

```
PDF
 ↓
 ├── [1] PDF → Imágenes (300 DPI, PNG)
 ↓
 ├── [2] Pasada 1: PaddleOCR (subproceso aislado)
 │       → Todas las páginas procesadas
 │       → Resultado serializado en pickle
 │       → Subprocess termina → VRAM liberada
 ↓
 ├── [3] Decisión de fallback por página
 │       → conf_promedio < 0.85 AND tasa_descarte > 0.35 → Qwen
 │       → Páginas separadoras (≤15 líneas) excluidas del fallback
 ↓
 ├── [4] Pasada 2: Qwen-VL (solo páginas que fallaron)
 │       → Reintentos con imagen más pequeña (2048 → 1024 → 768px)
 │       → Resultado reemplaza al de Paddle
 ↓
 ├── [5] DocumentResult (métricas + texto por página)
 │       → Genera: {nombre}_metricas_{ts}.md
 │       → Genera: {nombre}_texto_{ts}.md
 ↓
 ├── [6] Segmentación
 │   ├── Pre-filtro: es_candidata_separadora()
 │   │   → Lista blanca: debe contener patrón de cargo
 │   │   → Lista negra: excluir frases de descarte
 │   │   → Rango de líneas: 1-15 líneas limpias
 │   │
 │   ├── Evaluación: evaluar_separadora()
 │   │   → Qwen-VL confirma con imagen (reducida 50%)
 │   │   → Si Qwen falla → fuzzy matching (rapidfuzz, score ≥ 80)
 │   │
 │   ├── Agrupación: páginas entre separadoras consecutivas
 │   │
 │   └── Recorte: delimitadores de bloque como tijeras
 │       → Candidatas descartadas + es_delimitador_bloque()
 │       → Corta secciones infladas del último profesional
 ↓
 ├── [7] Consolidación
 │       → Tipo A: 1 bloque por profesional (pass-through)
 │       → Tipo B: N bloques por profesional → fusionar
 │       → Genera: {nombre}_segmentacion_{ts}.md
 │       → Genera: {nombre}_profesionales_{ts}.md
 ↓
 Resultado: (DocumentResult, List[ProfessionalSection])
```

---

## Capacidades existentes (reutilizables)

### OCR
| Capacidad | Estado | Detalles |
|-----------|--------|----------|
| PaddleOCR con español | ✅ | Corrección de rotación, perspective, orientación |
| Qwen-VL como fallback | ✅ | Reintentos con downsampling automático |
| Decisión inteligente de fallback | ✅ | Doble criterio: confianza + tasa descarte |
| Subproceso aislado (VRAM) | ✅ | Paddle y Qwen nunca comparten VRAM |
| Métricas por página | ✅ | Confianza, descarte, ángulo, líneas bajas |
| Procesamiento de rango de páginas | ✅ | `pages=list(range(10, 50))` |

### Segmentación
| Capacidad | Estado | Detalles |
|-----------|--------|----------|
| Detección de separadoras | ✅ | Pre-filtro + Qwen visual + fuzzy fallback |
| Lista blanca de cargos | ✅ | 7 patrones genéricos |
| Lista negra de descarte | ✅ | 8 frases que nunca son separadoras |
| Normalización de errores OCR | ✅ | 96 correcciones conocidas |
| Fuzzy matching de cargos | ✅ | 51 cargos base, score ≥ 80 |
| Recorte por delimitadores | ✅ | 8 patrones de bloque temático |
| Consolidación Tipo A/B | ✅ | Fusión de bloques del mismo profesional |
| Extracción de N° de cargo | ✅ | "Especialista N°2" → numero="2" |

### Reportes
| Capacidad | Estado | Detalles |
|-----------|--------|----------|
| Reporte de métricas OCR | ✅ | Calidad por página, errores, fallbacks |
| Reporte de texto extraído | ✅ | Texto completo con tags de motor |
| Reporte de segmentación | ✅ | Candidatas, separadoras, descartadas |
| Reporte de profesionales | ✅ | Lista consolidada con rangos |

### Modelos de datos
| Modelo | Uso | Campos clave |
|--------|-----|-------------|
| `PageResult` | Resultado OCR de 1 página | text, lines, conf_promedio, engine_used, line_scores |
| `DocumentResult` | Documento completo | pages, pages_paddle, pages_qwen, conf_promedio_documento |
| `ProfessionalSection` | Sección de profesional | cargo, numero, pages, bloques_origen, full_text |
| `SeparatorPage` | Evaluación de separadora | es_separadora, cargo_detectado, metodo, confianza_qwen |

---

## Capacidades a crear / pendientes

| Capacidad | Prioridad | Notas |
|-----------|-----------|-------|
| Fuzzy primero en segmentación (score ≥ 92) | Media | Ahorro ~25-30 min en docs grandes. Riesgo bajo. |
| Detección de repetición Qwen | Baja | Descartar respuestas alucinadas (200+ líneas iguales) |
| Detección de tablas (`tiene_tabla`) | Baja | Placeholder actual siempre False |
| API REST / endpoint | Depende | Si se necesita integrar con otros sistemas |
| Procesamiento batch de múltiples PDFs | Depende | Loop sobre directorio con reportes agregados |
| Cache de resultados OCR | Baja | Evitar re-procesar páginas ya procesadas |

---

## Configuración actual

### Umbrales OCR
```
UMBRAL_CONFIANZA_PROMEDIO = 0.85  (fallback a Qwen si conf < esto)
UMBRAL_TASA_DESCARTE      = 0.35  (fallback a Qwen si descarte > esto)
UMBRAL_CONFIANZA_LINEA     = 0.85  (marcar línea como baja confianza)
```

### Segmentación
```
MAX_LINEAS_SEPARADORA  = 15   (candidata a separadora)
MIN_LINEAS_SEPARADORA  = 1
MAX_LINEAS_DELIMITADOR = 30   (delimitador de bloque)
FUZZY_SCORE_MINIMO     = 80   (aceptar match fuzzy)
```

### Motor
```
QWEN_MODEL            = "qwen2.5vl:7b"
PDF_DPI               = 300
MAX_WORKERS            = 4
```

---

## API de uso

```python
# Solo OCR
from main import process_document
doc = process_document("documento.pdf")

# OCR + Segmentación
from main import process_and_segment
doc, secciones = process_and_segment("documento.pdf")

# Rango específico
doc, secciones = process_and_segment(
    "documento.pdf",
    pages=list(range(10, 50)),
    keep_images=True,
)

# Acceso a datos
for sec in secciones:
    print(f"{sec.cargo} — {sec.total_pages} págs")
    print(sec.full_text[:200])

for page in doc.pages:
    print(f"Pág {page.page_number}: {page.engine_used} conf={page.conf_promedio}")
```
