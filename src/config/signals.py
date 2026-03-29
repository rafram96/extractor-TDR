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

Analiza el siguiente texto y extrae los requisitos de PERSONAL CLAVE.
No omitas ningún profesional. Si un profesional tiene múltiples requisitos,
crea una fila por requisito.

TEXTO:
{texto}

Extrae esta estructura. Si un campo no aparece, usa null.

{{
  "personal_clave": [
    {{
      "cargo": "nombre exacto del cargo",
      "profesiones_aceptadas": ["lista de profesiones válidas"],
      "anos_colegiado": número entero o null,
      "experiencia_minima": {{
        "cantidad": número,
        "unidad": "meses" | "años" | "participaciones",
        "descripcion": "descripción completa del requisito",
        "cargos_similares_validos": ["lista de cargos similares aceptados"],
        "puntaje_por_experiencia": número o null,
        "puntaje_maximo": número o null
      }},
      "tipo_obra_valido": "tipo de obra o servicio válido o null",
      "tiempo_adicional_factores": "tiempo adicional en factores de evaluación o null",
      "capacitacion": {{
        "tema": "tema de la capacitación",
        "tipo": "curso | diplomado | especialización | etc.",
        "duracion_minima_horas": número o null,
        "es_factor_evaluacion": true | false
      }},
      "pagina": número de página donde aparece
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