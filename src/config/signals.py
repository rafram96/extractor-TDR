# ── Señales de scoring ────────────────────────────────────────────────────────
# Vocabulario OSCE regulado por ley — estable entre ministerios y convocatorias

SIGNALS: dict[str, list[tuple[str, float]]] = {

    "rtm_postor": [
        (r"debe acreditar",                            3.0),
        (r"monto facturado",                           3.0),
        (r"experiencia.{0,20}postor",                  2.5),
        (r"obra.{0,20}similar|servicio.{0,20}similar", 2.0),
        (r"no menor de",                               1.5),
        (r"requisito.{0,15}m[ií]nimo",                 1.5),
        (r"descalifica",                               2.0),
        (r"acumulado.{0,20}equivalente",               2.0),
        (r"contrato.{0,30}ejecutad",                   1.0),
    ],

    "rtm_personal": [
        (r"personal clave",                            3.0),
        (r"colegiatur|colegiado",                      2.5),
        (r"habilitad",                                 2.0),
        (r"tiempo de experiencia",                     2.5),
        (r"t[ií]tulo profesional",                     2.0),
        (r"puesto.{0,20}cargo|cargo.{0,20}denominaci", 1.5),
        (r"especialista en",                           1.5),
        (r"jefe de|coordinador|residente",             1.0),
        (r"cant\.",                                    1.0),
        (r"grado.{0,20}t[ií]tulo",                     1.5),
    ],

    "factores_evaluacion": [
        (r"factor.{0,20}evaluaci",                     3.0),
        (r"puntaje.{0,20}m[aá]ximo",                   2.5),
        (r"\d+\s+puntos",                              2.0),
        (r"criterio.{0,20}evaluaci",                   2.0),
        (r"se otorga|se asigna",                       1.5),
        (r"porcentaje.{0,20}personal",                 2.0),
        (r"supere.{0,20}tiempo|supere.{0,20}experiencia", 2.0),
        (r"metodolog.{0,20}asignaci",                  2.0),
    ],

    "blacklist": [
        (r"cl[aá]usula",                               2.5),
        (r"esta secci[oó]n no debe ser modificada",    3.0),
        (r"garant[ií]a.{0,20}fiel cumplimiento",       2.0),
        (r"penalidad",                                 1.5),
        (r"perfeccionamiento del contrato",            2.0),
        (r"disposiciones comunes",                     2.0),
        (r"adelanto directo",                          1.5),
    ],
}

# ── Prompts por tipo de bloque ────────────────────────────────────────────────

PROMPT_RTM_POSTOR = """
Eres un extractor de datos de bases de concurso público peruano (OSCE).
Responde SOLO con JSON válido, sin explicaciones. /no_think

Analiza el siguiente texto de bases de concurso y extrae los requisitos de experiencia
del POSTOR (empresa o consorcio). Solo extrae requisitos del POSTOR, no del personal clave.

INSTRUCCIONES:
- "tipo_experiencia_valida": el tipo de servicio u obra que debe acreditar el postor
  (ej: "ELABORACIÓN DE EXPEDIENTES TÉCNICOS DE OBRAS").
- "sector_valido": especialidad y subespecialidades válidas tal como aparecen en el texto.
- "cita_exacta": copia textual del párrafo donde dice qué debe acreditar el postor.
- "seccion": encabezado de sección donde aparece (ej: "3.4.1 Requisitos de Calificación
  Obligatorios - A. Experiencia del Postor en la Especialidad").
- "experiencia_adicional_factores": si en los FACTORES DE EVALUACIÓN se otorga puntaje
  adicional al postor por superar la experiencia mínima, describe cómo. Si NO existe ese
  factor adicional, escribe exactamente: "No aplica".
- "otros_factores_postor": lista los factores de evaluación que aplican al POSTOR
  (no al personal) con sus puntajes máximos, tal como aparecen en el texto. Si no hay,
  escribe null.

TEXTO:
{texto}

{{
  "items_concurso": [
    {{
      "item": "nombre o número del ítem, null si es único",
      "tipo_experiencia_valida": "descripción del tipo de obra/servicio válido",
      "sector_valido": "especialidad y subespecialidades válidas",
      "cita_exacta": "transcripción literal del requisito de experiencia del postor",
      "seccion": "encabezado de sección donde aparece el requisito",
      "pagina": número de página donde aparece,
      "experiencia_adicional_factores": "descripción o 'No aplica'",
      "otros_factores_postor": "lista de factores con puntajes o null"
    }}
  ]
}}
""".strip()

PROMPT_RTM_PERSONAL = """
Eres un extractor de datos de bases de concurso público peruano (OSCE).
Responde SOLO con JSON válido, sin explicaciones. /no_think

ADVERTENCIA CRÍTICA — TABLAS OCR ENTRELAZADAS:
El texto viene de OCR sobre PDF escaneado. Las tablas multi-columna aparecen con sus
columnas ENTRELAZADAS, no fila por fila. Por ejemplo, para un cargo con 48 meses de
experiencia, el texto puede aparecer así (columnas mezcladas):

  "Jefe y/o Gerente en elaboración de expedientes 48 meses en el Jefe de cargo elaboración
   Título profesional Arquitecto desempeñado del expediente (Computada desde la técnico
   fecha de la colegiatura)"

Para extraer correctamente debes:
1. Buscar el patrón EXACTO "N meses en el cargo desempeñado" — ese N es el tiempo requerido.
2. El cargo que aparece MÁS CERCANO a ese patrón en el texto es el cargo asociado.
3. Los cargos similares válidos son las frases "X y/o Y y/o Z" que aparecen antes del "N meses".

ESTRUCTURA DEL DOCUMENTO:
- Sección B.1 (o "CALIFICACIONES DEL PERSONAL CLAVE"): tabla con Ítem | Cargo | Título | Cant.
  → Da el nombre del cargo y las profesiones aceptadas (títulos). SIN experiencia.
- Sección B.2 (o "EXPERIENCIA DEL PERSONAL CLAVE"): tabla con Cargo | Formación | Experiencia | Tiempo
  → Da los MESES exactos ("48 meses", "36 meses", "24 meses") y los cargos similares válidos.
- Nota (*): define especialidad y subespecialidades válidas para la experiencia.
  → Copia su contenido en "tipo_obra_valido".

REGLA: combina B.1 y B.2 por cargo. Si un campo no está en el texto, usa null. NO inventes.

TEXTO:
{texto}

{{
  "personal_clave": [
    {{
      "cargo": "nombre exacto del cargo según el documento",
      "profesiones_aceptadas": ["lista de profesiones/títulos válidos"],
      "anos_colegiado": null,
      "experiencia_minima": {{
        "cantidad": número entero de meses (busca patrón "N meses en el cargo"),
        "unidad": "meses",
        "descripcion": "transcripción del requisito de experiencia tal como aparece",
        "cargos_similares_validos": ["cargos del tipo X y/o Y y/o Z que aparecen antes del N meses"],
        "puntaje_por_experiencia": número o null,
        "puntaje_maximo": número o null
      }},
      "tipo_obra_valido": "contenido de la nota (*) con especialidad y subespecialidades, o null",
      "tiempo_adicional_factores": null,
      "capacitacion": {{
        "tema": null,
        "tipo": null,
        "duracion_minima_horas": null,
        "es_factor_evaluacion": false
      }},
      "pagina": número de página donde aparece la sección B.2 para este cargo
    }}
  ]
}}
""".strip()

PROMPT_FACTORES = """
Eres un extractor de datos de bases de concurso público peruano (OSCE).
Responde SOLO con JSON válido, sin explicaciones. /no_think

Analiza el siguiente texto y extrae los factores de evaluación.
Enfócate en puntajes, criterios y metodología de asignación.

TEXTO:
{texto}

Extrae esta estructura. Si un campo no aparece, usa null.

{{
  "factores_evaluacion": [
    {{
      "factor": "nombre del factor",
      "aplica_a": "postor" | "personal" | "ambos",
      "cargo_personal": "nombre del cargo si aplica a personal, null si aplica al postor",
      "puntaje_maximo": número,
      "metodologia": "descripción de cómo se asigna el puntaje",
      "pagina": número de página donde aparece
    }}
  ]
}}
""".strip()

PROMPTS: dict[str, str] = {
    "rtm_postor":          PROMPT_RTM_POSTOR,
    "rtm_personal":        PROMPT_RTM_PERSONAL,
    "factores_evaluacion": PROMPT_FACTORES,
}