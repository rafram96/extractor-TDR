# Plan de Implementación: Extractor TDR desde Bases Escaneadas

**Fecha:** 28 de marzo de 2026
**Objetivo:** Extraer criterios TDR (Términos de Referencia) de un PDF de bases de concurso y generar Excel intermedio con requisitos de profesionales y experiencias.

---

## 📋 Entrada y Salida

### Entrada
- **Archivo:** `C:\Users\Holbi\Downloads\1. CP consultoria obras 1-2026-VIVIENDA_opt.pdf`
- **Tipo:** PDF escaneado (60MB)
- **Contenido:** Bases de concurso para supervisión de obras de vivienda

### Salida
- **Archivo:** `data/BASES_TDR_CRITERIOS.xlsx`
- **Formato:** 3 hojas Excel con requisitos detallados
- **Objetivo:** Input para Paso 4 (evaluación RTM) del sistema InfoObras

---

## 🏗️ Arquitectura de Solución

```
PDF Bases (escaneado)
    ↓
[1. PDF Reader]
├─ Intenta pdfplumber (texto digital)
└─ Si falla → motor-OCR subprocess
    ↓
Archivo .md consolidado (*_texto_*.md)
    ↓
[2. Markdown Processor]
├─ Parse *_texto_*.md
├─ Identifica secciones (cargos, experiencias)
└─ Retorna texto consolidado por sección
    ↓
[3. TDR Extractor]
├─ LLM Paso 1: Extrae cargos → list[TDRCargo]
├─ LLM Paso 2: Extrae experiencias → list[TDRExperience]
└─ Validación y deduplicación
    ↓
[4. Excel Writer]
├─ Sheet 1: Criterios RTM Profesionales (6 columnas)
├─ Sheet 2: Experiencias Solicitadas (6 columnas)
└─ Sheet 3: Texto Extraído (debug)
    ↓
Excel intermedio: BASES_TDR_CRITERIOS.xlsx
```

---

## 📁 Estructura de Archivos Nuevos

```
src/
└── tdr/                              (NUEVO módulo)
    ├── __init__.py
    ├── pdf_reader.py                 ← pdfplumber + motor-OCR fallback
    ├── motor_ocr_client.py            ← subprocess wrapper
    ├── markdown_processor.py           ← parse *_texto_*.md
    ├── models.py                       ← dataclasses TDR
    ├── prompts.py                      ← prompts LLM para TDR
    ├── tdr_extractor.py               ← orquestación LLM
    └── excel_writer.py                ← openpyxl output

run_tdr_extraction.py                 ← script CLI
tests/
└── test_tdr_extraction.py             ← tests unitarios
```

---

## 🔧 Fases de Implementación

### **Fase 1: Extracción de Texto**

#### 1.1 `src/tdr/pdf_reader.py`
- Función: `read_pdf(pdf_path: str) -> str`
- **Intento 1:** `pdfplumber.open()` → extrae texto digital
- **Intento 2:** Si texto < 200 caracteres/página promedio → invocar motor-OCR subprocess
- **Return:** Texto consolidado del PDF

#### 1.2 `src/tdr/motor_ocr_client.py`
- Función: `invoke_motor_ocr(pdf_path: str) -> str`
- **Crear:** Wrapper script en `C:\Users\Holbi\Documents\Freelance\proyectos\motor-OCR\subprocess_wrapper.py`
- **Invoca:** `process_and_segment()` vía subprocess
- **Manejo:**
  - Timeout: 3600 segundos (1 hora)
  - Errores: Captura stderr y levanta excepción clara
  - Limpieza: Remove archivos temporales en finally
- **Return:** Texto extraído de `*_texto_*.md`

#### 1.3 `src/tdr/motor_ocr_client.py` → Wrapper Script
**Ubicación:** `C:\Users\Holbi\Documents\Freelance\proyectos\motor-OCR\subprocess_wrapper.py`

```python
import sys, json, pickle
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent / "src"))
from main import process_and_segment

if __name__ == "__main__":
    args_file, results_file = sys.argv[1:3]
    with open(args_file) as f:
        args = json.load(f)
    doc, secciones = process_and_segment(**args)
    with open(results_file, 'wb') as f:
        pickle.dump((doc, secciones), f)
```

---

### **Fase 2: Procesamiento de Markdown**

#### 2.1 `src/tdr/markdown_processor.py`
- Función: `process_motor_ocr_output(output_dir: str) -> dict[str, str]`
- **Input:** Directorio `ocr_output/{pdf_name}/` con archivos `*_texto_*.md`
- **Proceso:**
  1. Lee archivos `*_texto_*.md` más reciente
  2. Parse por `## Página N` headers
  3. Consolida texto por secciones lógicas
  4. Identifica secciones de "cargos" y "experiencias"
- **Return:** `{section_name: consolidated_text}`

**Patrón:** Adaptar `src/extraction/md_parser.py` de Alpamayo-InfoObras

---

### **Fase 3: Extracción con LLM**

#### 3.1 `src/tdr/models.py`
```python
@dataclass
class TDRCargo:
    cargo: str                          # Ej: "Supervisor de Obra"
    profesion_requerida: str            # Ej: "Ingeniero Civil"
    anos_minimos_colegiado: int
    anos_minimos_experiencia: int
    tipos_obra_validos: list[str]       # Ej: ["salud", "vivienda"]
    intervenciones_requeridas: list[str]
    complejidad: str                    # "alta" | "media" | "baja"
    requisito_minimo_detallado: str     # Texto exacto del documento
    puntuacion_por_experiencia: dict    # {exp_type: points}
    capacitacion_solicitada: str        # Ej: "Curso de seguridad"
    tiempo_adicional_evaluacion: str
    pagina_documento: int               # Página donde aparece el requisito
    otros_factores_evaluacion: str

@dataclass
class TDRExperience:
    tipo_experiencia: str               # Ej: "Supervisión de obras"
    sector_valido: str                  # Ej: "Salud"
    descripcion_exacta: str             # Lo que dice el documento
    experiencia_adicional: str          # Qué se debe entregar
    otros_factores: str
    pagina_documento: int

@dataclass
class TDRExtraction:
    cargos: list[TDRCargo]
    experiencias: list[TDRExperience]
    fecha_extraccion: str
    pdf_name: str
    total_paginas: int
```

#### 3.2 `src/tdr/prompts.py`
```python
PROMPT_EXTRACT_CARGOS = """
Eres un extractor de criterios técnicos de bases de concursos de obras públicas.

Del texto de las BASES, extrae los requisitos por CARGO solicitado en el concurso.

Devuelve ÚNICAMENTE este JSON, sin texto antes ni después:
{
  "cargos": [
    {
      "cargo": "string (nombre del cargo)",
      "profesion_requerida": "string",
      "anos_minimos_colegiado": number,
      "anos_minimos_experiencia": number,
      "tipos_obra_validos": ["string"],
      "intervenciones_requeridas": ["string"],
      "complejidad": "alta|media|baja",
      "requisito_minimo_detallado": "string (texto EXACTO del documento)",
      "puntuacion_por_experiencia": {"type": number},
      "capacitacion_solicitada": "string",
      "tiempo_adicional_evaluacion": "string",
      "pagina_documento": number,
      "otros_factores_evaluacion": "string"
    }
  ]
}

TEXTO BASES:
{texto}
"""

PROMPT_EXTRACT_EXPERIENCIAS = """
Eres un extractor de criterios de experiencia de bases de concursos de obras públicas.

Del texto de las BASES, extrae los TIPOS DE EXPERIENCIA solicitados al postor.

Devuelve ÚNICAMENTE este JSON, sin texto antes ni después:
{
  "experiencias": [
    {
      "tipo_experiencia": "string",
      "sector_valido": "string",
      "descripcion_exacta": "string (texto EXACTO del documento)",
      "experiencia_adicional": "string (qué se debe entregar)",
      "otros_factores": "string",
      "pagina_documento": number
    }
  ]
}

TEXTO BASES:
{texto}
"""
```

#### 3.3 `src/tdr/tdr_extractor.py`
```python
class TDRExtractor:
    def extract(self, consolidated_text: dict[str, str]) -> TDRExtraction:
        # Paso 1: Extrae cargos
        cargos = self._extract_cargos(consolidated_text)

        # Paso 2: Extrae experiencias
        experiencias = self._extract_experiencias(consolidated_text)

        # Validación
        self._validate_results(cargos, experiencias)

        return TDRExtraction(cargos, experiencias, ...)

    def _extract_cargos(self, text_dict) -> list[TDRCargo]:
        # Combina texto de secciones relevantes
        full_text = "\n".join(text_dict.values())

        # Invoca LLM con PROMPT_EXTRACT_CARGOS
        result = call_llm(PROMPT_EXTRACT_CARGOS.format(texto=full_text))

        # Parse JSON y crea objetos TDRCargo
        return [TDRCargo(**c) for c in result["cargos"]]

    def _extract_experiencias(self, text_dict) -> list[TDRExperience]:
        # Similar para experiencias
        ...

    def _validate_results(self, cargos, experiencias):
        # Verifica campos obligatorios
        # Deduplica por nombre
        # Levanta excepción si hay issues críticos
        ...
```

**Patrón:** Adaptar `src/extraction/llm_extractor.py` de Alpamayo-InfoObras

---

### **Fase 4: Generación de Excel**

#### 4.1 `src/tdr/excel_writer.py`
```python
class TDRExcelWriter:
    def write(self, extraction: TDRExtraction, output_path: Path):
        wb = openpyxl.Workbook()

        # Sheet 1: Criterios RTM Profesionales (Tabla B)
        self._write_cargos_sheet(wb, extraction.cargos)

        # Sheet 2: Experiencias Solicitadas (Tabla A)
        self._write_experiencias_sheet(wb, extraction.experiencias)

        # Sheet 3: Texto Extraído (debug)
        self._write_debug_sheet(wb, extraction)

        wb.save(output_path)

def _write_cargos_sheet(self, wb, cargos):
    ws = wb.create_sheet("Criterios RTM Profesionales", 0)

    # Headers
    headers = [
        "Cargo y Profesión",
        "Años de Colegiado",
        "Requisito Mínimo (detallado + puntuación + máximo)",
        "Tipo Experiencia Similar",
        "Tiempo Adicional en Evaluación",
        "Capacitación Solicitada"
    ]
    ws.append(headers)

    # Data rows
    for cargo in cargos:
        ws.append([
            f"{cargo.cargo} ({cargo.profesion_requerida})",
            cargo.anos_minimos_colegiado,
            cargo.requisito_minimo_detallado,
            ", ".join(cargo.tipos_obra_validos),
            cargo.tiempo_adicional_evaluacion,
            cargo.capacitacion_solicitada
        ])

    # Formatos
    self._apply_formatting(ws)

def _write_experiencias_sheet(self, wb, experiencias):
    ws = wb.create_sheet("Experiencias Solicitadas", 1)

    headers = [
        "Tipo de Experiencia Válida",
        "Sector Válido",
        "Descripción Exacta del Documento",
        "Ubicación (página)",
        "Experiencia Adicional a Entregar",
        "Otros Factores de Evaluación"
    ]
    ws.append(headers)

    for exp in experiencias:
        ws.append([
            exp.tipo_experiencia,
            exp.sector_valido,
            exp.descripcion_exacta,
            exp.pagina_documento,
            exp.experiencia_adicional,
            exp.otros_factores
        ])

    self._apply_formatting(ws)

def _write_debug_sheet(self, wb, extraction):
    # Opcional: texto crudo para verificación manual
    ...
```

**Colores:**
- Verde (#00B050): Requisito obligatorio
- Amarillo (#FFFF00): Requisito recomendado
- Rojo (#FF0000): Crítico/Observación

---

### **Fase 5: CLI y Testing**

#### 5.1 `run_tdr_extraction.py`
```bash
usage: python run_tdr_extraction.py [-h] --pdf PDF [--output OUTPUT] [--text-only] [--parse-only]

Extrae criterios TDR de bases de concurso escaneadas.

Options:
  --pdf PDF              Ruta del PDF bases (digital o escaneado)
  --output OUTPUT        Ruta del Excel output (default: data/BASES_TDR_CRITERIOS.xlsx)
  --text-only            Solo extrae texto, no LLM ni Excel
  --parse-only           Parse markdown, no LLM
```

**Ejemplo:**
```bash
python run_tdr_extraction.py \
  --pdf "C:\Users\Holbi\Downloads\1. CP consultoria obras 1-2026-VIVIENDA_opt.pdf" \
  --output "data/BASES_TDR_CRITERIOS.xlsx"
```

---

## 🧪 Testing

### Unit Tests (`tests/test_tdr_extraction.py`)
- Test markdown parsing con ejemplo mock
- Test LLM extraction con response mock
- Test Excel generation (estructura, colores, headers)

### End-to-End Test
- Procesar PDF real → Excel
- Validar 3 sheets presentes
- Verificar conteo de filas esperadas (5-10 cargos, 3-8 experiencias)

---

## 📊 Dependencias Requeridas

```
pdfplumber>=0.11.0        # Digital PDF text extraction
openpyxl>=3.0.0           # Excel generation
requests>=2.31.0          # HTTP calls to Ollama
```

Verificar en `requirements.txt` del proyecto.

---

## ⚙️ Configuración Necesaria

### Motor-OCR
- Output dir: `D:\proyectos\infoobras\ocr_output` (debe existir)
- Ollama running: `http://localhost:11434`
- Config: `src/config.py` en motor-OCR repo

### Ollama
- Modelo: `qwen2.5:14b` disponible
- Verificar: `curl http://localhost:11434/api/tags`

---

## 🚨 Potenciales Problemas y Mitigaciones

| Problema | Mitigación |
|----------|-----------|
| Motor-OCR timeout | Aumentar timeout a 300s, procesar en chunks |
| LLM no responde JSON | Validación de schema + retry automático |
| PDF muy grande (60MB) | Opción `--pages 1-100` para procesar parcialmente |
| Ollama no disponible | Error claro pidiendo activar servicio |
| Duplicados en extracción | Deduplicación automática en tdr_extractor.py |

---

## 📝 Notas de Implementación

1. **Patrones Reusables:** Usar modelos de `Alpamayo-InfoObras/src/extraction/` como referencia
2. **Prompts Críticos:** Enfatizar "Devuelve ÚNICAMENTE JSON" para evitar texto extra
3. **Validación:** Después de cada LLM call, validar schema JSON antes de crear objetos
4. **Logs:** Usar logging en cada fase para debugging
5. **Excel:** Aplicar formatos (ancho columnas, wrapping texto, borders) para legibilidad

---

## 📅 Timeline Esperado

- **Fase 1 (PDF + OCR):** 30 min
- **Fase 2 (Markdown):** 20 min
- **Fase 3 (LLM):** 40 min
- **Fase 4 (Excel):** 30 min
- **Fase 5 (CLI + Testing):** 20 min

**Total:** ~2-3 horas de implementación

---

## ✅ Criterios de Éxito

- [ ] PDF se procesa sin errores (pdfplumber o motor-OCR)
- [ ] Texto se extrae y consolida correctamente
- [ ] LLM extrae ≥5 cargos y ≥3 experiencias
- [ ] Excel se genera con 3 sheets correctas
- [ ] Headers y colores formateados
- [ ] No hay datos NULL en campos críticos
- [ ] Script CLI funciona end-to-end

