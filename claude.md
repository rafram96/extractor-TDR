# Alpamayo-InfoObras

## Qué es este proyecto
Sistema de evaluación automatizada de propuestas técnicas para licitaciones de obras públicas en Perú.
El usuario sube dos PDFs (propuesta técnica + bases del concurso) y el sistema devuelve un análisis completo en una interfaz web propia.

El problema que resuelve: el análisis manual de una propuesta toma 6-12 horas. Este sistema lo reduce a 20-40 minutos incluyendo verificación cruzada con InfoObras.

## Arquitectura general
```
Browser
  ↓ sube PDF propuesta + PDF bases
FastAPI (este repo)
  ├─ llama motor-OCR como subprocess → procesa PDF propuesta (escaneado)
  ├─ extrae TDR del PDF bases directamente con pdfplumber (texto digital)
  ├─ pipeline extracción → validación → scraping
  └─ sirve resultados en UI web propia
```

- **motor-OCR** (repo separado, NO tocar): caja negra. Entra PDF escaneado, salen `.md` en `ocr_output/`. Se invoca como subprocess desde el backend.
- **Este repo**: orquesta todo — web app, extracción, validación, scraping, UI.

## Repos y entornos

### motor-OCR
- Repo local: `C:\Users\Holbi\Documents\Freelance\proyectos\motor-OCR`
- Servidor del cliente: `D:\proyectos\motor-OCR`
- Python 3.11, PaddleOCR, GPU NVIDIA Quadro RTX 5000 16GB
- Se ejecuta hoy manualmente como script `.py` — en producción se invoca como subprocess desde el backend
- Output en: `D:\proyectos\infoobras\ocr_output\{nombre_pdf}\`
- Outputs de prueba actualmente en `data/` de este repo
- **No tocar — funciona y tiene dependencias muy frágiles**

### Main repo (Alpamayo-InfoObras)
- Repo local: `C:\Users\Holbi\Documents\Freelance\Alpamayo-InfoObras`
- Repo público: `https://github.com/rafram96/InfoObras`
- Servidor del cliente: por definir (clona con `git clone` sin auth, repo público)
- Python 3.12, sin dependencias de ML
- El código se escribe en esta laptop, se ejecuta en el servidor

### Este repo (Extractor TDR)
- Nuevo

## Servidor del cliente
- OS: Windows 11 Pro
- CPU: Intel Core i9-14900K (24 cores)
- RAM: 64GB DDR5
- GPU: NVIDIA Quadro RTX 5000 16GB VRAM (usada por motor-OCR)
- SSD: 3TB NVMe
- Servicios corriendo: Docker, n8n, OpenWebUI, Nginx Proxy Manager, Ollama
- Modelos en Ollama: `qwen2.5vl:7b` (segmentación), `qwen2.5:14b` (extracción)
- Todo on-premise, sin cloud, sin APIs externas de pago

## Flujo completo del sistema
```
Usuario sube:
  ├─ PDF propuesta técnica (2300+ págs, escaneado)
  └─ PDF bases del concurso (texto digital)
        ↓
[motor-OCR — subprocess] OCR + segmentación
        ↓
ocr_output/{pdf}/*_profesionales_*.md  +  *_texto_*.md
        ↓
[extracción] md_parser → llm_extractor (qwen2.5:14b)
  → Paso 2: profesionales (nombre, CIP, profesión)
  → Paso 3: experiencias (certificados, fechas, empresas)
        ↓
[TDR] pdfplumber extrae texto bases → LLM extrae criterios RTM
  → Paso 1: requisitos por cargo (profesión, años, tipo obra)
        ↓
[scraping]
  → InfoObras: búsqueda por nombre proyecto → CUI → estado, suspensiones
  → SUNAT: fecha constitución empresa por RUC
  → CIP: vigencia de colegiatura
  CUIs no encontrados automáticamente → UI pide confirmación humana
        ↓
[validación]
  → Paso 4: evaluación RTM (22 criterios)
  → Paso 5: cálculo días efectivos (descuenta COVID, paralizaciones)
  → 9 alertas por certificado
        ↓
UI web muestra resultados + botón exportar Excel
```

## Output del motor-OCR
Por cada PDF procesado genera en `ocr_output/{nombre_pdf}/`:
- `*_metricas_*.md` — calidad OCR por página
- `*_texto_*.md` — texto extraído página a página
- `*_segmentacion_*.md` — bloques crudos de segmentación (debug)
- `*_profesionales_*.md` — secciones consolidadas por profesional ← **input principal**

## Extracción de TDR (bases del concurso)
Las bases pueden ser PDF digital o PDF escaneado — no hay garantía de cuál llegará.

### Estrategia: detección automática con fallback
`pdf_reader.py` intenta primero con `pdfplumber` (rápido, sin GPU).
Si el texto extraído es insuficiente (< N caracteres por página en promedio → probablemente escaneado),
se reenvía el PDF al motor-OCR como subprocess, igual que la propuesta técnica.

```
PDF bases
  ↓
pdfplumber → ¿texto suficiente?
  ├─ Sí → usar texto directamente
  └─ No → motor-OCR subprocess → *_texto_*.md → mismo parser que propuesta
```

Esto evita duplicar lógica OCR en este repo y reutiliza lo que ya funciona.
**Sí se puede llamar al motor-OCR para las bases** — la restricción es no tocar su código,
no que no se pueda invocar como proceso.

### Qué se extrae del TDR por cargo
- Profesión requerida (Ingeniero Civil, Arquitecto, etc.)
- Años mínimos de experiencia en obras similares
- Tipo de obra válido (salud, educación, etc.)
- Cargos válidos equivalentes
- Años mínimos de colegiatura
- Complejidad e intervención requerida

Esto alimenta el Paso 1 y es la base del motor de reglas (Pasos 4 y 5).

## Estructura
```
ocr_output/                  ← input (generado por motor-OCR, NO tocar)
src/
  extraction/                ← parsea .md → datos estructurados (Pasos 2 y 3)
    models.py                ← ProfessionalBlock, Professional, Experience
    md_parser.py             ← combina *_profesionales_*.md + *_texto_*.md
    ollama_client.py         ← wrapper HTTP para Ollama (temperatura 0)
    prompts.py               ← prompts Paso 2 y Paso 3
    llm_extractor.py         ← orquesta las dos llamadas LLM por bloque
  tdr/                       ← extrae criterios RTM de las bases (Paso 1)
    pdf_reader.py            ← pdfplumber → texto crudo del PDF bases
    tdr_extractor.py         ← LLM extrae requisitos por cargo
  validation/                ← motor de reglas determinístico (Pasos 4 y 5)
  scraping/                  ← InfoObras, SUNAT, CIP
  reporting/                 ← genera Excel final (5 hojas)
  api/                       ← FastAPI: endpoints, job system, websockets
utils/                       ← herramientas auxiliares y PoCs
docs/                        ← documentación del proyecto
data/                        ← datos procesados (NO subir al repo)
```

## Stack
- Python 3.12
- `fastapi` + `uvicorn` — backend web
- `pdfplumber` — extracción de texto de PDFs digitales (bases/TDR)
- `requests` — scraping InfoObras, SUNAT, CIP y llamadas Ollama
- `openpyxl` — generación Excel
- HTML + Tailwind CSS + Alpine.js — frontend (sin build step, sin npm)
- SQLite — estado de jobs y resultados
- LLM: `qwen2.5:14b` vía Ollama local (temperatura 0)
- SIN PaddleOCR ni dependencias de ML aquí

## Web app — pantallas
1. **Upload** — dos dropzones: propuesta técnica + bases. Botón "Analizar".
2. **Progreso** — stepper: `OCR → Extracción (12/30) → Scraping → Validación → Listo`
3. **Resultados** — tabla de profesionales con semáforo, click → detalle con certificados y alertas
4. **Confirmación CUIs** — lista de proyectos sin CUI automático para ingreso manual
5. **Exportar** — descarga el Excel final

## Intervención humana aceptada
- CUIs no encontrados automáticamente en InfoObras → el evaluador los ingresa en la UI
- El sistema propone candidatos si hay resultados ambiguos en la búsqueda

## Los 5 pasos del proceso (contexto del negocio)

### Paso 1 — Criterios TDR de las bases
Extrae de las bases del concurso qué se requiere por cargo: profesión, años colegiado, experiencia mínima, tipo de obra, cargos válidos.

### Paso 2 — Profesionales propuestos
Lista todos los profesionales del PDF: nombre, profesión, CIP, fecha colegiación, folio.

### Paso 3 — Base de datos de experiencias (27 columnas)
Por cada certificado: nombre, DNI, proyecto, cargo, empresa, RUC, fechas, folio, CUI, código InfoObras, firmante, etc.

### Paso 4 — Evaluación RTM (22 criterios)
Motor de reglas determinístico: cumple/no cumple por profesión, cargo, tipo de obra, intervención, complejidad.

### Paso 5 — Evaluación de años de experiencia
Suma días efectivos descontando paralizaciones, suspensiones y COVID (16/03/2020–31/12/2021).

## Las 9 alertas del motor de reglas
- ALT01: Fecha fin > fecha emisión certificado
- ALT02: Periodo COVID (16/03/2020–31/12/2021)
- ALT03: Experiencia > 20 años desde fecha de propuesta
- ALT04: Empresa emisora constituida después del inicio de experiencia
- ALT05: Certificado sin fecha de término ("a la fecha")
- ALT06: Cargo no válido según bases
- ALT07: Profesión no coincide con la requerida
- ALT08: Tipo de obra no coincide
- ALT09: CIP no vigente

## Scraping
- **InfoObras** (Contraloría): búsqueda por nombre → CUI → estado, avances, suspensiones, actas. Sin CAPTCHA, funciona con `requests`.
- **SUNAT**: fecha de inicio de actividades por RUC (ALT04).
- **CIP**: verificación de vigencia del número de colegiatura (ALT09).

## Excel de salida (5 hojas)
1. Resumen — totales, alertas críticas
2. Base de Datos (Paso 3) — 27 columnas
3. Evaluación RTM (Paso 4) — 22 columnas, CUMPLE/NO CUMPLE
4. Alertas — código, severidad, descripción por profesional
5. Verificación InfoObras — CUI, estado, suspensiones, días descontados

Colores: Verde = Cumple · Amarillo = Observación · Rojo = No cumple/Alerta crítica

## Cliente
- Inmobiliaria Alpamayo / Indeconsult
- Contacto: Ing. Manuel Echandía
- Uso: evaluación de propuestas técnicas en concursos públicos de supervisión de obras hospitalarias

## Convenciones
- Idioma del código: español (variables, funciones, clases)
- Idioma de comentarios y docs: español
- Idioma de commits: español
- Formato de commits: descripción cortísima (Feat, Fix, Debug, Refactor, etc.)

## Comandos útiles
```bash
# Activar entorno virtual
source venv/Scripts/activate    # Windows/Git Bash

# Instalar dependencias
pip install -r requirements.txt

# Prueba de extracción (sin web app)
python run_extraction.py --parse-only     # solo parseo, sin LLM
python run_extraction.py --index 1        # primer profesional con LLM
python run_extraction.py --all --output data/resultado.json

# Levantar web app (cuando esté implementada)
uvicorn src.api.main:app --reload --port 8000

# Ejecutar tests
pytest
```

## Qué NO hacer
- No instalar PaddleOCR ni dependencias de ML aquí
- No modificar archivos en `ocr_output/` — son generados por motor-OCR
- No subir PDFs ni datos del cliente al repositorio
- No tocar el repo motor-OCR — funciona y sus dependencias son frágiles
- No usar APIs cloud para procesamiento — todo debe correr on-premise
- No modificar el código del motor-OCR — sí se puede invocar como subprocess para bases escaneadas
