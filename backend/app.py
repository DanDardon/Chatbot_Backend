from flask import Flask, request, jsonify
from flask_cors import CORS
from backend.database import get_connection
from backend.logic import procesar_mensaje
from backend.logic import procesar_mensaje, contextos


app = Flask(__name__)
CORS(app)

@app.route("/verificar", methods=["GET"])
def verificar():
    conn = get_connection()
    if conn:
        conn.close()
        return jsonify({"conexion": "exitosa"}), 200
    else:
        return jsonify({"conexion": "fallida"}), 500

@app.route("/mensaje", methods=["POST"])
def mensaje():
    data = request.get_json()
    texto_usuario = data.get("mensaje")
    if not texto_usuario:
        return jsonify({"respuesta": "Mensaje vacío."}), 400

    respuesta = procesar_mensaje(texto_usuario)
    return jsonify({"respuesta": respuesta})


@app.route("/reiniciar", methods=["POST"])
def reiniciar():
    data = request.get_json()
    usuario = data.get("usuario")
    if usuario in contextos:
        del contextos[usuario]
    return jsonify({"estado": "reiniciado"})

if __name__ == "__main__":
    app.run(debug=True, port=3000)
