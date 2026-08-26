import sqlite3
from datetime import datetime
import pandas as pd
import streamlit as st

# ==========================================
# CONFIGURACIÓN DE PÁGINA
# ==========================================
st.set_page_config(
    page_title="Caja de Ahorro Comunitario", page_icon="💰", layout="wide"
)


# ==========================================
# GESTIÓN DE BASE DE DATOS (SQLite)
# ==========================================
def get_connection():
    conn = sqlite3.connect("caja_ahorro.db")
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


def init_db():
    conn = get_connection()
    cursor = conn.cursor()

    # Tabla de Socios
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS socios (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nombre TEXT NOT NULL,
            telefono TEXT,
            fecha_registro TEXT NOT NULL,
            estado TEXT DEFAULT 'Activo'
        )
    """)

    # Tabla de Ahorros
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS ahorros (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            socio_id INTEGER NOT NULL,
            monto REAL NOT NULL,
            fecha TEXT NOT NULL,
            nota TEXT,
            FOREIGN KEY (socio_id) REFERENCES socios (id)
        )
    """)

    # Tabla de Préstamos
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS prestamos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            socio_id INTEGER NOT NULL,
            monto_prestado REAL NOT NULL,
            tasa_interes REAL NOT NULL,
            plazo_meses INTEGER NOT NULL,
            interes_total REAL NOT NULL,
            monto_total REAL NOT NULL,
            fecha_inicio TEXT NOT NULL,
            estado TEXT DEFAULT 'Pendiente',
            FOREIGN KEY (socio_id) REFERENCES socios (id)
        )
    """)

    # Tabla de Pagos de Préstamos
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS pagos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            prestamo_id INTEGER NOT NULL,
            monto_pagado REAL NOT NULL,
            fecha TEXT NOT NULL,
            tipo TEXT CHECK(tipo IN ('Capital', 'Interés', 'Completo')),
            FOREIGN KEY (prestamo_id) REFERENCES prestamos (id)
        )
    """)

    conn.commit()
    conn.close()


init_db()


# ==========================================
# MENÚ NAVEGACIÓN LATERAL
# ==========================================
st.sidebar.title("🏦 Menú Principal")
opcion = st.sidebar.radio(
    "Selecciona una sección:",
    [
        "📊 Panel General",
        "👥 Socios",
        "💵 Ahorros y Cuotas",
        "🤝 Préstamos",
        "📑 Pagos de Préstamos",
        "🎉 Liquidación Anual",
    ],
)


# ==========================================
# SECCIÓN 1: PANEL GENERAL (DASHBOARD)
# ==========================================
if opcion == "📊 Panel General":
    st.title("📊 Panel General de la Caja de Ahorro")
    st.caption(
        "Resumen financiero en tiempo real del grupo de ahorro comunitario."
    )

    conn = get_connection()

    df_ahorros = pd.read_sql("SELECT SUM(monto) as total FROM ahorros", conn)
    total_ahorrado = df_ahorros["total"].iloc[0] or 0.0

    df_prestamos = pd.read_sql(
        "SELECT SUM(monto_prestado) as total FROM prestamos WHERE estado = 'Activo'",
        conn,
    )
    total_prestado = df_prestamos["total"].iloc[0] or 0.0

    df_pagos = pd.read_sql("SELECT SUM(monto_pagado) as total FROM pagos", conn)
    total_recaudado = df_pagos["total"].iloc[0] or 0.0

    df_socios = pd.read_sql(
        "SELECT COUNT(*) as total FROM socios WHERE estado = 'Activo'", conn
    )
    total_socios = df_socios["total"].iloc[0] or 0

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("💰 Fondo Total Ahorrado", f"${total_ahorrado:,.2f}")
    col2.metric("📉 Capital Prestado Activo", f"${total_prestado:,.2f}")
    col3.metric("📥 Cobros/Abonos Totales", f"${total_recaudado:,.2f}")
    col4.metric("👥 Socios Activos", f"{total_socios}")

    st.markdown("---")

    col_izq, col_der = st.columns(2)

    with col_izq:
        st.subheader("📌 Últimos Ahorros Registrados")
        query_ult_ahorros = """
            SELECT a.fecha as Fecha, s.nombre as Socio, a.monto as Monto
            FROM ahorros a
            JOIN socios s ON a.socio_id = s.id
            ORDER BY a.id DESC LIMIT 5
        """
        df_rec_ahorros = pd.read_sql(query_ult_ahorros, conn)
        st.dataframe(df_rec_ahorros, use_container_width=True)

    with col_der:
        st.subheader("⚠️ Préstamos Activos")
        query_prestamos_act = """
            SELECT p.id as ID, s.nombre as Socio, p.monto_prestado as Monto, p.monto_total as Total_Con_Interes
            FROM prestamos p
            JOIN socios s ON p.socio_id = s.id
            WHERE p.estado = 'Activo'
        """
        df_rec_prestamos = pd.read_sql(query_prestamos_act, conn)
        st.dataframe(df_rec_prestamos, use_container_width=True)

    conn.close()


# ==========================================
# SECCIÓN 2: GESTIÓN DE SOCIOS
# ==========================================
elif opcion == "👥 Socios":
    st.title("👥 Control de Socios")

    tab1, tab2 = st.tabs(["📋 Listado de Socios", "➕ Registrar Nuevo Socio"])

    conn = get_connection()

    with tab1:
        st.subheader("Socios Registrados")
        df_socios = pd.read_sql(
            "SELECT id as ID, nombre as Nombre, telefono as Teléfono, fecha_registro as 'Fecha Registro', estado as Estado FROM socios",
            conn,
        )
        st.dataframe(df_socios, use_container_width=True)

    with tab2:
        st.subheader("Formulario de Registro")
        with st.form("form_socio", clear_on_submit=True):
            nombre = st.text_input("Nombre Completo *")
            telefono = st.text_input("Número de Teléfono / WhatsApp")
            fecha_reg = st.date_input("Fecha de Ingreso", datetime.now())

            submitted = st.form_submit_button("Guardar Socio")
            if submitted:
                if nombre.strip() == "":
                    st.error("El nombre del socio es obligatorio.")
                else:
                    cursor = conn.cursor()
                    cursor.execute(
                        "INSERT INTO socios (nombre, telefono, fecha_registro) VALUES (?, ?, ?)",
                        (nombre, telefono, str(fecha_reg)),
                    )
                    conn.commit()
                    st.success(f"¡Socio '{nombre}' registrado correctamente!")
                    st.rerun()

    conn.close()


# ==========================================
# SECCIÓN 3: AHORROS Y CUOTAS
# ==========================================
elif opcion == "💵 Ahorros y Cuotas":
    st.title("💵 Registro de Ahorros")

    conn = get_connection()
    df_socios = pd.read_sql(
        "SELECT id, nombre FROM socios WHERE estado = 'Activo'", conn
    )

    if df_socios.empty:
        st.warning(
            "Primero debes registrar socios en la sección '👥 Socios'."
        )
    else:
        tab1, tab2 = st.tabs(
            ["➕ Depositar Ahorro", "📜 Historial de Ahorros"]
        )

        with tab1:
            st.subheader("Registrar Nueva Aportación")
            dict_socios = dict(zip(df_socios["nombre"], df_socios["id"]))

            with st.form("form_ahorro", clear_on_submit=True):
                socio_nom = st.selectbox(
                    "Selecciona el Socio *", list(dict_socios.keys())
                )
                monto_ahorro = st.number_input(
                    "Monto Ahorrado ($) *", min_value=1.0, step=5.0
                )
                fecha_ahorro = st.date_input(
                    "Fecha del Depósito", datetime.now()
                )
                nota_ahorro = st.text_input("Nota / Observación (Opcional)")

                btn_ahorro = st.form_submit_button("Registrar Depósito")
                if btn_ahorro:
                    socio_id = dict_socios[socio_nom]
                    cursor = conn.cursor()
                    cursor.execute(
                        "INSERT INTO ahorros (socio_id, monto, fecha, nota) VALUES (?, ?, ?, ?)",
                        (
                            socio_id,
                            monto_ahorro,
                            str(fecha_ahorro),
                            nota_ahorro,
                        ),
                    )
                    conn.commit()
                    st.success(
                        f"Ahorro de ${monto_ahorro:,.2f} registrado para {socio_nom}."
                    )
                    st.rerun()

        with tab2:
            st.subheader("Historial General de Aportaciones")
            query_ahorros = """
                SELECT a.id as ID, s.nombre as Socio, a.monto as 'Monto ($)', a.fecha as Fecha, a.nota as Nota
                FROM ahorros a
                JOIN socios s ON a.socio_id = s.id
                ORDER BY a.fecha DESC
            """
            df_hist_ahorros = pd.read_sql(query_ahorros, conn)
            st.dataframe(df_hist_ahorros, use_container_width=True)

    conn.close()


# ==========================================
# SECCIÓN 4: PRÉSTAMOS Y SIMULADOR
# ==========================================
elif opcion == "🤝 Préstamos":
    st.title("🤝 Gestión de Préstamos")

    conn = get_connection()
    df_socios = pd.read_sql(
        "SELECT id, nombre FROM socios WHERE estado = 'Activo'", conn
    )

    if df_socios.empty:
        st.warning("Registra socios antes de procesar préstamos.")
    else:
        dict_socios = dict(zip(df_socios["nombre"], df_socios["id"]))

        st.subheader("Nuevo Préstamo")

        col1, col2 = st.columns(2)
        with col1:
            socio_prestamo = st.selectbox(
                "Socio Solicitante", list(dict_socios.keys())
            )
            monto_solicitado = st.number_input(
                "Monto del Préstamo ($)", min_value=10.0, step=50.0
            )
            tasa_interes = st.number_input(
                "Tasa de Interés Mensual (%)",
                min_value=0.0,
                value=5.0,
                step=0.5,
            )

        with col2:
            plazo_meses = st.number_input(
                "Plazo en Meses", min_value=1, max_value=36, value=6
            )
            fecha_prestamo = st.date_input(
                "Fecha de Emisión", datetime.now()
            )

        interes_mensual = monto_solicitado * (tasa_interes / 100)
        interes_total = interes_mensual * plazo_meses
        monto_total_pagar = monto_solicitado + interes_total
        cuota_mensual = monto_total_pagar / plazo_meses

        st.info(f"""
        **Resumen del Préstamo:**
        * **Interés Total Calculado:** ${interes_total:,.2f}
        * **Monto Total a Devolver:** ${monto_total_pagar:,.2f}
        * **Cuota Mensual Estimada:** ${cuota_mensual:,.2f} / mes
        """)

        if st.button("Aprobar y Registrar Préstamo"):
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO prestamos (socio_id, monto_prestado, tasa_interes, plazo_meses, interes_total, monto_total, fecha_inicio, estado)
                VALUES (?, ?, ?, ?, ?, ?, ?, 'Activo')
            """,
                (
                    dict_socios[socio_prestamo],
                    monto_solicitado,
                    tasa_interes,
                    plazo_meses,
                    interes_total,
                    monto_total_pagar,
                    str(fecha_prestamo),
                ),
            )
            conn.commit()
            st.success(f"Préstamo registrado exitosamente para {socio_prestamo}")

        st.markdown("---")
        st.subheader("Historial de Préstamos")
        query_p = """
            SELECT p.id as ID, s.nombre as Socio, p.monto_prestado as 'Monto Original', 
                   p.interes_total as Interés, p.monto_total as 'Total a Pagar', 
                   p.fecha_inicio as Fecha, p.estado as Estado
            FROM prestamos p
            JOIN socios s ON p.socio_id = s.id
            ORDER BY p.id DESC
        """
        st.dataframe(pd.read_sql(query_p, conn), use_container_width=True)

    conn.close()


# ==========================================
# SECCIÓN 5: REGISTRO DE PAGOS DE PRÉSTAMOS
# ==========================================
elif opcion == "📑 Pagos de Préstamos":
    st.title("📑 Registro de Abonos y Pagos")

    conn = get_connection()

    query_activos = """
        SELECT p.id, s.nombre || ' - Préstamo #' || p.id || ' ($' || p.monto_total || ' total)' as label
        FROM prestamos p
        JOIN socios s ON p.socio_id = s.id
        WHERE p.estado = 'Activo'
    """
    df_prestamos_act = pd.read_sql(query_activos, conn)

    if df_prestamos_act.empty:
        st.info("No hay préstamos activos pendientes de pago.")
    else:
        dict_prestamos = dict(
            zip(df_prestamos_act["label"], df_prestamos_act["id"])
        )

        with st.form("form_pago", clear_on_submit=True):
            prestamo_sel = st.selectbox(
                "Selecciona el Préstamo *", list(dict_prestamos.keys())
            )
            monto_pago = st.number_input(
                "Monto del Pago/Abono ($) *", min_value=1.0, step=10.0
            )
            tipo_pago = st.selectbox(
                "Tipo de Abono", ["Capital", "Interés", "Completo"]
            )
            fecha_pago = st.date_input("Fecha del Pago", datetime.now())

            btn_pago = st.form_submit_button("Registrar Pago")

            if btn_pago:
                p_id = dict_prestamos[prestamo_sel]
                cursor = conn.cursor()
                cursor.execute(
                    "INSERT INTO pagos (prestamo_id, monto_pagado, fecha, tipo) VALUES (?, ?, ?, ?)",
                    (p_id, monto_pago, str(fecha_pago), tipo_pago),
                )

                df_total_p = pd.read_sql(
                    f"SELECT SUM(monto_pagado) as suma FROM pagos WHERE prestamo_id = {p_id}",
                    conn,
                )
                pagado_hasta_hoy = df_total_p["suma"].iloc[0] or 0.0

                df_monto_orig = pd.read_sql(
                    f"SELECT monto_total FROM prestamos WHERE id = {p_id}", conn
                )
                monto_orig = df_monto_orig["monto_total"].iloc[0]

                if pagado_hasta_hoy >= monto_orig:
                    cursor.execute(
                        "UPDATE prestamos SET estado = 'Saldado' WHERE id = ?",
                        (p_id,),
                    )
                    st.balloons()
                    st.success(
                        "¡El préstamo ha sido saldado completamente!"
                    )

                conn.commit()
                st.success("Abono registrado correctamente.")
                st.rerun()

        st.markdown("---")
        st.subheader("Historial de Pagos Recibidos")
        query_pagos = """
            SELECT pg.id as ID, s.nombre as Socio, pg.prestamo_id as 'ID Préstamo', 
                   pg.monto_pagado as 'Monto Pagado', pg.tipo as Tipo, pg.fecha as Fecha
            FROM pagos pg
            JOIN prestamos p ON pg.prestamo_id = p.id
            JOIN socios s ON p.socio_id = s.id
            ORDER BY pg.id DESC
        """
        st.dataframe(pd.read_sql(query_pagos, conn), use_container_width=True)

    conn.close()


# ==========================================
# SECCIÓN 6: LIQUIDACIÓN ANUAL DE SOCIOS
# ==========================================
elif opcion == "🎉 Liquidación Anual":
    st.title("🎉 Cálculo de Liquidación de Fin de Año")
    st.caption(
        "Reparto transparente de capital e intereses acumulados para cada socio."
    )

    conn = get_connection()

    # Total Ahorrado por todos los socios
    df_tot_ahorro = pd.read_sql("SELECT SUM(monto) as total FROM ahorros", conn)
    gran_total_ahorrado = df_tot_ahorro["total"].iloc[0] or 0.0

    # Total de Intereses Ganados (recaudados de préstamos o cuotas)
    df_tot_intereses = pd.read_sql(
        "SELECT SUM(monto_pagado) as total FROM pagos WHERE tipo = 'Interés' OR tipo = 'Completo'",
        conn,
    )
    total_intereses_ganados = df_tot_intereses["total"].iloc[0] or 0.0

    c1, c2, c3 = st.columns(3)
    c1.metric("💰 Fondo Total Ahorrado", f"${gran_total_ahorrado:,.2f}")
    c2.metric("📈 Intereses Totales Ganados", f"${total_intereses_ganados:,.2f}")
    c3.metric(
        "🏦 Gran Total en Caja a Repartir",
        f"${(gran_total_ahorrado + total_intereses_ganados):,.2f}",
    )

    st.markdown("---")

    if gran_total_ahorrado == 0:
        st.warning(
            "No hay aportaciones de ahorro registradas aún para calcular la liquidación."
        )
    else:
        st.subheader("📋 Tabla Oficial de Reparto por Socio")

        # Query para agrupar ahorro por socio
        query_liq = """
            SELECT s.id as ID, s.nombre as Socio, COALESCE(SUM(a.monto), 0) as Ahorro_Total
            FROM socios s
            LEFT JOIN ahorros a ON s.id = a.socio_id
            WHERE s.estado = 'Activo'
            GROUP BY s.id, s.nombre
        """
        df_liq = pd.read_sql(query_liq, conn)

        # Cálculo de porcentajes y reparto
        df_liq["Participación (%)"] = (
            df_liq["Ahorro_Total"] / gran_total_ahorrado
        ) * 100
        df_liq["Interés Ganado ($)"] = (
            df_liq["Participación (%)"] / 100
        ) * total_intereses_ganados
        df_liq["Total a Entregar ($)"] = (
            df_liq["Ahorro_Total"] + df_liq["Interés Ganado ($)"]
        )

        # Formatear columnas para visualización clara
        df_display = df_liq.copy()
        df_display["Ahorro_Total"] = df_display["Ahorro_Total"].map(
            "${:,.2f}".format
        )
        df_display["Participación (%)"] = df_display["Participación (%)"].map(
            "{:,.2f}%".format
        )
        df_display["Interés Ganado ($)"] = df_display["Interés Ganado ($)"].map(
            "${:,.2f}".format
        )
        df_display["Total a Entregar ($)"] = df_display[
            "Total a Entregar ($)"
        ].map("${:,.2f}".format)

        df_display = df_display.rename(
            columns={"Ahorro_Total": "Capital Ahorrado ($)"}
        )

        st.dataframe(df_display, use_container_width=True)

        st.success(
            "💡 **Fórmula aplicada:** El total de intereses generados se distribuye proporcionalmente al porcentaje del capital que cada socio aportó durante el periodo."
        )

    conn.close()
