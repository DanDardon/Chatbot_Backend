from flask import Flask, request, jsonify
from flask_cors import CORS
from dotenv import load_dotenv
import os
from pathlib import Path
from database import (
    crear_nueva_conversacion,
    listar_conversaciones_por_usuario,
    obtener_mensajes_por_conversacion,
    eliminar_conversacion
)
from logic import registrar_usuario, verificar_credenciales, procesar_mensaje

env_path = Path(__file__).parent / '.env'
load_dotenv(dotenv_path=env_path)

app = Flask(__name__)
CORS(app, resources={r"/*": {"origins": "*"}})

@app.route("/register", methods=["POST"])
def register():
    data = request.get_json()
    if not data:
        return jsonify({"error": "No data provided"}), 400

    nombre = data.get("nombre")
    correo = data.get("correo")
    password = data.get("password")

    if not all([nombre, correo, password]):
        return jsonify({"error": "Missing required fields"}), 400

    success, message = registrar_usuario(nombre, correo, password)

    if success:
        user_id = verificar_credenciales(correo, password)
        if user_id:
            return jsonify({
                "mensaje": message,
                "user_id": user_id,
                "nombre": nombre
            }), 201
        return jsonify({"mensaje": message}), 201
    else:
        return jsonify({"error": message}), 409

@app.route("/login", methods=["POST"])
def login():
    data = request.get_json()
    if not data:
        return jsonify({"error": "No data provided"}), 400

    correo = data.get("correo")
    password = data.get("password")

    if not correo or not password:
        return jsonify({"error": "Missing email or password"}), 400

    user_id = verificar_credenciales(correo, password)

    if user_id:
        from database import get_connection
        conn = get_connection()
        if conn:
            try:
                cursor = conn.cursor()
                cursor.execute("SELECT NOMBRE FROM ADMIN.USUARIOS WHERE ID_USUARIO = :1", [user_id])
                row = cursor.fetchone()
                nombre = row[0] if row else "Usuario"
            except:
                nombre = "Usuario"
            finally:
                conn.close()
        else:
            nombre = "Usuario"

        return jsonify({
            "mensaje": "Login exitoso",
            "user_id": user_id,
            "nombre": nombre
        }), 200
    else:
        return jsonify({"error": "Invalid credentials"}), 401

@app.route("/conversaciones", methods=["GET"])
def get_conversaciones():
    user_id = request.args.get("user_id")
    if not user_id:
        return jsonify({"error": "Missing user_id"}), 400

    conversaciones = listar_conversaciones_por_usuario(user_id)
    return jsonify(conversaciones), 200

@app.route("/nueva-conversacion", methods=["POST"])
def nueva_conversacion():
    data = request.get_json()
    if not data:
        return jsonify({"error": "No data provided"}), 400

    user_id = data.get("user_id")
    print(f"DEBUG nueva-conversacion: user_id recibido = {user_id}, data completa = {data}")

    if not user_id or user_id == "undefined":
        return jsonify({"error": "Missing or invalid user_id", "received": str(user_id)}), 400

    conv_id = crear_nueva_conversacion(user_id, "Nueva conversación")
    if conv_id:
        return jsonify({
            "id_conversacion": conv_id,
            "titulo": "Nueva conversación",
            "fecha_inicio": ""
        }), 201
    else:
        return jsonify({"error": "Failed to create conversation"}), 500

@app.route("/conversacion/<conversation_id>", methods=["GET", "DELETE"])
def get_conversacion(conversation_id):
    if request.method == "DELETE":
        success = eliminar_conversacion(int(conversation_id))
        if success:
            return jsonify({"mensaje": "Conversación eliminada correctamente"}), 200
        else:
            return jsonify({"error": "Error al eliminar conversación"}), 500

    mensajes = obtener_mensajes_por_conversacion(conversation_id)
    return jsonify(mensajes), 200

@app.route("/mensaje", methods=["POST"])
def enviar_mensaje():
    data = request.get_json()
    if not data:
        return jsonify({"error": "No data provided"}), 400

    user_id = data.get("user_id")
    conversacion_id = data.get("conversacion_id")
    contenido = data.get("contenido")

    if not all([user_id, conversacion_id, contenido]):
        return jsonify({"error": "Missing required fields"}), 400

    try:
        respuesta = procesar_mensaje(user_id, contenido, conversacion_id)
        return jsonify({"respuesta": respuesta}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/feedback", methods=["POST"])
def feedback():
    """Endpoint para recibir retroalimentación del usuario sobre respuestas"""
    data = request.get_json()
    if not data:
        return jsonify({"error": "No data provided"}), 400

    message_index = data.get("message_index")
    is_positive = data.get("is_positive")
    timestamp = data.get("timestamp")

    import logging
    logger = logging.getLogger(__name__)

    feedback_type = "👍 POSITIVO" if is_positive else "👎 NEGATIVO"
    logger.info(f"📊 Feedback recibido: {feedback_type} | Mensaje #{message_index} | {timestamp}")

    return jsonify({"status": "ok", "message": "Feedback recibido"}), 200

@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"}), 200

if __name__ == '__main__':
    app.run(debug=True, port=3000, host='0.0.0.0')
