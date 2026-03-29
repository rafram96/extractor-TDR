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

Analiza el siguiente texto extraído de un documento de bases y extrae
los requisitos de experiencia del POSTOR (empresa/consorcio).

TEXTO:
{texto}

Extrae esta estructura. Si un campo no aparece, usa null.

{{
  "items_concurso": [
    {{
      "item": "nombre o número del ítem, null si es único",
      "tipo_experiencia_valida": "descripción del tipo de obra/servicio válido",
      "sector_valido": "sector (salud, educación, saneamiento, etc.) o null",
      "cita_exacta": "transcripción literal del requisito de experiencia",
      "pagina": número de página donde aparece,
      "experiencia_adicional_factores": "experiencia adicional en factores de evaluación o null",
      "otros_factores_postor": "otros factores de evaluación aplicables al postor o null"
    }}
  ]
}}
""".strip()

PROMPT_RTM_PERSONAL = """
Eres un extractor de datos de bases de concurso público peruano (OSCE).
Responde SOLO con JSON válido, sin explicaciones. /no_think

Analiza el siguiente texto de bases de concurso y extrae los requisitos de PERSONAL CLAVE.
El texto puede tener DOS tablas relacionadas que debes combinar por cargo:

TABLA 1 — Lista de cargos (sección "CALIFICACIONES DEL PERSONAL CLAVE" o similar):
  Columnas: Ítem | Puesto/Cargo | Grado o Título Profesional | Cant.
  → Da el nombre del cargo y las profesiones aceptadas.

TABLA 2 — Experiencia requerida (sección "B.2 EXPERIENCIA DEL PERSONAL CLAVE" o similar):
  Columnas: Ítem | Cargo | Formación académica | Experiencia (cargos válidos) | Tiempo de experiencia
  → Da los meses requeridos, los cargos similares válidos, y la condición de colegiatura.
  → "Tiempo de experiencia" indica los MESES exactos (ej: "48 meses", "36 meses", "24 meses").
  → Puede decir "Computada desde la fecha de la colegiatura" — esto NO es años mínimos de colegiado,
    sino que el conteo de experiencia se inicia desde la colegiatura.

NOTA SOBRE TIPO DE OBRA: busca una nota al pie marcada con (*) que define las especialidades
y subespecialidades válidas para la experiencia. Cópiala en "tipo_obra_valido".

INSTRUCCIONES:
- Si el texto tiene AMBAS tablas, combina la información por cargo (mismo ítem o mismo nombre).
- Si solo hay una tabla, extrae lo que haya. NO inventes datos que no estén en el texto.
- Si un campo genuinamente no aparece, usa null.
- La unidad de experiencia es casi siempre "meses" en bases OSCE — verifica el texto.
- No repitas el mismo cargo dos veces.

TEXTO:
{texto}

{{
  "personal_clave": [
    {{
      "cargo": "nombre exacto del cargo",
      "profesiones_aceptadas": ["lista de profesiones válidas"],
      "anos_colegiado": null,
      "experiencia_minima": {{
        "cantidad": número de meses o años (solo el número),
        "unidad": "meses" | "años" | "participaciones",
        "descripcion": "transcripción literal del requisito de experiencia del cargo",
        "cargos_similares_validos": ["lista de cargos similares aceptados según el documento"],
        "puntaje_por_experiencia": número o null,
        "puntaje_maximo": número o null
      }},
      "tipo_obra_valido": "especialidad y subespecialidades válidas según nota (*) o texto, o null",
      "tiempo_adicional_factores": "tiempo adicional solicitado en factores de evaluación o null",
      "capacitacion": {{
        "tema": "tema de capacitación requerida o null",
        "tipo": "curso | diplomado | especialización | maestría | null",
        "duracion_minima_horas": número o null,
        "es_factor_evaluacion": true | false
      }},
      "pagina": número de página donde aparece la información de experiencia
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