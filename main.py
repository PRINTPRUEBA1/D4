# --- 1. IMPORTACIONES ---
import os
from fastapi import FastAPI, HTTPException, Depends
from pydantic import BaseModel
from dotenv import load_dotenv
import google.generativeai as genai
import psycopg2
from psycopg2.extras import RealDictCursor # Facilita la obtención de resultados como diccionarios

# --- 2. CONFIGURACIÓN INICIAL ---
# Carga las variables desde el archivo .env (para desarrollo local)
load_dotenv()

# Configura la API de Gemini
genai.configure(api_key=os.getenv("GEMINI_API_KEY"))

# Obtiene la URL de la base de datos
DATABASE_URL = os.getenv("DATABASE_URL")

# Define constantes para la estructura de la base de datos para fácil mantenimiento
NOMBRE_TABLA = '"ARANCELES EC-EEUU"'
COLUMNAS_DISPONIBLES = '"ReportingCo", "PartnerCountry", "Year", "Revision", "ProductCode", "ProductDescription", "AVE"'

# --- 3. INICIALIZACIÓN DE LA APLICACIÓN FASTAPI ---
app = FastAPI(
    title="API de Consulta de Aranceles con IA",
    description="Una API que traduce lenguaje natural a consultas SQL seguras y las ejecuta en una base de datos.",
    version="2.0.0", # Versión robusta y segura
)

# --- 4. MODELO DE DATOS DE ENTRADA ---
class PreguntaUsuario(BaseModel):
    pregunta: str

# --- 5. GESTIÓN DE LA CONEXIÓN A LA BASE DE DATOS (Patrón recomendado en FastAPI) ---
def get_db_connection():
    """
    Crea y gestiona una conexión a la base de datos por cada petición.
    Se asegura de que la conexión siempre se cierre.
    """
    conn = None
    try:
        conn = psycopg2.connect(dsn=DATABASE_URL)
        yield conn
    except psycopg2.OperationalError as e:
        # Error si no se puede conectar a la base de datos (URL incorrecta, etc.)
        print(f"ERROR DE CONEXIÓN A LA BASE DE DATOS: {e}")
        raise HTTPException(status_code=503, detail="Servicio de base de datos no disponible.")
    finally:
        if conn:
            conn.close()

# --- 6. ENDPOINTS DE LA API ---

@app.get("/", summary="Endpoint de Bienvenida")
def bienvenida():
    """Muestra un mensaje de bienvenida y dirige a la documentación."""
    return {"mensaje": "API de Aranceles activa. Visita /docs para la documentación interactiva."}

@app.post("/ask", summary="Procesa una pregunta del usuario")
async def procesar_pregunta(datos: PreguntaUsuario, conn=Depends(get_db_connection)):
    """
    Toma una pregunta en lenguaje natural, la convierte en SQL, la valida,
    la ejecuta de forma segura y devuelve los resultados.
    """
    # --- ETAPA 1: GENERAR SQL CON IA ---
    prompt = f"""
    Tu tarea es convertir la pregunta del usuario en una única consulta SQL SELECT para una base de datos PostgreSQL.
    La tabla se llama {NOMBRE_TABLA}.
    Solo puedes usar estas columnas: {COLUMNAS_DISPONIBLES}.
    La columna "ProductDescription" está en español; usa el operador ILIKE para búsquedas de texto flexibles.
    Si la pregunta del usuario es ambigua, vaga o no se puede convertir en una consulta SQL, responde ÚNICAMENTE con la palabra 'ERROR'.
    Nunca uses UPDATE, DELETE, INSERT o cualquier otro comando que no sea SELECT.
    Pregunta del usuario: "{datos.pregunta}"
    Genera únicamente el código SQL.
    """
    try:
        model = genai.GenerativeModel('gemini-1.5-flash')
        response = model.generate_content(prompt)
        sql_query_generada = response.text.replace("```sql", "").replace("```", "").strip()
        print(f"IA Generó: '{sql_query_generada}'")
    except Exception as e:
        print(f"ERROR LLAMANDO A LA API DE GEMINI: {e}")
        raise HTTPException(status_code=502, detail="No se pudo contactar al servicio de IA.")

    # --- ETAPA 2: VALIDACIÓN DEL SQL GENERADO ---

    # 2.1: Validar si la IA pudo procesar la pregunta