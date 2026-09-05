import io
import hashlib
import os
import pandas as pd
import streamlit as st
from datetime import datetime, timedelta
from sqlalchemy import create_engine, text

# ==========================================
# 1. CONFIGURACIÓN DE PÁGINA
# ==========================================
st.set_page_config(
    page_title="Caja de Ahorro Comunitario",
    page_icon="💰",
    layout="wide"
)

# ==========================================
# 2. GESTIÓN DE BASE DE DATOS (Supabase / PostgreSQL)
# ==========================================
@st.cache_resource
def obtener_motor():
    db_url = st.secrets["postgres"]["url"]
    return create_engine(db_url, pool_pre_ping=True, pool_recycle=300)

engine = obtener_motor()

def hash_password(password: str, salt: bytes = None) -> str:
    """Genera un hash seguro SHA-256 con salt para almacenar la contraseña."""
    if salt is None:
        salt = os.urandom(16)
    elif isinstance(salt, str):
        salt = bytes.fromhex(salt)
    pwd_hash = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), salt, 100000)
    return f"{salt.hex()}:{pwd_hash.hex()}"

def verificar_contrasena(contrasena_ingresada: str, hash_almacenado: str) -> bool:
    """Verifica si la contraseña ingresada coincide con el hash almacenado."""
    try:
        salt_hex, _ = hash_almacenado.split(':')
        sal = bytes.fromhex(salt_hex)
        hash_nuevo = hash_password(contrasena_ingresada, sal)
        return hash_nuevo == hash_almacenado
    except Exception:
        return False

def init_db():
    with engine.begin() as conn:
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
                {"val": pass_default_hash}
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
            CREATE TABLE IF NOT EXISTS cierres_anuales (
                id SERIAL PRIMARY KEY,
                anio INTEGER NOT NULL,
                total_ahorrado NUMERIC(12, 2) NOT NULL,
                total_intereses NUMERIC(12, 2) NOT NULL,
                fecha_cierre TIMESTAMP DEFAULT CURRENT_TIMESTAMP
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
    init_db()
    st.session_state.db_inicializada = True

# ==========================================
# 3. FUNCIONES UTILITARIAS
# ==========================================
def obtener_hash_password_bd():
    with engine.connect() as conn:
        res = conn.execute(text("SELECT valor FROM configuracion WHERE clave = 'admin_password'")).fetchone()
        return res[0] if res else None

def registrar_bitacora(accion: str):
    try:
        with engine.begin() as conn:
            conn.execute(
                text("INSERT INTO bitacora (accion) VALUES (:accion)"),
                {"accion": accion}
            )
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
    with engine.connect() as conn:
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
# 4. AUTENTICACIÓN
# ==========================================
if "autenticado" not in st.session_state:
    st.session_state.autenticado = False

st.sidebar.title("🔒 Control de Acceso")

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
                    with engine.begin() as conn:
                        conn.execute(
                            text("UPDATE configuracion SET valor = :v WHERE clave = 'admin_password'"),
                            {"v": nuevo_hash}
                        )
                    registrar_bitacora("Cambio de contraseña de administrador.")
                    st.success("Contraseña actualizada correctamente.")
                else:
                    st.error("La nueva contraseña debe tener al menos 4 caracteres.")
            else:
                st.error("La contraseña actual es incorrecta.")

    if st.sidebar.button("Cerrar sesión"):
        st.session_state.autenticado = False
        st.rerun()

# ==========================================
# 5. MENÚ NAVEGACIÓN
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
        "🛡️ Bitácora de Auditoría"
    ],
)

# ==========================================
# SECCIÓN 1: PANEL GENERAL (DASHBOARD)
# ==========================================
if opcion == "📊 Panel General":
    st.title("📊 Panel General de la Caja de Ahorro")
    st.caption("Resumen financiero consolidado en Córdoba (C$).")

    with engine.connect() as conn:
        df_ahorros = pd.read_sql(text("SELECT COALESCE(SUM(monto), 0) as total FROM ahorros"), conn)
        total_ahorrado = float(df_ahorros["total"].iloc[0])

        df_prestamos = pd.read_sql(text("""
            SELECT COALESCE(SUM(p.monto_prestado - COALESCE(pg.cap_pagado, 0)), 0) as total
            FROM prestamos p
            LEFT JOIN (
                SELECT prestamo_id, SUM(monto_capital) as cap_pagado 
                FROM pagos GROUP BY prestamo_id
            ) pg ON p.id = pg.prestamo_id
            WHERE p.estado = 'Activo'
        """), conn)
        total_prestado = float(df_prestamos["total"].iloc[0])

        df_pagos = pd.read_sql(text("SELECT COALESCE(SUM(monto_pagado), 0) as total FROM pagos"), conn)
        total_recaudado = float(df_pagos["total"].iloc[0])

        df_egresos = pd.read_sql(text("SELECT COALESCE(SUM(monto), 0) as total FROM egresos"), conn)
        total_egresos = float(df_egresos["total"].iloc[0])

        df_socios = pd.read_sql(text("SELECT COUNT(*) as total FROM socios WHERE estado = 'Activo'"), conn)
        total_socios = int(df_socios["total"].iloc[0])

        fondo_caja = total_ahorrado + total_recaudado - total_prestado - total_egresos

    col1, col2, col3, col4, col5 = st.columns(5)
    col1.metric("💵 Fondo Total Ahorrado", f"C$ {total_ahorrado:,.2f}")
    col2.metric("📉 Capital Prestado Pendiente", f"C$ {total_prestado:,.2f}")
    col3.metric("📥 Cobros/Abonos Totales", f"C$ {total_recaudado:,.2f}")
    col4.metric("💸 Egresos / Gastos", f"C$ {total_egresos:,.2f}")
    col5.metric("🏦 Disponible en Caja", f"C$ {fondo_caja:,.2f}")

    st.markdown("---")
    st.info(f"👥 **Socios Activos:** {total_socios} socios registrados.")

# ==========================================
# SECCIÓN 6: REGISTRO DE PAGOS DE PRÉSTAMOS
# ==========================================
elif opcion == "📖 Pagos de Préstamos":
    st.title("📖 Registro de Abonos y Pagos")
    tab1, tab2, tab3 = st.tabs(["➕ Registrar Abono", "📜 Historial de Pagos", "✏️ Editar / Borrar Pago"])

    with tab1:
        query_activos = """
        SELECT p.id, s.nombre || ' - Préstamo #' || p.id || ' (C$' || p.monto_prestado || ' capital original)' as label,
               p.monto_prestado, p.tasa_interes, p.plazo_meses, p.monto_total, s.nombre as socio_nombre
        FROM prestamos p
        JOIN socios s ON p.socio_id = s.id
        WHERE p.estado = 'Activo'
        """
        with engine.connect() as conn:
            df_prestamos_act = pd.read_sql(text(query_activos), conn)

        if df_prestamos_act.empty:
            st.info("No hay préstamos activos pendientes de pago.")
        else:
            dict_prestamos = dict(zip(df_prestamos_act["label"], df_prestamos_act["id"]))
            with st.form("form_pago", clear_on_submit=True):
                prestamo_sel = st.selectbox("Selecciona el Préstamo *", list(dict_prestamos.keys()))
                p_id = dict_prestamos[prestamo_sel]
                datos_p = df_prestamos_act[df_prestamos_act["id"] == p_id].iloc[0]

                with engine.connect() as conn:
                    df_cap_actual = pd.read_sql(
                        text("SELECT COALESCE(SUM(monto_capital), 0) as cap_pagado FROM pagos WHERE prestamo_id = :p_id"),
                        conn, params={"p_id": p_id}
                    )
                capital_pagado_prev = float(df_cap_actual["cap_pagado"].iloc[0])
                capital_pendiente = max(0.0, float(datos_p["monto_prestado"]) - capital_pagado_prev)

                interes_saldo_insoluto = round(capital_pendiente * (float(datos_p["tasa_interes"]) / 100.0), 2)
                capital_mensual_est = round(float(datos_p["monto_prestado"]) / int(datos_p["plazo_meses"]), 2)

                tipo_pago = st.selectbox("Tipo de Abono", ["Completo (Cuota + Interés sobre saldo)", "Solo Interés sobre saldo", "Abono a Capital", "Cancelación Total Anticipada"])

                if tipo_pago == "Completo (Cuota + Interés sobre saldo)":
                    monto_sugerido = capital_mensual_est + interes_saldo_insoluto
                elif tipo_pago == "Solo Interés sobre saldo":
                    monto_sugerido = interes_saldo_insoluto
                elif tipo_pago == "Abono a Capital":
                    monto_sugerido = capital_mensual_est
                else:
                    monto_sugerido = capital_pendiente + interes_saldo_insoluto

                st.caption(f"💡 **Capital Pendiente:** C$ {capital_pendiente:,.2f} | **Interés Mensual sobre Saldo Insoluto ({datos_p['tasa_interes']}%):** C$ {interes_saldo_insoluto:,.2f}")

                monto_pago = st.number_input("Monto del Pago/Abono (C$) *", min_value=1.0, value=float(monto_sugerido), step=10.0)
                fecha_pago = st.date_input("Fecha del Pago", datetime.now())
                btn_pago = st.form_submit_button("Registrar Pago")

                if btn_pago:
                    if tipo_pago == "Completo (Cuota + Interés sobre saldo)":
                        if monto_pago >= interes_saldo_insoluto:
                            m_interes = interes_saldo_insoluto
                            m_capital = monto_pago - m_interes
                        else:
                            m_interes = monto_pago
                            m_capital = 0.0
                        tipo_db = "Completo"
                    elif tipo_pago == "Solo Interés sobre saldo":
                        m_interes = monto_pago
                        m_capital = 0.0
                        tipo_db = "Interés"
                    elif tipo_pago == "Abono a Capital":
                        m_capital = monto_pago
                        m_interes = 0.0
                        tipo_db = "Capital"
                    else:
                        m_capital = min(monto_pago, capital_pendiente)
                        m_interes = max(0.0, monto_pago - m_capital)
                        tipo_db = "Cancelación"

                    with engine.begin() as conn:
                        res_p = conn.execute(
                            text("""
                                INSERT INTO pagos (prestamo_id, monto_pagado, monto_capital, monto_interes, fecha, tipo)
                                VALUES (:p_id, :monto, :capital, :interes, :fecha, :tipo)
                                RETURNING id;
                            """),
                            {
                                "p_id": p_id,
                                "monto": monto_pago,
                                "capital": m_capital,
                                "interes": m_interes,
                                "fecha": str(fecha_pago),
                                "tipo": tipo_db
                            }
                        )
                        pago_id_nuevo = res_p.fetchone()[0]

                        df_total_cap = pd.read_sql(
                            text("SELECT COALESCE(SUM(monto_capital), 0) as cap_sum FROM pagos WHERE prestamo_id = :p_id"),
                            conn, params={"p_id": p_id}
                        )
                        cap_pagado_total = float(df_total_cap["cap_sum"].iloc[0])

                        if cap_pagado_total >= float(datos_p["monto_prestado"]) or tipo_pago == "Cancelación Total Anticipada":
                            conn.execute(text("UPDATE prestamos SET estado = 'Saldado' WHERE id = :p_id"), {"p_id": p_id})
                            registrar_bitacora(f"Préstamo ID {p_id} de {datos_p['socio_nombre']} pasa a estado SALDADO por liquidación total de capital.")
                            st.balloons()
                            st.success("🎉 ¡El capital del préstamo ha sido completamente saldado!")
                        else:
                            registrar_bitacora(f"Abono de C$ {monto_pago} (Cap: C$ {m_capital}, Int: C$ {m_interes}) para préstamo ID {p_id}")
                            st.success(f"Abono registrado: C$ {m_capital:,.2f} a Capital y C$ {m_interes:,.2f} a Interés.")

                    st.rerun()

    with tab2:
        st.subheader("Historial de Pagos Recibidos")
        query_pagos = """
        SELECT pg.id as "ID", s.nombre as "Socio", pg.prestamo_id as "ID Préstamo", 
               pg.monto_pagado as "Monto Total Pagado (C$)", 
               COALESCE(pg.monto_capital, 0.00) as "Abono Capital (C$)", 
               COALESCE(pg.monto_interes, 0.00) as "Abono Interés (C$)", 
               pg.tipo as "Tipo", pg.fecha as "Fecha"
        FROM pagos pg
        JOIN prestamos p ON pg.prestamo_id = p.id
        JOIN socios s ON p.socio_id = s.id
        ORDER BY pg.id DESC
        """
        with engine.connect() as conn:
            df_pagos_hist = pd.read_sql(text(query_pagos), conn)
        st.dataframe(df_pagos_hist, use_container_width=True)

# ==========================================
# SECCIÓN 8: ESTADO DE CUENTA
# ==========================================
elif opcion == "📜 Estado de Cuenta":
    st.title("📜 Estado de Cuenta Individual")
    st.caption("Consulta e imprime la ficha detallada de ahorro y préstamos por socio.")

    with engine.connect() as conn:
        df_socios = pd.read_sql(text("SELECT id, nombre FROM socios ORDER BY nombre ASC"), conn)

    if df_socios.empty:
        st.warning("No hay socios registrados.")
    else:
        dict_socios = dict(zip(df_socios["nombre"], df_socios["id"]))
        socio_sel = st.selectbox("Selecciona un Socio para generar Estado de Cuenta", list(dict_socios.keys()))
        s_id = dict_socios[socio_sel]

        with engine.connect() as conn:
            df_ahorro_socio = pd.read_sql(
                text("SELECT COALESCE(SUM(monto), 0) as total FROM ahorros WHERE socio_id = :id"),
                conn, params={"id": s_id}
            )
            total_ahorrado_socio = float(df_ahorro_socio["total"].iloc[0])

            df_prestamo_socio = pd.read_sql(
                text("""
                    SELECT COALESCE(SUM(p.monto_prestado - COALESCE(pg.cap_pagado, 0)), 0) as total
                    FROM prestamos p
                    LEFT JOIN (
                        SELECT prestamo_id, SUM(monto_capital) as cap_pagado 
                        FROM pagos GROUP BY prestamo_id
                    ) pg ON p.id = pg.prestamo_id
                    WHERE p.socio_id = :id AND p.estado = 'Activo'
                """),
                conn, params={"id": s_id}
            )
            total_prestado_socio = max(0.0, float(df_prestamo_socio["total"].iloc[0]))

        st.markdown("---")
        st.markdown(f"## 🏦 Estado de Cuenta - **{socio_sel}**")

        c1, c2 = st.columns(2)
        c1.metric("💵 Capital Total Ahorrado", f"C$ {total_ahorrado_socio:,.2f}")
        c2.metric("📉 Préstamos Activos (Capital Pendiente)", f"C$ {total_prestado_socio:,.2f}")

        st.markdown("### 🤝 Detalle de Préstamos")
        with engine.connect() as conn:
            df_prestamos_det = pd.read_sql(
                text('''
                    SELECT p.id as "ID Préstamo", 
                           p.monto_prestado as "Capital Inicial (C$)", 
                           COALESCE(SUM(pg.monto_capital), 0.00) as "Capital Pagado (C$)",
                           GREATEST(0.00, p.monto_prestado - COALESCE(SUM(pg.monto_capital), 0.00)) as "Capital Pendiente (C$)",
                           p.tasa_interes as "Tasa (%)",
                           p.estado as "Estado", 
                           p.fecha_inicio as "Fecha Inicio"
                    FROM prestamos p
                    LEFT JOIN pagos pg ON p.id = pg.prestamo_id
                    WHERE p.socio_id = :id
                    GROUP BY p.id, p.monto_prestado, p.tasa_interes, p.estado, p.fecha_inicio
                    ORDER BY p.id DESC
                '''),
                conn, params={"id": s_id}
            )
        st.dataframe(df_prestamos_det, use_container_width=True)

        st.markdown("### 💳 Detalle de Abonos y Cancelaciones de Préstamos")
        with engine.connect() as conn:
            df_pagos_det = pd.read_sql(
                text('''
                    SELECT pg.fecha as "Fecha", pg.prestamo_id as "ID Préstamo Ref.", 
                           pg.monto_pagado as "Monto Pagado (C$)", 
                           COALESCE(pg.monto_capital, 0.00) as "Abono a Capital (C$)", 
                           COALESCE(pg.monto_interes, 0.00) as "Abono a Interés (C$)", 
                           pg.tipo as "Tipo de Pago / Detalle"
                    FROM pagos pg
                    JOIN prestamos p ON pg.prestamo_id = p.id
                    WHERE p.socio_id = :id
                    ORDER BY pg.fecha DESC, pg.id DESC
                '''),
                conn, params={"id": s_id}
            )
        if df_pagos_det.empty:
            st.info("El socio no registra pagos o abonos a préstamos.")
        else:
            st.dataframe(df_pagos_det, use_container_width=True)
