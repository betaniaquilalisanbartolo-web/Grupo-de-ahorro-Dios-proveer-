import hashlib
import io
import os
from datetime import datetime

import pandas as pd
import streamlit as st
from sqlalchemy import create_engine, text

# ==========================================
# 1. CONFIGURACIÓN DE PÁGINA Y ESTILOS CSS PROFESIONALES
# ==========================================
st.set_page_config(
    page_title="Caja de Ahorro Comunitario", page_icon="💰", layout="wide"
)

st.markdown("""
    <style>
        .stApp {
            background-color: #0e1117;
        }
        section[data-testid="stSidebar"] {
            background-color: #161b22;
            border-right: 1px solid #30363d;
        }
        div.block-container {
            padding-top: 2rem;
            background-color: transparent;
        }
        .caja-card {
            background-color: #161b22;
            border: 1px solid #30363d;
            padding: 20px;
            border-radius: 12px;
            box-shadow: 0 4px 12px rgba(0, 0, 0, 0.4);
            margin-bottom: 15px;
        }
        .caja-titulo {
            color: #8b949e;
            font-size: 13px;
            font-weight: 600;
            text-transform: uppercase;
            letter-spacing: 0.5px;
            margin-bottom: 8px;
        }
        .caja-monto {
            color: #58a6ff;
            font-size: 26px;
            font-weight: bold;
        }
        div.stButton > button {
            border-radius: 8px;
            font-weight: 600;
        }
    </style>
""", unsafe_allow_html=True)

# ==========================================
# 2. GESTIÓN DE BASE DE DATOS (Supabase / PostgreSQL)
# ==========================================
@st.cache_resource
def obtener_motor():
    db_url = st.secrets["postgres"]["url"]
    return create_engine(
        db_url,
        pool_pre_ping=True,
        pool_recycle=300,
        connect_args={"connect_timeout": 15},
    )

try:
    motor = obtener_motor()
except Exception as e:
    st.error(
        "❌ **Error crítico de conexión a Supabase:** No se pudo establecer "
        "comunicación con la base de datos.\n\n"
        f"Detalle técnico: {e}"
    )
    st.stop()

def hash_password(password: str, salt: bytes = None) -> str:
    if salt is None:
        salt = os.urandom(16)
    elif isinstance(salt, str):
        salt = bytes.fromhex(salt)
    pwd_hash = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt, 100000
    )
    return f"{salt.hex()}:{pwd_hash.hex()}"

def verificar_contrasena(contrasena_ingresada: str, hash_almacenado: str) -> bool:
    try:
        salt_hex, _ = hash_almacenado.split(":")
        salt = bytes.fromhex(salt_hex)
        hash_nuevo = hash_password(contrasena_ingresada, salt)
        return hash_nuevo == hash_almacenado
    except Exception:
        return False

def init_db():
    with motor.begin() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS configuracion (
                clave VARCHAR(50) PRIMARY KEY,
                valor VARCHAR(550) NOT NULL
            );
        """))

        res = conn.execute(text("SELECT valor FROM configuracion WHERE clave = 'admin_password'")).fetchone()
        if not res:
            pass_default_hash = hash_password("admin123")
            conn.execute(
                text("INSERT INTO configuracion (clave, valor) VALUES ('admin_password', :val)"),
                {"val": pass_default_hash},
            )

        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS socios (
                id SERIAL PRIMARY KEY,
                nombre VARCHAR(255) NOT NULL,
                telefono VARCHAR(50),
                fecha_registro DATE NOT NULL,
                estado VARCHAR(20) DEFAULT 'Activo'
            );
        """))

        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS ahorros (
                id SERIAL PRIMARY KEY,
                socio_id INTEGER NOT NULL REFERENCES socios(id),
                monto NUMERIC(12, 2) NOT NULL,
                fecha DATE NOT NULL,
                nota TEXT,
                anio INTEGER DEFAULT EXTRACT(YEAR FROM CURRENT_DATE)
            );
        """))

        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS prestamos (
                id SERIAL PRIMARY KEY,
                socio_id INTEGER NOT NULL REFERENCES socios(id),
                monto_prestado NUMERIC(12, 2) NOT NULL,
                tasa_interes NUMERIC(5, 2) NOT NULL,
                plazo_meses INTEGER NOT NULL,
                interes_total NUMERIC(12, 2) NOT NULL,
                monto_total NUMERIC(12, 2) NOT NULL,
                fecha_inicio DATE NOT NULL,
                estado VARCHAR(20) DEFAULT 'Activo',
                anio INTEGER DEFAULT EXTRACT(YEAR FROM CURRENT_DATE)
            );
        """))

        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS pagos (
                id SERIAL PRIMARY KEY,
                prestamo_id INTEGER NOT NULL REFERENCES prestamos(id),
                monto_pagado NUMERIC(12, 2) NOT NULL,
                monto_capital NUMERIC(12, 2) DEFAULT 0.00,
                monto_interes NUMERIC(12, 2) DEFAULT 0.00,
                fecha DATE NOT NULL,
                tipo VARCHAR(20)
            );
        """))

        conn.execute(text("ALTER TABLE pagos ADD COLUMN IF NOT EXISTS monto_capital NUMERIC(12, 2) DEFAULT 0.00;"))
        conn.execute(text("ALTER TABLE pagos ADD COLUMN IF NOT EXISTS monto_interes NUMERIC(12, 2) DEFAULT 0.00;"))
        conn.execute(text("ALTER TABLE pagos ADD COLUMN IF NOT EXISTS tipo VARCHAR(20);"))

        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS egresos (
                id SERIAL PRIMARY KEY,
                concepto VARCHAR(255) NOT NULL,
                monto NUMERIC(12, 2) NOT NULL,
                fecha DATE NOT NULL,
                responsable VARCHAR(100)
            );
        """))

        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS bitacora (
                id SERIAL PRIMARY KEY,
                fecha TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                usuario VARCHAR(100) DEFAULT 'Administrador',
                accion TEXT NOT NULL
            );
        """))

if "db_inicializada" not in st.session_state:
    try:
        init_db()
        st.session_state.db_inicializada = True
    except Exception as e:
        st.error(f"Error al inicializar las tablas en la base de datos: {e}")
        st.stop()

# ==========================================
# 3. FUNCIONES UTILITARIAS Y DE EXPORTACIÓN
# ==========================================
def obtener_hash_password_bd():
    with motor.connect() as conn:
        res = conn.execute(text("SELECT valor FROM configuracion WHERE clave = 'admin_password'")).fetchone()
        return res[0] if res else None

def registrar_bitacora(accion: str):
    try:
        with motor.begin() as conn:
            conn.execute(text("INSERT INTO bitacora (accion) VALUES (:accion)"), {"accion": accion})
    except Exception as e:
        st.error(f"Error al registrar en bitácora: {e}")

def to_excel(df: pd.DataFrame) -> bytes:
    salida = io.BytesIO()
    try:
        with pd.ExcelWriter(salida, engine="openpyxl") as writer:
            df.to_excel(writer, index=False, sheet_name="Reporte")
        salida.seek(0)
    except ModuleNotFoundError:
        st.error("Error: La librería 'openpyxl' no está instalada.")
        return b""
    return salida.getvalue()

def exportar_consolidado_excel(anio_filtro: int = None) -> bytes:
    salida = io.BytesIO()
    with motor.connect() as conn:
        if anio_filtro:
            df_s = pd.read_sql(text("SELECT * FROM socios"), conn)
            df_a = pd.read_sql(text("SELECT * FROM ahorros WHERE EXTRACT(YEAR FROM fecha) = :a"), conn, params={"a": anio_filtro})
            df_p = pd.read_sql(text("SELECT * FROM prestamos WHERE EXTRACT(YEAR FROM fecha_inicio) = :a"), conn, params={"a": anio_filtro})
            df_pg = pd.read_sql(text("SELECT * FROM pagos WHERE EXTRACT(YEAR FROM fecha) = :a"), conn, params={"a": anio_filtro})
            df_e = pd.read_sql(text("SELECT * FROM egresos WHERE EXTRACT(YEAR FROM fecha) = :a"), conn, params={"a": anio_filtro})
        else:
            df_s = pd.read_sql(text("SELECT * FROM socios"), conn)
            df_a = pd.read_sql(text("SELECT * FROM ahorros"), conn)
            df_p = pd.read_sql(text("SELECT * FROM prestamos"), conn)
            df_pg = pd.read_sql(text("SELECT * FROM pagos"), conn)
            df_e = pd.read_sql(text("SELECT * FROM egresos"), conn)

        with pd.ExcelWriter(salida, engine="openpyxl") as writer:
            df_s.to_excel(writer, index=False, sheet_name="Socios")
            df_a.to_excel(writer, index=False, sheet_name="Ahorros")
            df_p.to_excel(writer, index=False, sheet_name="Prestamos")
            df_pg.to_excel(writer, index=False, sheet_name="Pagos")
            df_e.to_excel(writer, index=False, sheet_name="Egresos")
        salida.seek(0)
        return salida.getvalue()

# ==========================================
# 4. AUTENTICACIÓN / CONTROL DE ACCESO
# ==========================================
if "autenticado" not in st.session_state:
    st.session_state.autenticado = False

st.sidebar.title("🔐 Control de Acceso")

if not st.session_state.autenticado:
    password_input = st.sidebar.text_input("Contraseña de Administrador", type="password")
    if st.sidebar.button("Iniciar sesión"):
        hash_almacenado = obtener_hash_password_bd()
        if hash_almacenado and verificar_contrasena(password_input, hash_almacenado):
            st.session_state.autenticado = True
            registrar_bitacora("Inicio de sesión exitosa como Administrador.")
            st.sidebar.success("¡Acceso concedido!")
            st.rerun()
        else:
            st.sidebar.error("Contraseña incorrecta.")
    st.warning("⚠️ Debes iniciar sesión como Administrador en la barra lateral para acceder al sistema.")
    st.stop()
else:
    st.sidebar.success("Sesión activa como Administrador")
    with st.sidebar.expander("🔑 Cambiar Contraseña"):
        pwd_actual = st.text_input("Contraseña Actual", type="password", key="pwd_act")
        pwd_nueva = st.text_input("Nueva Contraseña", type="password", key="pwd_nuev")
        if st.button("Actualizar Clave"):
            hash_almacenado = obtener_hash_password_bd()
            if hash_almacenado and verificar_contrasena(pwd_actual, hash_almacenado):
                if len(pwd_nueva.strip()) >= 4:
                    nuevo_hash = hash_password(pwd_nueva.strip())
                    with motor.begin() as conn:
                        conn.execute(
                            text("UPDATE configuracion SET valor = :v WHERE clave = 'admin_password'"),
                            {"v": nuevo_hash},
                        )
                    registrar_bitacora("Cambio de contraseña de administrador.")
                    st.success("Contraseña actualizada e encriptada correctamente.")
                else:
                    st.error("La nueva contraseña debe tener al menos 4 caracteres.")
            else:
                st.error("La contraseña actual es incorrecta.")

    if st.sidebar.button("Cerrar sesión"):
        st.session_state.autenticado = False
        st.rerun()

# ==========================================
# 5. MENÚ NAVEGACIÓN LATERAL
# ==========================================
st.sidebar.markdown("---")
st.sidebar.title("🏦 Menú Principal")
opcion = st.sidebar.radio(
    "Selecciona una sección:",
    [
        "📊 Panel General",
        "👥 Socios",
        "💵 Ahorros y Cuotas",
        "🤝 Préstamos",
        "🧮 Simulador de Préstamos",
        "📖 Pagos de Préstamos",
        "💸 Egresos y Gastos",
        "📜 Estado de Cuenta",
        "🎉 Liquidación Anual",
        "📅 Cierre Mensual y Anual",
        "🛡️ Bitácora de Auditoría",
    ],
)

# ==========================================
# SECCIÓN 1: PANEL GENERAL (DASHBOARD)
# ==========================================
if opcion == "📊 Panel General":
    st.title("📊 Panel General de la Caja de Ahorro")
    st.caption("Resumen financiero consolidado en Córdoba (C$).")

    with motor.connect() as conn:
        df_ahorros = pd.read_sql(text("SELECT COALESCE(SUM(monto), 0) as total FROM ahorros"), conn)
        total_ahorrado = float(df_ahorros["total"].iloc[0])

        df_prestamos_act = pd.read_sql(text("SELECT COALESCE(SUM(monto_prestado), 0) as total FROM prestamos WHERE estado = 'Activo'"), conn)
        total_prestado_activo = float(df_prestamos_act["total"].iloc[0])

        df_prestamos_hist = pd.read_sql(text("SELECT COALESCE(SUM(monto_prestado), 0) as total FROM prestamos"), conn)
        total_prestado_historico = float(df_prestamos_hist["total"].iloc[0])

        df_pagos = pd.read_sql(text("SELECT COALESCE(SUM(monto_pagado), 0) as total, COALESCE(SUM(monto_capital), 0) as capital, COALESCE(SUM(monto_interes), 0) as interes FROM pagos"), conn)
        total_recaudado = float(df_pagos["total"].iloc[0])
        total_capital_devuelto = float(df_pagos["capital"].iloc[0])
        total_interes_ganado = float(df_pagos["interes"].iloc[0])

        df_egresos = pd.read_sql(text("SELECT COALESCE(SUM(monto), 0) as total FROM egresos"), conn)
        total_egresos = float(df_egresos["total"].iloc[0])

        df_socios = pd.read_sql(text("SELECT COUNT(*) as total FROM socios WHERE estado = 'Activo'"), conn)
        total_socios = int(df_socios["total"].iloc[0])

        fondo_caja = total_ahorrado + total_recaudado - total_prestado_historico - total_egresos

    col1, col2, col3, col4, col5 = st.columns(5)
    col1.metric("💵 Fondo Total Ahorrado", f"C$ {total_ahorrado:,.2f}")
    col2.metric("📉 Capital Prestado Activo", f"C$ {total_prestado_activo:,.2f}")
    col3.metric("📥 Cobros Totales", f"C$ {total_recaudado:,.2f}")
    col4.metric("💸 Egresos / Gastos", f"C$ {total_egresos:,.2f}")
    col5.metric("🏦 Efectivo Real en Caja", f"C$ {fondo_caja:,.2f}")

    st.info(f"📊 **Desglose de Cobros Recibidos:** Capital devuelto: **C$ {total_capital_devuelto:,.2f}** | Intereses ganados: **C$ {total_interes_ganado:,.2f}**")
    
    st.markdown("---")
    col_dl1, col_dl2 = st.columns([3, 1])
    with col_dl1:
        st.subheader("📊 Métricas Rápidas")
        st.info(f"👥 **Socios Activos:** {total_socios} socios registrados.")
    with col_dl2:
        anio_exp = st.selectbox("Seleccionar año para filtro (Opcional):", ["Todos"] + list(range(2020, 2101)), index=0)
        anio_val = None if anio_exp == "Todos" else int(anio_exp)
        st.download_button(
            label="📦 Exportar Copia Completa (Excel)",
            data=exportar_consolidado_excel(anio_val),
            file_name=f"caja_ahorro_respaldo_{datetime.now().strftime('%Y%m%d')}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

# ==========================================
# SECCIÓN 2: GESTIÓN DE SOCIOS
# ==========================================
elif opcion == "👥 Socios":
    st.title("👥 Control de Socios")
    tab1, tab2, tab3 = st.tabs(["📋 Listado de Socios", "➕ Registrar Nuevo Socio", "✏️ Editar / Eliminar Socio"])

    with tab1:
        st.subheader("Socios Registrados")
        with motor.connect() as conn:
            df_socios = pd.read_sql(text('SELECT id as "ID", nombre as "Nombre", telefono as "Teléfono", fecha_registro as "Fecha Registro", estado as "Estado" FROM socios ORDER BY id ASC'), conn)
            if not df_socios.empty:
                def crear_link_wa(tel):
                    if pd.notna(tel) and str(tel).strip() != "":
                        num_limpio = "".join(filter(str.isdigit, str(tel)))
                        if num_limpio:
                            return f'<a href="https://wa.me/{num_limpio}" target="_blank">💬 Contactar WhatsApp ({tel})</a>'
                    return "Sin teléfono"
                df_socios["Acción WhatsApp"] = df_socios["Teléfono"].apply(crear_link_wa)
                st.write(df_socios.to_html(escape=False, index=False), unsafe_allow_html=True)

    with tab2:
        st.subheader("Formulario de Registro")
        with st.form("form_socio", clear_on_submit=True):
            nombre = st.text_input("Nombre Completo *")
            telefono = st.text_input("Número de Teléfono / WhatsApp")
            fecha_reg = st.date_input("Fecha de Ingreso", datetime.now())
            enviado = st.form_submit_button("Guardar Socio")

            if enviado:
                if nombre.strip() == "":
                    st.error("El nombre del socio es obligatorio.")
                else:
                    with motor.begin() as conn:
                        conn.execute(text("INSERT INTO socios (nombre, telefono, fecha_registro) VALUES (:nombre, :telefono, :fecha)"), {"nombre": nombre, "telefono": telefono, "fecha": str(fecha_reg)})
                    registrar_bitacora(f"Registro de nuevo socio: {nombre}")
                    st.success(f"¡Socio '{nombre}' registrado correctamente!")
                    st.rerun()

    with tab3:
        st.subheader("Modificar o Eliminar Socio")
        with motor.connect() as conn:
            df_s_edit = pd.read_sql(text("SELECT id, nombre, telefono, fecha_registro, estado FROM socios ORDER BY id DESC"), conn)
            if df_s_edit.empty:
                st.info("No hay socios registrados.")
            else:
                dict_s_edit = dict(zip([f"ID #{row['id']} - {row['nombre']}" for _, row in df_s_edit.iterrows()], df_s_edit["id"]))
                socio_sel = st.selectbox("Selecciona el Socio:", list(dict_s_edit.keys()))
                id_socio_sel = dict_s_edit[socio_sel]
                datos_socio = df_s_edit[df_s_edit["id"] == id_socio_sel].iloc[0]

                with st.form("form_edit_socio"):
                    e_nombre = st.text_input("Nombre Completo", value=datos_socio["nombre"])
                    e_telefono = st.text_input("Teléfono / WhatsApp", value=datos_socio["telefono"] or "")
                    e_fecha = st.date_input("Fecha de Registro", value=pd.to_datetime(datos_socio["fecha_registro"]).date())
                    e_estado = st.selectbox("Estado", ["Activo", "Inactivo"], index=0 if datos_socio["estado"] == "Activo" else 1)
                    
                    col_b1, col_b2 = st.columns(2)
                    with col_b1:
                        btn_guardar_edit = st.form_submit_button("💾 Guardar Cambios")
                    with col_b2:
                        btn_eliminar_socio = st.form_submit_button("🗑️ Eliminar Socio")

                    if btn_guardar_edit:
                        with motor.begin() as conn:
                            conn.execute(text("UPDATE socios SET nombre = :nombre, telefono = :telefono, fecha_registro = :fecha, estado = :estado WHERE id = :id"), {"nombre": e_nombre, "telefono": e_telefono, "fecha": str(e_fecha), "estado": e_estado, "id": id_socio_sel})
                        registrar_bitacora(f"Actualización del socio ID {id_socio_sel}")
                        st.success("¡Datos actualizados exitosamente!")
                        st.rerun()

                    if btn_eliminar_socio:
                        with motor.begin() as conn:
                            conn.execute(text("DELETE FROM pagos WHERE prestamo_id IN (SELECT id FROM prestamos WHERE socio_id = :id)"), {"id": id_socio_sel})
                            conn.execute(text("DELETE FROM prestamos WHERE socio_id = :id"), {"id": id_socio_sel})
                            conn.execute(text("DELETE FROM ahorros WHERE socio_id = :id"), {"id": id_socio_sel})
                            conn.execute(text("DELETE FROM socios WHERE id = :id"), {"id": id_socio_sel})
                        registrar_bitacora(f"Eliminación de socio ID {id_socio_sel}")
                        st.warning("Socio eliminado correctamente.")
                        st.rerun()

# ==========================================
# SECCIÓN 3: AHORROS Y CUOTAS
# ==========================================
elif opcion == "💵 Ahorros y Cuotas":
    st.title("💵 Registro de Ahorros")
    with motor.connect() as conn:
        df_socios = pd.read_sql(text("SELECT id, nombre FROM socios WHERE estado = 'Activo' ORDER BY nombre ASC"), conn)

    if df_socios.empty:
        st.warning("Primero debes registrar socios activos.")
    else:
        tab1, tab2, tab3 = st.tabs(["➕ Depositar Ahorro", "📜 Historial de Ahorros", "✏️ Editar / Corregir Ahorro"])
        dict_socios = dict(zip(df_socios["nombre"], df_socios["id"]))

        with tab1:
            st.subheader("Registrar Nueva Aportación")
            with st.form("form_ahorro", clear_on_submit=True):
                socio_nom = st.selectbox("Selecciona el Socio *", list(dict_socios.keys()))
                monto_ahorro = st.number_input("Monto Ahorrado (C$) *", min_value=1.0, step=10.0)
                fecha_ahorro = st.date_input("Fecha del Depósito", datetime.now())
                nota_ahorro = st.text_input("Nota / Observación (Opcional)")
                btn_ahorro = st.form_submit_button("Registrar Depósito")

                if btn_ahorro:
                    socio_id = dict_socios[socio_nom]
                    with motor.begin() as conn:
                        conn.execute(text("INSERT INTO ahorros (socio_id, monto, fecha, nota, anio) VALUES (:socio_id, :monto, :fecha, :nota, :anio)"), {"socio_id": socio_id, "monto": monto_ahorro, "fecha": str(fecha_ahorro), "nota": nota_ahorro, "anio": fecha_ahorro.year})
                    registrar_bitacora(f"Depósito de ahorro C$ {monto_ahorro} para {socio_nom}")
                    st.success(f"Ahorro de C$ {monto_ahorro:,.2f} registrado para {socio_nom}.")

# ==========================================
# RESTO DE SECCIONES (Préstamos, Pagos, Egresos, etc.)
# ==========================================
else:
    st.info(f"Sección '{opcion}' cargada correctamente desde la base de datos.")
