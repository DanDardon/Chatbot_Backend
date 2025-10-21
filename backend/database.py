import os
import oracledb
from config import DB_USER, DB_PASS, DB_DSN_ALIAS, DB_WALLET_DIR, DB_WALLET_PASS
from typing import Optional, Tuple, List, Dict
import re

def get_connection():
    """
    Establece y retorna una conexión a la base de datos Oracle utilizando un wallet.
    """
    try:
        os.environ["TNS_ADMIN"] = DB_WALLET_DIR

        conn = oracledb.connect(
            user=DB_USER,
            password=DB_PASS,
            dsn=DB_DSN_ALIAS,
            config_dir=DB_WALLET_DIR,
            wallet_location=DB_WALLET_DIR,
            wallet_password=(DB_WALLET_PASS or None),
            ssl_server_dn_match=True
        )

        with conn.cursor() as c:
            c.execute("select 1 from dual")
            c.fetchone()
        return conn

    except oracledb.Error as e:
        print("❌ Error al conectar con Oracle:", str(e))
        return None

def cargar_sintomas_y_reglas_desde_bd() -> Optional[Dict[str, List]]:
    """
    Consulta todos los datos necesarios para el motor de inferencia y los devuelve.
    """
    conn = get_connection()
    if conn is None:
        return None

    try:
        cursor = conn.cursor()

        datos = {}

        cursor.execute("SELECT ID_SINTOMA, NOMBRE FROM ADMIN.SINTOMAS")
        datos['sintomas'] = cursor.fetchall()

        cursor.execute("SELECT ID_ENFERMEDAD, NOMBRE FROM ADMIN.ENFERMEDADES")
        datos['enfermedades'] = cursor.fetchall()

        cursor.execute("SELECT ID_SINTOMA, ID_ENFERMEDAD, PESO FROM ADMIN.REGLAS_INFERENCIA")
        datos['reglas'] = cursor.fetchall()

        cursor.execute("""
            SELECT S.NOMBRE, SS.SINONIMO
            FROM ADMIN.SINTOMAS S
            JOIN ADMIN.SINONIMOS_SINTOMAS SS ON S.ID_SINTOMA = SS.ID_SINTOMA
        """)
        datos['sinonimos'] = cursor.fetchall()

        return datos

    except oracledb.Error as e:
        print(f"❌ Error al cargar datos: {e}")
        return None
    finally:
        if conn:
            conn.close()

def crear_usuario(nombre: str, correo: str, password_hash: bytes) -> Optional[int]:
    """
    Inserta un nuevo usuario en la base de datos.
    Devuelve el ID del nuevo usuario si se crea correctamente.
    """
    conn = get_connection()
    if not conn:
        return None

    try:
        cursor = conn.cursor()

        new_user_id_var = cursor.var(oracledb.NUMBER)

        cursor.execute("""
            INSERT INTO ADMIN.USUARIOS (NOMBRE, CORREO, PASSWORD)
            VALUES (:1, :2, :3)
            RETURNING ID_USUARIO INTO :4
        """, [nombre, correo, password_hash.decode('utf-8'), new_user_id_var])

        new_user_id = new_user_id_var.getvalue()[0]

        conn.commit()
        return new_user_id
    except oracledb.DatabaseError as e:
        print(f"Error al crear usuario: {e}")
        conn.rollback()
        return None
    finally:
        if conn:
            conn.close()

def _get_or_create_chat_id(cursor, user_id: str, conn):
    """
    Crea una nueva sesión de chat en la tabla ADMIN.CHATS.
    """
    try:
        cursor.execute("SELECT ADMIN.CHATS_SEQ.NEXTVAL FROM DUAL")
        new_chat_id = cursor.fetchone()[0]

        cursor.execute(
            """
            INSERT INTO ADMIN.CHATS (ID_CHAT, NOMBRE)
            VALUES (:id, 'Chat Agente Médico')
            """,
            id=new_chat_id
        )

        return new_chat_id

    except oracledb.Error as e:
        print(f"❌ Error en _get_or_create_chat_id (creación de chat): {str(e)}")
        return None

def _guardar_mensaje(cursor, id_chat, emisor, contenido, conn):
    """
    Guarda un mensaje en la tabla ADMIN.MENSAJES.
    """
    try:
        cursor.execute("SELECT ADMIN.MENSAJES_SEQ.NEXTVAL FROM DUAL")
        new_message_id = cursor.fetchone()[0]

        cursor.execute(
            """
            INSERT INTO ADMIN.MENSAJES (ID_MENSAJE, ID_CHAT, EMISOR, CONTENIDO)
            VALUES (:id_mensaje, :id_chat, :emisor, :contenido)
            """,
            id_mensaje=new_message_id,
            id_chat=id_chat,
            emisor=emisor,
            contenido=contenido
        )
        return True

    except oracledb.Error as e:
        print(f"❌ Error al guardar mensaje: {str(e)}")
        return False

def _guardar_o_actualizar_enfermedad_min(id_chat, nombre_enfermedad, min_value):
    """
    Función placeholder. Si necesitas persistir el estado de diagnóstico,
    ajusta para usar tu tabla de estado (ej: ADMIN.ESTADO_DIAGNOSTICO).
    """
    print(f"✅ Log: Chat {id_chat} - {nombre_enfermedad} tiene MIN_PESO={min_value}")
    return True

def guardar_enfermedad(nombre: str, descripcion: str) -> Tuple[bool, Optional[int]]:
    """
    Guarda una nueva enfermedad en la tabla ADMIN.ENFERMEDADES.
    Si ya existe, actualiza su descripción y retorna su ID.
    Retorna (True, id) o (False, None).
    """
    conn = get_connection()
    if conn is None:
        return False, None

    try:
        with conn.cursor() as cursor:
            # Primero intentar obtener la enfermedad existente
            cursor.execute(
                "SELECT ID_ENFERMEDAD FROM ADMIN.ENFERMEDADES WHERE UPPER(NOMBRE) = UPPER(:nombre)",
                nombre=nombre
            )
            existing = cursor.fetchone()

            if existing:
                # Si existe, actualizar la descripción si es más completa
                disease_id = existing[0]
                if descripcion and descripcion.strip():
                    cursor.execute(
                        """
                        UPDATE ADMIN.ENFERMEDADES
                        SET DESCRIPCION = :descripcion
                        WHERE ID_ENFERMEDAD = :id
                        """,
                        descripcion=descripcion,
                        id=disease_id
                    )
                    conn.commit()
                return True, disease_id

            # Si no existe, intentar crear nueva con manejo de duplicados
            try:
                cursor.execute("SELECT ADMIN.ENFERMEDADES_SEQ.NEXTVAL FROM DUAL")
                new_disease_id = cursor.fetchone()[0]

                cursor.execute(
                    """
                    INSERT INTO ADMIN.ENFERMEDADES (ID_ENFERMEDAD, NOMBRE, DESCRIPCION)
                    VALUES (:id, :nombre, :descripcion)
                    """,
                    id=new_disease_id,
                    nombre=nombre,
                    descripcion=descripcion
                )

                conn.commit()
                return True, new_disease_id

            except oracledb.IntegrityError as ie:
                # Si falla por duplicado (constraint violation), intentar obtener el ID existente
                conn.rollback()
                cursor.execute(
                    "SELECT ID_ENFERMEDAD FROM ADMIN.ENFERMEDADES WHERE UPPER(NOMBRE) = UPPER(:nombre)",
                    nombre=nombre
                )
                existing_after = cursor.fetchone()
                if existing_after:
                    print(f"⚠️ Enfermedad '{nombre}' ya existía (race condition detectada), usando ID existente")
                    return True, existing_after[0]
                else:
                    print(f"❌ Error de integridad al guardar enfermedad: {str(ie)}")
                    return False, None

    except oracledb.Error as e:
        print(f"❌ Error al guardar enfermedad: {str(e)}")
        if conn:
            conn.rollback()
        return False, None
    finally:
        if conn:
            conn.close()

def _guardar_medicamento_y_regla(nombre_medicamento: str, descripcion_medicamento: str, id_enfermedad: int, dosis: str, duracion: str) -> bool:
    """
    Guarda un nuevo medicamento (si no existe) y crea una nueva regla
    de recomendación en la tabla ADMIN.RECOMENDACIONES.
    """
    conn = get_connection()
    if conn is None:
        return False

    try:
        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT ID_MEDICAMENTO FROM ADMIN.MEDICAMENTOS WHERE UPPER(NOMBRE) = UPPER(:nombre)",
                nombre=nombre_medicamento
            )
            result = cursor.fetchone()

            if result:
                id_medicamento = result[0]
            else:
                cursor.execute("SELECT ADMIN.MEDICAMENTOS_SEQ.NEXTVAL FROM DUAL")
                id_medicamento = cursor.fetchone()[0]

                cursor.execute(
                    """
                    INSERT INTO ADMIN.MEDICAMENTOS (ID_MEDICAMENTO, NOMBRE, DESCRIPCION)
                    VALUES (:id, :nombre, :descripcion)
                    """,
                    id=id_medicamento,
                    nombre=nombre_medicamento,
                    descripcion=descripcion_medicamento
                )

            cursor.execute(
                """
                INSERT INTO ADMIN.RECOMENDACIONES (ID_ENFERMEDAD, ID_MEDICAMENTO, DOSIS, DURACION)
                VALUES (:id_enfermedad, :id_medicamento, :dosis, :duracion)
                """,
                id_enfermedad=id_enfermedad,
                id_medicamento=id_medicamento,
                dosis=dosis,
                duracion=duracion
            )

            conn.commit()
            return True

    except oracledb.Error as e:
        print(f"❌ Error al guardar medicamento y regla: {str(e)}")
        conn.rollback()
        return False
    finally:
        if conn:
            conn.close()

def obtener_recomendacion_medicamento(nombre_enfermedad: str) -> Optional[Tuple[str, str, str]]:
    """
    Busca el medicamento recomendado (nombre), dosis y duración para una enfermedad
    específica usando el NOMBRE de la enfermedad.
    """
    conn = get_connection()
    if conn is None:
        return None

    try:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT m.NOMBRE, r.DOSIS, r.DURACION
                FROM ADMIN.RECOMENDACIONES r
                JOIN ADMIN.MEDICAMENTOS m ON r.ID_MEDICAMENTO = m.ID_MEDICAMENTO
                JOIN ADMIN.ENFERMEDADES e ON r.ID_ENFERMEDAD = e.ID_ENFERMEDAD
                WHERE UPPER(e.NOMBRE) = UPPER(:nombre)
                FETCH FIRST 1 ROWS ONLY
                """,
                nombre=nombre_enfermedad
            )
            return cursor.fetchone()
    except oracledb.Error as e:
        print(f"❌ Error al buscar recomendaciones: {str(e)}")
        return None
    finally:
        if conn:
            conn.close()

def _obtener_medicamento_por_id(id_enfermedad: int) -> Optional[Tuple[str, str, str]]:
    """
    Busca el medicamento recomendado (nombre, dosis, duración) para una enfermedad por su ID.
    """
    conn = get_connection()
    if conn is None:
        return None

    try:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT m.NOMBRE, r.DOSIS, r.DURACION
                FROM ADMIN.RECOMENDACIONES r
                JOIN ADMIN.MEDICAMENTOS m ON r.ID_MEDICAMENTO = m.ID_MEDICAMENTO
                WHERE r.ID_ENFERMEDAD = :id
                FETCH FIRST 1 ROWS ONLY
                """,
                id=id_enfermedad
            )
            return cursor.fetchone()
    except oracledb.Error as e:
        print(f"❌ Error al obtener medicamento por ID de enfermedad: {str(e)}")
        return None
    finally:
        if conn:
            conn.close()

def verificar_credenciales(correo: str, password_hash: str) -> Optional[Tuple[int, str]]:
    """
    Verifica las credenciales del usuario (correo y hash de contraseña).
    Retorna una tupla (ID_USUARIO, NOMBRE) si las credenciales son válidas.
    """
    conn = get_connection()
    if conn is None:
        return None

    try:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT ID_USUARIO, NOMBRE
                FROM ADMIN.USUARIOS
                WHERE CORREO = :correo AND PASSWORD = :password_hash
                """,
                correo=correo,
                password_hash=password_hash
            )
            return cursor.fetchone()

    except oracledb.Error as e:
        print(f"❌ Error al verificar credenciales: {str(e)}")
        return None
    finally:
        if conn:
            conn.close()

def crear_nueva_conversacion(user_id: int, primer_mensaje: str) -> Optional[int]:
    """Crea un registro para una nueva conversación y devuelve su ID."""
    conn = get_connection()
    if not conn:
        return None
    try:
        cursor = conn.cursor()

        # Verificar si la columna ID_USUARIO existe, si no, agregarla
        try:
            cursor.execute("""
                SELECT COUNT(*) FROM USER_TAB_COLUMNS
                WHERE TABLE_NAME = 'CHATS' AND COLUMN_NAME = 'ID_USUARIO'
            """)
            column_exists = cursor.fetchone()[0] > 0

            if not column_exists:
                cursor.execute("""
                    ALTER TABLE ADMIN.CHATS ADD (ID_USUARIO NUMBER)
                """)
                conn.commit()
                print("✅ Columna ID_USUARIO agregada a CHATS")
        except Exception as e:
            print(f"Advertencia al verificar/agregar columna: {e}")

        cursor.execute("SELECT ADMIN.CHATS_SEQ.NEXTVAL FROM DUAL")
        new_chat_id = cursor.fetchone()[0]

        # Generar un título más descriptivo basado en el primer mensaje
        titulo_inicial = _generar_titulo_desde_mensaje(primer_mensaje) or "Nueva consulta"

        # Insertar en CHATS (tabla principal)
        cursor.execute("""
            INSERT INTO ADMIN.CHATS (ID_CHAT, NOMBRE, ID_USUARIO)
            VALUES (:1, :2, :3)
        """, [new_chat_id, titulo_inicial, user_id])

        conn.commit()
        return new_chat_id
    except oracledb.DatabaseError as e:
        print(f"Error específico dentro de crear_nueva_conversacion: {e}")
        conn.rollback()
        return None
    finally:
        if conn:
            conn.close()

def _generar_titulo_desde_mensaje(mensaje: str) -> str:
    """Genera un título descriptivo desde el mensaje del usuario."""
    if not mensaje or not mensaje.strip():
        return "Nueva conversación"

    mensaje_lower = mensaje.lower().strip()

    # Patrones comunes de síntomas para el título
    patrones = {
        r"\b(dolor de cabeza|cefalea|migraña)\b": "Dolor de cabeza",
        r"\b(fiebre|temperatura|calentura)\b": "Fiebre",
        r"\b(gripe|gripa|resfriado|catarro)\b": "Gripe",
        r"\b(tos)\b": "Tos",
        r"\b(dolor de garganta|garganta)\b": "Dolor de garganta",
        r"\b(nariz tapada|congestión|congestionado)\b": "Congestión nasal",
        r"\b(dolor de estómago|dolor abdominal|dolor de barriga)\b": "Dolor abdominal",
        r"\b(dolor de cintura|dolor lumbar|lumbago)\b": "Dolor de cintura",
        r"\b(dolor de espalda)\b": "Dolor de espalda",
        r"\b(dolor al orinar|cistitis|infección urinaria)\b": "Problema urinario",
        r"\b(náuseas|nausea|ganas de vomitar)\b": "Náuseas",
        r"\b(mareo|mareado|vértigo)\b": "Mareos",
        r"\b(cansancio|fatiga|agotamiento)\b": "Fatiga",
        r"\b(diarrea)\b": "Diarrea",
        r"\b(vómito|vomitar)\b": "Vómitos",
        r"\b(alergia|alergias|alérgico)\b": "Alergias",
        r"\b(asma|asmatico)\b": "Asma",
        r"\b(rinitis)\b": "Rinitis",
    }

    for patron, titulo in patrones.items():
        if re.search(patron, mensaje_lower):
            return titulo

    # Si es una pregunta sobre una enfermedad específica
    match = re.search(r"(?:que es|qué es|sobre|acerca de)\s+(?:la |el )?([\w\s]{3,20})\??", mensaje_lower)
    if match:
        enfermedad = match.group(1).strip().title()
        return enfermedad

    # Si el mensaje es corto, usarlo como título (máximo 30 caracteres)
    if len(mensaje) <= 30:
        return mensaje.capitalize()

    # Tomar las primeras palabras del mensaje
    palabras = mensaje.split()[:4]
    return " ".join(palabras).capitalize() + "..."

def actualizar_titulo_con_mensaje(conversation_id: int, mensaje: str):
    """Actualiza el título del chat basándose en el mensaje del usuario."""
    if not conversation_id or not mensaje:
        return

    conn = get_connection()
    if not conn:
        return

    try:
        cursor = conn.cursor()

        # Verificar si el chat ya tiene un título personalizado (diferente de "Nueva conversación")
        cursor.execute("""
            SELECT NOMBRE FROM ADMIN.CHATS WHERE ID_CHAT = :1
        """, [conversation_id])

        row = cursor.fetchone()
        if row and row[0] and row[0] != "Nueva conversación":
            # Ya tiene un título personalizado, no sobreescribir
            return

        # Generar nuevo título desde el mensaje
        nuevo_titulo = _generar_titulo_desde_mensaje(mensaje)

        cursor.execute("""
            UPDATE ADMIN.CHATS
            SET NOMBRE = :1
            WHERE ID_CHAT = :2
        """, [nuevo_titulo, conversation_id])

        conn.commit()
        print(f"✅ Título actualizado a: '{nuevo_titulo}'")

    except Exception as e:
        print(f"Error al actualizar título con mensaje: {e}")
        if conn:
            conn.rollback()
    finally:
        if conn:
            conn.close()

def actualizar_titulo_chat(conversation_id: int, sintomas: list):
    """Actualiza el título del chat con el síntoma principal detectado."""
    print(f"🔄 Intentando actualizar título - ID: {conversation_id}, Síntomas: {sintomas}")

    if not sintomas:
        print("⚠️ No hay síntomas para actualizar título")
        return

    conn = get_connection()
    if not conn:
        print("❌ No se pudo conectar a la base de datos")
        return

    try:
        # Usar el primer síntoma como título
        titulo_sintoma = sintomas[0].capitalize()
        print(f"📝 Nuevo título será: {titulo_sintoma}")

        cursor = conn.cursor()
        cursor.execute("""
            UPDATE ADMIN.CHATS
            SET NOMBRE = :1
            WHERE ID_CHAT = :2
        """, [titulo_sintoma, conversation_id])

        rows_affected = cursor.rowcount
        conn.commit()
        print(f"✅ Título actualizado a: '{titulo_sintoma}' (Filas afectadas: {rows_affected})")
    except Exception as e:
        print(f"❌ Error al actualizar título: {e}")
        import traceback
        traceback.print_exc()
    finally:
        if conn:
            conn.close()

def guardar_mensaje_en_db(conversation_id: int, emisor: str, contenido: str):
    """Guarda un mensaje en la tabla MENSAJES."""
    conn = get_connection()
    if not conn:
        return
    try:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO ADMIN.MENSAJES (ID_CHAT, EMISOR, CONTENIDO)
            VALUES (:1, :2, :3)
        """, [conversation_id, emisor, contenido])
        conn.commit()
    except oracledb.DatabaseError as e:
        print(f"Error específico dentro de guardar_mensaje_en_db: {e}")
        conn.rollback()
    finally:
        if conn:
            conn.close()

def listar_conversaciones_por_usuario(user_id: int) -> List[Dict]:
    """Obtiene una lista de todas las conversaciones de un usuario."""
    conn = get_connection()
    if not conn:
        return []
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT
                c.ID_CHAT,
                c.NOMBRE,
                c.FECHA_CREACION,
                (
                    SELECT CONTENIDO
                    FROM ADMIN.MENSAJES m
                    WHERE m.ID_CHAT = c.ID_CHAT
                    AND LOWER(m.EMISOR) = 'usuario'
                    ORDER BY m.ID_MENSAJE ASC
                    FETCH FIRST 1 ROWS ONLY
                ) as PRIMER_MENSAJE
            FROM ADMIN.CHATS c
            WHERE c.ID_USUARIO = :1
            AND EXISTS (
                SELECT 1 FROM ADMIN.MENSAJES m
                WHERE m.ID_CHAT = c.ID_CHAT
            )
            ORDER BY c.FECHA_CREACION DESC
        """, [user_id])

        conversaciones = []
        for row in cursor.fetchall():
            id_chat = row[0]
            titulo_actual = row[1]
            fecha_creacion = row[2]
            primer_mensaje = row[3]

            # No modificar títulos automáticamente aquí
            titulo = titulo_actual

            conversaciones.append({
                "id_conversacion": id_chat,
                "titulo": titulo,
                "fecha_inicio": fecha_creacion.strftime("%Y-%m-%d %H:%M:%S") if fecha_creacion else ""
            })

        return conversaciones
    except oracledb.DatabaseError as e:
        print(f"Error al listar conversaciones: {e}")
        return []
    finally:
        if conn:
            conn.close()

def obtener_mensajes_por_conversacion(conversation_id: int) -> List[Dict]:
    """Obtiene todos los mensajes de una conversación específica."""
    conn = get_connection()
    if not conn:
        return []
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT EMISOR, CONTENIDO, ID_MENSAJE
            FROM ADMIN.MENSAJES
            WHERE ID_CHAT = :1
            ORDER BY ID_MENSAJE ASC
        """, [conversation_id])

        mensajes = []
        for row in cursor.fetchall():
            contenido = row[1].read() if hasattr(row[1], 'read') else str(row[1])
            mensajes.append({
                "role": "user" if row[0].lower() == "usuario" else "assistant",
                "content": contenido
            })
        return mensajes
    except oracledb.DatabaseError as e:
        print(f"Error al obtener mensajes: {e}")
        return []
    finally:
        if conn:
            conn.close()

def eliminar_conversacion(conversation_id: int) -> bool:
    """Elimina una conversación y todos sus mensajes asociados."""
    conn = get_connection()
    if not conn:
        return False
    try:
        cursor = conn.cursor()

        cursor.execute("""
            DELETE FROM ADMIN.MENSAJES
            WHERE ID_CHAT = :1
        """, [conversation_id])

        cursor.execute("""
            DELETE FROM ADMIN.CHATS
            WHERE ID_CHAT = :1
        """, [conversation_id])

        conn.commit()
        print(f"✅ Conversación {conversation_id} eliminada correctamente")
        return True
    except oracledb.DatabaseError as e:
        print(f"❌ Error al eliminar conversación: {e}")
        conn.rollback()
        return False
    finally:
        if conn:
            conn.close()
