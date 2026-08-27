import io
import pandas as pd
import streamlit as st
from datetime import datetime
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
# 2. AUTENTICACIÓN / CONTRASEÑA DE ADMINISTRADOR
# ==========================================
ADMIN_PASSWORD = "admin123"

if "autenticado" not in st.session_state:
    st.session_state.autenticado = False

st.sidebar.title("🔒 Control de Acceso")

if not st.session_state.autenticado:
    password_input = st.sidebar.text_input("Contraseña de Administrador", type="password")
    if st.sidebar.button("Iniciar sesión"):
        if password_input == ADMIN_PASSWORD:
            st.session_state.autenticado = True
            st.sidebar.success("¡Acceso concedido!")
            st.rerun()
        else:
            st.sidebar.error("Contraseña incorrecta.")
    st.warning("⚠️ Debes iniciar sesión como Administrador en la barra lateral para acceder al sistema.")
    st.stop()
else:
    st.sidebar.success("Sesión activa como Administrador")
    if st.sidebar.button("Cerrar sesión"):
        st.session_state.autenticado = False
        st.rerun()

# ==========================================
# 3. GESTIÓN DE BASE DE DATOS (Supabase / PostgreSQL)
# ==========================================
def obtener_motor():
    db_url = st.secrets["postgres"]["url"]
    return create_engine(
        db_url,
        pool_pre_ping=True,
        pool_recycle=300
    )

def init_db():
    engine = obtener_motor()
    with engine.begin() as conn:
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
                fecha DATE NOT NULL,
                tipo VARCHAR(20) CHECK(tipo IN ('Capital', 'Interés', 'Completo'))
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

init_db()

# ==========================================
# 4. FUNCIÓN UTILITARIA PARA EXPORTAR A EXCEL
# ==========================================
def to_excel(df: pd.DataFrame) -> bytes:
    salida = io.BytesIO()
    try:
        with pd.ExcelWriter(salida, engine="openpyxl") as writer:
            df.to_excel(writer, index=False, sheet_name="Reporte")
    except ModuleNotFoundError:
        st.error("Error: La librería 'openpyxl' no está instalada. Agrégala a tu archivo requirements.txt.")
        return b""
    return salida.getvalue()

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
        "📖 Pagos de Préstamos",
        "📄 Estado de Cuenta",
        "🎉 Liquidación Anual",
        "🔒 Cierre Mensual y Anual"
    ],
)

engine = obtener_motor()

# ==========================================
# SECCIÓN 1: PANEL GENERAL (DASHBOARD)
# ==========================================
if opcion == "📊 Panel General":
    st.title("📊 Panel General de la Caja de Ahorro")
    st.caption("Resumen financiero en tiempo real expresado en Córdoba (C$).")

    with engine.connect() as conn:
        df_ahorros = pd.read_sql("SELECT COALESCE(SUM(monto), 0) as total FROM ahorros", conn)
        total_ahorrado = float(df_ahorros["total"].iloc[0])

        df_prestamos = pd.read_sql("SELECT COALESCE(SUM(monto_prestado), 0) as total FROM prestamos WHERE estado = 'Activo'", conn)
        total_prestado = float(df_prestamos["total"].iloc[0])

        df_pagos = pd.read_sql("SELECT COALESCE(SUM(monto_pagado), 0) as total FROM pagos", conn)
        total_recaudado = float(df_pagos["total"].iloc[0])

        df_socios = pd.read_sql("SELECT COUNT(*) as total FROM socios WHERE estado = 'Activo'", conn)
        total_socios = int(df_socios["total"].iloc[0])

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("💵 Fondo Total Ahorrado", f"C$ {total_ahorrado:,.2f}")
    col2.metric("📉 Capital Prestado Activo", f"C$ {total_prestado:,.2f}")
    col3.metric("📥 Cobros/Abonos Totales", f"C$ {total_recaudado:,.2f}")
    col4.metric("👥 Socios Activos", f"{total_socios}")

    st.markdown("---")
    col_izq, col_der = st.columns(2)

    with col_izq:
        st.subheader("📌 Últimos Ahorros Registrados")
        query_ult_ahorros = """
            SELECT a.fecha as "Fecha", s.nombre as "Socio", a.monto as "Monto (C$)"
            FROM ahorros a
            JOIN socios s ON a.socio_id = s.id
            ORDER BY a.id DESC LIMIT 5
        """
        with engine.connect() as conn:
            df_rec_ahorros = pd.read_sql(query_ult_ahorros, conn)
        st.dataframe(df_rec_ahorros, use_container_width=True)

    with col_der:
        st.subheader("⚠️ Préstamos Activos")
        query_prestamos_act = """
            SELECT p.id as "ID", s.nombre as "Socio", p.monto_prestado as "Monto (C$)", p.monto_total as "Total Con Interés (C$)"
            FROM prestamos p
            JOIN socios s ON p.socio_id = s.id
            WHERE p.estado = 'Activo'
        """
        with engine.connect() as conn:
            df_rec_prestamos = pd.read_sql(query_prestamos_act, conn)
        st.dataframe(df_rec_prestamos, use_container_width=True)

# ==========================================
# SECCIÓN 2: GESTIÓN DE SOCIOS
# ==========================================
elif opcion == "👥 Socios":
    st.title("👥 Control de Socios")

    tab1, tab2, tab3 = st.tabs(["📋 Listado de Socios", "➕ Registrar Nuevo Socio", "✏️ Editar / Modificar Socio"])

    with tab1:
        st.subheader("Socios Registrados")
        with engine.connect() as conn:
            df_socios = pd.read_sql(
                'SELECT id as "ID", nombre as "Nombre", telefono as "Teléfono", fecha_registro as "Fecha Registro", estado as "Estado" FROM socios ORDER BY id ASC',
                conn,
            )
        st.dataframe(df_socios, use_container_width=True)

        if not df_socios.empty:
            st.download_button(
                label="📥 Exportar Socios a Excel",
                data=to_excel(df_socios),
                file_name=f"reporte_socios_{datetime.now().strftime('%Y%m%d')}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )

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
                    with engine.begin() as conn:
                        conn.execute(
                            text("INSERT INTO socios (nombre, telefono, fecha_registro) VALUES (:nombre, :telefono, :fecha)"),
                            {"nombre": nombre, "telefono": telefono, "fecha": str(fecha_reg)}
                        )
                    st.success(f"¡Socio '{nombre}' registrado correctamente!")
                    st.rerun()

    with tab3:
        st.subheader("Modificar Datos de un Socio Existente")
        with engine.connect() as conn:
            df_s_edit = pd.read_sql("SELECT id, nombre, telefono, fecha_registro, estado FROM socios ORDER BY nombre ASC", conn)

        if df_s_edit.empty:
            st.info("No hay socios registrados para editar.")
        else:
            dict_s_edit = dict(zip(df_s_edit["nombre"], df_s_edit["id"]))
            socio_sel = st.selectbox("Selecciona el Socio a Editar:", list(dict_s_edit.keys()))
            id_socio_sel = dict_s_edit[socio_sel]

            datos_socio = df_s_edit[df_s_edit["id"] == id_socio_sel].iloc[0]

            with st.form("form_edit_socio"):
                e_nombre = st.text_input("Nombre Completo", value=datos_socio["nombre"])
                e_telefono = st.text_input("Teléfono / WhatsApp", value=datos_socio["telefono"] or "")
                
                fecha_orig = datos_socio["fecha_registro"]
                if isinstance(fecha_orig, str):
                    fecha_orig = datetime.strptime(fecha_orig, "%Y-%m-%d").date()
                
                e_fecha = st.date_input("Fecha de Registro", value=fecha_orig)
                e_estado = st.selectbox("Estado", ["Activo", "Inactivo"], index=0 if datos_socio["estado"] == "Activo" else 1)

                btn_guardar_edit = st.form_submit_button("Guardar Cambios")

                if btn_guardar_edit:
                    with engine.begin() as conn:
                        conn.execute(
                            text("UPDATE socios SET nombre = :nombre, telefono = :telefono, fecha_registro = :fecha, estado = :estado WHERE id = :id"),
                            {"nombre": e_nombre, "telefono": e_telefono, "fecha": str(e_fecha), "estado": e_estado, "id": id_socio_sel}
                        )
                    st.success("¡Datos del socio actualizados exitosamente!")
                    st.rerun()

# ==========================================
# SECCIÓN 3: AHORROS Y CUOTAS
# ==========================================
elif opcion == "💵 Ahorros y Cuotas":
    st.title("💵 Registro de Ahorros")

    with engine.connect() as conn:
        df_socios = pd.read_sql("SELECT id, nombre FROM socios WHERE estado = 'Activo' ORDER BY nombre ASC", conn)

    if df_socios.empty:
        st.warning("Primero debes registrar socios en la sección '👥 Socios'.")
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
                    anio_curr = fecha_ahorro.year
                    with engine.begin() as conn:
                        conn.execute(
                            text("INSERT INTO ahorros (socio_id, monto, fecha, nota, anio) VALUES (:socio_id, :monto, :fecha, :nota, :anio)"),
                            {"socio_id": socio_id, "monto": monto_ahorro, "fecha": str(fecha_ahorro), "nota": nota_ahorro, "anio": anio_curr}
                        )
                    st.success(f"Ahorro de C$ {monto_ahorro:,.2f} registrado para {socio_nom}.")
                    st.rerun()

        with tab2:
            st.subheader("Historial General de Aportaciones")
            query_ahorros = """
                SELECT a.id as "ID", s.nombre as "Socio", a.monto as "Monto (C$)", a.fecha as "Fecha", a.nota as "Nota"
                FROM ahorros a
                JOIN socios s ON a.socio_id = s.id
                ORDER BY a.fecha DESC, a.id DESC
            """
            with engine.connect() as conn:
                df_hist_ahorros = pd.read_sql(query_ahorros, conn)
            st.dataframe(df_hist_ahorros, use_container_width=True)

            if not df_hist_ahorros.empty:
                st.download_button(
                    label="📥 Exportar Ahorros a Excel",
                    data=to_excel(df_hist_ahorros),
                    file_name=f"reporte_ahorros_{datetime.now().strftime('%Y%m%d')}.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                )

        with tab3:
            st.subheader("Corregir o Eliminar Registro de Ahorro")
            query_edit_a = """
                SELECT a.id, s.nombre || ' - C$ ' || a.monto || ' (' || a.fecha || ')' as label,
                       a.socio_id, a.monto, a.fecha, a.nota
                FROM ahorros a
                JOIN socios s ON a.socio_id = s.id
                ORDER BY a.id DESC
            """
            with engine.connect() as conn:
                df_edit_a = pd.read_sql(query_edit_a, conn)

            if df_edit_a.empty:
                st.info("No hay registros de ahorro para modificar.")
            else:
                dict_edit_a = dict(zip(df_edit_a["label"], df_edit_a["id"]))
                ahorro_sel = st.selectbox("Selecciona el depósito a editar:", list(dict_edit_a.keys()))
                id_a_sel = dict_edit_a[ahorro_sel]

                reg_a = df_edit_a[df_edit_a["id"] == id_a_sel].iloc[0]

                with st.form("form_edit_ahorro"):
                    socio_idx = list(dict_socios.values()).index(reg_a["socio_id"]) if reg_a["socio_id"] in dict_socios.values() else 0
                    e_socio_nom = st.selectbox("Socio", list(dict_socios.keys()), index=socio_idx)
                    e_monto = st.number_input("Monto (C$)", value=float(reg_a["monto"]), min_value=1.0, step=10.0)
                    
                    f_a_orig = reg_a["fecha"]
                    if isinstance(f_a_orig, str):
                        f_a_orig = datetime.strptime(f_a_orig, "%Y-%m-%d").date()
                        
                    e_fecha = st.date_input("Fecha", value=f_a_orig)
                    e_nota = st.text_input("Nota", value=reg_a["nota"] or "")

                    col_btn1, col_btn2 = st.columns(2)
                    with col_btn1:
                        btn_update_a = st.form_submit_button("💾 Guardar Cambios")
                    with col_btn2:
                        btn_delete_a = st.form_submit_button("🗑️ Eliminar Registro")

                    if btn_update_a:
                        with engine.begin() as conn:
                            conn.execute(
                                text("UPDATE ahorros SET socio_id = :socio_id, monto = :monto, fecha = :fecha, nota = :nota, anio = :anio WHERE id = :id"),
                                {
                                    "socio_id": dict_socios[e_socio_nom],
                                    "monto": e_monto,
                                    "fecha": str(e_fecha),
                                    "nota": e_nota,
                                    "anio": e_fecha.year,
                                    "id": id_a_sel
                                }
                            )
                        st.success("¡Registro de ahorro actualizado!")
                        st.rerun()

                    if btn_delete_a:
                        with engine.begin() as conn:
                            conn.execute(text("DELETE FROM ahorros WHERE id = :id"), {"id": id_a_sel})
                        st.warning("Registro de ahorro eliminado correctamente.")
                        st.rerun()

# ==========================================
# SECCIÓN 4: PRÉSTAMOS Y SIMULADOR
# ==========================================
elif opcion == "🤝 Préstamos":
    st.title("🤝 Gestión de Préstamos")

    with engine.connect() as conn:
        df_socios = pd.read_sql("SELECT id, nombre FROM socios WHERE estado = 'Activo' ORDER BY nombre ASC", conn)

    if df_socios.empty:
        st.warning("Registra socios antes de procesar préstamos.")
    else:
        dict_socios = dict(zip(df_socios["nombre"], df_socios["id"]))
        tab1, tab2, tab3 = st.tabs(["➕ Nuevo Préstamo", "📜 Historial", "✏️ Editar Préstamo"])

        with tab1:
            st.subheader("Nuevo Préstamo")
            col1, col2 = st.columns(2)
            with col1:
                socio_prestamo = st.selectbox("Socio Solicitante", list(dict_socios.keys()))
                monto_solicitado = st.number_input("Monto del Préstamo (C$)", min_value=10.0, step=50.0)
                tasa_interes = st.number_input("Tasa de Interés Mensual (%)", min_value=0.0, value=5.0, step=0.5)

            with col2:
                plazo_meses = st.number_input("Plazo en Meses", min_value=1, max_value=36, value=6)
                fecha_prestamo = st.date_input("Fecha de Emisión", datetime.now())

            interes_mensual = monto_solicitado * (tasa_interes / 100)
            intereses_total = interes_mensual * plazo_meses
            monto_total_pagar = monto_solicitado + intereses_total
            cuota_mensual = monto_total_pagar / plazo_meses

            st.info(f"""
            **Resumen del Préstamo:**
            * **Interés Total Calculado:** C$ {intereses_total:,.2f}
            * **Monto Total a Devolver:** C$ {monto_total_pagar:,.2f}
            * **Cuota Mensual Estimada:** C$ {cuota_mensual:,.2f} / mes
            """)

            if st.button("Aprobar y Registrar Préstamo"):
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
                st.success(f"Préstamo registrado exitosamente para {socio_prestamo}")
                st.rerun()

        with tab2:
            st.subheader("Historial de Préstamos")
            query_p = """
                SELECT p.id as "ID", s.nombre as "Socio", p.monto_prestado as "Monto Prestado (C$)",
                       p.tasa_interes as "Tasa (%)", p.plazo_meses as "Plazo (Meses)",
                       p.interes_total as "Interés Total (C$)", p.monto_total as "Total a Pagar (C$)",
                       p.fecha_inicio as "Fecha", p.estado as "Estado"
                FROM prestamos p
                JOIN socios s ON p.socio_id = s.id
                ORDER BY p.id DESC
            """
            with engine.connect() as conn:
                df_prestamos_hist = pd.read_sql(query_p, conn)
            st.dataframe(df_prestamos_hist, use_container_width=True)

            if not df_prestamos_hist.empty:
                st.download_button(
                    label="📥 Exportar Préstamos a Excel",
                    data=to_excel(df_prestamos_hist),
                    file_name=f"reporte_prestamos_{datetime.now().strftime('%Y%m%d')}.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                )

        with tab3:
            st.subheader("Modificar Ficha de Préstamo")
            query_edit_p = """
                SELECT p.id, s.nombre || ' - Préstamo #' || p.id || ' (C$' || p.monto_prestado || ')' as label,
                       p.socio_id, p.monto_prestado, p.tasa_interes, p.plazo_meses, p.fecha_inicio, p.estado
                FROM prestamos p
                JOIN socios s ON p.socio_id = s.id
                ORDER BY p.id DESC
            """
            with engine.connect() as conn:
                df_edit_p = pd.read_sql(query_edit_p, conn)

            if df_edit_p.empty:
                st.info("No hay préstamos para editar.")
            else:
                dict_edit_p = dict(zip(df_edit_p["label"], df_edit_p["id"]))
                prestamo_sel_e = st.selectbox("Selecciona el Préstamo a Editar:", list(dict_edit_p.keys()))
                id_p_sel = dict_edit_p[prestamo_sel_e]

                reg_p = df_edit_p[df_edit_p["id"] == id_p_sel].iloc[0]

                with st.form("form_edit_prestamo"):
                    e_monto_p = st.number_input("Monto Prestado (C$)", value=float(reg_p["monto_prestado"]), min_value=10.0, step=50.0)
                    e_tasa_p = st.number_input("Tasa Interés (%)", value=float(reg_p["tasa_interes"]), min_value=0.0, step=0.5)
                    e_plazo_p = st.number_input("Plazo (Meses)", value=int(reg_p["plazo_meses"]), min_value=1, max_value=36)
                    
                    f_p_orig = reg_p["fecha_inicio"]
                    if isinstance(f_p_orig, str):
                        f_p_orig = datetime.strptime(f_p_orig, "%Y-%m-%d").date()
                        
                    e_fecha_p = st.date_input("Fecha Inicio", value=f_p_orig)
                    e_estado_p = st.selectbox("Estado del Préstamo", ["Activo", "Saldado", "Cancelado"], index=["Activo", "Saldado", "Cancelado"].index(reg_p["estado"]))

                    # Recálculos
                    e_int_m = e_monto_p * (e_tasa_p / 100)
                    e_int_tot = e_int_m * e_plazo_p
                    e_monto_tot = e_monto_p + e_int_tot

                    btn_guardar_p = st.form_submit_button("💾 Guardar Cambios")

                    if btn_guardar_p:
                        with engine.begin() as conn:
                            conn.execute(
                                text("""
                                    UPDATE prestamos
                                    SET monto_prestado = :monto, tasa_interes = :tasa, plazo_meses = :plazo,
                                        interes_total = :int_tot, monto_total = :monto_tot, fecha_inicio = :fecha,
                                        estado = :estado, anio = :anio
                                    WHERE id = :id
                                """),
                                {
                                    "monto": e_monto_p, "tasa": e_tasa_p, "plazo": e_plazo_p,
                                    "int_tot": e_int_tot, "monto_tot": e_monto_tot,
                                    "fecha": str(e_fecha_p), "estado": e_estado_p,
                                    "anio": e_fecha_p.year, "id": id_p_sel
                                }
                            )
                        st.success("¡Préstamo modificado correctamente!")
                        st.rerun()

# ==========================================
# SECCIÓN 5: REGISTRO DE PAGOS DE PRÉSTAMOS
# ==========================================
elif opcion == "📖 Pagos de Préstamos":
    st.title("📖 Registro de Abonos y Pagos")

    tab1, tab2, tab3 = st.tabs(["➕ Registrar Abono", "📜 Historial de Pagos", "✏️ Editar / Borrar Pago"])

    with tab1:
        query_activos = """
            SELECT p.id, s.nombre || ' - Préstamo #' || p.id || ' (C$' || p.monto_total || ' total)' as label
            FROM prestamos p
            JOIN socios s ON p.socio_id = s.id
            WHERE p.estado = 'Activo'
        """
        with engine.connect() as conn:
            df_prestamos_act = pd.read_sql(query_activos, conn)

        if df_prestamos_act.empty:
            st.info("No hay préstamos activos pendientes de pago.")
        else:
            dict_prestamos = dict(zip(df_prestamos_act["label"], df_prestamos_act["id"]))
            with st.form("form_pago", clear_on_submit=True):
                prestamo_sel = st.selectbox("Selecciona el Préstamo *", list(dict_prestamos.keys()))
                monto_pago = st.number_input("Monto del Pago/Abono (C$) *", min_value=1.0, step=10.0)
                tipo_pago = st.selectbox("Tipo de Abono", ["Capital", "Interés", "Completo"])
                fecha_pago = st.date_input("Fecha del Pago", datetime.now())
                btn_pago = st.form_submit_button("Registrar Pago")

                if btn_pago:
                    p_id = dict_prestamos[prestamo_sel]
                    with engine.begin() as conn:
                        conn.execute(
                            text("INSERT INTO pagos (prestamo_id, monto_pagado, fecha, tipo) VALUES (:p_id, :monto, :fecha, :tipo)"),
                            {"p_id": p_id, "monto": monto_pago, "fecha": str(fecha_pago), "tipo": tipo_pago}
                        )

                        df_total_p = pd.read_sql(text(f"SELECT COALESCE(SUM(monto_pagado), 0) as suma FROM pagos WHERE prestamo_id = {p_id}"), conn)
                        pagado_hasta_hoy = float(df_total_p["suma"].iloc[0])

                        df_monto_orig = pd.read_sql(text(f"SELECT monto_total FROM prestamos WHERE id = {p_id}"), conn)
                        monto_orig = float(df_monto_orig["monto_total"].iloc[0])

                        if pagado_hasta_hoy >= monto_orig:
                            conn.execute(text(f"UPDATE prestamos SET estado = 'Saldado' WHERE id = {p_id}"))
                            st.balloons()
                            st.success("¡El préstamo ha sido saldado completamente!")
                        else:
                            st.success("Abono registrado correctamente.")
                    st.rerun()

    with tab2:
        st.subheader("Historial de Pagos Recibidos")
        query_pagos = """
            SELECT pg.id as "ID", s.nombre as "Socio", pg.prestamo_id as "ID Préstamo",
                   pg.monto_pagado as "Monto Pagado (C$)", pg.tipo as "Tipo", pg.fecha as "Fecha"
            FROM pagos pg
            JOIN prestamos p ON pg.prestamo_id = p.id
            JOIN socios s ON p.socio_id = s.id
            ORDER BY pg.id DESC
        """
        with engine.connect() as conn:
            df_pagos_hist = pd.read_sql(query_pagos, conn)
        st.dataframe(df_pagos_hist, use_container_width=True)

        if not df_pagos_hist.empty:
            st.download_button(
                label="📥 Exportar Pagos a Excel",
                data=to_excel(df_pagos_hist),
                file_name=f"reporte_pagos_{datetime.now().strftime('%Y%m%d')}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )

    with tab3:
        st.subheader("Editar o Eliminar un Pago")
        query_edit_pg = """
            SELECT pg.id, s.nombre || ' - Pago #' || pg.id || ' (C$' || pg.monto_pagado || ')' as label,
                   pg.monto_pagado, pg.tipo, pg.fecha, pg.prestamo_id
            FROM pagos pg
            JOIN prestamos p ON pg.prestamo_id = p.id
            JOIN socios s ON p.socio_id = s.id
            ORDER BY pg.id DESC
        """
        with engine.connect() as conn:
            df_edit_pg = pd.read_sql(query_edit_pg, conn)

        if df_edit_pg.empty:
            st.info("No hay pagos para editar.")
        else:
            dict_edit_pg = dict(zip(df_edit_pg["label"], df_edit_pg["id"]))
            pago_sel_e = st.selectbox("Selecciona el Pago:", list(dict_edit_pg.keys()))
            id_pg_sel = dict_edit_pg[pago_sel_e]

            reg_pg = df_edit_pg[df_edit_pg["id"] == id_pg_sel].iloc[0]

            with st.form("form_edit_pago"):
                e_monto_pg = st.number_input("Monto Pagado (C$)", value=float(reg_pg["monto_pagado"]), min_value=1.0, step=10.0)
                e_tipo_pg = st.selectbox("Tipo", ["Capital", "Interés", "Completo"], index=["Capital", "Interés", "Completo"].index(reg_pg["tipo"]))
                
                f_pg_orig = reg_pg["fecha"]
                if isinstance(f_pg_orig, str):
                    f_pg_orig = datetime.strptime(f_pg_orig, "%Y-%m-%d").date()
                    
                e_fecha_pg = st.date_input("Fecha de Pago", value=f_pg_orig)

                c_btn1, c_btn2 = st.columns(2)
                with c_btn1:
                    btn_upd_pg = st.form_submit_button("💾 Guardar Cambios")
                with c_btn2:
                    btn_del_pg = st.form_submit_button("🗑️ Eliminar Pago")

                if btn_upd_pg:
                    with engine.begin() as conn:
                        conn.execute(
                            text("UPDATE pagos SET monto_pagado = :monto, tipo = :tipo, fecha = :fecha WHERE id = :id"),
                            {"monto": e_monto_pg, "tipo": e_tipo_pg, "fecha": str(e_fecha_pg), "id": id_pg_sel}
                        )
                    st.success("¡Pago actualizado!")
                    st.rerun()

                if btn_del_pg:
                    with engine.begin() as conn:
                        conn.execute(text("DELETE FROM pagos WHERE id = :id"), {"id": id_pg_sel})
                    st.warning("Pago eliminado.")
                    st.rerun()

# ==========================================
# SECCIÓN 6: IMPRIMIR ESTADO DE CUENTA
# ==========================================
elif opcion == "📄 Estado de Cuenta":
    st.title("📄 Estado de Cuenta Individual")
    st.caption("Consulta e imprime la ficha detallada de ahorro y préstamos por socio.")

    with engine.connect() as conn:
        df_socios = pd.read_sql("SELECT id, nombre FROM socios ORDER BY nombre ASC", conn)

    if df_socios.empty:
        st.warning("No hay socios registrados.")
    else:
        dict_socios = dict(zip(df_socios["nombre"], df_socios["id"]))
        socio_sel = st.selectbox("Selecciona un Socio para generar Estado de Cuenta", list(dict_socios.keys()))
        s_id = dict_socios[socio_sel]

        with engine.connect() as conn:
            df_ahorro_socio = pd.read_sql(f"SELECT COALESCE(SUM(monto), 0) as total FROM ahorros WHERE socio_id = {s_id}", conn)
            total_ahorrado_socio = float(df_ahorro_socio["total"].iloc[0])

            df_prestamo_socio = pd.read_sql(f"SELECT COALESCE(SUM(monto_prestado), 0) as total FROM prestamos WHERE socio_id = {s_id} AND estado = 'Activo'", conn)
            total_prestado_socio = float(df_prestamo_socio["total"].iloc[0])

        st.markdown("---")
        st.markdown(f"## 🏦 Estado de Cuenta - **{socio_sel}**")
        st.markdown(f"**Fecha de emisión:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

        c1, c2 = st.columns(2)
        c1.metric("💵 Capital Total Ahorrado", f"C$ {total_ahorrado_socio:,.2f}")
        c2.metric("📉 Préstamos Activos", f"C$ {total_prestado_socio:,.2f}")

        st.markdown("### 📜 Detalle de Ahorros")
        with engine.connect() as conn:
            df_ahorros_det = pd.read_sql(f'SELECT fecha as "Fecha", monto as "Monto (C$)", nota as "Nota" FROM ahorros WHERE socio_id = {s_id} ORDER BY fecha DESC', conn)
        st.dataframe(df_ahorros_det, use_container_width=True)

        st.markdown("### 🤝 Detalle de Préstamos")
        with engine.connect() as conn:
            df_prestamos_det = pd.read_sql(f'SELECT id as "ID Préstamo", monto_prestado as "Monto (C$)", interes_total as "Interés Total (C$)", monto_total as "Total a Pagar (C$)", estado as "Estado", fecha_inicio as "Fecha" FROM prestamos WHERE socio_id = {s_id}', conn)
        st.dataframe(df_prestamos_det, use_container_width=True)

        if not df_ahorros_det.empty or not df_prestamos_det.empty:
            output_socio = io.BytesIO()
            with pd.ExcelWriter(output_socio, engine="openpyxl") as writer:
                df_ahorros_det.to_excel(writer, index=False, sheet_name="Ahorros")
                df_prestamos_det.to_excel(writer, index=False, sheet_name="Prestamos")

            st.download_button(
                label=f"📥 Imprimir / Descargar Estado de Cuenta de {socio_sel} (Excel)",
                data=output_socio.getvalue(),
                file_name=f"estado_cuenta_{socio_sel.replace(' ', '_')}_{datetime.now().strftime('%Y%m%d')}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )

# ==========================================
# SECCIÓN 7: LIQUIDACIÓN ANUAL DE SOCIOS
# ==========================================
elif opcion == "🎉 Liquidación Anual":
    st.title("🎉 Cálculo de Liquidación Automática de Fin de Año")
    st.caption("Reparto transparente de capital prestado/alquilado e intereses generados para cada socio.")

    with engine.connect() as conn:
        df_tot_ahorro = pd.read_sql("SELECT COALESCE(SUM(monto), 0) as total FROM ahorros", conn)
        gran_total_ahorrado = float(df_tot_ahorro["total"].iloc[0])

        df_tot_intereses = pd.read_sql("SELECT COALESCE(SUM(monto_pagado), 0) as total FROM pagos WHERE tipo = 'Interés' OR tipo = 'Completo'", conn)
        total_intereses_ganados = float(df_tot_intereses["total"].iloc[0])

    c1, c2, c3 = st.columns(3)
    c1.metric("💵 Fondo Total Ahorrado", f"C$ {gran_total_ahorrado:,.2f}")
    c2.metric("📈 Intereses Totales Ganados", f"C$ {total_intereses_ganados:,.2f}")
    c3.metric("🏦 Gran Total en Caja a Repartir", f"C$ {(gran_total_ahorrado + total_intereses_ganados):,.2f}")

    st.markdown("---")

    if gran_total_ahorrado == 0:
        st.warning("No hay aportaciones de ahorro registradas aún para calcular la liquidación.")
    else:
        st.subheader("📋 Tabla Oficial de Reparto por Socio")
        query_liq = """
            SELECT s.id as "ID", s.nombre as "Socio", COALESCE(SUM(a.monto), 0) as "Ahorro_Total"
            FROM socios s
            LEFT JOIN ahorros a ON s.id = a.socio_id
            WHERE s.estado = 'Activo'
            GROUP BY s.id, s.nombre
        """
        with engine.connect() as conn:
            df_liq = pd.read_sql(query_liq, conn)

        df_liq["Participación (%)"] = (df_liq["Ahorro_Total"] / gran_total_ahorrado) * 100
        df_liq["Interés Ganado (C$)"] = (df_liq["Participación (%)"] / 100) * total_intereses_ganados
        df_liq["Total a Entregar (C$)"] = df_liq["Ahorro_Total"] + df_liq["Interés Ganado (C$)"]

        df_display = df_liq.copy()
        df_display["Ahorro_Total"] = df_display["Ahorro_Total"].map("C$ {:,.2f}".format)
        df_display["Participación (%)"] = df_display["Participación (%)"].map("{:,.2f}%".format)
        df_display["Interés Ganado (C$)"] = df_display["Interés Ganado (C$)"].map("C$ {:,.2f}".format)
        df_display["Total a Entregar (C$)"] = df_display["Total a Entregar (C$)"].map("C$ {:,.2f}".format)
        df_display = df_display.rename(columns={"Ahorro_Total": "Capital Ahorrado (C$)"})

        st.dataframe(df_display, use_container_width=True)

        st.download_button(
            label="📥 Exportar Tabla de Liquidación a Excel",
            data=to_excel(df_liq),
            file_name=f"liquidacion_anual_{datetime.now().strftime('%Y%m%d')}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        st.success("💡 **Cálculo Automático Aplicado:** Los intereses totales generados se distribuyen proporcionalmente al capital aportado por cada socio.")

# ==========================================
# SECCIÓN 8: CIERRE MENSUAL Y REINICIO ANUAL
# ==========================================
elif opcion == "🔒 Cierre Mensual y Anual":
    st.title("🔒 Módulo de Cierre Mensual y Anual")
    st.caption("Control mensual de caja e historial de liquidaciones cerradas.")

    tab1, tab2 = st.tabs(["📅 Cierre Mensual", "🔄 Reinicio de Ciclo Anual"])

    with tab1:
        st.subheader("Resumen Mensual")
        col_m1, col_m2 = st.columns(2)
        with col_m1:
            mes_sel = st.selectbox("Seleccionar Mes", list(range(1, 13)), index=datetime.now().month - 1)
        with col_m2:
            anio_sel = st.number_input("Seleccionar Año", min_value=2020, max_value=2100, value=datetime.now().year)

        query_mensual_ahorro = """
            SELECT COALESCE(SUM(monto), 0) as total
            FROM ahorros
            WHERE EXTRACT(MONTH FROM fecha) = :mes AND EXTRACT(YEAR FROM fecha) = :anio
        """
        query_mensual_pagos = """
            SELECT COALESCE(SUM(monto_pagado), 0) as total
            FROM pagos
            WHERE EXTRACT(MONTH FROM fecha) = :mes AND EXTRACT(YEAR FROM fecha) = :anio
        """

        with engine.connect() as conn:
            tot_ahorro_m = float(pd.read_sql(text(query_mensual_ahorro), conn, params={"mes": mes_sel, "anio": anio_sel})["total"].iloc[0])
            tot_pagos_m = float(pd.read_sql(text(query_mensual_pagos), conn, params={"mes": mes_sel, "anio": anio_sel})["total"].iloc[0])

        st.metric(f"💵 Ahorros del Mes ({mes_sel}/{anio_sel})", f"C$ {tot_ahorro_m:,.2f}")
        st.metric(f"📥 Pagos/Cobros Recibidos en el Mes ({mes_sel}/{anio_sel})", f"C$ {tot_pagos_m:,.2f}")

    with tab2:
        st.subheader("⚠️ Cerrar Año Lectivo y Reiniciar Ciclo")
        st.warning("Al ejecutar el Cierre Anual, se registrará el resumen de este período en el historial. Los saldos de ahorro se archivarán para empezar un nuevo ciclo el próximo año manteniendo la lista de socios.")

        anio_cierre = st.number_input("Año a Cerrar", min_value=2020, max_value=2100, value=datetime.now().year, key="cierre_anio")

        if st.button("🚀 Ejecutar Cierre y Reiniciar Año"):
            with engine.connect() as conn:
                df_tot_a = pd.read_sql("SELECT COALESCE(SUM(monto), 0) as total FROM ahorros", conn)
                tot_a = float(df_tot_a["total"].iloc[0])

                df_tot_i = pd.read_sql("SELECT COALESCE(SUM(monto_pagado), 0) as total FROM pagos WHERE tipo = 'Interés' OR tipo = 'Completo'", conn)
                tot_i = float(df_tot_i["total"].iloc[0])

            with engine.begin() as conn:
                conn.execute(
                    text("INSERT INTO cierres_anuales (anio, total_ahorrado, total_intereses) VALUES (:anio, :tot_a, :tot_i)"),
                    {"anio": anio_cierre, "tot_a": tot_a, "tot_i": tot_i}
                )

                # Limpiar tablas de caja activa
                conn.execute(text("DELETE FROM pagos;"))
                conn.execute(text("DELETE FROM prestamos;"))
                conn.execute(text("DELETE FROM ahorros;"))

            st.success(f"¡El año {anio_cierre} ha sido cerrado correctamente! El sistema está listo para el nuevo ciclo.")
            st.rerun()

        st.markdown("---")
        st.subheader("📚 Historial de Cierres Anuales")
        with engine.connect() as conn:
            df_hist_cierres = pd.read_sql('SELECT id as "ID", anio as "Año", total_ahorrado as "Total Ahorrado (C$)", total_intereses as "Intereses (C$)", fecha_cierre as "Fecha de Cierre" FROM cierres_anuales ORDER BY anio DESC', conn)
        st.dataframe(df_hist_cierres, use_container_width=True)
