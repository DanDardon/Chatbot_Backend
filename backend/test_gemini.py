import os
import sys
from dotenv import load_dotenv

load_dotenv()

GEMINI_API_KEY = os.getenv('GEMINI_API_KEY')

print(f"🔑 API Key encontrada: {GEMINI_API_KEY[:20] if GEMINI_API_KEY else 'NO'}...")
print(f"🔑 Longitud de API Key: {len(GEMINI_API_KEY) if GEMINI_API_KEY else 0}")

try:
    import google.generativeai as genai
    print("✅ Librería google.generativeai importada correctamente")

    genai.configure(api_key=GEMINI_API_KEY)
    print("✅ API Key configurada")

    print("\n📋 Intentando listar modelos disponibles...")
    try:
        models = genai.list_models()
        print("\n✅ Modelos disponibles:")
        for model in models:
            if 'generateContent' in model.supported_generation_methods:
                print(f"  - {model.name}")
    except Exception as e:
        print(f"❌ Error al listar modelos: {e}")

    print("\n🧪 Probando modelos recomendados (Gemini 2.0/2.5)...")
    model_names = [
        'models/gemini-2.0-flash',
        'models/gemini-2.5-flash',
        'gemini-2.0-flash',
        'gemini-2.5-flash',
        'models/gemini-2.0-flash-exp',
        'models/gemini-flash-latest'
    ]

    for model_name in model_names:
        try:
            print(f"\n🔄 Probando: {model_name}")
            model = genai.GenerativeModel(model_name)
            response = model.generate_content("Di hola")
            print(f"✅ {model_name} FUNCIONA!")
            print(f"   Respuesta: {response.text[:50]}...")
            print(f"\n🎯 MODELO RECOMENDADO PARA USAR: {model_name}")
            break
        except Exception as e:
            print(f"❌ {model_name} falló: {str(e)[:100]}")

except ImportError as e:
    print(f"❌ Error al importar google.generativeai: {e}")
    print("💡 Instala con: pip install google-generativeai")
except Exception as e:
    print(f"❌ Error general: {e}")
    import traceback
    traceback.print_exc()
