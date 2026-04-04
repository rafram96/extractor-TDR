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
        # "declaración jurada" aparece también en referencias — peso moderado
        (r"declaraci[oó]n jurada",                     1.5),
        # Señales estructurales de páginas que SON un anexo (formulario vacío)
        (r"firma\s+(?:y\s+)?sello",                    2.5),  # pie de formulario
        (r"datos\s+del\s+postor",                      2.0),  # cabecera de formulario
        (r"denominaci[oó]n.{0,60}monto.{0,60}fecha",  3.0),  # encabezados de tabla vacía
        (r"declaraci[oó]n\s+jurada\s+de\s+.{0,60}(?:experiencia|proveedor|ejecutor|postor)", 3.0),
        (r"estructura de costos",                      3.0),
        (r"precio de la oferta",                       2.5),
        (r"promesa de consorcio",                      2.5),
        (r"elecci[oó]n de instituci[oó]n arbitral",    2.5),
        (r"constancia de capacidad",                   1.5),
        (r"señores\s+evaluadores",                     1.5),
        (r"presente\.?-",                              1.5),
        (r"consignar seg[uú]n corresponda",            2.0),

        # ── Secciones de contrato / perfeccionamiento ──
        # Ruido: "personal clave" aparece en contexto contractual, no RTM
        (r"postor ganador de la buena pro",            2.5),
        (r"mesa de partes",                            2.0),
        (r"firma.{0,10}digital",                       1.5),
        (r"plazo.{0,20}art[ií]culo.{0,10}\d+.{0,15}reglamento", 2.0),
        (r"suscripci[oó]n del contrato",               2.0),
        (r"cuenta.{0,10}interbancaria",                2.0),

        # ── Intro genérica del procedimiento de selección ──
        # Ruido: "factor evaluación" aparece describiendo el proceso, no los factores
        (r"sin precalificaci[oó]n",                    3.0),
        (r"admisi[oó]n de.{0,20}ofertas",              2.0),
        (r"evaluaci[oó]n de ofertas econ[oó]micas",    2.5),
        (r"pladicop",                                  2.0),
        (r"puntaje m[ií]nimo.{0,20}evaluaci[oó]n t[eé]cnica", 2.0),

        # ── Entregables / especificaciones técnicas del TDR ──
        # Ruido: "personal clave" aparece como entregable, no como requisito
        (r"el consultor deber[aá]",                    2.0),
        (r"el contratista deber[aá]",                  2.0),
        (r"plan de trabajo",                           1.5),
        (r"plan de ejecuci[oó]n bim",                  2.0),
        (r"entregable",                                1.5),
        (r"informe quincenal",                         1.5),

        # ── Anexos / formularios vacíos ──
        # Ruido: anexos tienen "personal clave" y "experiencia" en encabezados
        (r"anexo\s+n[°º]\s*\d+",                      2.5),
        (r"formato\s+n[°º]\s*\d+",                     2.5),
        (r"modelo\s+de\s+carta",                       2.0),

        # ── Personal NO clave ──
        # Ruido: tablas de asistentes/bachilleres disparan señales de rtm_personal
        (r"personal no clave",                         3.0),
        (r"asistente\s+(?:de|en)\s+\w",                2.0),
        (r"bachiller\s+en",                            2.0),
        (r"contabilizada desde la emisi[oó]n del grado", 2.5),
    ],

    # ── Capacitación del personal clave ──
    # Tabla separada (usualmente en sección A del TDR) con cursos/diplomas por cargo
    "capacitacion": [
        (r"capacitaci[oó]n.{0,30}personal clave",     4.0),
        (r"capacitaci[oó]n requerida",                 3.0),
        (r"programa y/o curso y/o diplomado",          3.0),
        (r"especializaci[oó]n.{0,20}m[ií]n",           2.5),
        (r"duraci[oó]n m[ií]nima.{0,20}horas",          2.5),
        (r"horas acad[eé]micas",                        2.0),
        (r"\d+\s*horas?\s*acad[eé]micas",               2.5),
        (r"curso de especializaci[oó]n",                2.0),
    ],
}

# ── Prompts por tipo de bloque ────────────────────────────────────────────────

PROMPT_RTM_POSTOR = """
Eres un extractor de datos de bases de concurso público peruano (OSCE).
Responde SOLO con JSON válido, sin explicaciones. /no_think

Analiza el siguiente texto de bases de concurso y extrae los requisitos de experiencia
del POSTOR (empresa o consorcio). Solo extrae requisitos del POSTOR, no del personal clave.

REGLA CRÍTICA:
- Si el texto NO contiene requisitos de experiencia del postor (secciones como "Experiencia
  del Postor en la Especialidad", montos facturados, especialidades válidas), responde:
  {{"items_concurso": []}}
- NUNCA inventes datos, ejemplos ni plantillas. NO uses frases como "podría ser" o "ejemplo".
- Solo extrae información que REALMENTE aparece en el texto proporcionado.

INSTRUCCIONES (solo si encuentras requisitos reales):
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

REGLA CRÍTICA:
- Si el texto NO contiene NINGUNA información sobre personal clave (ni cargos, ni profesiones,
  ni experiencia), responde: {{"personal_clave": []}}
- Si encuentras datos PARCIALES (ej: tabla con cargos y profesiones pero sin datos de experiencia,
  o viceversa), extrae lo que haya y deja los campos faltantes como null.
  Esto es importante: una tabla B.1 sin B.2 DEBE extraerse con experiencia en null.
- NUNCA inventes datos, ejemplos ni plantillas. NO uses frases como "podría ser" o "ejemplo".
- Solo extrae información que REALMENTE aparece en el texto proporcionado.
- Extrae TODOS los cargos que encuentres, no solo algunos.

ADVERTENCIA — TABLAS OCR ENTRELAZADAS:
El texto viene de OCR sobre PDF escaneado. Las tablas multi-columna aparecen con sus
columnas ENTRELAZADAS, no fila por fila. Por ejemplo, para un cargo con 48 meses de
experiencia, el texto puede aparecer así (columnas mezcladas):

  "Jefe y/o Gerente en elaboración de expedientes 48 meses en el Jefe de cargo elaboración
   Título profesional Arquitecto desempeñado del expediente (Computada desde la técnico
   fecha de la colegiatura)"

Para extraer correctamente debes:
1. Buscar TODOS los patrones "N meses en el cargo" — cada uno corresponde a un profesional.
2. El cargo que aparece MÁS CERCANO a ese patrón en el texto es el cargo asociado.
3. Los cargos similares válidos son las frases "X y/o Y y/o Z" que aparecen antes del "N meses".
4. Si ves "24 meses en el cargo desempeñado" repetido varias veces, cada uno es un cargo DIFERENTE.

ESTRUCTURA DEL DOCUMENTO:
- Sección B.1 (o "CALIFICACIONES DEL PERSONAL CLAVE"): tabla con Ítem | Cargo | Título | Cant.
  → Da el nombre del cargo y las profesiones aceptadas (títulos). SIN experiencia.
- Sección B.2 (o "EXPERIENCIA DEL PERSONAL CLAVE"): tabla con Cargo | Formación | Experiencia | Tiempo
  → Da los MESES exactos ("48 meses", "36 meses", "24 meses") y los cargos similares válidos.
- Nota (*): define especialidad y subespecialidades válidas para la experiencia.
  → Copia su contenido en "tipo_obra_valido".

REGLA: combina B.1 y B.2 por cargo. Si un campo no está en el texto, usa null. NO inventes.

EXTRACCIÓN DE TIEMPO DE COLEGIADO (anos_colegiado):
- Busca patrones como "N meses" cerca de "colegiatura", "colegiado", "Computada desde la fecha
  de la colegiatura", o en columnas de la tabla etiquetadas "Tiempo de Colegiado".
- El OCR puede fragmentarlo: "48 meses (Computada desde la fecha de la colegiatura)"
  o "Tiempo mín. de colegiatura: 36 meses".
- Extrae el STRING completo incluyendo la unidad, ej: "48 meses", "36 meses", "24 meses".

EXTRACCIÓN DE CAPACITACIÓN (capacitacion):
- Busca patrones como "Programa", "Curso", "Diplomado", "Especialización" seguido de
  "(mín. Xh)" o "(mínimo X horas)" y luego el tema.
- Ejemplo OCR: "Prog./Curso/Dipl. (mín. 60h) en Gestión de Proyectos, Expedientes Técnicos"
  → tema: "Gestión de Proyectos, Expedientes Técnicos, ...", tipo: "Programa/Curso/Diplomado",
    duracion_minima_horas: 60
- Ejemplo OCR: "Especialización (mín. 120h) en Gestión BIM, BIM Management"
  → tema: "Gestión BIM, BIM Management, ...", tipo: "Especialización",
    duracion_minima_horas: 120
- El campo "tipo" es la categoría: "Programa/Curso/Diplomado" o "Especialización".
- Si la capacitación solo se exige como RTM (sin puntaje extra), es_factor_evaluacion = false.

TEXTO:
{texto}

{{
  "personal_clave": [
    {{
      "cargo": "nombre exacto del cargo según el documento",
      "profesiones_aceptadas": ["lista de profesiones/títulos válidos"],
      "anos_colegiado": "N meses (texto tal como aparece, ej: '48 meses')",
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
        "tema": "tema(s) de la capacitación tal como aparecen en el texto",
        "tipo": "Programa/Curso/Diplomado o Especialización",
        "duracion_minima_horas": número entero de horas mínimas,
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

REGLA CRÍTICA:
- Solo extrae factores que tengan un PUNTAJE MÁXIMO explícito (ej: "60 puntos", "5 puntos").
- Si el texto NO contiene factores de evaluación con puntajes, responde:
  {{"factores_evaluacion": []}}
- NUNCA inventes datos, ejemplos ni plantillas.
- Descripciones genéricas del proceso de evaluación (ej: "se aplica evaluación técnica")
  NO son factores — solo extrae factores con puntajes concretos.

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

PROMPT_CAPACITACION = """
Eres un extractor de datos de bases de concurso público peruano (OSCE).
Responde SOLO con JSON válido, sin explicaciones. /no_think

Analiza el siguiente texto y extrae los requisitos de CAPACITACIÓN del personal clave.
Busca la sección "Capacitación del personal clave" o tabla similar que liste qué
cursos/diplomados/especializaciones necesita cada cargo.

REGLA CRÍTICA:
- Si el texto NO contiene requisitos de capacitación del personal clave, responde:
  {{"capacitaciones": []}}
- NUNCA inventes datos. Solo extrae lo que REALMENTE aparece en el texto.
- Ignora completamente el personal NO clave (asistentes, bachilleres).

ADVERTENCIA — TEXTO OCR FRAGMENTADO:
El texto viene de OCR y puede estar fragmentado. Busca estos patrones:
- "Programa y/o Curso y/o Diplomado" seguido de "(mín. Xh)" o "duración mínima de X horas"
- "Especialización" seguido de horas mínimas
- El cargo aparece CERCA del requisito de capacitación

Ejemplo OCR fragmentado:
  "Programa y/o Curso y/o Diplomado y/o Curso de
   Especialización, con una duración mínima de 60 horas
   Jefe de elaboración del expediente técnico
   Gestión de Proyectos y/o Expedientes Técnicos"

Extracción: cargo="Jefe de elaboración del expediente técnico",
  tipo="Programa/Curso/Diplomado/Especialización", horas=60,
  tema="Gestión de Proyectos, Expedientes Técnicos"

TEXTO:
{texto}

{{
  "capacitaciones": [
    {{
      "cargo": "nombre del cargo tal como aparece",
      "tipo": "Programa/Curso/Diplomado o Especialización",
      "duracion_minima_horas": número entero de horas,
      "tema": "tema(s) de la capacitación",
      "pagina": número de página donde aparece
    }}
  ]
}}
""".strip()

PROMPTS: dict[str, str] = {
    "rtm_postor":          PROMPT_RTM_POSTOR,
    "rtm_personal":        PROMPT_RTM_PERSONAL,
    "factores_evaluacion": PROMPT_FACTORES,
    "capacitacion":        PROMPT_CAPACITACION,
}