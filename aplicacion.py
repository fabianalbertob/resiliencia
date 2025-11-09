import streamlit as st
import pandas as pd
import numpy as np
# Importamos las funciones del archivo google_sheets.py
from google_sheets import get_google_sheet, get_padron_df, save_historical_record, get_historical_df
import time

# --- FUNCIONES DE LÓGICA DE NEGOCIO ---
def clasificar_paciente(diagnostico, tratamiento):
    """Clasifica el paciente basado en palabras clave en Diagnóstico o Tratamiento."""
    keywords_critico = ['DIABETES', 'INFARTO', 'ACV', 'INSUFICIENCIA']
    keywords_control = ['HIPERTENSIÓN', 'LOSARTAN', 'ENALAPRIL']
    keywords_alerta = ['COLESTEROL', 'TRIGLICÉRIDOS', 'OBESIDAD']
    
    texto = (diagnostico + " " + tratamiento).upper()
    
    if any(k in texto for k in keywords_critico):
        return 'CRÍTICO'
    elif any(k in texto for k in keywords_control):
        return 'CONTROL'
    elif any(k in texto for k in keywords_alerta):
        return 'ALERTA'
    else:
        return 'GENERAL'

# --- CONEXIÓN Y CACHEO DE DATOS ---
@st.cache_resource(ttl=3600)
def load_data():
    sheet_conn = get_google_sheet()
    if sheet_conn is None:
        st.error("❌ No se pudo conectar a Google Sheets. Verifique la llave JSON y los permisos de 'Editor'.")
        return None, None
    
    padron_df = get_padron_df(sheet_conn)
    return sheet_conn, padron_df

# --- INICIALIZACIÓN DE LA APLICACIÓN ---
st.set_page_config(layout="wide", page_title="Sistema Médico")

sheet_conn, padron_df = load_data()

# Primera verificación: la conexión falló
if sheet_conn is None:
    st.stop()

# Segunda verificación: la conexión existe, pero el DataFrame está vacío o es None
if padron_df is None or padron_df.empty:
    st.error("❌ No se pudo cargar el padrón o el archivo está vacío. Verifique la hoja de Google Sheets (ID, Contenido en A1 y Pestaña).")
    st.stop()

# --- ESTADO DE SESIÓN Y VALORES INICIALES ---
if 'search_dni' not in st.session_state:
    st.session_state.search_dni = ""
if 'current_data' not in st.session_state:
    st.session_state.current_data = None
if 'current_dni' not in st.session_state:
    st.session_state.current_dni = None

# Inicialización de valores de formulario (numéricos deben ser 0.0, no None)
if 'peso_input' not in st.session_state:
    st.session_state.peso_input = 0.0
if 'estatura_input' not in st.session_state:
    st.session_state.estatura_input = 0.0
if 'pa_input' not in st.session_state:
    st.session_state.pa_input = ""
if 'diag_input' not in st.session_state:
    st.session_state.diag_input = ""
if 'trata_input' not in st.session_state:
    st.session_state.trata_input = ""

st.title("👨‍⚕️ Sistema Médico: Padrón y Ficha de Atención")

# --- BARRA DE BÚSQUEDA ---
col_search, col_btn, col_spacer = st.columns([3, 1, 6])

with col_search:
    dni_input = st.text_input("Ingresar DNI del paciente", value=st.session_state.search_dni, key="dni_search_input")

with col_btn:
    st.markdown("<div style='margin-top: 28px;'></div>", unsafe_allow_html=True)
    buscar_btn = st.button("🔎 Buscar")

# --- BÚSQUEDA ROBUSTA POR DNI ---
if buscar_btn or st.session_state.current_dni:
    dni_a_buscar = dni_input if buscar_btn else st.session_state.current_dni

    if dni_a_buscar:
        dni_a_buscar_limpio = str(dni_a_buscar).strip()
        
        data_match = padron_df[padron_df['dni'] == dni_a_buscar_limpio]

        if not data_match.empty:
            st.session_state.current_data = data_match.iloc[0].to_dict()
            st.session_state.current_dni = dni_a_buscar_limpio
        else:
            st.warning(f"Paciente con DNI '{dni_a_buscar_limpio}' no encontrado en el padrón.")
            st.session_state.current_data = None
            st.session_state.current_dni = None

# --- FICHA DE PACIENTE ---
data = st.session_state.current_data

if data:
    st.divider()
    col1, col2, col3 = st.columns([3, 3, 2])
    
    with col1:
        st.subheader("Datos del Paciente")
        st.markdown(f"**DNI:** `{data.get('dni', 'N/A')}`")
        st.markdown(f"**Nombre:** `{data.get('nombre', 'N/A')}`")
        st.markdown(f"**Beneficio:** `{data.get('beneficio', 'N/A')}`")

    with col2:
        st.subheader("Información Base")
        st.markdown(f"**Domicilio:** `{data.get('domicilio', 'N/A')}`")
        st.markdown(f"**Telefono:** `{data.get('telefono', 'N/A')}`")
        st.markdown(f"**Apellido:** `{data.get('apellido', 'N/A')}`")

    with col3:
        history_df = get_historical_df(sheet_conn)
        fecha_actual = pd.to_datetime('today')
        trimestre_actual_str = f"Q{fecha_actual.quarter}-{fecha_actual.year}"
        
        atenciones_trimestre = history_df[
            (history_df['DNI'] == st.session_state.current_dni) &
            (history_df['Trimestre'] == trimestre_actual_str)
        ].shape[0]
        
        st.markdown("---")
        st.markdown(f"**Atenciones Trimestrales ({trimestre_actual_str}):** `{atenciones_trimestre}`")
        st.markdown("---")

    st.divider()

    # --- FORMULARIO DE ATENCIÓN ---
    st.subheader("📝 Registro de Atención Médica")
    
    with st.form("atencion_form", clear_on_submit=False):
        col_medidas1, col_medidas2 = st.columns(2)
        
        with col_medidas1:
            peso = st.number_input("Peso (kg)", min_value=0.0, step=0.1, key="peso_input", value=st.session_state.peso_input)
        
        with col_medidas2:
            estatura = st.number_input("Estatura (m)", min_value=0.0, step=0.01, key="estatura_input", value=st.session_state.estatura_input)
        
        pa = st.text_input("Presión Arterial (PA) mm/Hg", placeholder="Ej: 120/80", key="pa_input", value=st.session_state.pa_input)
        
        imc_calculado = 0.0
        if peso > 0 and estatura > 0:
            imc_calculado = round(peso / (estatura ** 2), 2)
        
        st.metric(label="Índice de Masa Corporal (IMC)", value=f"{imc_calculado}", delta="")
        
        diagnostico = st.text_area("Diagnóstico", key="diag_input", value=st.session_state.diag_input)
        tratamiento = st.text_area("Tratamiento / Observaciones", key="trata_input", value=st.session_state.trata_input)
        
        clasificacion = clasificar_paciente(diagnostico, tratamiento)
        
        color_map = {
            'CRÍTICO': 'background-color: #6a0dad; color: white; padding: 10px; border-radius: 5px;',
            'CONTROL': 'background-color: #00bfff; color: white; padding: 10px; border-radius: 5px;',
            'ALERTA': 'background-color: #ff4500; color: white; padding: 10px; border-radius: 5px;',
            'GENERAL': 'background-color: #2e8b57; color: white; padding: 10px; border-radius: 5px;'
        }
        
        st.markdown(f"<div style='{color_map.get(clasificacion, color_map['GENERAL'])}'>**Clasificación de Riesgo:** {clasificacion}</div>", unsafe_allow_html=True)
        st.markdown("---")
        
        guardar_btn = st.form_submit_button("💾 Guardar y Actualizar Registro")

        # --- Lógica de Guardado ---
        if guardar_btn:
            fecha_actual = pd.to_datetime('today')
            trimestre_actual = f"Q{fecha_actual.quarter}-{fecha_actual.year}"

            record_data = {
                'DNI': st.session_state.current_dni,
                'Fecha': fecha_actual.strftime('%Y-%m-%d %H:%M:%S'),
                'Trimestre': trimestre_actual,
                'Nombre': data.get('nombre'),
                'Apellido': data.get('apellido'), 
                'PA_mmhg': pa,
                'Peso_kg': peso,
                'Estatura_m': estatura,
                'IMC': imc_calculado,
                'Diagnostico': diagnostico,
                'Tratamiento': tratamiento,
                'Clasificacion': clasificacion
            }

            try:
                if save_historical_record(sheet_conn, record_data):
                    st.success("🎉 Registro guardado y actualizado en Google Sheets.")
                    
                    st.session_state.peso_input = 0.0
                    st.session_state.estatura_input = 0.0
                    st.session_state.pa_input = ""
                    st.session_state.diag_input = ""
                    st.session_state.trata_input = ""
                    
                    load_data.clear()
                    st.rerun()
                else:
                    st.error("❌ Error al guardar en Google Sheets. Revisar logs.")
            
            except Exception as e:
                st.error(f"❌ Error inesperado al procesar el guardado: {e}")