"""
Prompts para extracción de criterios TDR con LLM.

Usa qwen2.5:14b con temperatura 0 para extracciones determinísticas.
Prompts diseñados con reglas de prioridad y ejemplos resueltos
para maximizar la precisión de extracción.
"""

# ─── PROMPT: EXTRACCIÓN DE CARGOS / PROFESIONALES ────────────────────────────

PROMPT_EXTRACT_CARGOS = """Del texto de las BASES DE CONCURSO, extrae TODOS los cargos profesionales solicitados.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
PASO 1 — IDENTIFICA los cargos del plantel profesional clave:
  Busca secciones como "REQUISITOS TÉCNICOS MÍNIMOS", "PERSONAL CLAVE",
  "PLANTEL PROFESIONAL", "EQUIPO TÉCNICO", "FACTORES DE EVALUACIÓN".
  Cada cargo listado ahí es una entrada en tu respuesta.

  Cargos típicos (no limitativo):
  → Jefe de Supervisión / Jefe de Proyecto
  → Supervisor/Especialista en Arquitectura
  → Supervisor/Especialista en Estructuras
  → Supervisor/Especialista en Instalaciones Eléctricas
  → Supervisor/Especialista en Instalaciones Sanitarias
  → Supervisor/Especialista en Instalaciones Mecánicas
  → Supervisor/Especialista en Metrados y Valorizaciones
  → Supervisor/Especialista en Seguridad y Salud
  → Supervisor de Control de Calidad
  → Especialista Ambiental
  → Otros que aparezcan

PASO 2 — Para CADA cargo, extrae estos campos:
  - cargo: nombre exacto del cargo como aparece en las bases
  - profesion_requerida: profesiones aceptadas (ej: "Ingeniero Civil y/o Arquitecto")
  - anos_minimos_colegiado: años mínimos de colegiatura (número entero, 0 si no dice)
  - anos_minimos_experiencia: años mínimos de experiencia general o específica (número entero)
  - tipos_obra_validos: lista de tipos de obra que califican (ej: ["salud", "hospitalaria", "vivienda"])
  - cargos_similares_validos: lista de cargos equivalentes aceptados (ej: ["Jefe de Supervisión", "Jefe de Obra", "Director de Obra"])
  - requisito_minimo_detallado: COPIAR TEXTUALMENTE lo que dicen las bases sobre el requisito mínimo de experiencia para este cargo. NO resumir. Incluir número de participaciones, años, tipo de obra, montos si los hay.
  - puntuacion_experiencia: texto sobre la puntuación asignada por experiencia adicional, si existe en factores de evaluación. Incluir puntaje por experiencia y puntaje máximo.
  - capacitacion_solicitada: capacitaciones, cursos, diplomados solicitados (tipo y horas si se indican). Vacío si no aplica.
  - tiempo_adicional_evaluacion: experiencia adicional solicitada en FACTORES DE EVALUACIÓN (más allá del mínimo). Vacío si no aplica.
  - otros_factores_evaluacion: cualquier otro factor de evaluación mencionado para este cargo.

PASO 3 — REGLAS DE PRIORIDAD:
  - Si un cargo aparece tanto en RTM como en Factores de Evaluación, COMBINAR la info en una sola entrada.
  - Si dice "Ingeniero Civil y/o Arquitecto", poner AMBAS profesiones en profesion_requerida.
  - Si dice "experiencia mínima de 3 participaciones" → anos_minimos_experiencia = 3, y en requisito_minimo_detallado copiar el texto completo.
  - NO OMITIR ningún profesional clave. Si hay 10 cargos, deben ser 10 entradas.
  - Si no se especifica un campo, devolver string vacío "" o 0 para números.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
EJEMPLOS RESUELTOS:

Texto: "Jefe de Supervisión: Ingeniero Civil colegiado, con 10 años de colegiatura mínima, experiencia mínima de 3 supervisiones de obras hospitalarias mayores a S/ 10,000,000. Se otorgará 5 puntos por cada supervisión adicional hasta un máximo de 15 puntos."
→ {{
    "cargo": "Jefe de Supervisión",
    "profesion_requerida": "Ingeniero Civil",
    "anos_minimos_colegiado": 10,
    "anos_minimos_experiencia": 3,
    "tipos_obra_validos": ["hospitalaria", "salud"],
    "cargos_similares_validos": ["Jefe de Supervisión", "Jefe de Obra"],
    "requisito_minimo_detallado": "Experiencia mínima de 3 supervisiones de obras hospitalarias mayores a S/ 10,000,000",
    "puntuacion_experiencia": "5 puntos por cada supervisión adicional, máximo 15 puntos",
    "capacitacion_solicitada": "",
    "tiempo_adicional_evaluacion": "",
    "otros_factores_evaluacion": ""
  }}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
REGLA CRÍTICA: Devuelve ÚNICAMENTE el JSON, sin texto antes ni después.

{{
  "cargos": [
    {{
      "cargo": "string",
      "profesion_requerida": "string",
      "anos_minimos_colegiado": 0,
      "anos_minimos_experiencia": 0,
      "tipos_obra_validos": ["string"],
      "cargos_similares_validos": ["string"],
      "requisito_minimo_detallado": "string TEXTUAL de las bases",
      "puntuacion_experiencia": "string",
      "capacitacion_solicitada": "string",
      "tiempo_adicional_evaluacion": "string",
      "otros_factores_evaluacion": "string"
    }}
  ]
}}

TEXTO BASES:
{texto}"""


# ─── PROMPT: EXTRACCIÓN DE EXPERIENCIA DEL POSTOR ────────────────────────────

PROMPT_EXTRACT_EXPERIENCIAS = """Del texto de las BASES DE CONCURSO, extrae los requisitos de EXPERIENCIA DEL POSTOR (empresa/consorcio).

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
PASO 1 — IDENTIFICA las secciones de experiencia del postor:
  Busca secciones como "EXPERIENCIA DEL POSTOR EN LA ESPECIALIDAD",
  "REQUISITOS TÉCNICOS MÍNIMOS - A", "3.4.1", "FACTORES DE EVALUACIÓN".
  Cada ÍTEM del concurso puede tener sus propios requisitos.

PASO 2 — Para CADA requisito de experiencia, extrae:
  - tipo_experiencia: tipo de experiencia válida (ej: "Supervisión de obras", "Ejecución de obras")
  - sector_valido: sector o tipo de obra (ej: "Salud", "Vivienda", "Hospitalaria")
  - descripcion_exacta: COPIAR TEXTUALMENTE lo que dicen las bases. NO resumir. Incluir montos, cantidades, porcentajes.
  - experiencia_adicional: experiencia adicional solicitada en FACTORES DE EVALUACIÓN (más allá del mínimo)
  - otros_factores: cualquier otro factor de evaluación del postor (equipamiento, metodología, etc.)

PASO 3 — REGLAS:
  - Si hay múltiples ítems, crear una entrada por cada ítem.
  - Si la experiencia aparece tanto en RTM como en Factores de Evaluación, combinar en una entrada.
  - COPIAR TEXTUALMENTE: no resumir, no parafrasear. Si dice "1.5 veces el valor referencial", escribir exactamente eso.
  - Incluir montos, porcentajes, número de contratos si se mencionan.
  - Si no se especifica un campo, devolver string vacío "".

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
EJEMPLOS RESUELTOS:

Texto: "El postor debe acreditar experiencia en supervisión de obras de salud o similares por un monto mínimo de 1.5 veces el valor referencial. Se otorgará 10 puntos por cada S/ 1,000,000 adicional hasta un máximo de 30 puntos."
→ {{
    "tipo_experiencia": "Supervisión de obras",
    "sector_valido": "Salud",
    "descripcion_exacta": "El postor debe acreditar experiencia en supervisión de obras de salud o similares por un monto mínimo de 1.5 veces el valor referencial",
    "experiencia_adicional": "Se otorgará 10 puntos por cada S/ 1,000,000 adicional hasta un máximo de 30 puntos",
    "otros_factores": ""
  }}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
REGLA CRÍTICA: Devuelve ÚNICAMENTE el JSON, sin texto antes ni después.

{{
  "experiencias": [
    {{
      "tipo_experiencia": "string",
      "sector_valido": "string",
      "descripcion_exacta": "string TEXTUAL de las bases",
      "experiencia_adicional": "string",
      "otros_factores": "string"
    }}
  ]
}}

TEXTO BASES:
{texto}"""


# ─── FUNCIONES AUXILIARES ─────────────────────────────────────────────────────

def format_prompt_cargos(texto: str) -> str:
    """Formatea prompt para extracción de cargos."""
    return PROMPT_EXTRACT_CARGOS.format(texto=texto)


def format_prompt_experiencias(texto: str) -> str:
    """Formatea prompt para extracción de experiencias."""
    return PROMPT_EXTRACT_EXPERIENCIAS.format(texto=texto)
