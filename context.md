# extractor-Bases_TDR — Contexto del Proyecto

## Qué es este proyecto

`extractor-Bases_TDR` es un pipeline que automatiza la lectura de documentos de bases de concursos públicos peruanos (OSCE) y extrae de forma estructurada los requisitos técnicos mínimos (RTM) y factores de evaluación. El output es un JSON con toda la información necesaria para los pasos 1 y 2 del proceso de análisis de propuestas.

Este proyecto es un componente del sistema mayor **InfoObras Analyzer**, pero funciona de forma completamente independiente. Su única dependencia externa es el motor OCR (comunicación vía subprocess).

---

## Problema que resuelve

Un documento de bases de concurso público tiene entre 150 y 400 páginas. La información relevante (RTM de postor, personal clave, factores de evaluación) está concentrada en 15-30 páginas específicas. El proceso manual actual implica leer todo el documento para encontrar esas secciones, luego copiar la información a mano en una planilla Excel.

Este extractor reduce ese proceso a un pipeline automático de ~5 minutos:

1. El motor OCR convierte el PDF en texto estructurado
2. El scorer identifica las páginas relevantes sin LLM
3. Qwen extrae los datos solo de esas páginas
4. El resultado sale como JSON listo para consumir

---

## Ecosistema: cómo encaja este proyecto

```
InfoObras Analyzer (sistema mayor)
│
├── motor-OCR/                  ← proyecto separado, repo propio
│   ├── mode="ocr_only"         ← lo que usa este proyecto
│   └── mode="full"             ← segmentación de profesionales (propuestas)
│
├── extractor-Bases_TDR/        ← ESTE PROYECTO
│   └── Extrae RTM y factores de bases de concurso
│
└── (futuro) evaluador/         ← usará el output de este proyecto
    └── Cruza propuestas contra los RTM extraídos
```

### Comunicación con motor-OCR

El motor OCR es una **caja negra**. Este proyecto solo lo invoca vía subprocess usando el client en `clients/motor_ocr_client.py`. No se importa ningún módulo interno del motor.

```python
# Única interfaz con el motor OCR
from clients.motor_ocr_client import invoke_motor_ocr

full_text = invoke_motor_ocr(pdf_path, output_dir)
# full_text es un string con formato ## Página N
```

El motor corre en su propio venv (`D:\proyectos\motor-OCR\venv`). Este proyecto tiene su propio venv separado.

---

## Estructura del proyecto

```
extractor-Bases_TDR/
│
├── clients/
│   └── motor_ocr_client.py     # Cliente subprocess del motor OCR (copia exacta)
│
├── config/
│   ├── settings.py             # Rutas, URLs, timeouts, umbrales numéricos
│   └── signals.py              # Señales del scorer + prompts de Qwen
│
├── extractor/
│   ├── parser.py               # parse_full_text() → list[PageResult]
│   ├── scorer.py               # score_page(), group_into_blocks()
│   ├── llm.py                  # Comunicación con Qwen vía OpenAI client
│   └── pipeline.py             # extraer_bases() — orquesta todo
│
├── output/                     # JSONs generados (gitignored)
├── data/                       # PDFs de prueba (gitignored)
│
├── main.py                     # Entry point CLI
└── requirements.txt
```

### Responsabilidad de cada módulo

| Módulo | Responsabilidad | Depende de |
|--------|----------------|------------|
| `clients/motor_ocr_client.py` | Invocar el motor OCR como subprocess | Nada del proyecto |
| `config/settings.py` | Toda la configuración que cambia entre entornos | Nada |
| `config/signals.py` | Señales del scorer y prompts del LLM | Nada |
| `extractor/parser.py` | Convertir `full_text` en `list[PageResult]` | Nada |
| `extractor/scorer.py` | Clasificar páginas y agrupar en bloques | `config/` + `extractor/parser.py` |
| `extractor/llm.py` | Llamar a Qwen y parsear la respuesta | `config/` + `extractor/scorer.py` |
| `extractor/pipeline.py` | Orquestar parser → scorer → llm | Todo `extractor/` |
| `main.py` | CLI: argumentos, logging, guardar output | `clients/` + `extractor/pipeline.py` |

La regla es: `config/` no importa nada del proyecto. `extractor/` no sabe nada del CLI. Cuando llegue la API, solo se agrega `api/` sin modificar los módulos existentes.

---

## Pipeline de procesamiento

### Visión general

```
PDF de bases
    ↓
[subprocess] motor-OCR (mode="ocr_only")
    ↓
full_text — string con formato "## Página N · conf X"
    ↓
[parser.py] parse_full_text()
    ↓
list[PageResult]  — página por página con número, motor, confianza y texto
    ↓
[scorer.py] score_page() por cada página
    ↓
list[PageScore]  — cada página con scores por tipo (rtm_postor, rtm_personal, factores, blacklist)
    ↓
[scorer.py] group_into_blocks()
    ↓
list[Block]  — 3-5 bloques clasificados, ~15-30 páginas total
    ↓
[llm.py] extraer_bloque() por cada bloque  ← único punto donde se usa Qwen
    ↓
JSON estructurado con RTM postor + personal clave + factores
```

### Etapa 1 — Parser (`extractor/parser.py`)

Convierte el `full_text` del motor OCR en una lista de `PageResult`. El formato del motor es consistente:

```
## Página 47  _🔵 paddle · conf 0.923_
```
texto de la página
```
---
```

El parser usa regex para extraer número de página, motor usado, confianza y texto limpio. No hace ninguna clasificación — es puramente estructural.

### Etapa 2 — Scorer (`extractor/scorer.py`)

El scorer es el componente más importante del proyecto. Clasifica cada página sin usar LLM, basándose en señales semánticas del vocabulario OSCE.

**Por qué funciona sin anclas fijas:** El vocabulario OSCE es regulado por ley (Ley de Contrataciones del Estado y sus directivas). Términos como "debe acreditar", "monto facturado", "personal clave", "tiempo de experiencia" aparecen en todo documento de bases sin importar el ministerio, la convocatoria o el año.

**Tipos de bloque detectados:**

- `rtm_postor` — requisitos de experiencia de la empresa/consorcio
- `rtm_personal` — requisitos de personal clave (cargos, profesiones, experiencia mínima)
- `factores_evaluacion` — puntajes y criterios de evaluación
- `blacklist` — páginas de ruido: cláusulas de contrato, disposiciones generales, etc.

**Lógica de `dominant_type`:** Una página es relevante si su score de contenido supera `SCORER_MIN_SCORE` (default 2.0) Y ese score supera el score de blacklist. Si blacklist gana, la página se descarta aunque tenga señales relevantes.

**Agrupamiento:** Páginas contiguas del mismo tipo dominante se agrupan en bloques. Se tolera un gap de hasta `SCORER_MAX_GAP` páginas (default 3) para mantener unidos bloques cuya señal principal aparece solo en la primera página (ej: tabla que continúa sin repetir el header). Se agregan `SCORER_CONTEXT` páginas de contexto antes y después de cada bloque.

### Etapa 3 — LLM (`extractor/llm.py`)

Qwen recibe bloques de texto ya clasificados, nunca el documento completo. Cada tipo de bloque tiene su propio prompt con el esquema JSON esperado.

**Configuración de Qwen:** Corre localmente vía Ollama, expuesto como API compatible con OpenAI. Se consume con el paquete `openai` apuntando a `http://localhost:11434/v1`.

**Limpieza de respuesta:** Qwen2.5 a veces devuelve un bloque `<think>...</think>` antes del JSON (razonamiento interno del modelo). El cliente lo elimina antes de parsear. También limpia backticks de markdown que el modelo a veces agrega alrededor del JSON.

**Temperatura 0:** Todas las llamadas usan `temperature=0` para máximo determinismo. Este es un task de extracción, no generación creativa.

### Etapa 4 — Pipeline (`extractor/pipeline.py`)

Orquesta las tres etapas y acumula resultados. Cada resultado incluye un campo `_meta` con el tipo de bloque y el rango de páginas de origen, para trazabilidad.

---

## Formato del output

```json
{
  "rtm_postor": [
    {
      "item": null,
      "tipo_experiencia_valida": "Consultoría de obra para elaboración de expediente técnico",
      "sector_valido": "saneamiento",
      "cita_exacta": "El postor debe acreditar un monto facturado acumulado equivalente a...",
      "pagina": 87,
      "experiencia_adicional_factores": null,
      "otros_factores_postor": null
    }
  ],
  "rtm_personal": [
    {
      "cargo": "Jefe de elaboración del expediente técnico",
      "profesiones_aceptadas": ["Arquitecto", "Ingeniero Civil"],
      "anos_colegiado": 5,
      "experiencia_minima": {
        "cantidad": 48,
        "unidad": "meses",
        "descripcion": "...",
        "cargos_similares_validos": ["Jefe", "Gerente", "Director de proyecto"],
        "puntaje_por_experiencia": null,
        "puntaje_maximo": null
      },
      "tipo_obra_valido": "Expedientes técnicos de edificaciones",
      "tiempo_adicional_factores": "60 meses para puntaje máximo",
      "capacitacion": {
        "tema": "BIM",
        "tipo": "curso",
        "duracion_minima_horas": 40,
        "es_factor_evaluacion": true
      },
      "pagina": 94
    }
  ],
  "factores_evaluacion": [
    {
      "factor": "Experiencia en elaboración de expedientes técnicos",
      "aplica_a": "personal",
      "cargo_personal": "Jefe de elaboración del expediente técnico",
      "puntaje_maximo": 15,
      "metodologia": "Se otorgan 3 puntos por cada 12 meses adicionales...",
      "pagina": 112
    }
  ],
  "_bloques_detectados": [
    {"tipo": "rtm_postor", "paginas": [85, 91]},
    {"tipo": "rtm_personal", "paginas": [92, 108]},
    {"tipo": "factores_evaluacion", "paginas": [109, 118]}
  ]
}
```

---

## Uso desde CLI

```bash
# Instalación
pip install -r requirements.txt

# Dry run: ver qué bloques detecta el scorer sin usar Qwen
# Útil para calibrar señales antes de gastar tiempo en inferencia
python main.py extraer "data/bases_vivienda.pdf" --dry-run

# Extracción completa
python main.py extraer "data/bases_vivienda.pdf"

# Output en: output/bases_vivienda_bases.json
```

### Interpretando el dry-run

```
──────────────────────────────────────────────────
DRY RUN — 192 páginas → 3 bloques detectados
──────────────────────────────────────────────────
  [rtm_postor]          págs (85, 91)   conf_avg=0.941
  [rtm_personal]        págs (92, 108)  conf_avg=0.887
  [factores_evaluacion] págs (109, 118) conf_avg=0.912
──────────────────────────────────────────────────
```

Si un bloque esperado no aparece, revisar los scores individuales de cada página para identificar qué señal no está disparando y ajustar `config/signals.py`.

---

## Configuración (`config/settings.py`)

| Variable | Default | Descripción |
|----------|---------|-------------|
| `MOTOR_OCR_REPO` | `D:\proyectos\motor-OCR` | Ruta al repo del motor OCR |
| `QWEN_MODEL` | `qwen2.5:14b` | Modelo Ollama a usar |
| `QWEN_OLLAMA_BASE_URL` | `http://localhost:11434/v1` | URL de Ollama |
| `SCORER_MIN_SCORE` | `2.0` | Score mínimo para considerar una página relevante |
| `SCORER_MAX_GAP` | `3` | Páginas de gap toleradas dentro de un bloque |
| `SCORER_CONTEXT` | `1` | Páginas de contexto antes/después de cada bloque |

### Cuándo ajustar los umbrales

- **Falsos negativos** (secciones relevantes no detectadas): bajar `SCORER_MIN_SCORE` a 1.5, o agregar señales en `config/signals.py`
- **Falsos positivos** (páginas de ruido que se cuelan): subir `SCORER_MIN_SCORE` a 2.5, o agregar señales a `blacklist`
- **Bloques partidos** (una sección continua detectada como dos bloques separados): subir `SCORER_MAX_GAP`

---

## Señales del scorer (`config/signals.py`)

Las señales son pares `(regex, peso)`. El score de una página es la suma de pesos de todas las señales que matchean.

El vocabulario es estable entre documentos OSCE porque proviene de la Ley de Contrataciones del Estado y sus directivas. Lo que varía entre ministerios es el número de capítulo, el nombre exacto de la sección, el encabezado — todo eso lo ignora el scorer.

Para agregar una señal nueva:

```python
# En config/signals.py, dentro de SIGNALS["rtm_personal"]:
(r"nueva señal regex",  2.0),  # peso entre 0.5 y 3.0
```

Para agregar un nuevo tipo de bloque (ej: si en el futuro se quiere extraer el plazo de ejecución):

1. Agregar el tipo y sus señales en `SIGNALS` dentro de `config/signals.py`
2. Agregar el prompt correspondiente en `PROMPTS`
3. En `extractor/pipeline.py`, agregar el tipo al dict `resultado` y el extend correspondiente

---

## Decisiones de diseño

### Por qué no pasar todo el texto al LLM directamente

Un documento de 192 páginas tiene ~150,000 tokens. Qwen2.5 14B tiene ventana de contexto de 32k tokens — no cabe. Incluso con modelos de ventana mayor, más contexto = peor calidad de extracción (el modelo pierde foco) y más tiempo de inferencia.

El scorer reduce el input del LLM a ~15,000 tokens en 3-4 llamadas enfocadas. Cada llamada recibe solo el bloque relevante con un prompt específico para ese tipo de contenido.

### Por qué regex y no embeddings para el scorer

Los embeddings requieren un modelo de embedding corriendo localmente (más VRAM), latencia de inferencia por página, y un índice vectorial. Para este problema, regex sobre vocabulario OSCE controlado tiene precisión equivalente a costo cero. Los embeddings agregarían complejidad sin beneficio real.

### Por qué Qwen y no la API de Anthropic/OpenAI

Privacidad absoluta — los documentos de bases de concurso contienen información sensible de procesos de licitación activos. Todo se procesa en el servidor local. Además, costo cero por llamada una vez instalado.

### Por qué `temperature=0`

Este es un task de extracción de información, no generación. Se quiere que el modelo extraiga exactamente lo que dice el documento, sin parafrasear ni "mejorar". Temperatura 0 maximiza el determinismo.

### Por qué `blacklist` es un tipo de señal y no una lista separada

Permite que el `dominant_type` haga una sola decisión comparando todos los scores: si `blacklist` supera al mejor tipo de contenido, la página se descarta. No hay lógica especial — es el mismo mecanismo que cualquier otro tipo.

---

## Limitaciones conocidas

**Señales del scorer:** Si un documento usa terminología inusual o muy específica de un sector (ej: bases de consultoría de salud con términos muy técnicos de infraestructura hospitalaria), puede que algunas señales no disparen. Solución: correr `--dry-run`, identificar qué páginas no se detectan, agregar señales específicas en `config/signals.py`.

**Tablas escaneadas de baja calidad:** Si el OCR produce texto muy ruidoso en las tablas de personal clave, Qwen puede tener dificultad extrayendo valores numéricos (años de colegiado, meses de experiencia). El campo `_meta.page_range` permite ir directamente a esas páginas para verificación manual.

**Documentos con múltiples ítems:** Algunos concursos tienen varios ítems con requisitos distintos. El extractor los agrupa todos en el mismo bloque `rtm_postor`. Qwen los diferencia por ítem en el JSON si el texto lo indica claramente, pero si están mezclados puede haber confusión.

**Sin validación del JSON de Qwen:** Si Qwen devuelve un JSON válido pero con campos incorrectos (ej: `cantidad` como string en vez de número), el pipeline lo pasa igual. La validación con Pydantic está prevista como mejora futura.

---

## Roadmap

### Estado actual
- [x] Parser de `full_text`
- [x] Scorer con señales OSCE
- [x] Agrupador de bloques
- [x] Extracción con Qwen (3 tipos de bloque)
- [x] CLI con `--dry-run`

### Próximos pasos
- [ ] Calibrar señales con 3-5 documentos reales de distintos ministerios
- [ ] Validación de output con Pydantic
- [ ] Script de evaluación: comparar output del extractor contra Excel de referencia del cliente
- [ ] Manejo de documentos con múltiples ítems
- [ ] API REST (FastAPI) para integración con InfoObras Analyzer

### Fuera de scope (este proyecto)
- Segmentación de profesionales en propuestas → es el motor OCR con `mode="full"`
- Evaluación de cumplimiento RTM → es el evaluador (proyecto separado)
- Verificación en InfoObras → es el scraper de InfoObras Analyzer