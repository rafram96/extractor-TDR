# Funcionamiento del Extractor de TDR

## Resumen Ejecutivo

El programa **Extractor de TDR (Términos de Referencia)** analiza PDFs de bases de concursos de obras públicas y extrae automáticamente los criterios técnicos requeridos para cada cargo, generando un Excel estructurado con los requisitos identificados.

### Problema que resuelve
El análisis manual de bases de concurso es tedioso y propenso a errores. Este sistema automatiza la extracción de:
- Cargos requeridos
- Profesiones y años mínimos de colegiatura
- Experiencias mínimas en obras similares
- Tipos de obra válidos
- Factores de evaluación y puntuación

---

## Diagrama de Flujo General

```
PDF Bases del Concurso
    ↓
┌─────────────────────────────────────────┐
│  LECTURA (pdf_reader.py)                │
├─────────────────────────────────────────┤
│ 1. Intenta pdfplumber (PDF digital)     │
│ 2. Si texto < umbral → motor-OCR        │
│    (PDF escaneado)                      │
│ 3. Retorna texto consolidado            │
└─────────────────────────────────────────┘
    ↓ Texto crudo
┌─────────────────────────────────────────┐
│  LIMPIEZA (markdown_processor.py)        │
├─────────────────────────────────────────┤
│ 1. Normaliza espacios y saltos          │
│ 2. Filtra secciones relevantes          │
│    (cargos, experiencias)               │
│ 3. Trunca si excede límite LLM          │
└─────────────────────────────────────────┘
    ↓ Texto limpio
┌─────────────────────────────────────────┐
│  EXTRACCIÓN LLM (tdr_extractor.py)      │
├─────────────────────────────────────────┤
│ Paso 1: Extrae CARGOS y requisitos      │
│         qwen2.5:14b → JSON structured   │
│                                         │
│ Paso 2: Extrae EXPERIENCIAS solicitadas │
│         qwen2.5:14b → JSON structured   │
└─────────────────────────────────────────┘
    ↓ Estructurado
┌─────────────────────────────────────────┐
│  VALIDACIÓN (models.py)                 │
├─────────────────────────────────────────┤
│ Valida esquemas y parsea a dataclasses  │
│ Maneja errores JSON fallback            │
└─────────────────────────────────────────┘
    ↓ Modelos validados
┌─────────────────────────────────────────┐
│  GENERACIÓN EXCEL (excel_writer.py)     │
├─────────────────────────────────────────┤
│ 3+ hojas con formato, colores, headers  │
└─────────────────────────────────────────┘
    ↓
Excel BASES_TDR_CRITERIOS.xlsx
```

---

## Componentes Principales

### 1. **pdf_reader.py** — Lectura con Fallback Inteligente

**Responsabilidad:** Extraer texto del PDF sin importar su formato.

**Flujo:**
```python
read_pdf(pdf_path) → str
    ├─ Intenta pdfplumber (sin OCR)
    │      ↓ Extrae texto digital
    │      ↓ Valida cantidad (>200 chars/página)
    │      ↓ SI → Retorna texto ✓
    │
    └─ SI INSUFICIENTE → motor-OCR subprocess
           ↓ Invoca D:\proyectos\motor-OCR
           ↓ Lee *_texto_*.md generado
           ↓ Retorna texto consolidado
```

**Funciones principales:**
- `read_pdf()`: Orquesta lectura
- `_read_with_pdfplumber()`: Extrae con pdfplumber
- `_is_sufficient_text()`: Valida cantidad de texto
- `_read_motor_ocr_output()`: Lee *_texto_*.md del motor-OCR

**Fallback a motor-OCR:**
- Se activa si promedio de caracteres < 200 por página (indica PDF escaneado)
- **No modifica** código de motor-OCR, solo lo **invoca como subprocess**
- Output esperado: `D:\proyectos\infoobras\ocr_output\{pdf_name}\*_texto_*.md`

---

### 2. **markdown_processor.py** — Limpieza y Relevancia

**Responsabilidad:** Normalizar texto y filtrar secciones importantes.

**Funciones principales:**
- `process_motor_ocr_output()`: Lee archivos Markdown de motor-OCR
- `clean_markdown_text()`: Limpia espacios, saltos, caracteres especiales
- `extract_relevant_sections()`: Filtra por palabras clave (cargos, experiencia, requisitos)

**Ejemplo:**
```python
texto_limpio = extract_relevant_sections(
    texto_crudo, 
    mode="cargos"  # o "experiencias"
)
# Retorna solo párrafos con palabras clave: 
# "supervisor", "coordinador", "ingeniero", "años", "experiencia"
```

**Límites:**
- Si texto > ~4000 tokens, trunca para no exceder contexto del LLM
- Preserva orden del documento original

---

### 3. **ollama_client.py** — Cliente LLM

**Responsabilidad:** Llamar a modelo Local LLM (Ollama).

**Funciones principales:**
- `call_llm()`: HTTP POST a `http://localhost:11434/api/generate`
- `check_ollama_available()`: Validación de conectividad
- Modelo: `qwen2.5:14b` (temperatura 0, determinístico)

**Parámetros de llamada:**
```python
{
    "model": "qwen2.5:14b",
    "prompt": "(prompt con instrucción + contexto)",
    "stream": False,
    "temperature": 0,  # Determinístico
    "top_p": 0.95,
    "top_k": 40
}
```

**Manejo de errores:**
- Si Ollama no disponible → `RuntimeError`
- Si respuesta invalida → reintentos automáticos (max 3)

---

### 4. **tdr_extractor.py** — Orquestador Principal

**Responsabilidad:** Coordinar lectura → limpieza → LLM → validación.

**Flujo:**
```python
extractor = TDRExtractor()
resultado = extractor.extract(
    texto="...",
    pdf_name="BASES.pdf",
    max_retries=3
)
# Retorna: TDRExtraction(cargos=[], experiencias=[])
```

**Pasos internos:**

#### Paso 1: Extracción de Cargos
```python
_extract_cargos(texto_cargos, max_retries=3)
```

**Prompt:** `format_prompt_cargos()`  
**Extrae:**
- Nombre del cargo
- Profesión requerida
- Años mínimos colegiado
- Años mínimos experiencia
- Tipos de obra válidos
- Cargos equivalentes
- Complejidad, intervenciones, capacitación

**Output JSON esperado:**
```json
{
  "cargos": [
    {
      "cargo": "Supervisor de Obra",
      "profesion_requerida": "Ingeniero Civil",
      "anos_minimos_colegiado": 5,
      "anos_minimos_experiencia": 10,
      "tipos_obra_validos": ["salud", "educación"],
      "cargos_similares_validos": ["Jefe de Supervisión"],
      "intervenciones_requeridas": ["supervisión", "coordinación"],
      "complejidad": "alta",
      "pagina_documento": 3
    }
  ]
}
```

#### Paso 2: Extracción de Experiencias
```python
_extract_experiencias(texto_experiencias, max_retries=3)
```

**Prompt:** `format_prompt_experiencias()`  
**Extrae:**
- Tipo de experiencia válida
- Sector válido
- Descripción exacta del requisito
- Experiencia adicional solicitada

**Output JSON esperado:**
```json
{
  "experiencias": [
    {
      "tipo_experiencia": "Supervisión de obras de salud",
      "sector_valido": "Salud",
      "descripcion_exacta": "Mínimo 10 años supervisando...",
      "pagina_documento": 5
    }
  ]
}
```

**Manejo de fallos JSON:**
- Si LLM devuelve JSON inválido → extrae campo `""""` del response
- Si aún falla → retorna lista vacía y continúa
- Registra error en logs pero **no interrumpe** ejecución

---

### 5. **models.py** — Modelos de Datos

**Dataclasses** structurados con validación:

```python
@dataclass
class TDRCargo:
    cargo: str
    profesion_requerida: str
    anos_minimos_colegiado: int
    anos_minimos_experiencia: int
    tipos_obra_validos: list[str]
    cargos_similares_validos: list[str]
    intervenciones_requeridas: list[str]
    complejidad: str  # "alta" | "media" | "baja"
    requisito_minimo_detallado: str
    puntuacion_experiencia: str
    capacitacion_solicitada: str
    pagina_documento: int
    severidad: Severidad  # "obligatorio" | "recomendado" | "critico"

@dataclass
class TDRExperience:
    tipo_experiencia: str
    sector_valido: str
    descripcion_exacta: str
    pagina_documento: int
    severidad: Severidad

@dataclass
class TDRExtraction:
    pdf_name: str
    fecha_extraccion: datetime
    cargos: list[TDRCargo]
    experiencias: list[TDRExperience]
    mensaje_extraccion: str
```

---

### 6. **excel_writer.py** — Generación de Excel

**Responsabilidad:** Formatear y escribir resultados en `.xlsx`.

**Hojas generadas:**
1. **Resumen**: 
   - Nombre del PDF
   - Fecha extracción
   - Total cargos / experiencias
   - Advertencias

2. **Cargos**:
   - Tabla con columnas del `TDRCargo`
   - Colores por severidad
   - Headers con formato

3. **Experiencias**:
   - Tabla con columnas del `TDRExperience`
   - Colores consistentes
   - Paginación automática si > 1000 filas

4. **Verificación** (opcional):
   - Notas de extracción
   - Errores LLM reintentados
   - Secciones ambiguas del PDF

---

## Flujo Detallado Paso a Paso

### Ejemplo: Procesar `BASES_SALUD.pdf`

```bash
python run_tdr_extraction.py \
  --pdf "C:\Downloads\BASES_SALUD.pdf" \
  --output "data/BASES_SALUD_TDR.xlsx"
```

**Logs esperados:**

```
[INFO] Logs guardados en: C:\...\extractor_tdr.log
[INFO] [PDF Reader] Procesando BASES_SALUD.pdf
[INFO] [PDF Reader] Extrayendo con pdfplumber...
[INFO] [PDF Reader] ✓ Texto suficiente extraído con pdfplumber (123,456 chars)
[INFO] [TDR Extractor] Iniciando extracción...
[INFO] [TDR Extractor] Texto consolidado: 120,000 caracteres
[INFO] [TDR Extractor] Paso 1: Extrayendo CARGOS...
[INFO] [Ollama] Llamando qwen2.5:14b (modelo: qwen2.5:14b, max_tokens: 4000)
[INFO] [TDR Extractor] JSON Paso 1 parseado: {'cargos': [...]}
[INFO] [TDR Extractor] ✓ 5 cargos extraídos
[INFO] [TDR Extractor] Paso 2: Extrayendo EXPERIENCIAS...
[INFO] [Ollama] Llamando qwen2.5:14b (modelo: qwen2.5:14b, max_tokens: 4000)
[INFO] [TDR Extractor] JSON Paso 2 parseado: {'experiencias': [...]}
[INFO] [TDR Extractor] ✓ 8 experiencias extraídas
[INFO] [Excel Writer] Escribiendo Excel...
[INFO] [Excel Writer] Hoja 'Resumen' creada (1 fila de datos)
[INFO] [Excel Writer] Hoja 'Cargos' creada (5 filas)
[INFO] [Excel Writer] Hoja 'Experiencias' creada (8 filas)
[INFO] [Excel Writer] ✓ Excel guardado: data/BASES_SALUD_TDR.xlsx
[INFO] Tiempo total: 45.3 segundos
```

---

## Uso del Programa

### Opción 1: Procesamiento Completo (PDF → Excel)

```bash
python run_tdr_extraction.py \
  --pdf "C:\path\to\BASES.pdf" \
  --output "data/RESULTADO_TDR.xlsx"
```

**Flags:**
- `--pdf` (requerido): Ruta del PDF
- `--output` (default: `data/BASES_TDR_CRITERIOS.xlsx`): Ruta del Excel
- Sin flags adicionales = procesamiento completo

---

### Opción 2: Solo Extracción de Texto (sin LLM)

```bash
python run_tdr_extraction.py \
  --pdf "C:\path\to\BASES.pdf" \
  --text-only
```

**Genera:**
- `data/BASES_texto_crudo.txt`: Texto sin LLM

**Útil para:**
- Debugging visual del texto extraído
- Verificar calidad OCR antes de LLM
- Estimar costo computacional

---

### Opción 3: Solo Parsing (PDF ya procesado, Markdown cacheado)

```bash
python run_tdr_extraction.py \
  --pdf "C:\path\to\BASES.pdf" \
  --parse-only
```

**Asume:**
- Los archivos Markdown ya existen en `D:\proyectos\infoobras\ocr_output\BASES\`
- Solo ejecuta limpieza + LLM, salta lectura/OCR

**Usa:**
- Para reintentar LLM sin re-procesar PDF
- Más rápido (evita OCR/pdfplumber)

---

## Archivos de Entrada y Salida

| Tipo | Ubicación | Descripción |
|------|-----------|-------------|
| **Entrada** | `C:\path\to\BASES.pdf` | PDF digital o escaneado |
| **OCR temp** | `D:\proyectos\infoobras\ocr_output\{pdf_name}\` | Archivos Markdown de motor-OCR (si escaneado) |
| **Salida** | `data/BASES_TDR_CRITERIOS.xlsx` | Excel estructurado con criterios |
| **Logs** | `extractor_tdr.log` | Logs completosDebug: `[DEBUG]`, Producción: `[INFO]+` |

---

## Configuración y Constantes

### pdf_reader.py
```python
min_chars_per_page = 200  # Umbral para detectar PDF escaneado
output_dir = r"D:\proyectos\infoobras\ocr_output"  # Path motor-OCR
```

### tdr_extractor.py
```python
modelo_llm = "qwen2.5:14b"
max_retries = 3  # Reintentos por paso LLM
```

### ollama_client.py
```python
url_base = "http://localhost:11434"
temperatura = 0  # Determinístico
top_p = 0.95
top_k = 40
```

---

## Manejo de Errores y Fallbacks

| Error | Manejo | Fallback |
|-------|--------|----------|
| PDF no existe | Excepción `FileNotFoundError` | Parar ejecución |
| pdfplumber falla | Log warning, continúa | motor-OCR |
| Texto < umbral | Activa motor-OCR | Subprocess motor-OCR |
| motor-OCR no disponible | Excepción `RuntimeError` | Parar ejecución |
| Ollama no disponible | Excepción `RuntimeError` | Parar ejecución |
| JSON inválido del LLM | Reintento (max 3), fallback vacío | Continúa sin error |
| CSV/Excel write falla | Log error, pero genera lo que pudo | Archivo parcial |

---

## Stack Tecnológico

| Componente | Versión | Uso |
|-----------|---------|-----|
| Python | 3.12 | Runtime |
| FastAPI | - | (futuro, no usado aún) |
| pdfplumber | latest | Lectura PDF digital |
| requests | latest | Llamadas Ollama, scraping |
| openpyxl | latest | Generación Excel |
| Ollama | local | LLM qwen2.5:14b |
| qwen2.5:14b | 7B params | Extracción LLM |
| motor-OCR | separado | OCR para PDF escaneados |

---

## Diagrama de Clases

```
PDFReader
  ├─ read_pdf()
  ├─ _read_with_pdfplumber()
  └─ invoke_motor_ocr()

MarkdownProcessor
  ├─ process_motor_ocr_output()
  ├─ clean_markdown_text()
  └─ extract_relevant_sections()

OllamaClient
  ├─ call_llm()
  └─ check_ollama_available()

TDRExtractor
  ├─ extract()
  ├─ _extract_cargos()
  └─ _extract_experiencias()

Models
  ├─ TDRCargo (dataclass)
  ├─ TDRExperience (dataclass)
  └─ TDRExtraction (dataclass)

ExcelWriter
  ├─ write_extraction()
  ├─ _write_resumen_sheet()
  ├─ _write_cargos_sheet()
  └─ _write_experiencias_sheet()
```

---

## Restricciones y Limitaciones

1. **Modelado LLM es directo**: No hay corrección manual ni ajustes post-LLM.
2. **JSON parsing fallible**: Si LLM devuelve JSON malformado, puede perder datos.
3. **Contexto LLM acotado**: Si documento > ~4000 tokens, se trunca.
4. **No soporta tablas complejas**: Solo texto secuencial.
5. **Motor-OCR obligatorio**: No hay fallback alternativo si PDF es escaneado y motor-OCR no disponible.
6. **Umbral estático**: `min_chars_per_page=200` no se adapta a idioma o formato.

---

## Próximas Fases (No Implementadas)

- [ ] FastAPI web app con upload drag-and-drop
- [ ] Websockets para progreso en tiempo real
- [ ] Base de datos SQLite para cacheo de resultados
- [ ] Validación post-LLM humanizada
- [ ] Integración scraping InfoObras/SUNAT/CIP
- [ ] Motor de reglas (RTM) para evaluación de profesionales
- [ ] Exportación multi-formato (PDF, CSV, JSON)

---

## Troubleshooting

### Problema: "Ollama no disponible"
```
✓ Verificar Ollama corriendo: http://localhost:11434
✓ Modelo qwen2.5:14b cargado: ollama ls
✓ Firewall: puerto 11434 abierto
```

### Problema: "motor-OCR no disponible"
```
✓ Verificar repo: D:\proyectos\motor-OCR existe
✓ Verificar env PaddleOCR: python -c "import paddleocr"
✓ Logs: revisar extractor_tdr.log para detalles
```

### Problema: JSON del LLM inválido
```
✓ Ver logs [DEBUG] para prompt y response
✓ Verificar temperatura = 0 en ollama_client.py
✓ Reducir tamaño del contexto en markdown_processor.py
```

---

**Última actualización:** Marzo 2026  
**Versión:** 0.1.0 (MVP)
