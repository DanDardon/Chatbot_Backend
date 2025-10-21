import os
import logging
from typing import Optional, List, Dict
from pathlib import Path
from dotenv import load_dotenv

env_path = Path(__file__).parent.parent / '.env'
load_dotenv(dotenv_path=env_path)

logger = logging.getLogger(__name__)

# Intentar importar Gemini, pero no fallar si no está disponible
GEMINI_ENABLED = False
model = None

try:
    import google.generativeai as genai
    GEMINI_API_KEY = os.getenv('GEMINI_API_KEY')

    if GEMINI_API_KEY and GEMINI_API_KEY != 'your_gemini_api_key_here':
        genai.configure(api_key=GEMINI_API_KEY)
        # Intentar con los modelos más recientes disponibles (Gemini 2.0/2.5)
        model_names = [
            'models/gemini-2.0-flash',
            'models/gemini-2.5-flash',
            'gemini-2.0-flash',
            'gemini-2.5-flash',
            'models/gemini-2.0-flash-exp',
            'models/gemini-flash-latest'
        ]
        model_loaded = False

        for model_name in model_names:
            try:
                model = genai.GenerativeModel(model_name)
                # Hacer una prueba simple para verificar que funciona
                test_response = model.generate_content("Hola")
                GEMINI_ENABLED = True
                model_loaded = True
                logger.info(f"✅ Gemini AI activado (modelo: {model_name})")
                break
            except Exception as e:
                logger.debug(f"⚠️ Modelo {model_name} no disponible: {str(e)[:100]}")
                continue

        if not model_loaded:
            logger.warning("⚠️ Ningún modelo de Gemini disponible - usando modo fallback")
    else:
        logger.warning("⚠️ Gemini API key no configurada - usando modo fallback")
except ImportError:
    logger.warning("⚠️ google-generativeai no instalado - usando modo fallback")
    logger.info("💡 Para instalar: pip install google-generativeai")
except Exception as e:
    logger.error(f"⚠️ Error al inicializar Gemini: {e} - usando modo fallback")

SINTOMAS_EMERGENCIA = [
    "dolor de pecho", "dolor en el pecho", "opresion en el pecho",
    "dificultad para respirar", "falta de aire", "no puedo respirar",
    "sangrado severo", "sangrado abundante", "hemorragia",
    "confusion mental", "confusion", "desorientado", "desorientacion",
    "convulsiones", "convulsion", "ataque",
    "perdida de conciencia", "desmayo", "me desmaye",
    "vision borrosa repentina", "perdida de vision",
    "paralisis", "no puedo mover", "entumecimiento severo",
    "dolor abdominal severo", "dolor abdominal intenso"
]

PROMPT_SISTEMA = """Eres un médico virtual. REGLA CRÍTICA: Lee TODO el historial antes de responder.

🚨 INSTRUCCIONES OBLIGATORIAS:

1. ANALIZA EL HISTORIAL:
   - ¿Ya diagnosticaste algo? → Menciónalo explícitamente
   - ¿Usuario pregunta por alternativas? → Compara con tu recomendación original
   - ¿Pregunta de seguimiento? → Responde directamente, NO repitas todo

2. ESCENARIOS:

📋 DIAGNÓSTICO INICIAL (primera consulta):
**Posible diagnóstico:** [Nombre]
**Descripción:** [1-2 líneas]
**Tratamiento:**
• Medicamento: [Nombre]
• Dosis: [Ej: "400mg cada 6-8h"]
• Duración: [Ej: "3-5 días"]
**Recomendaciones:**
• [Punto 1]
• [Punto 2]

🔄 ALTERNATIVAS (usuario pregunta "qué más aparte de X"):
FORMATO EXACTO:
"Para tu [DIAGNÓSTICO YA DADO], te recomendé [MEDICAMENTO ORIGINAL]. Alternativas:

**Opción 1: [Nombre]**
• Dosis: [específica]
• ✅ Ventaja: [breve]
• ⚠️ Desventaja: [breve]

**Opción 2: [Nombre]**
• Dosis: [específica]
• ✅ Ventaja: [breve]
• ⚠️ Desventaja: [breve]

Recomiendo [medicamento] porque [razón]."

💬 SEGUIMIENTO (dudas sobre diagnóstico/tratamiento):
- Menciona el diagnóstico previo directamente
- Responde la duda específica
- Máximo 4 líneas

❌ PROHIBIDO:
- Pedir información que YA diste
- Decir "necesito más información" si ya diagnosticaste
- Hacer preguntas repetitivas
- Ignorar el contexto previo

✅ OBLIGATORIO:
- Medicamentos siempre con dosis exactas
- Respuestas directas y concisas
- Tono profesional pero cercano"""

def detectar_emergencia_medica(texto: str) -> bool:
    """Detecta si el mensaje contiene indicadores de emergencia médica."""
    texto_lower = texto.lower()
    return any(sintoma in texto_lower for sintoma in SINTOMAS_EMERGENCIA)

def generar_alerta_emergencia() -> str:
    """Genera mensaje de alerta para situaciones de emergencia."""
    return """🚨 **ALERTA DE EMERGENCIA** 🚨

Los síntomas que describes podrían indicar una situación GRAVE que requiere atención médica INMEDIATA.

⚠️ **ACCIONES URGENTES:**
1. Llama al número de emergencias (911 o el de tu país)
2. Acude al hospital más cercano
3. No conduzcas tú mismo si es posible
4. Mantén la calma y explica tus síntomas claramente

**NO ESPERES** - Busca ayuda profesional AHORA."""

def agregar_disclaimer_medico(respuesta: str, nivel_urgencia: str = "bajo") -> str:
    """Agrega disclaimer médico apropiado según el nivel de urgencia."""

    if nivel_urgencia == "emergencia":
        return f"{generar_alerta_emergencia()}\n\n{respuesta}"

    disclaimer = "\n\n---\n\n⚠️ **RECORDATORIO IMPORTANTE:** "

    if nivel_urgencia == "alto":
        disclaimer += "Esta evaluación es preliminar. Tus síntomas requieren **consulta médica pronto**. No sustituye diagnóstico profesional."
    elif nivel_urgencia == "medio":
        disclaimer += "Esta es una orientación general. Si los síntomas persisten o empeoran, consulta a un médico."
    else:
        disclaimer += "Esta información es orientativa y NO reemplaza una consulta médica profesional."

    return respuesta + disclaimer

def generar_respuesta_con_gemini(
    mensaje_usuario: str,
    sintomas_detectados: List[str],
    contexto: Dict,
    diagnostico_previo: Optional[str] = None,
    historial_conversacion: Optional[List[Dict]] = None
) -> tuple[str, str]:
    """
    Genera respuesta usando Gemini AI con contexto de conversación completo.

    Args:
        mensaje_usuario: Mensaje actual del usuario
        sintomas_detectados: Lista de síntomas identificados
        contexto: Contexto médico actual
        diagnostico_previo: Diagnóstico previo si existe
        historial_conversacion: Historial completo de mensajes [{"role": "user"/"assistant", "content": "..."}]

    Returns:
        tuple: (respuesta, nivel_urgencia)
        nivel_urgencia puede ser: "emergencia", "alto", "medio", "bajo"
    """

    # Detectar emergencia primero
    if detectar_emergencia_medica(mensaje_usuario):
        return generar_alerta_emergencia(), "emergencia"

    # Si Gemini no está habilitado, retornar None para usar fallback
    if not GEMINI_ENABLED:
        logger.warning("Gemini no disponible - usando lógica tradicional")
        return None, "medio"

    try:
        # Construir el historial de conversación para Gemini
        conversacion_formateada = ""
        if historial_conversacion and len(historial_conversacion) >= 1:
            conversacion_formateada = "\n\n" + "="*70 + "\n"
            conversacion_formateada += "📜 CONVERSACIÓN PREVIA - ¡LEE TODO ANTES DE RESPONDER!\n"
            conversacion_formateada += "="*70 + "\n\n"
            # Solo incluir los últimos 10 mensajes para no exceder límites
            historial_reciente = historial_conversacion[-10:]
            for i, msg in enumerate(historial_reciente, 1):
                rol = "👤 USUARIO" if msg["role"] == "user" else "�� TÚ (ASISTENTE)"
                contenido = msg.get('content', '')
                conversacion_formateada += f"[{i}] {rol}:\n{contenido}\n"
                conversacion_formateada += "-"*70 + "\n"

            conversacion_formateada += "\n🚨 CRÍTICO: Esta es tu conversación previa con el paciente.\n"
            conversacion_formateada += "- Si ya diste un diagnóstico → menciónalo\n"
            conversacion_formateada += "- Si pregunta por alternativas → compara con tu recomendación original\n"
            conversacion_formateada += "- NO pidas datos que ya te dieron\n"
            conversacion_formateada += "="*70 + "\n"
        else:
            logger.warning("⚠️ Sin historial previo - primera interacción")

        # Construir contexto enriquecido
        contexto_medico = f"""
📨 MENSAJE NUEVO DEL USUARIO:
{mensaje_usuario}
{conversacion_formateada}
🩺 CONTEXTO CLÍNICO:
- Síntomas detectados: {', '.join(sintomas_detectados) if sintomas_detectados else 'Ninguno detectado en este mensaje'}
- Temperatura: {contexto.get('temperatura', 'No reportada')}°C
"""

        if diagnostico_previo:
            contexto_medico += f"- Diagnóstico preliminar previo: {diagnostico_previo}\n"

        if contexto.get('triage', {}).get('respuestas'):
            resp_triage = contexto['triage']['respuestas']
            contexto_medico += f"""
INFORMACIÓN ADICIONAL DEL TRIAJE:
- Intensidad del malestar: {resp_triage.get('intensidad', 'No especificada')}/10
- Duración: {resp_triage.get('duracion', 'No especificada')}
- Otros síntomas: {', '.join([k for k, v in resp_triage.items() if v and k not in ['temperatura', 'intensidad', 'duracion']])}
"""

        prompt_completo = f"{PROMPT_SISTEMA}\n\n{contexto_medico}"

        # Log del prompt para debugging (solo primeros 500 caracteres)
        logger.debug(f"🔍 Prompt enviado a Gemini (primeros 500 chars):\n{prompt_completo[:500]}...")
        logger.debug(f"📏 Longitud total del prompt: {len(prompt_completo)} caracteres")

        # Llamar a Gemini
        response = model.generate_content(prompt_completo)
        respuesta_generada = response.text

        logger.debug(f"💬 Respuesta de Gemini (primeros 200 chars): {respuesta_generada[:200]}...")

        # Determinar nivel de urgencia basado en la respuesta
        nivel_urgencia = determinar_nivel_urgencia(mensaje_usuario, sintomas_detectados, contexto)

        # Agregar disclaimer apropiado
        respuesta_final = agregar_disclaimer_medico(respuesta_generada, nivel_urgencia)

        # Log para debug
        logger.info(f"✅ Respuesta generada con Gemini (urgencia: {nivel_urgencia}) | Historial: {len(historial_conversacion) if historial_conversacion else 0} mensajes")
        if historial_conversacion:
            logger.debug(f"Historial enviado a Gemini: {len(historial_conversacion)} mensajes")
            logger.debug(f"Prompt completo length: {len(prompt_completo)} caracteres")
        return respuesta_final, nivel_urgencia

    except Exception as e:
        logger.error(f"❌ Error al generar respuesta con Gemini: {e}")
        return None, "medio"

def determinar_nivel_urgencia(mensaje: str, sintomas: List[str], contexto: Dict) -> str:
    """Determina el nivel de urgencia basado en síntomas y contexto."""

    # Emergencia ya fue detectada antes
    if detectar_emergencia_medica(mensaje):
        return "emergencia"

    # Alto: fiebre muy alta, múltiples síntomas severos
    temp = contexto.get('temperatura')
    if temp is not None and temp >= 39.5:
        return "alto"

    sintomas_alto_riesgo = [
        "dolor abdominal", "vomitos persistentes", "diarrea severa",
        "dolor intenso", "fiebre alta", "rigidez de cuello"
    ]

    if any(sintoma in ' '.join(sintomas).lower() for sintoma in sintomas_alto_riesgo):
        return "alto"

    # Medio: síntomas comunes pero requieren atención
    if (temp is not None and temp >= 38.0) or len(sintomas) >= 3:
        return "medio"

    # Bajo: síntomas leves
    return "bajo"

def generar_respuesta_fallback(
    sintomas: List[str],
    enfermedad: str,
    descripcion: str,
    medicamento: Optional[tuple] = None
) -> str:
    """
    Genera respuesta cuando Gemini no está disponible.
    Formato conciso y directo al punto.
    """
    respuesta = f"**Posible diagnóstico:** {enfermedad}\n\n"

    if medicamento and len(medicamento) == 3:
        nombre, dosis, duracion = medicamento
        respuesta += f"**💊 Tratamiento recomendado:**\n"
        respuesta += f"• Medicamento: {nombre}\n"
        respuesta += f"• Dosis: {dosis}\n"
        respuesta += f"• Duración: {duracion}\n\n"
    elif medicamento:
        respuesta += f"**💊 Medicamento sugerido:** {medicamento[0]}\n\n"

    respuesta += "**💡 Recomendaciones:**\n"
    respuesta += "• Hidrátate bien\n"
    respuesta += "• Descansa lo suficiente\n"
    respuesta += "• Si los síntomas empeoran, acude al médico\n"

    return agregar_disclaimer_medico(respuesta, "medio")
