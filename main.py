# --- 1. IMPORTAR LIBRERÍAS ---
import os
import json
from fastapi import FastAPI
from pydantic import BaseModel
from dotenv import load_dotenv
import google.generativeai as genai
import psycopg2

# --- 2. CARGAR VARIABLES DE ENTORNO Y CONFIGURAR ---
load_dotenv()
genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
DATABASE_URL = os.getenv("DATABASE_URL")

# --- 3. INICIAR LA APLICACIÓN FASTAPI ---
app = FastAPI(
    title="API de Consulta de Aranceles con IA (usando Gemini)",
    description="Una API que traduce lenguaje natural a consultas SQL en una base de datos de aranceles."
)

# --- 4. DEFINIR EL FORMATO DE LA PREGUNTA ---
class PreguntaUsuario(BaseModel):
    pregunta: str

# --- 5. CREAR EL ENDPOINT PRINCIPAL DE LA API ---
@app.post("/ask")
async def procesar_pregunta(datos: PreguntaUsuario):
    print(f"Pregunta recibida: {datos.pregunta}")

    # --- PARTE 1: GENERAR SQL CON GEMINI ---
    nombre_tabla = '"ARANCELES EC-EEUU"'
    columnas_disponibles = '"ReportingCo", "PartnerCountry", "Year", "Revision", "ProductCode", "ProductDescription", "AVE"'
    
    # CORRECCIÓN: Restauramos el prompt completo que se había perdido.
    prompt = f"""
    Tu tarea es convertir la pregunta del usuario en una única consulta SQL para una base de datos PostgreSQL.
    La tabla se llama {nombre_tabla}.
    Solo puedes usar las siguientes columnas: {columnas_disponibles}.
    La consulta debe ser únicamente de tipo SELECT. Nunca uses UPDATE, DELETE o INSERT.
    La columna "ProductDescription" contiene texto en español, usa el operador ILIKE para búsquedas de texto flexibles.
    Si no puedes generar una consulta SQL basada en la pregunta, responde únicamente con la palabra 'ERROR'.
    Pregunta del usuario: "{datos.pregunta}"
    Genera únicamente el código SQL.
    """

    try:
        model = genai.GenerativeModel('gemini-1.5-flash')
        response = model.generate_content(prompt)
        sql_query_generada = response.text.replace("```sql", "").replace("```", "").strip()
        print(f"SQL Generado: {sql_query_generada}")
    except Exception as e:
        print(f"Error llamando a la API de Gemini: {e}")
        return {"error": "No se pudo contactar al servicio de IA."}

    # --- PARTE 2: EJECUTAR EL SQL EN SUPABASE ---
    resultados_db = []
    try:
        conn = psycopg2.connect(DATABASE_URL)
        cursor = conn.cursor()
        cursor.execute(sql_query_generada)
        column_names = [desc[0] for desc in cursor.description]
        resultados = cursor.fetchall()
        resultados_db = [dict(zip(column_names, row)) for row in resultados]
        print(f"Resultados de la base de datos: {resultados_db}")
        cursor.close()
        conn.close()
    except Exception as e:
        print(f"Error conectando o consultando la base de datos: {e}")
        # Este es el error que estás viendo ahora
        return {"error": "No se pudo ejecutar la consulta en la base de datos."}

    # --- PARTE 3: DEVOLVER LA RESPUESTA FINAL COMPLETA ---
    return {
        "pregunta_original": datos.pregunta,
        "respuesta_sql_generada": sql_query_generada,
        "datos_de_la_base_de_datos": resultados_db
    }

# --- Endpoint de bienvenida ---
@app.get("/")
def bienvenida():
    return {"mensaje": "¡Bienvenido a la API de Aranceles! Visita /docs para probar."}