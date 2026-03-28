# Extractor TDR — Extracción de Criterios de Bases de Concurso

Sistema automatizado para extraer criterios técnicos (Paso 1) de bases de concurso escaneadas.

## 🎯 Objetivo

Procesar un PDF de bases de concurso (digital o escaneado) y generar un Excel intermedio con:

1. **Tabla A:** Experiencias solicitadas (tipo, sector, descripción, ubicación, etc.)
2. **Tabla B:** Criterios RTM de profesionales (cargo, profesión, años, requisitos, etc.)

## 📋 Entrada y Salida

### Entrada
- PDF de bases de concurso (digital o escaneado)
- Ubicación: `C:\Users\Holbi\Downloads\1. CP consultoria obras 1-2026-VIVIENDA_opt.pdf`

### Salida
- Excel: `data/BASES_TDR_CRITERIOS.xlsx`
- 3 hojas:
  1. **Criterios RTM Profesionales** — Tabla B
  2. **Experiencias Solicitadas** — Tabla A
  3. **Información** — Metadatos de extracción

## 🚀 Instalación

### 1. Crear entorno virtual
```bash
python -m venv venv
source venv/Scripts/activate  # Windows Git Bash
# o
venv\Scripts\activate  # Windows CMD
```

### 2. Instalar dependencias
```bash
pip install -r requirements.txt
```

### 3. Verificar servicios disponibles

**Motor-OCR:**
```bash
ls "C:\Users\Holbi\Documents\Freelance\proyectos\motor-OCR"
```

**Ollama (LLM):**
```bash
curl http://localhost:11434/api/tags
```

Debe retornar modelo `qwen2.5:14b` disponible.

## 📖 Uso

### Procesamiento Completo (PDF → Excel)

```bash
python run_tdr_extraction.py \
  --pdf "C:\Users\Holbi\Downloads\1. CP consultoria obras 1-2026-VIVIENDA_opt.pdf" \
  --output "data/BASES_TDR_CRITERIOS.xlsx"
```

### Solo Extracción de Texto (sin LLM ni Excel)

```bash
python run_tdr_extraction.py \
  --pdf "bases.pdf" \
  --text-only
```

Output: `data/bases_texto.txt`

### Solo Parseo de Markdown (sin LLM)

```bash
python run_tdr_extraction.py \
  --pdf "bases.pdf" \
  --parse-only
```

### Con Logging Detallado

```bash
python run_tdr_extraction.py \
  --pdf "bases.pdf" \
  --verbose
```

## 🏗️ Arquitectura

```
PDF Bases
    ↓
[1. PDF Reader]
├─ Intenta pdfplumber (texto digital)
└─ Si falla → motor-OCR subprocess
    ↓
Archivo .md consolidado
    ↓
[2. Markdown Processor]
└─ Parse *_texto_*.md → diccionario por páginas
    ↓
[3. TDR Extractor + LLM]
├─ Paso 1: Extrae cargos → list[TDRCargo]
├─ Paso 2: Extrae experiencias → list[TDRExperience]
└─ Validación de resultado
    ↓
[4. Excel Writer]
└─ 3 sheets con formato y colores
    ↓
Excel intermedio
```

## 📁 Estructura

```
src/
├── tdr/
│   ├── __init__.py
│   ├── pdf_reader.py              # pdfplumber + motor-OCR fallback
│   ├── motor_ocr_client.py         # Subprocess wrapper
│   ├── markdown_processor.py        # Parse *_texto_*.md
│   ├── models.py                   # TDRCargo, TDRExperience
│   ├── prompts.py                  # Prompts LLM
│   ├── ollama_client.py            # Cliente Ollama
│   ├── tdr_extractor.py            # Orquestación
│   └── excel_writer.py             # openpyxl output

run_tdr_extraction.py               # CLI entry point
data/                               # Outputs
ocr_output/                         # Motor-OCR temp files
```

## 🔧 Configuración

### Motor-OCR

Motor-OCR busca el archivo wrapper en:
```
C:\Users\Holbi\Documents\Freelance\proyectos\motor-OCR\subprocess_wrapper.py
```

Se crea automáticamente si no existe.

Output directory (configurable con `--ocr-output`):
```
D:\proyectos\infoobras\ocr_output
```

Debe existir antes de ejecutar.

### Ollama

Servidor: `http://localhost:11434`
Modelo: `qwen2.5:14b`

Verificar disponibilidad:
```bash
curl http://localhost:11434/api/tags
```

## 🧪 Testing

### Unit Tests
```bash
pytest tests/
```

### Manual Testing
```bash
python run_tdr_extraction.py \
  --pdf "C:\Users\Holbi\Downloads\1. CP consultoria obras 1-2026-VIVIENDA_opt.pdf" \
  --output "data/TEST_BASES_TDR.xlsx" \
  --verbose
```

## 🚨 Troubleshooting

### Error: "motor-OCR no disponible"
- Verificar que `C:\Users\Holbi\Documents\Freelance\proyectos\motor-OCR` existe
- Verificar que `subprocess_wrapper.py` está presente

### Error: "Ollama no disponible"
- Iniciar servidor Ollama: `ollama serve`
- Verificar modelo: `ollama pull qwen2.5:14b`
- Verificar endpoint: `curl http://localhost:11434/api/tags`

### Error: "LLM timeout"
- Aumentar timeout en `--verbose` para ver detalles
- Verificar que Ollama tiene recursos disponibles
- Intentar con `--parse-only` primero para aislar problema

### Motor-OCR extrae poco texto
- Verificar calidad del PDF (resolver OCR, etc.)
- Revisar output en `D:\proyectos\infoobras\ocr_output\`
- Comparar con `--text-only` para ver diferencia

## 📊 Salida Esperada

### Excel Sheet 1: "Criterios RTM Profesionales"
```
Cargo y Profesión | Años Colegiado | Requisito Mínimo | Tipo Experiencia | Tiempo Adicional | Capacitación
Supervisor (Ing Civil) | 5 | Mínimo 5 años en... | Salud, Vivienda | ... | ...
...
```

### Excel Sheet 2: "Experiencias Solicitadas"
```
Tipo de Experiencia | Sector Válido | Descripción Exacta | Página | Experiencia Adicional | Otros Factores
Supervisión de obras | Salud | Debe contar con experiencia... | 15 | Certificado | ...
...
```

### Excel Sheet 3: "Información"
- Metadatos: PDF procesado, fechas, modelos, tiempos
- Resumen: Lista de cargos y experiencias

## 🔗 Integración con InfoObras

Este módulo genera el **Paso 1 (TDR)** del pipeline Alpamayo-InfoObras.

El Excel intermedio alimenta:
- **Paso 4:** Evaluación RTM (validación de cargos contra propuesta)
- **Paso 5:** Cálculo de días efectivos

## 📝 Notas

- **Idioma:** Español (código, comentarios, documentación)
- **Modelo LLM:** qwen2.5:14b en Ollama local
- **Temperatura:** 0 (determinístico)
- **Sin cloud:** Todo on-premise
- **GPU:** Motor-OCR usa RTX 5000 del servidor del cliente

## ✅ Checklist de Éxito

- [ ] PDF se procesa sin errores
- [ ] Texto se extrae (pdfplumber o motor-OCR)
- [ ] LLM extrae ≥5 cargos y ≥3 experiencias
- [ ] Excel se genera con 3 sheets
- [ ] Headers con colores y formato correcto
- [ ] No hay datos NULL en campos críticos
- [ ] CLI funciona end-to-end
