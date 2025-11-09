import gspread
import pandas as pd
import unidecode
import os
import json
from io import StringIO
from gspread.utils import rowcol_to_a1
from gspread.exceptions import APIError, WorksheetNotFound, SpreadsheetNotFound

# --- CONFIGURACIÓN CRÍTICA ---
# Nombre de la variable de entorno que contendrá el JSON completo (para Streamlit Cloud)
GCP_SECRET_KEY = "GCP_SA_CREDENTIALS"

# Ruta local de las credenciales (para desarrollo en VS Code)
SERVICE_ACCOUNT_FILE_LOCAL = "credenciales/service_account.json"

# ID DE SU HOJA DE CÁLCULO
SHEET_ID = "1mA52azLTK3w0l_2bQSKJa7aWgNqnkXrB29y35ixKTq8"
SHEET_NAME_HISTORY = "Registro_Historico"
# -----------------------------


def normalize_col_name(col):
    """Normaliza el nombre de la columna para la búsqueda y uso interno."""
    return unidecode.unidecode(col).strip().lower().replace(" ", "")


# --- LÓGICA DE CONEXIÓN Y BÚSQUEDA ---


def get_google_sheet(sheet_id=SHEET_ID):
    """
    Autentica con credenciales. Intenta leer del entorno (Streamlit Secrets) primero,
    y luego del archivo local.
    """
    creds = None

    # 1. Intentar cargar desde Streamlit Secrets (Variable de Entorno/Nube)
    if GCP_SECRET_KEY in os.environ:
        try:
            # Los secretos de Streamlit Cloud suelen inyectarse como JSON en un string
            creds_info = json.loads(os.environ[GCP_SECRET_KEY])
            gc = gspread.service_account_from_dict(creds_info)
            print("✅ Autenticación exitosa desde Streamlit Secrets.")
        except Exception as e:
            print(
                f"!!! ERROR: Falló la decodificación de la variable de entorno ({GCP_SECRET_KEY}). {e}"
            )
            return None

    # 2. Si no hay secreto o falló, intentar cargar desde archivo local
    elif os.path.exists(SERVICE_ACCOUNT_FILE_LOCAL):
        try:
            gc = gspread.service_account(filename=SERVICE_ACCOUNT_FILE_LOCAL)
            print("✅ Autenticación exitosa desde archivo local.")
        except Exception as e:
            print(f"!!! ERROR: Falló la autenticación del archivo JSON local. {e}")
            return None

    # 3. Fallo total
    else:
        print(
            f"!!! ERROR CRÍTICO: No se encontró la variable de entorno '{GCP_SECRET_KEY}' ni el archivo local '{SERVICE_ACCOUNT_FILE_LOCAL}'."
        )
        return None

    # Abrir la hoja de cálculo
    try:
        sheet = gc.open_by_key(sheet_id)
        return sheet
    except SpreadsheetNotFound:
        print(
            f"!!! ERROR: Archivo con ID '{sheet_id}' no encontrado. Confirme el ID y permisos de Editor."
        )
        return None
    except Exception as e:
        print(
            f"!!! ERROR: Falló la apertura de la hoja por API/Permisos ({type(e).__name__}): {e}"
        )
        return None


def find_padron_worksheet(sheet):
    """Busca la pestaña que contenga una columna llamada 'DNI' (normalizada)."""
    if sheet is None:
        return None
    all_worksheets = sheet.worksheets()

    for ws in all_worksheets:
        if ws.title == SHEET_NAME_HISTORY:
            continue
        print(f"-> Escaneando pestaña: {ws.title}")
        try:
            headers = ws.row_values(1)
            if not headers:
                continue

            normalized_headers = [normalize_col_name(h) for h in headers]

            if "dni" in normalized_headers:
                print(f"✅ Padrón encontrado en la pestaña: {ws.title}")
                return ws
        except Exception as e:
            # Captura API Errors o errores de red al escanear la pestaña
            print(
                f"   Error al escanear la pestaña '{ws.title}' ({type(e).__name__}): {e}"
            )
            continue

    print("❌ ERROR CRÍTICO: No se encontró ninguna pestaña con la columna 'DNI'.")
    return None


# --- LÓGICA DE LECTURA ROBUSTA ---


def get_padron_df(sheet):
    """Obtiene el DataFrame del padrón usando la pestaña identificada y lectura robusta por rango."""
    if sheet is None:
        return pd.DataFrame()
    worksheet = find_padron_worksheet(sheet)
    if worksheet is None:
        return pd.DataFrame()

    try:
        # 1. Determinar el rango de lectura (Filas y Columnas)
        headers = worksheet.row_values(1)

        last_col_index = len([h for h in headers if h.strip()])
        if last_col_index == 0:
            print("!!! Error: La hoja de padrón no tiene encabezados válidos.")
            return pd.DataFrame()

        # Determinamos la última fila usada (más preciso que row_count)
        # Esto requiere una lectura costosa, pero garantiza precisión si las filas están vacías.
        # Simplificaremos usando get_all_records() si la hoja no es enorme, o manteniendo la lógica original:

        # Lectura simplificada y robusta: get_all_records()
        # Es más simple, maneja mejor las filas vacías, y solo falla si la hoja es > 50,000 celdas.
        records = worksheet.get_all_records(value_render_option="UNFORMATTED_VALUE")
        df = pd.DataFrame(records)

    except APIError as api_e:
        print(
            f"\n❌ ERROR FATAL DE LECTURA DE DATOS (API): Código {api_e.response.status_code}"
        )
        print(f"   Mensaje de GSheets: {api_e}")
        return pd.DataFrame()

    except Exception as e:
        print(
            f"\n❌ ERROR FATAL DE LECTURA DE DATOS (Interno): {type(e).__name__}: {e}"
        )
        return pd.DataFrame()

    # 2. Normalización y limpieza final
    try:
        df.columns = [normalize_col_name(col) for col in df.columns]

        if "dni" in df.columns:
            # Limpieza: Convertir a string, quitar espacios, eliminar decimales (.0)
            df["dni"] = df["dni"].astype(str).str.strip().str.split(".").str[0]

        return df
    except Exception as e:
        print(f"❌ ERROR en la Normalización/Limpieza del DataFrame: {e}")
        return pd.DataFrame()


# --- FUNCIONES DE HISTÓRICO ---


def save_historical_record(sheet, data_row):
    """Guarda una nueva fila de datos en la pestaña 'Registro_Historico'."""
    if sheet is None:
        return False
    try:
        history_sheet = sheet.worksheet(SHEET_NAME_HISTORY)
    except WorksheetNotFound:
        # Si la hoja no existe, la crea con los encabezados
        headers = list(data_row.keys())
        history_sheet = sheet.add_worksheet(
            title=SHEET_NAME_HISTORY, rows="100", cols="20"
        )
        history_sheet.append_row(headers)

    try:
        values_to_write = list(data_row.values())
        # USER_ENTERED permite que las fechas y números se interpreten correctamente
        history_sheet.append_row(values_to_write, value_input_option="USER_ENTERED")
        return True
    except Exception as e:
        print(f"❌ ERROR al intentar escribir en la hoja '{SHEET_NAME_HISTORY}': {e}")
        return False


def get_historical_df(sheet):
    """Devuelve la hoja de registro histórico como un DataFrame."""
    if sheet is None:
        return pd.DataFrame(columns=["DNI", "Fecha", "Trimestre"])
    try:
        history_sheet = sheet.worksheet(SHEET_NAME_HISTORY)
        data = history_sheet.get_all_records()
        df = pd.DataFrame(data)
        # Aseguramos la existencia de las columnas clave
        if "DNI" not in df.columns:
            df["DNI"] = ""
        if "Trimestre" not in df.columns:
            df["Trimestre"] = ""
        return df
    except WorksheetNotFound:
        print(
            f"!!! ADVERTENCIA: La hoja '{SHEET_NAME_HISTORY}' no existe aún. Se creará en el primer guardado."
        )
        return pd.DataFrame(columns=["DNI", "Fecha", "Trimestre"])
