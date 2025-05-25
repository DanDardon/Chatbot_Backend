import re
import wikipedia
from backend.database import get_connection
from collections import defaultdict

contextos = defaultdict(lambda: {
    "saludo_hecho": False,
    "ultimo_sintoma": None,
    "enfermedades_reportadas": set(),
    "sintomas_reportados": [],
    "esperando_enfermedad": False,
    "enfermedad_propuesta": None,
    "esperando_medicamento": False
})

# Contexto de conversación temporal en memoria
ultimo_contexto = {
    "enfermedad": None,
    "saludo_hecho": False,
    "ultimo_sintoma": None,
    "sugerencia_dada": False
}

estado_enseñanza = {
    "esperando_enfermedad": False,
    "sintoma_reportado": None,
    "enfermedad_propuesta": None,
    "esperando_medicamento": False
}

consejos_generales = [
    "Recuerda mantenerte hidratado y descansar lo suficiente. 💧😴",
    "Evita automedicarte y consulta a un médico si los síntomas persisten. 🩺",
    "Lávate las manos frecuentemente y evita tocarte la cara. 🧼🤲",
    "Una alimentación balanceada puede ayudar a fortalecer tu sistema inmune. 🥦🍊"
]

def procesar_mensaje(mensaje):
    mensaje_lower = mensaje.lower().strip()
    print("📝 Texto del usuario:", mensaje)

    # Manejo de saludos comunes
    saludos = ["hola", "buenos días", "buenas tardes", "buenas noches"]
    despedidas = ["adiós", "hasta luego", "nos vemos", "bye"]
    agradecimientos = ["gracias", "muchas gracias", "te lo agradezco"]

    if any(saludo in mensaje_lower for saludo in saludos):
        if not ultimo_contexto.get("saludo_hecho", False):
            ultimo_contexto["saludo_hecho"] = True
            if ultimo_contexto["ultimo_sintoma"]:
                return f"¡Hola de nuevo! ¿Cómo sigues del {ultimo_contexto['ultimo_sintoma']}? 😊"
            else:
                return "¡Hola! ¿Cómo te sientes hoy? 😊"
        else:
            return "¡Ya estamos en contacto! ¿Cómo puedo ayudarte ahora? 😉"

    if any(gracias in mensaje_lower for gracias in agradecimientos):
        ultimo_contexto.clear()
        ultimo_contexto.update({
            "saludo_hecho": False,
            "ultimo_sintoma": None
        })

        estado_enseñanza.clear()
        estado_enseñanza.update({
            "esperando_enfermedad": False,
            "enfermedad_propuesta": None,
            "esperando_medicamento": False
        })
    
        return "¡De nada! 😊 Si necesitas algo más, aquí estaré."


    # Aprendizaje: enfermedad propuesta
    if estado_enseñanza["esperando_enfermedad"]:
        enfermedad = mensaje.strip().capitalize()
        estado_enseñanza["enfermedad_propuesta"] = enfermedad
        estado_enseñanza["esperando_enfermedad"] = False
        estado_enseñanza["esperando_medicamento"] = True

        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT ID_ENFERMEDAD FROM ENFERMEDADES WHERE LOWER(NOMBRE) = :1", [enfermedad.lower()])
        row = cursor.fetchone()
        if not row:
            cursor.execute("SELECT MAX(ID_ENFERMEDAD) FROM ENFERMEDADES")
            nuevo_id = (cursor.fetchone()[0] or 0) + 1
            cursor.execute("INSERT INTO ENFERMEDADES (ID_ENFERMEDAD, NOMBRE, DESCRIPCION) VALUES (:1, :2, :3)",
                           [nuevo_id, enfermedad, "Enfermedad aprendida por retroalimentación."])
            conn.commit()
        conn.close()

        return "¡Gracias por compartirlo! ¿Recuerdas qué medicamento tomaste y cómo lo usaste? Algo como: nombre, dosis, cada cuántas horas y por cuántos días. 🙏"

    # Aprendizaje: medicamento asociado
    if estado_enseñanza["esperando_medicamento"]:
        partes = mensaje.split(",")
        if len(partes) < 4:
            return "Por favor, indica el medicamento en este formato: nombre, dosis, frecuencia, duración."

        nombre = partes[0].strip().capitalize()
        dosis = partes[1].strip()
        frecuencia = partes[2].strip()
        duracion = partes[3].strip()
        enfermedad = estado_enseñanza["enfermedad_propuesta"]
        sintoma = estado_enseñanza["sintoma_reportado"]

        conn = get_connection()
        cursor = conn.cursor()

        cursor.execute("SELECT ID_MEDICAMENTO FROM MEDICAMENTOS WHERE LOWER(NOMBRE) = :1", [nombre.lower()])
        row = cursor.fetchone()
        if row:
            id_medicamento = row[0]
        else:
            cursor.execute("SELECT MAX(ID_MEDICAMENTO) FROM MEDICAMENTOS")
            id_medicamento = (cursor.fetchone()[0] or 0) + 1
            cursor.execute("INSERT INTO MEDICAMENTOS (ID_MEDICAMENTO, NOMBRE) VALUES (:1, :2)", [id_medicamento, nombre])

        cursor.execute("SELECT ID_ENFERMEDAD FROM ENFERMEDADES WHERE LOWER(NOMBRE) = :1", [enfermedad.lower()])
        id_enfermedad = cursor.fetchone()[0]

        cursor.execute("INSERT INTO RECOMENDACIONES (ID_ENFERMEDAD, ID_MEDICAMENTO, DOSIS, DURACION) VALUES (:1, :2, :3, :4)",
                       [id_enfermedad, id_medicamento, f"{dosis} cada {frecuencia}", duracion])

        cursor.execute("SELECT ID_SINTOMA FROM SINTOMAS WHERE LOWER(NOMBRE) = :1", [sintoma.lower()])
        row = cursor.fetchone()
        if row:
            id_sintoma = row[0]
        else:
            cursor.execute("SELECT MAX(ID_SINTOMA) FROM SINTOMAS")
            id_sintoma = (cursor.fetchone()[0] or 0) + 1
            cursor.execute("INSERT INTO SINTOMAS (ID_SINTOMA, NOMBRE) VALUES (:1, :2)", [id_sintoma, sintoma])

        # Agregar variantes del síntoma como sinónimos aprendidos
        variantes = list(set([
            sintoma.lower(),
            estado_enseñanza["sintoma_reportado"].lower(),
            f"tengo {sintoma.lower()}",
            f"me da {sintoma.lower()}",
            f"siento {sintoma.lower()}",
            f"presento {sintoma.lower()}",
            f"experimento {sintoma.lower()}"
        ]))

        cursor.execute("SELECT MAX(ID) FROM SINONIMOS_SINTOMAS")
        last_id = cursor.fetchone()[0] or 0

        for i, sinonimo in enumerate(variantes, start=1):
            cursor.execute("""
                INSERT INTO SINONIMOS_SINTOMAS (ID, ID_SINTOMA, SINONIMO)
                VALUES (:1, :2, :3)
            """, [last_id + i, id_sintoma, sinonimo])

        cursor.execute("SELECT MAX(ID_REGLA) FROM REGLAS_INFERENCIA")
        id_regla = (cursor.fetchone()[0] or 0) + 1
        cursor.execute("INSERT INTO REGLAS_INFERENCIA (ID_REGLA, ID_ENFERMEDAD, ID_SINTOMA, PESO) VALUES (:1, :2, :3, :4)",
                       [id_regla, id_enfermedad, id_sintoma, 0.75])

        conn.commit()
        conn.close()

        estado_enseñanza.update({
            "esperando_medicamento": False,
            "sintoma_reportado": None,
            "enfermedad_propuesta": None
        })

        return f"¡Genial! He aprendido que cuando alguien menciona '{sintoma.lower()}', podría tratarse de *{enfermedad}*, y podría recomendar *{nombre}*. ¡Gracias por enseñarme! 🧠💊"

    # 🔍 Consultas sobre medicamentos
    if re.search(r'(qué puedo tomar|qué medicamento|cuál es el tratamiento)', mensaje_lower):
        enfermedad = extraer_nombre_enfermedad(mensaje) or ultimo_contexto.get("enfermedad")
        if not enfermedad:
            return "Por favor, dime primero qué enfermedad tienes."
        return obtener_recomendacion_medicamento(enfermedad)

    # 🤖 Preguntas tipo "¿Qué es...?"
    if re.search(r'¿?(que|qué|cuales|cuáles|explica|explícame)\b.*\b(es|son|sobre)\b', mensaje_lower):
        resumen = intentar_busqueda_externa(mensaje)
        if resumen:
            nombre_enf = extraer_nombre_enfermedad(mensaje)
            if nombre_enf:
                guardar_enfermedad(nombre_enf, resumen)
                ultimo_contexto['enfermedad'] = nombre_enf
                return f"🧠 He aprendido sobre '{nombre_enf}' y lo he guardado en la base de datos.\n\n{resumen}"
            else:
                return resumen
        else:
            return "No se encontró información sobre eso en Wikipedia."

    # 🩺 Procesamiento de síntomas
    sintomas_detectados = detectar_sintomas(mensaje)
    print("🔍 Síntomas detectados:", sintomas_detectados)

    if not sintomas_detectados:
        estado_enseñanza["sintoma_reportado"] = mensaje
        estado_enseñanza["esperando_enfermedad"] = True
        return "Hmm, aún no reconozco lo que estás sintiendo... ¿Te diagnosticaron con alguna enfermedad en ese momento? Puedo aprender de eso. 😊"

    if len(sintomas_detectados) == 1:
        sugerencias_relacionadas = {
            "fiebre": ["dolor de cabeza", "escalofríos", "fatiga"],
            "dolor abdominal": ["náuseas", "vómitos", "diarrea"],
            "tos": ["dolor de garganta", "congestión nasal", "fiebre"],
            "dolor de garganta": ["tos", "fiebre", "congestión nasal"],
            "mareos": ["náuseas", "fatiga", "dolor de cabeza"]
        }

        # después de if len(sintomas_detectados) == 1:
        sintoma_unico = sintomas_detectados[0]

        if sintoma_unico in sugerencias_relacionadas:
            if "sugerencia_dada" not in ultimo_contexto or not ultimo_contexto["sugerencia_dada"]:
                ultimo_contexto["sugerencia_dada"] = True
                sugerencias = sugerencias_relacionadas[sintoma_unico]
                return f"Además de {sintoma_unico}, ¿también tienes {' o '.join(sugerencias)}?"
            else:
                # ya se sugirió antes, seguir con la lógica normal
                pass

    conn = get_connection()
    if not conn:
        return "No se pudo establecer conexión con la base de datos."
    cursor = conn.cursor()

    cursor.execute("ALTER SESSION SET NLS_COMP = LINGUISTIC")
    cursor.execute("ALTER SESSION SET NLS_SORT = BINARY_CI")

    puntajes = {}
    sintomas_utilizados = []

    for sintoma_detectado in sintomas_detectados:
        sintoma_detectado = sintoma_detectado.lower()
        like_pattern = f"%{sintoma_detectado}%"
        cursor.execute("SELECT ID_SINTOMA FROM SINTOMAS WHERE LOWER(NOMBRE) LIKE :1", [like_pattern])
        row = cursor.fetchone()
        if row:
            id_sintoma = row[0]
            sintomas_utilizados.append((sintoma_detectado, id_sintoma))
            cursor.execute("SELECT ID_ENFERMEDAD, PESO FROM REGLAS_INFERENCIA WHERE ID_SINTOMA = :1", [id_sintoma])
            reglas = cursor.fetchall()
            for id_enfermedad, peso in reglas:
                puntajes[id_enfermedad] = puntajes.get(id_enfermedad, 0) + peso

    if not puntajes and sintomas_utilizados:
        conn = get_connection()
        cursor = conn.cursor()

    # Crear una enfermedad genérica si no se tiene contexto previo
    enfermedad_generica = "Condición relacionada a " + sintomas_utilizados[0][0]
    cursor.execute("SELECT ID_ENFERMEDAD FROM ENFERMEDADES WHERE LOWER(NOMBRE) = :1", [enfermedad_generica.lower()])
    row = cursor.fetchone()
    if row:
        id_enfermedad = row[0]
    else:
        cursor.execute("SELECT MAX(ID_ENFERMEDAD) FROM ENFERMEDADES")
        id_enfermedad = (cursor.fetchone()[0] or 0) + 1
        cursor.execute("INSERT INTO ENFERMEDADES (ID_ENFERMEDAD, NOMBRE, DESCRIPCION) VALUES (:1, :2, :3)",
                       [id_enfermedad, enfermedad_generica, "Enfermedad generada automáticamente por el agente."])

    # Insertar regla por cada síntoma detectado
    cursor.execute("SELECT MAX(ID_REGLA) FROM REGLAS_INFERENCIA")
    id_regla_base = cursor.fetchone()[0] or 0

    for i, (_, id_sintoma) in enumerate(sintomas_utilizados):
        cursor.execute("INSERT INTO REGLAS_INFERENCIA (ID_REGLA, ID_ENFERMEDAD, ID_SINTOMA, PESO) VALUES (:1, :2, :3, :4)",
                       [id_regla_base + i + 1, id_enfermedad, id_sintoma, 0.5])

    conn.commit()
    conn.close()

    # Intentar inmediatamente un nuevo análisis con los síntomas detectados
    return f"No encontré una enfermedad asociada, pero he aprendido una relación para futuros casos con '{sintomas_utilizados[0][0]}'. Por favor intenta hacer una nueva consulta para aplicar lo que aprendí. 🧠"

    mejor_id = max(puntajes.items(), key=lambda x: x[1])[0]
    cursor.execute("SELECT NOMBRE, DESCRIPCION FROM ENFERMEDADES WHERE ID_ENFERMEDAD = :1", [mejor_id])
    row = cursor.fetchone()
    if not row or not row[0]:
        conn.close()
        return "Se identificó una enfermedad, pero no se pudo recuperar su información."

    enfermedad = row[0]
    descripcion_limpia = row[1].read() if hasattr(row[1], 'read') else row[1]
    descripcion_limpia = descripcion_limpia.replace("Enfermedad aprendida por retroalimentación.", "").strip()

    ultimo_contexto["enfermedad"] = enfermedad


    cursor.execute("""SELECT M.NOMBRE, R.DOSIS, R.DURACION
                      FROM RECOMENDACIONES R
                      JOIN MEDICAMENTOS M ON R.ID_MEDICAMENTO = M.ID_MEDICAMENTO
                      WHERE R.ID_ENFERMEDAD = :1""", [mejor_id])
    med = cursor.fetchone()
    conn.close()

    sintomas_str = ", ".join(sorted(set(s for s, _ in sintomas_utilizados)))
    respuesta = f"Según los síntomas que mencionas ({sintomas_str}), podrías estar presentando *{enfermedad}*. {descripcion_limpia}"

    if med:
        nombre, dosis, duracion = med
        respuesta += f" Se recomienda el medicamento {nombre}, con una dosis de {dosis}, durante {duracion}."
    else:
        respuesta += " Por el momento, no tengo una recomendación específica de medicamento para esto."

    respuesta = f"Según los síntomas que mencionas ({sintomas_str}), podrías estar presentando *{enfermedad}*. {descripcion_limpia}"

    if med:
        nombre, dosis, duracion = med
        respuesta += f" Se recomienda el medicamento {nombre}, con una dosis de {dosis}, durante {duracion}."
    else:
        respuesta += " Por el momento, no tengo una recomendación específica de medicamento para esto."

    # 🔴 Clasificación por gravedad justo aquí:
    gravedad_alta = ["dolor abdominal", "mareos", "fiebre alta"]
    gravedad_media = ["tos", "congestión nasal", "dolor de garganta"]
    gravedad_baja = ["picor en los ojos", "dolor de cabeza", "fatiga"]

    nivel_gravedad = "leve"
    emoji_alerta = "🟢"

    if any(s in gravedad_alta for s in sintomas_detectados):
        nivel_gravedad = "alta"
        emoji_alerta = "🔴"
    elif any(s in gravedad_media for s in sintomas_detectados):
        nivel_gravedad = "media"
        emoji_alerta = "🟠"

    respuesta += f"\n\nNivel de gravedad estimado: {nivel_gravedad.upper()} {emoji_alerta}"
    if nivel_gravedad == "alta":
        respuesta += "\n⚠️ Te recomiendo visitar a un médico cuanto antes."
    elif nivel_gravedad == "media":
        respuesta += "\n🩺 Observa cómo evolucionan tus síntomas. Si empeoran, busca atención médica."
    else:
        respuesta += "\n🙂 Parece una condición leve, pero mantente atento a cambios."

    import random
    respuesta += f"\n\nConsejo de salud: {random.choice(consejos_generales)}"

    # 🔁 Reiniciar contexto automáticamente tras el diagnóstico
    ultimo_contexto.clear()
    ultimo_contexto.update({
        "saludo_hecho": False,
        "ultimo_sintoma": None,
        "enfermedad": None
    })

    estado_enseñanza.clear()
    estado_enseñanza.update({
        "esperando_enfermedad": False,
        "sintoma_reportado": None,
        "enfermedad_propuesta": None,
        "esperando_medicamento": False
    })

    return respuesta

def obtener_recomendacion_medicamento(enfermedad):
    conn = get_connection()
    if not conn:
        return "No se pudo conectar para recuperar recomendaciones."

    cursor = conn.cursor()
    cursor.execute("SELECT ID_ENFERMEDAD FROM ENFERMEDADES WHERE LOWER(NOMBRE) = :1", [enfermedad.lower()])
    row = cursor.fetchone()
    if not row:
        conn.close()
        return f"No tengo registrado un tratamiento para '{enfermedad}'."

    id_enf = row[0]
    cursor.execute("""SELECT M.NOMBRE, R.DOSIS, R.DURACION
                      FROM RECOMENDACIONES R
                      JOIN MEDICAMENTOS M ON R.ID_MEDICAMENTO = M.ID_MEDICAMENTO
                      WHERE R.ID_ENFERMEDAD = :1""", [id_enf])
    med = cursor.fetchone()
    conn.close()

    if med:
        nombre, dosis, duracion = med
        return f"💊 Para {enfermedad}, se recomienda el medicamento {nombre}, con una dosis de {dosis}, durante {duracion}."
    else:
        return f"💊 No se encontró una recomendación específica de medicamento para {enfermedad}."

def detectar_sintomas(texto):
    texto = texto.lower()
    sintomas_detectados = []

    patrones = {
        "dolor de cabeza": ["dolor de cabeza", "me duele la cabeza", "cabeza me duele"],
        "fiebre": ["fiebre", "temperatura alta", "me siento con fiebre", "mucha fiebre"],
        "gripe": ["me siento con gripe", "tengo gripe", "síntomas de la gripe"],
        "tos": ["tengo tos", "estoy tosiendo", "tos"],
        "dolor de garganta": ["me duele la garganta", "dolor en la garganta", "garganta inflamada"],
        "congestión nasal": ["nariz tapada", "congestión nasal", "no respiro por la nariz"],
        "dolor abdominal": ["dolor abdominal", "me duele el estómago", "dolor de estómago", "me duele la barriga"],
        "náuseas": ["náuseas", "ganas de vomitar", "estómago revuelto"],
        "mareos": ["me siento mareado", "mareos", "estoy mareado"],
        "fatiga": ["cansancio", "me siento cansado", "fatiga", "cansancio extremo"],
        "escalofríos": ["tengo escalofríos", "escalofríos", "siento escalofríos"],
        "dolor lumbar": ["dolor en la espalda baja", "dolor lumbar", "me duele la parte baja de la espalda"],
        "picor en los ojos": ["me pican los ojos", "picazón en los ojos", "picor en los ojos"]
    }

    for sintoma, frases in patrones.items():
        for frase in frases:
            if frase in texto:
                sintomas_detectados.append(sintoma)
                break

    # 🔍 Buscar sinónimos en la base de datos si no se detectó nada
    if not sintomas_detectados:
        conn = get_connection()
        if conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT S.NOMBRE
                FROM SINONIMOS_SINTOMAS SS
                JOIN SINTOMAS S ON SS.ID_SINTOMA = S.ID_SINTOMA
                WHERE :1 LIKE '%' || LOWER(SS.SINONIMO) || '%'
            """, [texto])
            rows = cursor.fetchall()
            conn.close()

            for row in rows:
                sintomas_detectados.append(row[0])

    return sintomas_detectados


def intentar_busqueda_externa(pregunta):
    wikipedia.set_lang("es")
    try:
        nombre = extraer_nombre_enfermedad(pregunta)
        resumen_bruto = wikipedia.summary(nombre, sentences=2)
        resumen = limpiar_texto_wikipedia(resumen_bruto)
        return resumen
    except wikipedia.exceptions.DisambiguationError as e:
        return f"Se encontró más de una opción para '{pregunta}': {', '.join(e.options[:3])}"
    except wikipedia.exceptions.PageError:
        return None

def extraer_nombre_enfermedad(texto):
    texto = texto.lower()
    patrones = [r'sobre (la |el )?(.+)', r'qué es (la |el )?(.+)', r'cuáles son los síntomas de (la |el )?(.+)']
    for patron in patrones:
        match = re.search(patron, texto)
        if match:
            return match.groups()[-1].strip()
    return texto.strip()

def limpiar_texto_wikipedia(texto):
    texto = re.sub(r'\[\d+\]|\[nota \d+\]', '', texto, flags=re.IGNORECASE)
    texto = re.sub(r'\([^)]*\)', '', texto)
    texto = re.sub(r'\s+', ' ', texto).strip()

    oraciones = re.split(r'(?<=[.])\s+', texto)
    palabras_clave = [
        "síntoma", "infección", "provoca", "produce", "caracteriza", "afecta", "causa",
        "dolor", "tos", "fiebre", "fatiga", "náuseas", "síndrome", "enfermedad", "virus"
    ]

    oraciones_utiles = []
    for o in oraciones:
        if (
            len(o.split()) >= 6
            and not o.lower().startswith(("véase", "puede referirse a"))
            and not re.search(r'\d{4}', o)
            and not re.search(r'[\d,]+ (vacunas|fallecidos)', o.lower())
            and any(p in o.lower() for p in palabras_clave)
        ):
            oraciones_utiles.append(o.strip())
        if len(oraciones_utiles) >= 2:
            break

    return " ".join(oraciones_utiles) if oraciones_utiles else "No se encontró una descripción precisa en Wikipedia."

def guardar_enfermedad(nombre, descripcion):
    conn = get_connection()
    if not conn:
        return
    cursor = conn.cursor()
    cursor.execute("SELECT MAX(ID_ENFERMEDAD) FROM ENFERMEDADES")
    nuevo_id = (cursor.fetchone()[0] or 0) + 1
    cursor.execute("INSERT INTO ENFERMEDADES (ID_ENFERMEDAD, NOMBRE, DESCRIPCION) VALUES (:1, :2, :3)",
                   [nuevo_id, nombre.capitalize(), descripcion])

    sintomas = detectar_sintomas(descripcion)
    for sintoma in sintomas:
        cursor.execute("SELECT ID_SINTOMA FROM SINTOMAS WHERE LOWER(NOMBRE) = :1", [sintoma])
        row = cursor.fetchone()
        if row:
            id_sintoma = row[0]
        else:
            cursor.execute("SELECT MAX(ID_SINTOMA) FROM SINTOMAS")
            id_sintoma = (cursor.fetchone()[0] or 0) + 1
            cursor.execute("INSERT INTO SINTOMAS (ID_SINTOMA, NOMBRE) VALUES (:1, :2)", [id_sintoma, sintoma.lower()])

    # Guardar múltiples formas del mismo síntoma como sinónimos
    variantes = [
    sintoma.lower(),
    f"tengo {sintoma.lower()}",
    f"me da {sintoma.lower()}",
    f"siento {sintoma.lower()}",
    f"presento {sintoma.lower()}",
    f"experimento {sintoma.lower()}"
    ]

    cursor.execute("SELECT MAX(ID) FROM SINONIMOS_SINTOMAS")
    last_id = cursor.fetchone()[0] or 0

    for i, sinonimo in enumerate(variantes, start=1):
        cursor.execute("""
        INSERT INTO SINONIMOS_SINTOMAS (ID, ID_SINTOMA, SINONIMO)
        VALUES (:1, :2, :3)
        """, [last_id + i, id_sintoma, sinonimo])


        cursor.execute("SELECT 1 FROM REGLAS_INFERENCIA WHERE ID_ENFERMEDAD = :1 AND ID_SINTOMA = :2",
                       [nuevo_id, id_sintoma])
        if not cursor.fetchone():
            cursor.execute("SELECT MAX(ID_REGLA) FROM REGLAS_INFERENCIA")
            nueva_regla = (cursor.fetchone()[0] or 0) + 1
            cursor.execute("""INSERT INTO REGLAS_INFERENCIA (ID_REGLA, ID_ENFERMEDAD, ID_SINTOMA, PESO)
                              VALUES (:1, :2, :3, :4)""", [nueva_regla, nuevo_id, id_sintoma, 0.75])

    conn.commit()
    conn.close()
