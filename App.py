import streamlit as st
import pandas as pd
from sqlalchemy import create_engine, text
from datetime import datetime
import hashlib
import io

# ==========================================
# CONFIGURACIÓN DE PÁGINA Y ESTILOS
# ==========================================
st.set_page_config(
    page_title="Sistema de Caja de Ahorro",
    page_icon="🏦",
    layout="wide"
)

# ==========================================
# CONEXIÓN A LA BASE DE DATOS (SUPABASE)
# ==========================================
@st.cache_resource
def get_engine():
    # Lee desde la estructura [postgres] url presente en tus Secrets de Streamlit Cloud
    if "postgres" in st.secrets and "url" in st.secrets["postgres"]:
        db_url = st.secrets["postgres"]["url"]
    else:
        db_url = st.secrets.get("DB_URL", "postgresql://postgres:password@localhost:5432/postgres")
        
    return create_engine(db_url, pool_pre_ping=True)

engine = get_engine()

# ==========================================
# FUNCIONES DE SEGURIDAD Y UTILIDADES
# ==========================================
def hash_password(password: str) -> str:
    """Genera un hash SHA-256 para la contraseña."""
    return hashlib.sha256(password.encode('utf-8')).hexdigest()

def inicializar_bd():
    """Crea las tablas necesarias si no existen e inserta la clave por defecto."""
    with engine.begin() as conn:
        # Tabla configuración (autenticación)
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS configuracion (
                clave TEXT PRIMARY KEY,
                valor TEXT NOT NULL
            );
        """))
        
        # Tabla socios
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS socios (
                id SERIAL PRIMARY KEY,
                nombre TEXT NOT NULL,
                cedula TEXT,
                telefono TEXT,
                fecha_ingreso DATE NOT NULL,
                estado TEXT DEFAULT 'Activo'
            );
        """))

        # Tabla ahorros
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS ahorros (
                id SERIAL PRIMARY KEY,
                socio_id INT REFERENCES socios(id),
                monto NUMERIC(12,2) NOT NULL,
                tipo TEXT NOT NULL,
                fecha DATE NOT NULL,
                anio INT NOT NULL
            );
        """))

        # Tabla préstamos
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS prestamos (
                id SERIAL PRIMARY KEY,
                socio_id INT REFERENCES socios(id),
                monto_prestado NUMERIC(12,2) NOT NULL,
                tasa_interes NUMERIC(5,2) NOT NULL,
                plazo_meses INT NOT NULL,
                interes_total NUMERIC(12,2) NOT NULL,
                monto_total NUMERIC(12,2) NOT NULL,
                fecha_inicio DATE NOT NULL,
                estado TEXT DEFAULT 'Activo',
                anio INT NOT NULL
            );
        """))

        # Tabla pagos
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS pagos (
                id SERIAL PRIMARY KEY,
                prestamo_id INT REFERENCES prestamos(id),
                monto NUMERIC(12,2) NOT NULL,
                concepto TEXT NOT NULL,
                fecha DATE NOT NULL,
                anio INT NOT NULL
            );
        """))

        # Tabla bitácora
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS bitacora (
                id SERIAL PRIMARY KEY,
                fecha TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                accion TEXT NOT NULL
            );
        """))

        # Insertar clave admin si no existe
        res = conn.execute(text("SELECT valor FROM configuracion WHERE clave = 'admin_password'")).fetchone()
        if not res:
            default_pass_hash = hash_password("admin123")
            conn.execute(
                text("INSERT INTO configuracion (clave, valor) VALUES ('admin_password', :pass)"),
                {"pass": default_pass_hash}
            )

def registrar_bitacora(accion: str):
    """Registra un evento en la tabla bitácora."""
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO bitacora (accion) VALUES (:accion)"), {"accion": accion})

def to_excel(df: pd.DataFrame) -> bytes:
    """Convierte un DataFrame a archivo Excel binario."""
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        df.to_excel(writer, index=False, sheet_name='Reporte')
    return output.getvalue()

# Inicializar Base de Datos
try:
    inicializar_bd()
except Exception as e:
    st.error(f"Error al conectar con la Base de Datos: {e}")

# ==========================================
# MÓDULO DE AUTENTICACIÓN
# ==========================================
if "authenticated" not in st.session_state:
    st.session_state["authenticated"] = False

if not st.session_state["authenticated"]:
    st.title("🔑 Sistema de Caja de Ahorro - Iniciar Sesión")
    with st.form("form_login", clear_on_submit=True):
        input_pass = st.text_input("Ingrese la Contraseña Admin", type="password")
        btn_login = st.form_submit_button("Ingresar")

        if btn_login:
            with engine.connect() as conn:
                real_hash = conn.execute(text("SELECT valor FROM configuracion WHERE clave = 'admin_password'")).scalar()
            
            if hash_password(input_pass) == real_hash:
                st.session_state["authenticated"] = True
                st.success("¡Acceso concedido!")
                st.rerun()
            else:
                st.error("Contraseña incorrecta. Intente nuevamente.")
    st.stop()

# ==========================================
# MENÚ LATERAL Y NAVEGACIÓN
# ==========================================
st.sidebar.title("🏦 Menú Principal")
opcion = st.sidebar.radio(
    "Seleccione una opción:",
    ["📊 Tablero Principal", "👥 Socios", "💰 Ahorros", "🤝 Préstamos", "💵 Pagos / Abonos", "🔑 Cambiar Contraseña"]
)

if st.sidebar.button("🚪 Cerrar Sesión"):
    st.session_state["authenticated"] = False
    st.rerun()

# ==========================================
# SECCIÓN 1: TABLERO PRINCIPAL
# ==========================================
if opcion == "📊 Tablero Principal":
    st.title("📊 Resumen General de la Caja de Ahorro")

    with engine.connect() as conn:
        tot_socios = conn.execute(text("SELECT COUNT(*) FROM socios WHERE estado = 'Activo'")).scalar() or 0
        tot_ahorros = conn.execute(text("SELECT SUM(monto) FROM ahorros")).scalar() or 0.0
        tot_prestado = conn.execute(text("SELECT SUM(monto_prestado) FROM prestamos WHERE estado = 'Activo'")).scalar() or 0.0
        tot_pagos = conn.execute(text("SELECT SUM(monto) FROM pagos")).scalar() or 0.0

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("👥 Socios Activos", f"{tot_socios}")
    col2.metric("💰 Fondo Total Ahorrado", f"C$ {tot_ahorros:,.2f}")
    col3.metric("🤝 Capital en Préstamos", f"C$ {tot_prestado:,.2f}")
    col4.metric("💵 Total Recaudado (Pagos)", f"C$ {tot_pagos:,.2f}")

    st.markdown("---")
    st.subheader("📋 Últimos Movimientos (Bitácora)")
    with engine.connect() as conn:
        df_bit = pd.read_sql(text("SELECT fecha as 'Fecha y Hora', accion as 'Acción' FROM bitacora ORDER BY id DESC LIMIT 10"), conn)
        st.dataframe(df_bit, use_container_width=True)

# ==========================================
# SECCIÓN 2: SOCIOS
# ==========================================
elif opcion == "👥 Socios":
    st.title("👥 Gestión de Socios")
    tab1, tab2, tab3 = st.tabs(["➕ Registrar Socio", "📋 Lista de Socios", "✏️ Editar / Eliminar"])

    with tab1:
        st.subheader("Registrar Nuevo Socio")
        with st.form("form_nuevo_socio", clear_on_submit=True):
            col1, col2 = st.columns(2)
            with col1:
                nombre_socio = st.text_input("Nombre Completo *")
                cedula_socio = st.text_input("No. Cédula *")
            with col2:
                telefono_socio = st.text_input("Teléfono")
                fecha_ingreso = st.date_input("Fecha de Ingreso", datetime.now())

            btn_guardar_socio = st.form_submit_button("💾 Guardar Socio")

            if btn_guardar_socio:
                if not nombre_socio.strip():
                    st.error("El nombre del socio es obligatorio.")
                else:
                    with engine.begin() as conn:
                        conn.execute(
                            text("""
                                INSERT INTO socios (nombre, cedula, telefono, fecha_ingreso, estado)
                                VALUES (:nombre, :cedula, :telefono, :fecha, 'Activo')
                            """),
                            {
                                "nombre": nombre_socio.strip(),
                                "cedula": cedula_socio.strip(),
                                "telefono": telefono_socio.strip(),
                                "fecha": str(fecha_ingreso)
                            }
                        )
                    registrar_bitacora(f"Registro de nuevo socio: {nombre_socio}")
                    st.success(f"¡Socio {nombre_socio} registrado con éxito!")
                    st.rerun()

    with tab2:
        st.subheader("Socios Registrados")
        with engine.connect() as conn:
            df_socios = pd.read_sql(text("SELECT id as 'ID', nombre as 'Nombre', cedula as 'Cédula', telefono as 'Teléfono', fecha_ingreso as 'Fecha Ingreso', estado as 'Estado' FROM socios ORDER BY nombre ASC"), conn)
            st.dataframe(df_socios, use_container_width=True)

    with tab3:
        st.subheader("Modificar Datos de Socio")
        with engine.connect() as conn:
            df_s_edit = pd.read_sql(text("SELECT id, nombre, cedula, telefono, estado FROM socios ORDER BY nombre ASC"), conn)

        if df_s_edit.empty:
            st.info("No hay socios registrados para editar.")
        else:
            dict_s_edit = dict(zip(df_s_edit["nombre"], df_s_edit["id"]))
            socio_sel_e = st.selectbox("Selecciona un Socio:", list(dict_s_edit.keys()))
            id_s_sel = dict_s_edit[socio_sel_e]
            reg_s = df_s_edit[df_s_edit["id"] == id_s_sel].iloc[0]

            with st.form("form_edit_socio"):
                e_nombre = st.text_input("Nombre Completo", value=reg_s["nombre"])
                e_cedula = st.text_input("No. Cédula", value=reg_s["cedula"] if reg_s["cedula"] else "")
                e_telefono = st.text_input("Teléfono", value=reg_s["telefono"] if reg_s["telefono"] else "")
                e_estado = st.selectbox("Estado", ["Activo", "Inactivo"], index=0 if reg_s["estado"] == "Activo" else 1)

                btn_update_s = st.form_submit_button("💾 Actualizar Socio")

                if btn_update_s:
                    with engine.begin() as conn:
                        conn.execute(
                            text("""
                                UPDATE socios
                                SET nombre = :nombre, cedula = :cedula, telefono = :telefono, estado = :estado
                                WHERE id = :id
                            """),
                            {"nombre": e_nombre, "cedula": e_cedula, "telefono": e_telefono, "estado": e_estado, "id": id_s_sel}
                        )
                    registrar_bitacora(f"Actualización de datos del socio ID {id_s_sel}")
                    st.success("¡Socio actualizado correctamente!")
                    st.rerun()

# ==========================================
# SECCIÓN 3: AHORROS
# ==========================================
elif opcion == "💰 Ahorros":
    st.title("💰 Gestión de Ahorros")
    with engine.connect() as conn:
        df_socios = pd.read_sql(text("SELECT id, nombre FROM socios WHERE estado = 'Activo' ORDER BY nombre ASC"), conn)

    if df_socios.empty:
        st.warning("Debe registrar socios antes de gestionar ahorros.")
    else:
        dict_socios = dict(zip(df_socios["nombre"], df_socios["id"]))
        tab1, tab2 = st.tabs(["➕ Registrar Ahorro", "📜 Historial de Ahorros"])

        with tab1:
            st.subheader("Registrar Ahorro / Aporte")
            with st.form("form_nuevo_ahorro", clear_on_submit=True):
                col1, col2 = st.columns(2)
                with col1:
                    socio_ahorro = st.selectbox("Socio *", list(dict_socios.keys()))
                    monto_ahorro = st.number_input("Monto (C$) *", min_value=10.0, step=50.0)
                with col2:
                    tipo_ahorro = st.selectbox("Tipo de Aporte", ["Ahorro Ordinario", "Ahorro Extraordinario", "Cuota Social"])
                    fecha_ahorro = st.date_input("Fecha de Pago", datetime.now())

                btn_guardar_ahorro = st.form_submit_button("💰 Registrar Ahorro")

                if btn_guardar_ahorro:
                    if monto_ahorro <= 0:
                        st.error("El monto debe ser mayor a 0.")
                    else:
                        socio_id = dict_socios[socio_ahorro]
                        with engine.begin() as conn:
                            conn.execute(
                                text("""
                                    INSERT INTO ahorros (socio_id, monto, tipo, fecha, anio)
                                    VALUES (:socio_id, :monto, :tipo, :fecha, :anio)
                                """),
                                {
                                    "socio_id": socio_id,
                                    "monto": monto_ahorro,
                                    "tipo": tipo_ahorro,
                                    "fecha": str(fecha_ahorro),
                                    "anio": fecha_ahorro.year
                                }
                            )
                        registrar_bitacora(f"Ahorro de C$ {monto_ahorro} registrado para {socio_ahorro}")
                        st.success(f"¡Ahorro de C$ {monto_ahorro:,.2f} registrado para {socio_ahorro}!")
                        st.rerun()

        with tab2:
            st.subheader("Historial de Ahorros")
            query_a = """
                SELECT a.id as "ID", s.nombre as "Socio", a.monto as "Monto (C$)", a.tipo as "Tipo", a.fecha as "Fecha"
                FROM ahorros a JOIN socios s ON a.socio_id = s.id
                ORDER BY a.id DESC
            """
            with engine.connect() as conn:
                df_ahorros_hist = pd.read_sql(text(query_a), conn)
                st.dataframe(df_ahorros_hist, use_container_width=True)

            if not df_ahorros_hist.empty:
                st.download_button(
                    label="📥 Exportar Ahorros a Excel",
                    data=to_excel(df_ahorros_hist),
                    file_name=f"reporte_ahorros_{datetime.now().strftime('%Y%m%d')}.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                )

# ==========================================
# SECCIÓN 4: PRÉSTAMOS
# ==========================================
elif opcion == "🤝 Préstamos":
    st.title("🤝 Gestión de Préstamos")
    with engine.connect() as conn:
        df_socios = pd.read_sql(text("SELECT id, nombre FROM socios WHERE estado = 'Activo' ORDER BY nombre ASC"), conn)

    if df_socios.empty:
        st.warning("Registra socios antes de procesar préstamos.")
    else:
        dict_socios = dict(zip(df_socios["nombre"], df_socios["id"]))
        tab1, tab2, tab3 = st.tabs(["➕ Nuevo Préstamo", "📜 Historial", "✏️ Editar / Eliminar Préstamo"])

        with tab1:
            st.subheader("Nuevo Préstamo")
            with st.form("form_nuevo_prestamo", clear_on_submit=True):
                col1, col2 = st.columns(2)
                with col1:
                    socio_prestamo = st.selectbox("Socio Solicitante *", list(dict_socios.keys()))
                    monto_solicitado = st.number_input("Monto del Préstamo (C$) *", min_value=10.0, step=50.0)
                    tasa_interes = st.number_input("Tasa de Interés Mensual (%) *", min_value=0.0, value=5.0, step=0.5)
                with col2:
                    plazo_meses = st.number_input("Plazo en Meses *", min_value=1, max_value=36, value=6)
                    fecha_prestamo = st.date_input("Fecha de Emisión", datetime.now())

                btn_aprobar = st.form_submit_button("Aprobar y Registrar Préstamo")

                if btn_aprobar:
                    if monto_solicitado <= 0:
                        st.error("El monto ingresado debe ser mayor a 0.")
                    else:
                        interes_mensual = monto_solicitado * (tasa_interes / 100)
                        intereses_total = interes_mensual * plazo_meses
                        monto_total_pagar = monto_solicitado + intereses_total
                        
                        socio_id = dict_socios[socio_prestamo]
                        anio_curr = fecha_prestamo.year
                        
                        with engine.begin() as conn:
                            conn.execute(
                                text("""
                                    INSERT INTO prestamos (socio_id, monto_prestado, tasa_interes, plazo_meses, interes_total, monto_total, fecha_inicio, estado, anio)
                                    VALUES (:socio_id, :monto_prestado, :tasa_interes, :plazo_meses, :interes_total, :monto_total, :fecha_inicio, 'Activo', :anio)
                                """),
                                {
                                    "socio_id": socio_id,
                                    "monto_prestado": monto_solicitado,
                                    "tasa_interes": tasa_interes,
                                    "plazo_meses": plazo_meses,
                                    "interes_total": intereses_total,
                                    "monto_total": monto_total_pagar,
                                    "fecha_inicio": str(fecha_prestamo),
                                    "anio": anio_curr
                                }
                            )
                        registrar_bitacora(f"Aprobación de préstamo C$ {monto_solicitado} para socio {socio_prestamo}")
                        st.success(f"¡Préstamo de C$ {monto_solicitado:,.2f} registrado exitosamente para {socio_prestamo}!")
                        st.rerun()

        with tab2:
            st.subheader("Historial de Préstamos")
            query_p = """
                SELECT p.id as "ID", s.nombre as "Socio", p.monto_prestado as "Monto Prestado (C$)", p.tasa_interes as "Tasa (%)", p.plazo_meses as "Plazo (Meses)", p.interes_total as "Interés Total (C$)", p.monto_total as "Total a Pagar (C$)", p.fecha_inicio as "Fecha", p.estado as "Estado"
                FROM prestamos p JOIN socios s ON p.socio_id = s.id
                ORDER BY p.id DESC
            """
            with engine.connect() as conn:
                df_prestamos_hist = pd.read_sql(text(query_p), conn)
                st.dataframe(df_prestamos_hist, use_container_width=True)

            if not df_prestamos_hist.empty:
                st.download_button(
                    label="📥 Exportar Préstamos a Excel",
                    data=to_excel(df_prestamos_hist),
                    file_name=f"reporte_prestamos_{datetime.now().strftime('%Y%m%d')}.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                )

        with tab3:
            st.subheader("Modificar o Eliminar Préstamo")
            query_edit_p = """
                SELECT p.id, s.nombre || ' - Préstamo #' || p.id || ' (C$' || p.monto_prestado || ')' as label, p.socio_id, p.monto_prestado, p.tasa_interes, p.plazo_meses, p.fecha_inicio, p.estado
                FROM prestamos p JOIN socios s ON p.socio_id = s.id
                ORDER BY p.id DESC
            """
            with engine.connect() as conn:
                df_edit_p = pd.read_sql(text(query_edit_p), conn)

            if df_edit_p.empty:
                st.info("No hay préstamos para editar o eliminar.")
            else:
                dict_edit_p = dict(zip(df_edit_p["label"], df_edit_p["id"]))
                prestamo_sel_e = st.selectbox("Selecciona el Préstamo:", list(dict_edit_p.keys()))
                id_p_sel = dict_edit_p[prestamo_sel_e]
                reg_p = df_edit_p[df_edit_p["id"] == id_p_sel].iloc[0]

                with st.form("form_edit_prestamo"):
                    e_monto_p = st.number_input("Monto Prestado (C$)", value=float(reg_p["monto_prestado"]), min_value=10.0, step=50.0)
                    e_tasa_p = st.number_input("Tasa Interés (%)", value=float(reg_p["tasa_interes"]), min_value=0.0, step=0.5)
                    e_plazo_p = st.number_input("Plazo (Meses)", value=int(reg_p["plazo_meses"]), min_value=1, max_value=36)
                    f_p_orig = pd.to_datetime(reg_p["fecha_inicio"]).date()
                    e_fecha_p = st.date_input("Fecha Inicio", value=f_p_orig)
                    e_estado_p = st.selectbox("Estado del Préstamo", ["Activo", "Saldado", "Cancelado"], index=["Activo", "Saldado", "Cancelado"].index(reg_p["estado"]))

                    e_int_m = e_monto_p * (e_tasa_p / 100)
                    e_int_tot = e_int_m * e_plazo_p
                    e_monto_tot = e_monto_p + e_int_tot

                    col_btn1, col_btn2 = st.columns(2)
                    with col_btn1:
                        btn_guardar_p = st.form_submit_button("💾 Guardar Cambios")
                    with col_btn2:
                        btn_eliminar_p = st.form_submit_button("🗑️ Eliminar Préstamo")

                    if btn_guardar_p:
                        with engine.begin() as conn:
                            conn.execute(
                                text("""
                                    UPDATE prestamos 
                                    SET monto_prestado = :monto, tasa_interes = :tasa, plazo_meses = :plazo, interes_total = :int_tot, monto_total = :monto_tot, fecha_inicio = :fecha, estado = :estado, anio = :anio
                                    WHERE id = :id
                                """),
                                {
                                    "monto": e_monto_p,
                                    "tasa": e_tasa_p,
                                    "plazo": e_plazo_p,
                                    "int_tot": e_int_tot,
                                    "monto_tot": e_monto_tot,
                                    "fecha": str(e_fecha_p),
                                    "estado": e_estado_p,
                                    "anio": e_fecha_p.year,
                                    "id": id_p_sel
                                }
                            )
                        registrar_bitacora(f"Edición de préstamo ID {id_p_sel}")
                        st.success("¡Préstamo modificado correctamente!")
                        st.rerun()

                    if btn_eliminar_p:
                        with engine.begin() as conn:
                            conn.execute(text("DELETE FROM pagos WHERE prestamo_id = :id"), {"id": id_p_sel})
                            conn.execute(text("DELETE FROM prestamos WHERE id = :id"), {"id": id_p_sel})
                        registrar_bitacora(f"Eliminación de préstamo ID {id_p_sel}")
                        st.warning("Préstamo eliminado correctamente.")
                        st.rerun()

# ==========================================
# SECCIÓN 5: PAGOS / ABONOS
# ==========================================
elif opcion == "💵 Pagos / Abonos":
    st.title("💵 Registro de Pagos y Abonos")
    query_p_act = """
        SELECT p.id, s.nombre || ' - Préstamo #' || p.id || ' (C$' || p.monto_prestado || ')' as label
        FROM prestamos p JOIN socios s ON p.socio_id = s.id
        WHERE p.estado = 'Activo'
        ORDER BY p.id DESC
    """
    with engine.connect() as conn:
        df_p_activos = pd.read_sql(text(query_p_act), conn)

    if df_p_activos.empty:
        st.info("No hay préstamos activos registrados.")
    else:
        dict_prestamos = dict(zip(df_p_activos["label"], df_p_activos["id"]))
        tab1, tab2 = st.tabs(["➕ Registrar Pago", "📜 Historial de Pagos"])

        with tab1:
            st.subheader("Registrar Abono a Préstamo")
            with st.form("form_nuevo_pago", clear_on_submit=True):
                col1, col2 = st.columns(2)
                with col1:
                    prestamo_pago = st.selectbox("Seleccionar Préstamo Activo *", list(dict_prestamos.keys()))
                    monto_pago = st.number_input("Monto abonado (C$) *", min_value=10.0, step=50.0)
                with col2:
                    concepto_pago = st.selectbox("Concepto", ["Cuota Normal", "Abono a Capital", "Cancelación Total"])
                    fecha_pago = st.date_input("Fecha del Pago", datetime.now())

                btn_guardar_pago = st.form_submit_button("💵 Registrar Pago")

                if btn_guardar_pago:
                    if monto_pago <= 0:
                        st.error("El monto ingresado debe ser mayor a 0.")
                    else:
                        p_id = dict_prestamos[prestamo_pago]
                        with engine.begin() as conn:
                            conn.execute(
                                text("""
                                    INSERT INTO pagos (prestamo_id, monto, concepto, fecha, anio)
                                    VALUES (:prestamo_id, :monto, :concepto, :fecha, :anio)
                                """),
                                {
                                    "prestamo_id": p_id,
                                    "monto": monto_pago,
                                    "concepto": concepto_pago,
                                    "fecha": str(fecha_pago),
                                    "anio": fecha_pago.year
                                }
                            )
                        registrar_bitacora(f"Pago de C$ {monto_pago} al préstamo ID {p_id}")
                        st.success(f"¡Pago de C$ {monto_pago:,.2f} registrado con éxito!")
                        st.rerun()

        with tab2:
            st.subheader("Historial de Pagos")
            query_pagos = """
                SELECT pg.id as "ID Pago", s.nombre as "Socio", pg.prestamo_id as "ID Préstamo", pg.monto as "Monto Abonado (C$)", pg.concepto as "Concepto", pg.fecha as "Fecha"
                FROM pagos pg
                JOIN prestamos pr ON pg.prestamo_id = pr.id
                JOIN socios s ON pr.socio_id = s.id
                ORDER BY pg.id DESC
            """
            with engine.connect() as conn:
                df_pagos_hist = pd.read_sql(text(query_pagos), conn)
                st.dataframe(df_pagos_hist, use_container_width=True)

            if not df_pagos_hist.empty:
                st.download_button(
                    label="📥 Exportar Pagos a Excel",
                    data=to_excel(df_pagos_hist),
                    file_name=f"reporte_pagos_{datetime.now().strftime('%Y%m%d')}.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                )

# ==========================================
# SECCIÓN 6: CAMBIAR CONTRASEÑA
# ==========================================
elif opcion == "🔑 Cambiar Contraseña":
    st.title("🔑 Cambiar Contraseña de Administración")

    with st.form("form_cambiar_pass", clear_on_submit=True):
        pass_actual = st.text_input("Contraseña Actual", type="password")
        pass_nueva = st.text_input("Nueva Contraseña", type="password")
        pass_confirma = st.text_input("Confirmar Nueva Contraseña", type="password")

        btn_cambiar = st.form_submit_button("🔒 Actualizar Contraseña")

        if btn_cambiar:
            with engine.connect() as conn:
                real_hash = conn.execute(text("SELECT valor FROM configuracion WHERE clave = 'admin_password'")).scalar()

            if hash_password(pass_actual) != real_hash:
                st.error("La contraseña actual es incorrecta.")
            elif pass_nueva != pass_confirma:
                st.error("La nueva contraseña y la confirmación no coinciden.")
            elif len(pass_nueva.strip()) < 4:
                st.error("La nueva contraseña debe tener al menos 4 caracteres.")
            else:
                new_hash = hash_password(pass_nueva.strip())
                with engine.begin() as conn:
                    conn.execute(
                        text("UPDATE configuracion SET valor = :pass WHERE clave = 'admin_password'"),
                        {"pass": new_hash}
                    )
                registrar_bitacora("Cambio de contraseña de administración")
                st.success("¡Contraseña actualizada exitosamente!")
