# --- 1. IMPORTACIONES ---
import os
from fastapi import FastAPI, HTTPException, Depends
from pydantic import BaseModel
from dotenv import load_dotenv
import google.generativeai as genai
import psycopg2
from psycopg2.extras import RealDictCursor

# --- 2. CONFIGURACIÓN INICIAL ---
load_dotenv()
genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
DATABASE_URL = os.getenv("DATABASE_URL")

# --- CORRECCIÓN DEFINITIVA: Nombres de columnas con comillas dobles ---
NOMBRE_TABLA = '"ARANCELES EC-EEUU"'
COLUMNAS_DISPONIBLES = '"ReportingCo", "PartnerCountry", "Year", "Revision", "ProductCode", "ProductDescription", "AVE"'

# --- 3. INICIALIZACIÓN DE LA APLICACIÓN FASTAPI ---
app = FastAPI(
    title="API de Consulta de Aranceles con IA",
    description="Una API que traduce lenguaje natural a consultas SQL seguras y las ejecuta en una base de datos.",
    version="3.0.0", # Versión final con corrección de mayúsculas
)

# --- 4. MODELO DE DATOS DE ENTRADA ---
class PreguntaUsuario(BaseModel):
    pregunta: str

# --- 5. GESTIÓN DE LA CONEXIÓN A LA BASE DE DATOS ---
def get_db_connection():
    conn = None
    try:
        conn = psycopg2.connect(dsn=DATABASE_URL)
        yield conn
    except psycopg2.OperationalError as e:
        print(f"ERROR DE CONEXIÓN A LA BASE DE DATOS: {e}")
        raise HTTPException(status_code=503, detail="Servicio de base de datos no disponible.")
    finally:
        if conn:
            conn.close()

# --- 6. ENDPOINTS DE LA API ---
@app.get("/", summary="Endpoint de Bienvenida")
def bienvenida():
    return {"mensaje": "API de Aranceles activa. Visita /docs para la documentación interactiva."}

@app.post("/ask", summary="Procesa una pregunta del usuario")
async def procesar_pregunta(datos: PreguntaUsuario, conn=Depends(get_db_connection)):
    # --- ETAPA 1: GENERAR SQL CON IA ---
    prompt = f"""
    Tu tarea es convertir la pregunta del usuario en una única consulta SQL SELECT para una base de datos PostgreSQL.
    La tabla se llama {NOMBRE_TABLA}.
    Solo puedes usar estas columnas: {COLUMNAS_DISPONIBLES}.
    La columna "ProductDescription" está en español; usa el operador ILIKE para búsquedas de texto flexibles.
    Si la pregunta del usuario es ambigua, vaga o no se puede convertir en una consulta SQL, responde ÚNICAMENTE con la palabra 'ERROR'.
    Nunca uses UPDATE, DELETE, INSERT o cualquier otro comando que no sea SELECT.
    La consulta SQL que generes DEBE usar comillas dobles para todos los identificadores de columna. Ejemplo: SELECT "ProductDescription", "AVE" FROM "ARANCELES EC-EEUU" WHERE "ProductDescription" ILIKE '%cacao%';
    Pregunta del usuario: "{datos.pregunta}"
    Genera únicamente el código SQL.
    """
    try:
        model = genai.GenerativeModel('gemini-1.5-flash')
        response = model.generate_content(prompt)
        sql_query_generada = response.text.replace("```sql", "").replace("```", "").strip()
        print(f"IA Generó: '{sql_query_generada}'")
    except Exception as e:
        raise HTTPException(status_code=502, detail="No se pudo contactar al servicio de IA.")

    # --- ETAPA 2: VALIDACIÓN DEL SQL GENERADO ---
    if sql_query_generada.strip().upper() == 'ERROR':
        raise HTTPException(status_code=400, detail="La pregunta es demasiado vaga. Por favor, sé más específico.")

    if not sql_query_generada.lower().strip().startswith("select"):
        raise HTTPException(status_code=403, detail="Operación no permitida: Solo se permiten consultas SELECT.")

    # --- ETAPA 3: EJECUTAR CONSULTA EN LA BASE DE DATOS ---
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute(sql_query_generada)
            resultados_db = cursor.fetchall()
            print(f"Resultados obtenidos: {len(resultados_db)} fila(s)")
    except psycopg2.Error as e:
        print(f"ERROR DE EJECUCIÓN DE SQL: {e}")
        # Este error ahora devolverá un código 400, no un 200 OK.
        raise HTTPException(
            status_code=400,
            detail=f"La consulta generada por la IA es inválida. Error: {e}"
        )

    # --- ETAPA 4: DEVOLVER RESPUESTA EXITOSA ---
    return {
        "pregunta_original": datos.pregunta,
        "sql_ejecutado": sql_query_generada,
        "datos": resultados_db
    }