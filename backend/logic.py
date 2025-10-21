import re
import random
import unicodedata
import wikipedia
import bcrypt
import logging
from typing import Optional, Tuple, List, Dict
from collections import defaultdict

from database import (
    get_connection,
    crear_usuario,
    crear_nueva_conversacion,
    guardar_mensaje_en_db,
    actualizar_titulo_chat,
    actualizar_titulo_con_mensaje,
    _guardar_o_actualizar_enfermedad_min,
    _guardar_medicamento_y_regla,
    guardar_enfermedad,
    obtener_recomendacion_medicamento,
    _obtener_medicamento_por_id,
    obtener_mensajes_por_conversacion
)

from gemini_service import (
    generar_respuesta_con_gemini,
    generar_respuesta_fallback,
    GEMINI_ENABLED
)

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

contextos: Dict[int, Dict] = {}

PREGUNTAS_TRIAGE = [
    "¿Has medido tu temperatura recientemente? Si es así, ¿cuál fue?",
    "Además de lo que mencionaste, ¿sientes algún otro malestar como náuseas, mareos o dolor en otra parte del cuerpo?",
    "¿Tienes alguna alergia conocida a medicamentos?",
    "¿Estás tomando algún medicamento actualmente?",
    "¿Tienes alguna condición médica preexistente (como diabetes, hipertensión, asma, etc.)?",
    "Finalmente, en una escala del 1 al 10, ¿qué tan severo consideras tu malestar general?"
]

consejos_generales = [
    "Recuerda mantenerte bien hidratado, es fundamental para tu recuperación.",
    "El descanso es clave. Intenta dormir al menos 8 horas.",
    "Una dieta balanceada ayuda a tu sistema inmune. Evita alimentos procesados.",
    "Si tus síntomas persisten o empeoran, no dudes en consultar a un médico.",
    "Evita automedicarte sin la supervisión de un profesional de la salud."
]

def _get_contexto_o_crear(user_id: int) -> Dict:
    """
    Obtiene o crea el diccionario de contexto para un usuario.
    """
    if user_id not in contextos:
        contextos[user_id] = {
            "estado_conversacion": "inicio",
            "sintomas_detectados": set(),
            "diagnostico_propuesto": None,
            "confirmacion_pendiente": False,
            "temperatura": None,
            "enfermedad": None,
            "triage": {"activo": False, "paso": 0, "respuestas": {}},
            "esperando_enfermedad": False,
            "esperando_medicamento": False,
            "enfermedad_propuesta": None,
            "sintoma_reportado": None,
            "conversation_id": None
        }
    return contextos[user_id]

def _reset_flujos_secundarios(ctx: Dict):
    """Resetea los estados de flujos como triaje o aprendizaje."""
    ctx["triage"]["activo"] = False
    ctx["esperando_enfermedad"] = False
    ctx["esperando_medicamento"] = False

def registrar_usuario(nombre: str, correo: str, password: str) -> tuple[bool, str]:
    """Registra un nuevo usuario, hasheando su contraseña."""
    salt = bcrypt.gensalt()
    password_hash = bcrypt.hashpw(password.encode('utf-8'), salt)
    user_id = crear_usuario(nombre, correo, password_hash)
    if user_id:
        return True, "Usuario registrado exitosamente."
    else:
        return False, "El correo electrónico ya podría estar en uso o hubo un error."

def verificar_credenciales(correo: str, password: str) -> Optional[int]:
    """
    Verifica credenciales usando bcrypt y maneja errores.
    """
    conn = get_connection()
    if not conn:
        print("Error: No se pudo conectar a la BD en verificar_credenciales.")
        return None
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT ID_USUARIO, PASSWORD FROM ADMIN.USUARIOS WHERE CORREO = :1", [correo])
        user_data = cursor.fetchone()

        if not user_data:
            return None

        user_id, stored_hash_str = user_data

        if not stored_hash_str:
            return None

        try:
            password_bytes = password.encode('utf-8')
            stored_hash_bytes = str(stored_hash_str).encode('utf-8')

            if bcrypt.checkpw(password_bytes, stored_hash_bytes):
                return user_id
            else:
                return None
        except ValueError:
            return None
    except Exception as e:
        print(f"Error en verificar_credenciales: {e}")
        return None
    finally:
        if conn:
            conn.close()

def _detectar_emocion(texto: str) -> Tuple[Optional[str], int]:
    t = _norm(texto)
    patrones = {
        "dolor_agudo": [r"\bdolor (fuerte|intenso|agudo)\b", r"\binsoportable\b"],
        "ansiedad":    [r"\bpreocupad[oa]\b", r"\bansiedad\b", r"\bme da miedo\b"],
        "malestar":    [r"\bme siento mal\b", r"\bmalestar\b", r"\bmal\b", r"\bnauseas?\b", r"\bmare(o|os)\b"],
        "alivio":      [r"\bmejor\b", r"\bme siento mejor\b", r"\bgracias,?\s*me ayud[oó]\b"]
    }
    prioridad = ["dolor_agudo","ansiedad","malestar","alivio"]
    hits = {k:any(re.search(p, t) for p in ps) for k,ps in patrones.items()}
    emocion = next((e for e in prioridad if hits.get(e)), None)

    exclam = texto.count("!") >= 2
    strong = bool(re.search(r"\b(mucho|demasiado|terrible|horrible|insoportable)\b", t))
    intensidad = 1 + int(exclam) + int(strong)
    intensidad = max(1, min(3, intensidad))
    return emocion, intensidad

def _prefacio_empatico(emocion: Optional[str], intensidad: int) -> str:
    T = {
        "dolor_agudo": {1: "Entiendo que hay dolor. Te acompaño.", 2: "Siento que el dolor es fuerte. Vamos a actuar con señales de alerta.", 3: "Tu dolor suena intenso. Si hay falta de aire o dolor en el pecho, busca atención ya. Te guío con pasos claros."},
        "ansiedad": {1: "Gracias por compartir cómo te sientes. Vamos paso a paso.", 2: "Veo ansiedad. Te doy recomendaciones concretas.", 3: "Suena abrumador. Estoy aquí para ayudarte con acciones simples."},
        "malestar": {1: "Gracias por describirlo. Revisemos síntomas y opciones.", 2: "Tomé nota del malestar. Te doy recomendaciones y señales de alerta.", 3: "Entiendo que se siente fuerte. Te ofrezco pasos claros y cuándo buscar ayuda."},
        "alivio": {1: "¡Qué bien! Te dejo indicaciones para mantener la mejora.", 2: "Buen progreso. Consolidemos con hábitos sencillos.", 3: "Excelente avance. Cierro con un plan breve de prevención."},
        "neutral": {1: "Te ayudo con gusto.", 2: "Te lo explico de forma clara y directa.", 3: "Resumiré lo crítico y luego ampliamos."}
    }
    e = emocion if emocion in T else "neutral"
    i = max(1, min(3, intensidad or 1))
    return T[e][i]

def _interpretar_respuesta_triage(paso: int, texto: str, respuestas: dict):
    """Interpreta la respuesta del usuario en cada paso del triaje."""
    t = _norm(texto)

    if paso == 0:
        m = re.search(r"(\d{1,2}[\.,]\d+|\d{2,3})", t)
        if m:
             respuestas["temperatura"] = float(m.group(1).replace(',', '.'))

        temp_alta = respuestas.get("temperatura", 0) >= 38
        respuestas["fiebre"] = ("si" in t or "sí" in t or temp_alta)

    elif paso == 1:
        es_si = ("si" in t or "sí" in t)
        respuestas["tos"] = es_si or "tos" in t
        respuestas["dolor_garganta"] = es_si or "garganta" in t

    elif paso == 2:
        zonas = ["cabeza","garganta","abdomen","pecho","estomago","estómago"]

        for zona in zonas:
            if zona in t:
                if zona == "cabeza":
                    respuestas["dolor_cabeza"] = True
                elif zona == "garganta":
                    respuestas["dolor_garganta"] = True
                elif zona == "abdomen" or zona == "estomago" or zona == "estómago":
                    respuestas["dolor_abdominal"] = True
                elif zona == "pecho":
                    respuestas["dolor_pecho"] = True

    elif paso == 3:
        es_si = ("si" in t or "sí" in t)
        respuestas["nauseas"] = es_si or ("nausea" in t or "nauseas" in t)
        respuestas["vomitos"] = es_si or ("vomit" in t)
        respuestas["diarrea"] = es_si or ("diarrea" in t)

    elif paso == 4:
        m = re.search(r"(\d+)\s*(dia|dias|hora|horas)", t)
        respuestas["duracion"] = f"{m.group(1)} {m.group(2)}" if m else texto.strip()

    elif paso == 5:
        m = re.search(r"\b(10|[1-9])\b", t)
        respuestas["intensidad"] = int(m.group(1)) if m else None

def _respuestas_a_sintomas(r: dict) -> List[str]:
    """Convierte el diccionario de respuestas del triaje a una lista de síntomas canónicos."""
    sintomas = []

    if r.get("temperatura") and r["temperatura"] >= 39.5: sintomas.append("fiebre alta")
    elif r.get("fiebre"): sintomas.append("fiebre")

    if r.get("tos"): sintomas.append("tos")

    if r.get("dolor_cabeza"): sintomas.append("dolor de cabeza")
    if r.get("dolor_garganta"): sintomas.append("dolor de garganta")

    if r.get("dolor_abdominal"): sintomas.append("dolor abdominal")
    if r.get("dolor_pecho"): sintomas.append("dolor en el pecho")

    if r.get("nauseas"): sintomas.append("náuseas")
    if r.get("vomitos"): sintomas.append("vómitos")
    if r.get("diarrea"): sintomas.append("diarrea")

    return list(set(sintomas))

def extraer_nombre_enfermedad(texto: str):
    t = _norm(texto)
    patrones = [r"sobre (la |el )?(.+)", r"qué es (la |el )?(.+)", r"cuales son los sintomas de (la |el )?(.+)"]
    for patron in patrones:
        m = re.search(patron, t)
        if m and m.groups()[-1].strip() and m.groups()[-1].strip() not in ["que", "qué"]:
            return m.groups()[-1].strip()
    return t.strip()

def intentar_busqueda_externa(pregunta: str):
    wikipedia.set_lang("es")
    try:
        nombre = extraer_nombre_enfermedad(pregunta)
        resumen_bruto = wikipedia.summary(nombre, sentences=3)
        return limpiar_texto_wikipedia(resumen_bruto)
    except wikipedia.exceptions.DisambiguationError as e:
        return f"Se encontró más de una opción para '{pregunta}': {', '.join(e.options[:3])}. ¿Podrías ser más específico?"
    except wikipedia.exceptions.PageError:
        return None

def detectar_sintomas(texto: str, cursor) -> Tuple[List[str], dict]:
    """Combina patrones locales (incluyendo temperatura) y sinónimos de la BD."""
    t = _norm(texto)
    sintomas_detectados = []
    temp_context = {"temperatura": None}

    m = re.search(r"(\d{1,2}[\.,]\d+|\d{2,3})\s*(grados|°|c|celsius|de temperatura|fiebre)", t)
    if m:
        temp_str = m.group(1).replace(',', '.').strip()
        try:
            temp = float(temp_str)
            if 35.0 <= temp <= 43.0:
                temp_context["temperatura"] = temp
                if temp >= 39.5:
                    sintomas_detectados.append("fiebre alta")
                elif temp >= 38.0:
                    sintomas_detectados.append("fiebre")
        except ValueError:
            pass

    patrones_locales = {
        "dolor de cabeza": ["dolor de cabeza", "me duele la cabeza"],
        "fiebre": ["fiebre", "temperatura alta", "mucha fiebre"],
        "gripe": ["gripe", "síntomas de la gripe"],
        "tos": ["tos", "estoy tosiendo"],
        "dolor de garganta": ["me duele la garganta", "garganta inflamada"],
        "congestión nasal": ["nariz tapada", "congestión nasal"],
        "dolor abdominal": ["dolor abdominal", "me duele el estómago", "dolor de barriga"],
        "náuseas": ["náuseas", "ganas de vomitar"],
        "mareos": ["mareos", "me siento mareado"],
        "fatiga": ["cansancio", "fatiga", "cansancio extremo"],
        "escalofríos": ["escalofríos", "siento escalofríos"],
        "dolor lumbar": ["dolor en la espalda baja", "dolor lumbar"],
        "picor en los ojos": ["me pican los ojos", "picazón en los ojos"]
    }

    for sintoma, frases in patrones_locales.items():
        if any(frase in t for frase in frases) and sintoma not in sintomas_detectados:
            sintomas_detectados.append(sintoma)

    try:
        cursor.execute(
            """
            SELECT DISTINCT S.NOMBRE
            FROM ADMIN.SINONIMOS_SINTOMAS SS
            JOIN ADMIN.SINTOMAS S ON SS.ID_SINTOMA = S.ID_SINTOMA
            WHERE :texto LIKE '%' || LOWER(SS.SINONIMO) || '%'
            """,
            [t]
        )
        for row in cursor.fetchall():
            sintoma_norm = _norm(row[0])
            if sintoma_norm not in sintomas_detectados:
                sintomas_detectados.append(sintoma_norm)
    except Exception as e:
        print(f"Error al buscar sinónimos en BD: {e}")

    return list(dict.fromkeys(sintomas_detectados)), temp_context

def _diagnosticar_por_sintomas(cursor, sintomas_detectados: List[str]):
    """Busca el mejor diagnóstico sumando pesos, excluyendo el genérico (ID 1) si hay otras opciones."""
    puntajes = defaultdict(float)
    sintomas_utilizados = []

    for s in sintomas_detectados:
        s_norm = _norm(s)

        cursor.execute("SELECT ID_SINTOMA FROM SINTOMAS WHERE LOWER(NOMBRE) = :1", [s_norm])
        row = cursor.fetchone()

        if not row:
            continue

        id_sintoma = row[0]
        sintomas_utilizados.append((s_norm, id_sintoma))

        cursor.execute("SELECT ID_ENFERMEDAD, PESO FROM REGLAS_INFERENCIA WHERE ID_SINTOMA = :1", [id_sintoma])
        for id_enf, peso in cursor.fetchall():
            puntajes[id_enf] = puntajes[id_enf] + peso

    if not puntajes:
        return None, {}, sintomas_utilizados

    ID_GENERICO = 1

    candidatos_reales = {k: v for k, v in puntajes.items() if k != ID_GENERICO}

    mejor_id = None

    if candidatos_reales:
        mejor_id = max(candidatos_reales.items(), key=lambda x: x[1])[0]
    elif ID_GENERICO in puntajes:
        mejor_id = ID_GENERICO

    return mejor_id, puntajes, sintomas_utilizados

def _norm(s: str) -> str:
    """Normaliza el texto, lo pasa a minúsculas y quita acentos."""
    s = s.strip().lower()
    s = unicodedata.normalize("NFD", s)
    return "".join(ch for ch in s if unicodedata.category(ch) != "Mn")

def procesar_mensaje(user_id: int, texto_usuario: str, conversacion_id: int = None) -> str:
    """
    Función principal, refactorizada para integrar la lógica de diagnóstico
    con el nuevo sistema de historial de conversaciones en la base de datos.
    """
    contexto = _get_contexto_o_crear(user_id)

    # Si se proporciona un conversacion_id, usar ese; de lo contrario, crear uno nuevo
    if conversacion_id:
        contexto["conversation_id"] = conversacion_id
        conversation_id = conversacion_id
    elif "conversation_id" not in contexto or contexto["conversation_id"] is None:
        conv_id = crear_nueva_conversacion(user_id, texto_usuario)
        if not conv_id:
            return "Lo siento, hubo un error crítico al iniciar una nueva conversación. Por favor, intenta de nuevo más tarde."
        contexto["conversation_id"] = conv_id
        conversation_id = conv_id
    else:
        conversation_id = contexto["conversation_id"]

    guardar_mensaje_en_db(conversation_id, 'usuario', texto_usuario)

    # Actualizar el título si es una conversación nueva (solo tiene "Nueva conversación")
    actualizar_titulo_con_mensaje(conversation_id, texto_usuario)

    def guardar_y_retornar(respuesta: str) -> str:
        guardar_mensaje_en_db(conversation_id, 'agente', respuesta)
        return respuesta

    conn = None
    try:
        mensaje = texto_usuario
        tnorm = _norm(mensaje)
        logger.info(f"📝 Usuario {user_id} | Conversación {conversation_id} | Mensaje: '{mensaje[:100]}...'")

        emocion, intensidad = _detectar_emocion(mensaje)
        prefacio = _prefacio_empatico(emocion, intensidad)

        if any(s in tnorm for s in ["hola","buenos dias","buenas tardes","buenas noches"]):
            _reset_flujos_secundarios(contexto)
            return guardar_y_retornar("¡Hola! ¿Cómo te sientes hoy? 😊")

        if any(a in tnorm for a in ["gracias","muchas gracias","te lo agradezco"]):
            _reset_flujos_secundarios(contexto)
            respuesta = f"{prefacio}\n\n¡De nada! 😊 Si necesitas algo más, aquí estaré."
            return guardar_y_retornar(respuesta)

        frases_mejora = ["me siento bien", "ya estoy mejor", "estoy bien", "mejoré", "ya me siento mejor", "me encuentro mejor", "ya me recuperé", "estoy recuperado", "todo bien", "ya pasó", "ya no tengo nada", "ya no me duele", "ya me siento normal", "ya no tengo síntomas", "ya todo está bien", "ya estoy como nuevo", "ya estoy bien gracias", "ya me curé", "ya me alivió", "ya se me pasó", "ya no tengo molestias", "estoy mucho mejor", "ya me sané", "ya no me molesta", "todo tranquilo", "ya pasó todo", "ya estoy al 100", "ya me repuse", "ya estoy al cien", "gracias ya estoy bien", "estoy estable", "todo en orden", "ya estoy ok"]
        if any(f in tnorm for f in frases_mejora):
            _reset_flujos_secundarios(contexto)
            respuesta = f"{_prefacio_empatico('alivio', 2)}\n\n¡Qué buena noticia! Me alegra que te sientas mejor 😊"
            return guardar_y_retornar(respuesta)

        gatillos_triage = {"mas o menos","ahi vamos","regular","no muy bien","masomenos","me siento mal","mal","peor","no muy bien","no bien","no estoy bien","no me siento bien"}
        if (tnorm in gatillos_triage or not tnorm) and not contexto["triage"]["activo"]:
            _reset_flujos_secundarios(contexto)
            contexto["triage"].update({"activo": True,"paso":0,"respuestas":{}})
            respuesta = f"{_prefacio_empatico('malestar',1)}\n\nPara ayudarte mejor, haré unas preguntas rápidas.\n1/6: {PREGUNTAS_TRIAGE[0]}"
            return guardar_y_retornar(respuesta)

        if contexto["triage"]["activo"]:
            paso = contexto["triage"]["paso"]
            _interpretar_respuesta_triage(paso, mensaje, contexto["triage"]["respuestas"])
            paso += 1
            if paso < len(PREGUNTAS_TRIAGE):
                contexto["triage"]["paso"] = paso
                respuesta = f"{paso+1}/6: {PREGUNTAS_TRIAGE[paso]}"
                return guardar_y_retornar(respuesta)

            contexto["triage"]["activo"] = False
            sintomas_del_triage = _respuestas_a_sintomas(contexto["triage"]["respuestas"])
            if contexto["triage"]["respuestas"].get("temperatura"):
                contexto["temperatura"] = contexto["triage"]["respuestas"]["temperatura"]

            if not sintomas_del_triage:
                respuesta = "No logré identificar síntomas específicos. Por favor, descríbeme con más detalle qué sientes."
                return guardar_y_retornar(respuesta)

            # Actualizar título del chat con síntomas del triage
            if sintomas_del_triage and conversation_id:
                actualizar_titulo_chat(conversation_id, sintomas_del_triage)

            mensaje = "tengo " + ", ".join(sintomas_del_triage)
            tnorm = _norm(mensaje)
            print("📝 Síntomas de Triaje convertidos:", mensaje)

        if contexto["esperando_enfermedad"] or contexto["esperando_medicamento"]:
            conn_aprendizaje = get_connection()
            if not conn_aprendizaje: return guardar_y_retornar("Error de conexión al intentar aprender.")
            try:
                cursor_aprendizaje = conn_aprendizaje.cursor()
                if contexto["esperando_enfermedad"]:
                    enfermedad = mensaje.strip().capitalize()
                    contexto.update({"enfermedad_propuesta": enfermedad, "esperando_enfermedad": False, "esperando_medicamento": True})
                    # Guardar o actualizar la enfermedad
                    ok, _ = guardar_enfermedad(enfermedad, "Enfermedad aprendida por retroalimentación.")
                    if not ok:
                        logger.warning(f"No se pudo guardar la enfermedad '{enfermedad}', pero continuando...")
                    respuesta = f"{prefacio}\n\n¡Gracias! ¿Recuerdas qué medicamento usaste y cómo? Formato: nombre, dosis, frecuencia, duración. 🙏"
                    return guardar_y_retornar(respuesta)

                if contexto["esperando_medicamento"]:
                    partes = [p.strip() for p in mensaje.split(",")]
                    if len(partes) < 4:
                        respuesta = f"{prefacio}\n\nPor favor, indica el medicamento en el formato correcto: nombre, dosis, frecuencia, duración."
                        return guardar_y_retornar(respuesta)
                    nombre, dosis, frecuencia, duracion = partes[0].capitalize(), partes[1], partes[2], partes[3]
                    enfermedad = contexto["enfermedad_propuesta"]
                    # 1) Obtener ID_ENFERMEDAD
                    cursor_aprendizaje.execute(
                        "SELECT ID_ENFERMEDAD FROM ADMIN.ENFERMEDADES WHERE UPPER(NOMBRE)=UPPER(:n)",
                        n=enfermedad
                    )
                    row = cursor_aprendizaje.fetchone()
                    if not row:
                        # Si la enfermedad no existe aún, créala de forma mínima
                        ok, new_id = guardar_enfermedad(enfermedad, "Enfermedad aprendida por retroalimentación.")
                        id_enf = new_id if ok else None
                    else:
                        id_enf = row[0]

                    if not id_enf:
                        return guardar_y_retornar("No pude registrar la enfermedad para aprender la recomendación. Intenta de nuevo.")

                    # 2) Unir dosis + frecuencia en el campo DOSIS (porque el esquema no tiene FRECUENCIA)
                    dosis_final = f"{dosis} {frecuencia}".strip()
                    # 3) Guardar medicamento + regla
                    ok = _guardar_medicamento_y_regla(nombre, f"Aprendido del usuario", id_enf, dosis_final, duracion)
                    if not ok:
                        return guardar_y_retornar("Ocurrió un problema al guardar la recomendación. Intenta nuevamente.")

                    _reset_flujos_secundarios(contexto)
                    respuesta = f"{prefacio}\n\n¡Genial! He aprendido que para *{enfermedad}* se puede recomendar **{nombre}** ({dosis_final}, {duracion}). 🧠💊"
                    return guardar_y_retornar(respuesta)
            finally:
                if conn_aprendizaje: conn_aprendizaje.close()

        if re.search(r"(que puedo tomar|que medicamento|cual es el tratamiento)", tnorm):
            enf = extraer_nombre_enfermedad(mensaje) or contexto.get("enfermedad")
            if not enf:
                respuesta = f"{prefacio}\n\nPor favor, dime primero qué enfermedad tienes para poder darte una recomendación."
                return guardar_y_retornar(respuesta)
            rec = obtener_recomendacion_medicamento(enf)
            if not rec:
                return guardar_y_retornar(f"{prefacio}\n\nNo tengo aún una recomendación registrada para **{enf}**.")
            nombre, dosis, duracion = rec
            bonito = (
                f"**💊 Tratamiento recomendado para {enf}:**\n"
                f"• Medicamento: {nombre}\n"
                f"• Dosis: {dosis}\n"
                f"• Duración: {duracion}"
            )
            return guardar_y_retornar(f"{prefacio}\n\n{bonito}")

        if re.search(r"¿?(que|qué|cuales|cuáles|explica|explícame)\b.*\b(es|son|sobre)\b", mensaje.lower()):
            resumen = intentar_busqueda_externa(mensaje)
            if resumen:
                nombre_enf = extraer_nombre_enfermedad(mensaje)
                if nombre_enf and nombre_enf not in ["que", "qué", "cuales", "cuáles"]:
                    guardar_enfermedad(nombre_enf, resumen)
                    contexto['enfermedad'] = nombre_enf
                    respuesta = f"{prefacio}\n\n🧠 He aprendido sobre '{nombre_enf}' y lo he guardado.\n\n{resumen}"
                    return guardar_y_retornar(respuesta)
                else:
                    return guardar_y_retornar(f"{prefacio}\n\n{resumen}")
            else:
                return guardar_y_retornar(f"{prefacio}\n\nNo encontré información sobre eso.")

        conn = get_connection()
        if not conn: return guardar_y_retornar("Error de conexión al intentar diagnosticar.")

        cursor = conn.cursor()
        cursor.execute("ALTER SESSION SET NLS_COMP = LINGUISTIC")
        cursor.execute("ALTER SESSION SET NLS_SORT = BINARY_CI")

        sintomas_detectados, temp_ctx = detectar_sintomas(mensaje, cursor)
        if temp_ctx.get("temperatura"):
            contexto["temperatura"] = temp_ctx["temperatura"]

        print("🔍 Síntomas detectados:", sintomas_detectados)

        # Actualizar título del chat con el síntoma principal
        if sintomas_detectados and conversation_id:
            actualizar_titulo_chat(conversation_id, sintomas_detectados)

        if not sintomas_detectados:
            # NUEVA FUNCIONALIDAD: Si no hay síntomas en BD, intentar Gemini primero
            if GEMINI_ENABLED:
                logger.info("🤖 No hay síntomas en BD, intentando Gemini AI...")
                # Obtener historial de conversación
                historial = obtener_mensajes_por_conversacion(conversation_id)
                logger.info(f"📜 Historial obtenido: {len(historial)} mensajes")
                if historial:
                    logger.debug(f"Último mensaje en historial: role={historial[-1].get('role')}, content={historial[-1].get('content', '')[:100]}")
                respuesta_gemini, nivel_urgencia = generar_respuesta_con_gemini(
                    mensaje_usuario=mensaje,
                    sintomas_detectados=[],
                    contexto=contexto,
                    diagnostico_previo=None,
                    historial_conversacion=historial
                )

                if respuesta_gemini:
                    logger.info(f"✅ Gemini proporcionó respuesta (urgencia: {nivel_urgencia})")
                    _reset_flujos_secundarios(contexto)
                    return guardar_y_retornar(respuesta_gemini)
                else:
                    logger.warning("⚠️ Gemini no pudo responder, activando modo aprendizaje")

            # FALLBACK: Si Gemini falla o no está disponible, pedir aprendizaje
            _reset_flujos_secundarios(contexto)
            contexto["sintoma_reportado"] = mensaje
            contexto["esperando_enfermedad"] = True
            respuesta = f"{prefacio}\n\nHmm, no reconozco ese síntoma... ¿Te diagnosticaron alguna enfermedad relacionada? Puedo aprender de ello. 😊"
            return guardar_y_retornar(respuesta)

        mejor_id, _, sintomas_utilizados = _diagnosticar_por_sintomas(cursor, sintomas_detectados)

        if not mejor_id:
            respuesta = f"{prefacio}\n\nCon los síntomas que mencionas, no pude encontrar una enfermedad coincidente en mi base de conocimientos."
            return guardar_y_retornar(respuesta)

        cursor.execute("SELECT NOMBRE, DESCRIPCION FROM ADMIN.ENFERMEDADES WHERE ID_ENFERMEDAD = :1", [mejor_id])
        row = cursor.fetchone()
        if not row or not row[0]:
            return guardar_y_retornar(f"{prefacio}\n\nIdentifiqué una posible enfermedad, pero no pude recuperar su información.")

        enfermedad, desc_raw = row[0], row[1]
        descripcion = desc_raw.read() if hasattr(desc_raw, 'read') else desc_raw
        descripcion = (descripcion or "").replace("Enfermedad aprendida por retroalimentación.", "").strip()
        contexto["enfermedad"] = enfermedad
        med = _obtener_medicamento_por_id(mejor_id)

        sintomas_canonicos = [s for s, _ in sintomas_utilizados]

        # NUEVA FUNCIONALIDAD: Intentar usar Gemini AI primero
        if GEMINI_ENABLED:
            logger.info("🤖 Generando respuesta con Gemini AI...")
            # Obtener historial de conversación
            historial = obtener_mensajes_por_conversacion(conversation_id)
            logger.info(f"📜 Historial obtenido: {len(historial)} mensajes")
            if historial:
                logger.debug(f"Últimos 2 mensajes: {historial[-2:] if len(historial) >= 2 else historial}")
            respuesta_gemini, nivel_urgencia = generar_respuesta_con_gemini(
                mensaje_usuario=mensaje,
                sintomas_detectados=sintomas_canonicos,
                contexto=contexto,
                diagnostico_previo=enfermedad,
                historial_conversacion=historial
            )

            if respuesta_gemini:
                logger.info(f"✅ Respuesta Gemini generada (urgencia: {nivel_urgencia})")
                _reset_flujos_secundarios(contexto)
                return guardar_y_retornar(respuesta_gemini)
            else:
                logger.warning("⚠️ Gemini falló, usando método tradicional")

        # FALLBACK: Usar método tradicional si Gemini no está disponible
        logger.info("📋 Generando respuesta con método tradicional...")
        respuesta_diag = generar_respuesta_fallback(
            sintomas=sintomas_canonicos,
            enfermedad=enfermedad,
            descripcion=descripcion,
            medicamento=med
        )

        _reset_flujos_secundarios(contexto)
        return guardar_y_retornar(respuesta_diag)

    except Exception as e:
        logger.error(f"❌ Error fatal en procesar_mensaje para user_id {user_id}: {e}", exc_info=True)
        respuesta_error = "Lo siento mucho, ocurrió un error inesperado al procesar tu mensaje. Por favor, intenta de nuevo."
        return guardar_y_retornar(respuesta_error)
    finally:
        if conn:
            conn.close()

PESO_APRENDIZAJE_DEFECTO = 0.6

def limpiar_texto_wikipedia(texto: str):
    texto = re.sub(r"\[\d+\]|\[nota \d+\]", "", texto, flags=re.IGNORECASE)
    texto = re.sub(r"\s+", " ", texto).strip()
    oraciones = re.split(r"(?<=[.])\s+", texto)
    palabras_clave = ["sintoma","infeccion","provoca","produce","caracteriza","afecta","causa",
                      "dolor","tos","fiebre","fatiga","nauseas","sindrome","enfermedad","virus","trastorno"]
    utiles = []
    for o in oraciones:
        if (len(o.split()) >= 6 and not o.lower().startswith(("véase","vease","puede referirse a"))
            and not re.search(r"\d{4}", o) and any(p in _norm(o) for p in palabras_clave)):
            utiles.append(o.strip())
        if len(utiles) >= 2:
            break
    return " ".join(utiles) if utiles else "No se encontró una descripción precisa en Wikipedia."
