import hashlib
import io
import os
from datetime import datetime

import pandas as pd
import streamlit as st
from sqlalchemy import create_engine, text

# ReportLab para la generación del Recibo en PDF
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.platypus import HRFlowable, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

# ==========================================
# 1. CONFIGURACIÓN DE PÁGINA
# ==========================================
st.set_page_config(
    page_title="Caja de Ahorro Comunitario", page_icon="💰", layout="wide"
)


# ==========================================
# 2. GESTIÓN DE BASE DE DATOS (Supabase / PostgreSQL)
# ==========================================
@st.cache_resource
def obtener_motor():
    db_url = st.secrets["postgres"]["url"]
    return create_engine(db_url, pool_pre_ping=True, pool_recycle=300)


motor = obtener_motor()


def hash_password(password: str, salt: bytes = None) -> str:
    """Genera un hash seguro SHA-256 con salt para almacenar la contraseña."""
    if salt is None:
        salt = os.urandom(16)
    elif isinstance(salt, str):
        salt = bytes.fromhex(salt)
    pwd_hash = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt, 100000
    )
    return f"{salt.hex()}:{pwd_hash.hex()}"


def verificar_contrasena(contrasena_ingresada: str, hash_almacenado: str) -> bool:
    """Verifica si la contraseña ingresada coincide con el hash almacenado."""
    try:
        salt_hex, _ = hash_almacenado.split(":")
        salt = bytes.fromhex(salt_hex)
        hash_nuevo = hash_password(contrasena_ingresada, salt)
        return hash_nuevo == hash_almacenado
    except Exception:
        return False


def init_db():
    with motor.begin() as conn:
        conn.execute(
            text("""
            CREATE TABLE IF NOT EXISTS configuracion (
                clave VARCHAR(50) PRIMARY KEY,
                valor VARCHAR(550) NOT NULL
            );
        """)
        )

        res = conn.execute(
            text("SELECT valor FROM configuracion WHERE clave = 'admin_password'")
        ).fetchone()
        if not res:
            pass_default_hash = hash_password("admin123")
            conn.execute(
                text(
                    "INSERT INTO configuracion (clave, valor) VALUES"
                    " ('admin_password', :val)"
                ),
                {"val": pass_default_hash},
            )

        # Tablas Comunitarias
        conn.execute(
            text("""
            CREATE TABLE IF NOT EXISTS socios (
                id SERIAL PRIMARY KEY,
                nombre VARCHAR(255) NOT NULL,
                telefono VARCHAR(50),
                fecha_registro DATE NOT NULL,
                estado VARCHAR(20) DEFAULT 'Activo'
            );
        """)
        )

        conn.execute(
            text("""
            CREATE TABLE IF NOT EXISTS ahorros (
                id SERIAL PRIMARY KEY,
                socio_id INTEGER NOT NULL REFERENCES socios(id),
                monto NUMERIC(12, 2) NOT NULL,
                fecha DATE NOT NULL,
                nota TEXT,
                anio INTEGER DEFAULT EXTRACT(YEAR FROM CURRENT_DATE)
            );
        """)
        )

        conn.execute(
            text("""
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
        """)
        )

        conn.execute(
            text("""
            CREATE TABLE IF NOT EXISTS pagos (
                id SERIAL PRIMARY KEY,
                prestamo_id INTEGER NOT NULL REFERENCES prestamos(id),
                monto_pagado NUMERIC(12, 2) NOT NULL,
                monto_capital NUMERIC(12, 2) DEFAULT 0.00,
                monto_interes NUMERIC(12, 2) DEFAULT 0.00,
                fecha DATE NOT NULL,
                tipo VARCHAR(20)
            );
        """)
        )

        conn.execute(
            text("""
            CREATE TABLE IF NOT EXISTS egresos (
                id SERIAL PRIMARY KEY,
                concepto VARCHAR(255) NOT NULL,
                monto NUMERIC(12, 2) NOT NULL,
                fecha DATE NOT NULL,
                responsable VARCHAR(100)
            );
        """)
        )

        conn.execute(
            text("""
            CREATE TABLE IF NOT EXISTS cierres_anuales (
                id SERIAL PRIMARY KEY,
                anio INTEGER NOT NULL,
                total_ahorrado NUMERIC(12, 2) NOT NULL,
                total_intereses NUMERIC(12, 2) NOT NULL,
                fecha_cierre TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        )

        conn.execute(
            text("""
            CREATE TABLE IF NOT EXISTS bitacora (
                id SERIAL PRIMARY KEY,
                fecha TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                usuario VARCHAR(100) DEFAULT 'Administrador',
                accion TEXT NOT NULL
            );
        """)
        )

        # Tablas Personales Independientes
        conn.execute(
            text("""
            CREATE TABLE IF NOT EXISTS personal_socios (
                id SERIAL PRIMARY KEY,
                nombre VARCHAR(255) NOT NULL,
                telefono VARCHAR(50),
                fecha_registro DATE NOT NULL,
                estado VARCHAR(20) DEFAULT 'Activo'
            );
        """)
        )

        conn.execute(
            text("""
            CREATE TABLE IF NOT EXISTS personal_ahorros (
                id SERIAL PRIMARY KEY,
                socio_id INTEGER NOT NULL REFERENCES personal_socios(id),
                monto NUMERIC(12, 2) NOT NULL,
                fecha DATE NOT NULL,
                nota TEXT
            );
        """)
        )

        conn.execute(
            text("""
            CREATE TABLE IF NOT EXISTS personal_prestamos (
                id SERIAL PRIMARY KEY,
                socio_id INTEGER NOT NULL REFERENCES personal_socios(id),
                monto_prestado NUMERIC(12, 2) NOT NULL,
                tasa_interes NUMERIC(5, 2) NOT NULL,
                plazo_meses INTEGER NOT NULL,
                interes_total NUMERIC(12, 2) NOT NULL,
                monto_total NUMERIC(12, 2) NOT NULL,
                fecha_inicio DATE NOT NULL,
                estado VARCHAR(20) DEFAULT 'Activo'
            );
        """)
        )

        conn.execute(
            text("""
            CREATE TABLE IF NOT EXISTS personal_pagos (
                id SERIAL PRIMARY KEY,
                prestamo_id INTEGER NOT NULL REFERENCES personal_prestamos(id),
                monto_pagado NUMERIC(12, 2) NOT NULL,
                monto_capital NUMERIC(12, 2) DEFAULT 0.00,
                monto_interes NUMERIC(12, 2) DEFAULT 0.00,
                fecha DATE NOT NULL,
                tipo VARCHAR(20)
            );
        """)
        )

        conn.execute(
            text("""
            CREATE TABLE IF NOT EXISTS personal_egresos (
                id SERIAL PRIMARY KEY,
                concepto VARCHAR(255) NOT NULL,
                monto NUMERIC(12, 2) NOT NULL,
                fecha DATE NOT NULL,
                responsable VARCHAR(100)
            );
        """)
        )


if "db_inicializada" not in st.session_state:
    init_db()
    st.session_state.db_inicializada = True


# ==========================================
# 3. FUNCIONES UTILITARIAS Y DE SEGURIDAD
# ==========================================
def obtener_hash_password_bd():
    with motor.connect() as conn:
        res = conn.execute(
            text("SELECT valor FROM configuracion WHERE clave = 'admin_password'")
        ).fetchone()
        return res[0] if res else None


def registrar_bitacora(accion: str):
    try:
        with motor.begin() as conn:
            conn.execute(
                text("INSERT INTO bitacora (accion) VALUES (:accion)"),
                {"accion": accion},
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


def generar_recibo_pdf(
    comprobante_id: str,
    fecha: str,
    socio: str,
    prestamo_ref: str,
    monto_total: float,
    monto_capital: float,
    monto_interes: float,
    capital_pendiente: float,
) -> bytes:
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=letter,
        rightMargin=40,
        leftMargin=40,
        topMargin=40,
        bottomMargin=40,
    )
    styles = getSampleStyleSheet()

    style_header = ParagraphStyle(
        "HeaderStyle",
        parent=styles["Heading1"],
        fontName="Helvetica-Bold",
        fontSize=18,
        leading=22,
        textColor=colors.HexColor("#1A365D"),
        alignment=1,
    )

    style_sub = ParagraphStyle(
        "SubStyle",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=11,
        leading=14,
        textColor=colors.HexColor("#4A5568"),
        alignment=1,
    )

    style_title_recibo = ParagraphStyle(
        "ReciboTitle",
        parent=styles["Heading2"],
        fontName="Helvetica-Bold",
        fontSize=14,
        leading=18,
        textColor=colors.HexColor("#2B6CB0"),
        alignment=1,
    )

    style_body = ParagraphStyle(
        "BodyStyle",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=10,
        leading=14,
        textColor=colors.HexColor("#2D3748"),
    )

    style_bold = ParagraphStyle(
        "BoldStyle", parent=style_body, fontName="Helvetica-Bold"
    )

    story = []
    story.append(Paragraph("<b>COMPROBANTE OFICIAL</b>", style_header))
    story.append(Paragraph("Recibo de Pago", style_sub))
    story.append(Spacer(1, 10))
    story.append(
        HRFlowable(
            width="100%", thickness=1.5, color=colors.HexColor("#2B6CB0")
        )
    )
    story.append(Spacer(1, 15))
    story.append(Paragraph(f"<b>{comprobante_id}</b>", style_title_recibo))
    story.append(Spacer(1, 10))

    datos_tabla = [
        [
            Paragraph("<b>Fecha de Pago:</b>", style_bold),
            Paragraph(str(fecha), style_body),
        ],
        [
            Paragraph("<b>Cliente / Socio:</b>", style_bold),
            Paragraph(str(socio), style_body),
        ],
        [
            Paragraph("<b>Referencia:</b>", style_bold),
            Paragraph(str(prestamo_ref), style_body),
        ],
    ]

    t_info = Table(datos_tabla, colWidths=[150, 350])
    t_info.setStyle(
        TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ])
    )
    story.append(t_info)
    story.append(Spacer(1, 15))

    desglose_tabla = [
        [
            Paragraph("<b>Concepto / Detalle</b>", style_bold),
            Paragraph("<b>Monto (C$)</b>", style_bold),
        ],
        [
            Paragraph("Abono Aplicado a Capital", style_body),
            Paragraph(f"C$ {monto_capital:,.2f}", style_body),
        ],
        [
            Paragraph("Pago de Interés", style_body),
            Paragraph(f"C$ {monto_interes:,.2f}", style_body),
        ],
        [
            Paragraph("<b>TOTAL RECIBIDO</b>", style_bold),
            Paragraph(f"<b>C$ {monto_total:,.2f}</b>", style_bold),
        ],
        [
            Paragraph("Saldo Capital Pendiente", style_body),
            Paragraph(f"C$ {capital_pendiente:,.2f}", style_body),
        ],
    ]

    t_desglose = Table(desglose_tabla, colWidths=[320, 180])
    t_desglose.setStyle(
        TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#E2E8F0")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor("#1A202C")),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#CBD5E0")),
            ("PADDING", (0, 0), (-1, -1), 8),
            ("BACKGROUND", (0, 3), (-1, 3), colors.HexColor("#EDF2F7")),
        ])
    )
    story.append(t_desglose)
    story.append(Spacer(1, 50))

    firmas_tabla = [
        [
            Paragraph("_______________________________", style_sub),
            Paragraph("_______________________________", style_sub),
        ],
        [
            Paragraph("<b>Firma Entregado</b>", style_sub),
            Paragraph("<b>Firma Recibido</b>", style_sub),
        ],
    ]
    t_firmas = Table(firmas_tabla, colWidths=[250, 250])
    t_firmas.setStyle(
        TableStyle([("ALIGN", (0, 0), (-1, -1), "CENTER"), ("TOPPADDING", (0, 1), (-1, 1), 4)])
    )
    story.append(t_firmas)

    doc.build(story)
    buffer.seek(0)
    return buffer.getvalue()


def exportar_consolidado_excel(anio_filtro: int = None) -> bytes:
    salida = io.BytesIO()
    with motor.connect() as conn:
        if anio_filtro:
            df_s = pd.read_sql(text("SELECT * FROM socios"), conn)
            df_a = pd.read_sql(
                text(
                    "SELECT * FROM ahorros WHERE EXTRACT(YEAR FROM fecha) = :a"
                ),
                conn,
                params={"a": anio_filtro},
            )
            df_p = pd.read_sql(
                text(
                    "SELECT * FROM prestamos WHERE EXTRACT(YEAR FROM"
                    " fecha_inicio) = :a"
                ),
                conn,
                params={"a": anio_filtro},
            )
            df_pg = pd.read_sql(
                text(
                    "SELECT * FROM pagos WHERE EXTRACT(YEAR FROM fecha) = :a"
                ),
                conn,
                params={"a": anio_filtro},
            )
            df_e = pd.read_sql(
                text(
                    "SELECT * FROM egresos WHERE EXTRACT(YEAR FROM fecha) = :a"
                ),
                conn,
                params={"a": anio_filtro},
            )
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
    password_input = st.sidebar.text_input(
        "Contraseña de Administrador", type="password"
    )
    if st.sidebar.button("Iniciar sesión"):
        hash_almacenado = obtener_hash_password_bd()
        if hash_almacenado and verificar_contrasena(
            password_input, hash_almacenado
        ):
            st.session_state.autenticado = True
            registrar_bitacora("Inicio de sesión exitosa como Administrador.")
            st.sidebar.success("¡Acceso concedido!")
            st.rerun()
        else:
            st.sidebar.error("Contraseña incorrecta.")
    st.warning(
        "⚠️ Debes iniciar sesión como Administrador en la barra lateral para"
        " acceder al sistema."
    )
    st.stop()
else:
    st.sidebar.success("Sesión activa como Administrador")
    with st.sidebar.expander("🔑 Cambiar Contraseña"):
        pwd_actual = st.text_input(
            "Contraseña Actual", type="password", key="pwd_act"
        )
        pwd_nueva = st.text_input(
            "Nueva Contraseña", type="password", key="pwd_nuev"
        )
        if st.button("Actualizar Clave"):
            hash_almacenado = obtener_hash_password_bd()
            if hash_almacenado and verificar_contrasena(
                pwd_actual, hash_almacenado
            ):
                if len(pwd_nueva.strip()) >= 4:
                    nuevo_hash = hash_password(pwd_nueva.strip())
                    with motor.begin() as conn:
                        conn.execute(
                            text(
                                "UPDATE configuracion SET valor = :v WHERE"
                                " clave = 'admin_password'"
                            ),
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
        "📂 Mis Proyectos Personales",
    ],
)

# ==========================================
# SECCIÓN 1: PANEL GENERAL (COMUNITARIO)
# ==========================================
if opcion == "📊 Panel General":
    st.title("📊 Panel General de la Caja de Ahorro")
    st.caption("Resumen financiero consolidado en Córdoba (C$).")

    with motor.connect() as conn:
        df_ahorros = pd.read_sql(
            text("SELECT COALESCE(SUM(monto), 0) as total FROM ahorros"), conn
        )
        total_ahorrado = float(df_ahorros["total"].iloc[0])

        df_prestamos = pd.read_sql(
            text(
                "SELECT COALESCE(SUM(monto_prestado), 0) as total FROM"
                " prestamos WHERE estado = 'Activo'"
            ),
            conn,
        )
        total_prestado = float(df_prestamos["total"].iloc[0])

        df_pagos = pd.read_sql(
            text("SELECT COALESCE(SUM(monto_pagado), 0) as total FROM pagos"),
            conn,
        )
        total_recaudado = float(df_pagos["total"].iloc[0])

        df_egresos = pd.read_sql(
            text("SELECT COALESCE(SUM(monto), 0) as total FROM egresos"), conn
        )
        total_egresos = float(df_egresos["total"].iloc[0])

        df_socios = pd.read_sql(
            text(
                "SELECT COUNT(*) as total FROM socios WHERE estado = 'Activo'"
            ),
            conn,
        )
        total_socios = int(df_socios["total"].iloc[0])

        query_mora = """
            SELECT p.id, s.nombre, p.monto_prestado, p.fecha_inicio, p.plazo_meses
            FROM prestamos p
            JOIN socios s ON p.socio_id = s.id
            WHERE p.estado = 'Activo'
            AND (p.fecha_inicio + MAKE_INTERVAL(months => p.plazo_meses)) < CURRENT_DATE
            """
        df_mora = pd.read_sql(text(query_mora), conn)

        consulta_por_vencer = """
            SELECT p.id, s.nombre, p.monto_prestado, p.fecha_inicio,
            (p.fecha_inicio + MAKE_INTERVAL(months => p.plazo_meses)) as fecha_vencimiento
            FROM prestamos p
            JOIN socios s ON p.socio_id = s.id
            WHERE p.estado = 'Activo'
            AND (p.fecha_inicio + MAKE_INTERVAL(months => p.plazo_meses)) >= CURRENT_DATE
            AND (p.fecha_inicio + MAKE_INTERVAL(months => p.plazo_meses)) <= (CURRENT_DATE + INTERVAL '30 days')
            """
        df_por_vencer = pd.read_sql(text(consulta_por_vencer), conn)

        df_mora_sum = pd.read_sql(
            text("""
            SELECT COALESCE(SUM(monto_prestado), 0) as total
            FROM prestamos
            WHERE estado = 'Activo'
            AND (fecha_inicio + MAKE_INTERVAL(months => plazo_meses)) < CURRENT_DATE
            """),
            conn,
        )
        capital_mora = float(df_mora_sum["total"].iloc[0])
        ratio_mora = (
            (capital_mora / total_prestado * 100) if total_prestado > 0 else 0.0
        )

        fondo_caja = (
            total_ahorrado + total_recaudado - total_prestado - total_egresos
        )

    col1, col2, col3, col4, col5 = st.columns(5)
    col1.metric("💰 Fondo Total Ahorrado", f"C$ {total_ahorrado:,.2f}")
    col2.metric("📉 Capital Prestado Activo", f"C$ {total_prestado:,.2f}")
    col3.metric("📥 Cobros/Abonos Totales", f"C$ {total_recaudado:,.2f}")
    col4.metric("💸 Egresos / Gastos", f"C$ {total_egresos:,.2f}")
    col5.metric("🏦 Disponible en Caja", f"C$ {fondo_caja:,.2f}")

    col_a1, col_a2 = st.columns(2)
    with col_a1:
        if not df_mora.empty:
            st.error(
                f"⚠️ **Atención:** Se identificaron **{len(df_mora)}"
                f" préstamo(s) en MORA** (Índice de Mora: **{ratio_mora:.1f}%**)."
            )
            with st.expander("👁️ Ver Préstamos en Mora"):
                st.dataframe(df_mora, use_container_width=True)
        else:
            st.success("✅ **Sin morosidad:** Cartera de préstamos al día.")

    with col_a2:
        if not df_por_vencer.empty:
            st.warning(
                f"🔔 **Alerta Temprana:** **{len(df_por_vencer)} préstamo(s)**"
                " vencerán en los próximos 30 días."
            )
            with st.expander("👁️ Ver Préstamos Próximos a Vencer"):
                st.dataframe(df_por_vencer, use_container_width=True)
        else:
            st.info("ℹ️ No hay préstamos por vencer en los próximos 30 días.")

    st.markdown("---")
    col_dl1, col_dl2 = st.columns([3, 1])
    with col_dl1:
        st.subheader("📊 Métricas Rápidas")
        st.info(f"👥 **Socios Activos:** {total_socios} socios registrados.")
    with col_dl2:
        anio_exp = st.selectbox(
            "Seleccionar año para filtro (Opcional):",
            ["Todos"] + list(range(2020, 2101)),
            index=0,
        )
        anio_val = None if anio_exp == "Todos" else int(anio_exp)
        st.download_button(
            label="📦 Exportar Copia Completa (Excel)",
            data=exportar_consolidado_excel(anio_val),
            file_name=(
                "caja_ahorro_respaldo_"
                f"{datetime.now().strftime('%Y%m%d')}.xlsx"
            ),
            mime=(
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            ),
        )

# ==========================================
# SECCIÓN 2: GESTIÓN DE SOCIOS
# ==========================================
elif opcion == "👥 Socios":
    st.title("👥 Control de Socios")
    tab1, tab2, tab3 = st.tabs(
        [
            "📋 Listado de Socios",
            "➕ Registrar Nuevo Socio",
            "✏️ Editar / Eliminar Socio",
        ]
    )

    with tab1:
        st.subheader("Socios Registrados")
        with motor.connect() as conn:
            df_socios = pd.read_sql(
                text(
                    'SELECT id as "ID", nombre as "Nombre", telefono as'
                    ' "Teléfono", fecha_registro as "Fecha Registro", estado as'
                    ' "Estado" FROM socios ORDER BY id ASC'
                ),
                conn,
            )
        if not df_socios.empty:

            def crear_link_wa(tel):
                if pd.notna(tel) and str(tel).strip() != "":
                    num_limpio = "".join(filter(str.isdigit, str(tel)))
                    if num_limpio:
                        return (
                            f'<a href="https://wa.me/{num_limpio}"'
                            f' target="_blank">💬 Contactar WhatsApp ({tel})</a>'
                        )
                return "Sin teléfono"

            df_socios["Acción WhatsApp"] = df_socios["Teléfono"].apply(crear_link_wa)
            st.write(
                df_socios.to_html(escape=False, index=False),
                unsafe_allow_html=True,
            )
            st.markdown("<br>", unsafe_allow_html=True)
            st.download_button(
                label="📥 Exportar Socios a Excel",
                data=to_excel(
                    df_socios.drop(columns=["Acción WhatsApp"], errors="ignore")
                ),
                file_name=(
                    f"reporte_socios_{datetime.now().strftime('%Y%m%d')}.xlsx"
                ),
                mime=(
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                ),
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
                with motor.begin() as conn:
                    conn.execute(
                        text(
                            "INSERT INTO socios (nombre, telefono,"
                            " fecha_registro) VALUES (:nombre, :telefono,"
                            " :fecha)"
                        ),
                        {
                            "nombre": nombre,
                            "telefono": telefono,
                            "fecha": str(fecha_reg),
                        },
                    )
                registrar_bitacora(f"Registro de nuevo socio: {nombre}")
                st.success(f"¡Socio '{nombre}' registrado correctamente!")
                st.rerun()

    with tab3:
        st.subheader("Modificar o Eliminar Socio")
        with motor.connect() as conn:
            df_s_edit = pd.read_sql(
                text(
                    "SELECT id, nombre, telefono, fecha_registro, estado FROM"
                    " socios ORDER BY id DESC"
                ),
                conn,
            )

        if df_s_edit.empty:
            st.info("No hay socios registrados para editar o eliminar.")
        else:
            dict_s_edit = dict(
                zip(
                    [
                        f"ID #{row['id']} - {row['nombre']}"
                        for _, row in df_s_edit.iterrows()
                    ],
                    df_s_edit["id"],
                )
            )
            socio_sel = st.selectbox("Selecciona el Socio:", list(dict_s_edit.keys()))
            id_socio_sel = dict_s_edit[socio_sel]
            datos_socio = df_s_edit[df_s_edit["id"] == id_socio_sel].iloc[0]

            with st.form("form_edit_socio"):
                e_nombre = st.text_input("Nombre Completo", value=datos_socio["nombre"])
                e_telefono = st.text_input(
                    "Teléfono / WhatsApp",
                    value=datos_socio["telefono"] or "",
                )
                fecha_orig = pd.to_datetime(datos_socio["fecha_registro"]).date()
                e_fecha = st.date_input("Fecha de Registro", value=fecha_orig)
                e_estado = st.selectbox(
                    "Estado",
                    ["Activo", "Inactivo"],
                    index=0 if datos_socio["estado"] == "Activo" else 1,
                )

                col_b1, col_b2 = st.columns(2)
                with col_b1:
                    btn_guardar_edit = st.form_submit_button("💾 Guardar Cambios")
                with col_b2:
                    btn_eliminar_socio = st.form_submit_button("🗑️ Eliminar Socio")

                if btn_guardar_edit:
                    with motor.begin() as conn:
                        conn.execute(
                            text(
                                "UPDATE socios SET nombre = :nombre,"
                                " telefono = :telefono, fecha_registro ="
                                " :fecha, estado = :estado WHERE id = :id"
                            ),
                            {
                                "nombre": e_nombre,
                                "telefono": e_telefono,
                                "fecha": str(e_fecha),
                                "estado": e_estado,
                                "id": id_socio_sel,
                            },
                        )
                    registrar_bitacora(
                        "Actualización de datos del socio ID"
                        f" {id_socio_sel}: {e_nombre}"
                    )
                    st.success("¡Datos del socio actualizados exitosamente!")
                    st.rerun()

                if btn_eliminar_socio:
                    with motor.begin() as conn:
                        conn.execute(
                            text(
                                "DELETE FROM pagos WHERE prestamo_id IN"
                                " (SELECT id FROM prestamos WHERE socio_id"
                                " = :id)"
                            ),
                            {"id": id_socio_sel},
                        )
                        conn.execute(
                            text("DELETE FROM prestamos WHERE socio_id = :id"),
                            {"id": id_socio_sel},
                        )
                        conn.execute(
                            text("DELETE FROM ahorros WHERE socio_id = :id"),
                            {"id": id_socio_sel},
                        )
                        conn.execute(
                            text("DELETE FROM socios WHERE id = :id"),
                            {"id": id_socio_sel},
                        )
                    registrar_bitacora(
                        f"Eliminación de socio ID {id_socio_sel}:"
                        f" {datos_socio['nombre']}"
                    )
                    st.warning(
                        f"Socio ID #{id_socio_sel} y sus registros"
                        " vinculados han sido eliminados."
                    )
                    st.rerun()

# ==========================================
# SECCIÓN 3: AHORROS Y CUOTAS
# ==========================================
elif opcion == "💵 Ahorros y Cuotas":
    st.title("💵 Registro de Ahorros")
    with motor.connect() as conn:
        df_socios = pd.read_sql(
            text(
                "SELECT id, nombre FROM socios WHERE estado = 'Activo' ORDER BY"
                " nombre ASC"
            ),
            conn,
        )

    if df_socios.empty:
        st.warning("Primero debes registrar socios en la sección '👥 Socios'.")
    else:
        tab1, tab2, tab3 = st.tabs(
            [
                "➕ Depositar Ahorro",
                "📜 Historial de Ahorros",
                "✏️ Editar / Corregir Ahorro",
            ]
        )
        dict_socios = dict(zip(df_socios["nombre"], df_socios["id"]))

        with tab1:
            st.subheader("Registrar Nueva Aportación")
            with st.form("form_ahorro", clear_on_submit=True):
                socio_nom = st.selectbox(
                    "Selecciona el Socio *", list(dict_socios.keys())
                )
                monto_ahorro = st.number_input(
                    "Monto Ahorrado (C$) *", min_value=1.0, step=10.0
                )
                fecha_ahorro = st.date_input("Fecha del Depósito", datetime.now())
                nota_ahorro = st.text_input("Nota / Observación (Opcional)")
                btn_ahorro = st.form_submit_button("Registrar Depósito")

            if btn_ahorro:
                socio_id = dict_socios[socio_nom]
                anio_curr = fecha_ahorro.year
                with motor.begin() as conn:
                    conn.execute(
                        text(
                            "INSERT INTO ahorros (socio_id, monto, fecha,"
                            " nota, anio) VALUES (:socio_id, :monto,"
                            " :fecha, :nota, :anio)"
                        ),
                        {
                            "socio_id": socio_id,
                            "monto": monto_ahorro,
                            "fecha": str(fecha_ahorro),
                            "nota": nota_ahorro,
                            "anio": anio_curr,
                        },
                    )
                registrar_bitacora(
                    f"Ahorro de C$ {monto_ahorro:,.2f} registrado para"
                    f" {socio_nom}"
                )
                st.success(
                    f"¡Ahorro de C$ {monto_ahorro:,.2f} registrado para"
                    f" {socio_nom}!"
                )
                st.rerun()

        with tab2:
            st.subheader("Historial de Ahorros")
            with motor.connect() as conn:
                df_ahorros_hist = pd.read_sql(
                    text("""
                    SELECT a.id, s.nombre as socio, a.monto, a.fecha, a.nota
                    FROM ahorros a
                    JOIN socios s ON a.socio_id = s.id
                    ORDER BY a.fecha DESC
                    """),
                    conn,
                )
            if not df_ahorros_hist.empty:
                st.dataframe(df_ahorros_hist, use_container_width=True)
            else:
                st.info("No hay registros de ahorros.")

        with tab3:
            st.subheader("Editar / Eliminar Ahorro")
            with motor.connect() as conn:
                df_a_edit = pd.read_sql(
                    text("""
                    SELECT a.id, s.nombre as socio, a.monto, a.fecha, a.nota, a.socio_id
                    FROM ahorros a
                    JOIN socios s ON a.socio_id = s.id
                    ORDER BY a.id DESC
                    """),
                    conn,
                )
            if df_a_edit.empty:
                st.info("No hay depósitos registrados para modificar.")
            else:
                dict_a = {
                    f"ID #{row['id']} - {row['socio']} (C$ {row['monto']:,.2f} - {row['fecha']})": row[
                        "id"
                    ]
                    for _, row in df_a_edit.iterrows()
                }
                ahorro_sel = st.selectbox("Selecciona Registro:", list(dict_a.keys()))
                id_ahorro_sel = dict_a[ahorro_sel]
                datos_a = df_a_edit[df_a_edit["id"] == id_ahorro_sel].iloc[0]

                with st.form("form_edit_ahorro"):
                    m_monto = st.number_input(
                        "Monto (C$)",
                        value=float(datos_a["monto"]),
                        min_value=1.0,
                    )
                    m_fecha = st.date_input(
                        "Fecha",
                        value=pd.to_datetime(datos_a["fecha"]).date(),
                    )
                    m_nota = st.text_input("Nota", value=datos_a["nota"] or "")

                    col_ea1, col_ea2 = st.columns(2)
                    with col_ea1:
                        btn_up_a = st.form_submit_button("💾 Guardar Cambios")
                    with col_ea2:
                        btn_del_a = st.form_submit_button("🗑️ Eliminar Registro")

                    if btn_up_a:
                        with motor.begin() as conn:
                            conn.execute(
                                text(
                                    "UPDATE ahorros SET monto = :monto, fecha ="
                                    " :fecha, nota = :nota WHERE id = :id"
                                ),
                                {
                                    "monto": m_monto,
                                    "fecha": str(m_fecha),
                                    "nota": m_nota,
                                    "id": id_ahorro_sel,
                                },
                            )
                        registrar_bitacora(
                            f"Actualización de ahorro ID {id_ahorro_sel}"
                        )
                        st.success("¡Registro de ahorro actualizado!")
                        st.rerun()

                    if btn_del_a:
                        with motor.begin() as conn:
                            conn.execute(
                                text("DELETE FROM ahorros WHERE id = :id"),
                                {"id": id_ahorro_sel},
                            )
                        registrar_bitacora(
                            f"Eliminación de ahorro ID {id_ahorro_sel}"
                        )
                        st.warning("Registro de ahorro eliminado.")
                        st.rerun()

# ==========================================
# SECCIÓN 4: PRÉSTAMOS
# ==========================================
elif opcion == "🤝 Préstamos":
    st.title("🤝 Gestión de Préstamos")
    with motor.connect() as conn:
        df_socios = pd.read_sql(text("SELECT id, nombre FROM socios WHERE estado = 'Activo' ORDER BY nombre ASC"), conn)
    
    if df_socios.empty:
        st.warning("Debe registrar socios activos para otorgar préstamos.")
    else:
        tab1, tab2 = st.tabs(["➕ Otorgar Préstamo", "📋 Cartera de Préstamos Activos"])
        dict_socios = dict(zip(df_socios["nombre"], df_socios["id"]))
        
        with tab1:
            with st.form("form_prestamo", clear_on_submit=True):
                soc_nom = st.selectbox("Seleccionar Socio *", list(dict_socios.keys()))
                m_prestado = st.number_input("Monto Prestado (C$) *", min_value=100.0, step=100.0)
                t_interes = st.number_input("Tasa de Interés Mensual (%) *", min_value=0.0, value=5.0, step=0.5)
                p_meses = st.number_input("Plazo en Meses *", min_value=1, value=12, step=1)
                f_inicio = st.date_input("Fecha de Inicio", datetime.now())
                btn_p = st.form_submit_button("Aprobar y Registrar Préstamo")
                
                if btn_p:
                    sid = dict_socios[soc_nom]
                    interes_tot = m_prestado * (t_interes / 100.0) * p_meses
                    monto_tot = m_prestado + interes_tot
                    anio_c = f_inicio.year
                    
                    with motor.begin() as conn:
                        conn.execute(text("""
                            INSERT INTO prestamos (socio_id, monto_prestado, tasa_interes, plazo_meses, interes_total, monto_total, fecha_inicio, anio)
                            VALUES (:s, :mp, :ti, :pl, :it, :mt, :fi, :a)
                        """), {
                            "s": sid, "mp": m_prestado, "ti": t_interes, "pl": p_meses, "it": interes_tot, "mt": monto_tot, "fi": str(f_inicio), "a": anio_c
                        })
                    registrar_bitacora(f"Préstamo de C$ {monto_prestado:,.2f} otorgado a {soc_nom}")
                    st.success("¡Préstamo registrado y aprobado con éxito!")
                    st.rerun()
                    
        with tab2:
            with motor.connect() as conn:
                df_p_act = pd.read_sql(text("SELECT p.id, s.nombre as socio, p.monto_prestado, p.tasa_interes, p.plazo_meses, p.monto_total, p.fecha_inicio, p.estado FROM prestamos p JOIN socios s ON p.socio_id = s.id ORDER BY p.id DESC"), conn)
            if not df_p_act.empty:
                st.dataframe(df_p_act, use_container_width=True)
            else:
                st.info("No hay préstamos registrados.")

# ==========================================
# SECCIÓN 5: SIMULADOR DE PRÉSTAMOS
# ==========================================
elif opcion == "🧮 Simulador de Préstamos":
    st.title("🧮 Simulador Financiero de Préstamos")
    sim_monto = st.number_input("Monto a solicitar (C$)", min_value=100.0, value=10000.0, step=500.0)
    sim_tasa = st.number_input("Tasa de interés mensual (%)", min_value=0.0, value=5.0, step=0.5)
    sim_plazo = st.number_input("Plazo en meses", min_value=1, value=12, step=1)
    
    if st.button("Calcular Proyección"):
        interes_mensual = sim_monto * (sim_tasa / 100.0)
        capital_mensual = sim_monto / sim_plazo
        cuota_total = interes_mensual + capital_mensual
        monto_total_pagar = sim_monto + (interes_mensual * sim_plazo)
        
        c1, c2, c3 = st.columns(3)
        c1.metric("Cuota Mensual Estimada", f"C$ {cuota_total:,.2f}")
        c2.metric("Interés Total Generado", f"C$ {interes_mensual * sim_plazo:,.2f}")
        c3.metric("Monto Total a Cancelar", f"C$ {monto_total_pagar:,.2f}")

# ==========================================
# SECCIÓN 6: PAGOS DE PRÉSTAMOS
# ==========================================
elif opcion == "📖 Pagos de Préstamos":
    st.title("📖 Registro de Pagos y Abonos")
    with motor.connect() as conn:
        df_prest_activos = pd.read_sql(text("SELECT p.id, s.nombre, p.monto_total FROM prestamos p JOIN socios s ON p.socio_id = s.id WHERE p.estado = 'Activo'"), conn)
        
    if df_prest_activos.empty:
        st.info("No hay préstamos activos para recibir pagos.")
    else:
        dict_pres = {f"Préstamo #{row['id']} - {row['nombre']} (Total: C$ {row['monto_total']:,.2f})": row['id'] for _, row in df_prest_activos.iterrows()}
        pres_sel = st.selectbox("Seleccione el Préstamo", list(dict_pres.keys()))
        pid = dict_pres[pres_sel]
        
        with st.form("form_pago_comunitario"):
            monto_pag = st.number_input("Monto Pagado (C$)", min_value=1.0, step=10.0)
            m_cap = st.number_input("Aplicado a Capital (C$)", min_value=0.0, step=10.0)
            m_int = st.number_input("Aplicado a Interés (C$)", min_value=0.0, step=10.0)
            f_pag = st.date_input("Fecha de Pago", datetime.now())
            btn_reg_pago = st.form_submit_button("Registrar Pago y Emitir Recibo")
            
            if btn_reg_pago:
                with motor.begin() as conn:
                    conn.execute(text("""
                        INSERT INTO pagos (prestamo_id, monto_pagado, monto_capital, monto_interes, fecha, tipo)
                        VALUES (:pid, :mp, :mc, :mi, :f, 'Abono')
                    """), {"pid": pid, "mp": monto_pag, "mc": m_cap, "mi": m_int, "f": str(f_pag)})
                registrar_bitacora(f"Pago de C$ {monto_pag:,.2f} registrado para Préstamo #{pid}")
                st.success("¡Pago registrado con éxito!")
                
                pdf_bytes = generar_recibo_pdf(
                    comprobante_id=f"RECIBO-COM-{pid}",
                    fecha=str(f_pag),
                    socio=pres_sel.split("-")[1].split("(")[0].strip(),
                    prestamo_ref=f"Préstamo Comunitario #{pid}",
                    monto_total=monto_pag,
                    monto_capital=m_cap,
                    monto_interes=m_int,
                    capital_pendiente=0.0
                )
                st.download_button(
                    label="📄 Descargar Recibo Oficial en PDF",
                    data=pdf_bytes,
                    file_name=f"recibo_pago_{pid}.pdf",
                    mime="application/pdf"
                )

# ==========================================
# SECCIÓN 7: EGRESOS Y GASTOS
# ==========================================
elif opcion == "💸 Egresos y Gastos":
    st.title("💸 Control de Egresos y Gastos Operativos")
    with st.form("form_egreso", clear_on_submit=True):
        concepto = st.text_input("Concepto del Gasto *")
        monto = st.number_input("Monto (C$)", min_value=1.0, step=10.0)
        fecha = st.date_input("Fecha", datetime.now())
        responsable = st.text_input("Responsable", value="Administrador")
        btn_e = st.form_submit_button("Registrar Egreso")
        
        if btn_e:
            if concepto.strip():
                with motor.begin() as conn:
                    conn.execute(text("INSERT INTO egresos (concepto, monto, fecha, responsable) VALUES (:c, :m, :f, :r)"), {"c": concepto, "m": monto, "f": str(fecha), "r": responsable})
                registrar_bitacora(f"Egreso registrado: {concepto} por C$ {monto:,.2f}")
                st.success("¡Egreso registrado correctamente!")
                st.rerun()
            else:
                st.error("El concepto es obligatorio.")

    with motor.connect() as conn:
        df_eg = pd.read_sql(text("SELECT id as \"ID\", concepto as \"Concepto\", monto as \"Monto\", fecha as \"Fecha\", responsable as \"Responsable\" FROM egresos ORDER BY fecha DESC"), conn)
    if not df_eg.empty:
        st.dataframe(df_eg, use_container_width=True)

# ==========================================
# SECCIÓN 8: ESTADO DE CUENTA
# ==========================================
elif opcion == "📜 Estado de Cuenta":
    st.title("📜 Estado de Cuenta Consolidado")
    with motor.connect() as conn:
        df_socios = pd.read_sql(text("SELECT id, nombre FROM socios WHERE estado = 'Activo'"), conn)
    
    if df_socios.empty:
        st.info("No hay socios registrados.")
    else:
        dict_s = dict(zip(df_socios["nombre"], df_socios["id"]))
        soc_sel = st.selectbox("Seleccionar Socio para ver Estado de Cuenta", list(dict_s.keys()))
        sid = dict_s[soc_sel]
        
        with motor.connect() as conn:
            ahorros_soc = pd.read_sql(text("SELECT monto, fecha, nota FROM ahorros WHERE socio_id = :sid"), conn, params={"sid": sid})
            prest_soc = pd.read_sql(text("SELECT id, monto_prestado, tasa_interes, monto_total, fecha_inicio, estado FROM prestamos WHERE socio_id = :sid"), conn, params={"sid": sid})
        
        st.subheader(f"Estado de Cuenta de: {soc_sel}")
        st.markdown("### Ahorros Registrados")
        st.dataframe(ahorros_soc, use_container_width=True)
        st.markdown("### Préstamos Registrados")
        st.dataframe(prest_soc, use_container_width=True)

# ==========================================
# SECCIÓN 9: LIQUIDACIÓN ANUAL
# ==========================================
elif opcion == "🎉 Liquidación Anual":
    st.title("🎉 Liquidación Anual de Intereses y Ahorros")
    anio_liq = st.selectbox("Seleccionar Año a Liquidar", [2024, 2025, 2026, 2027], index=2)
    
    with motor.connect() as conn:
        tot_ah = pd.read_sql(text("SELECT COALESCE(SUM(monto), 0) as t FROM ahorros WHERE anio = :a"), conn, params={"a": anio_liq})["t"].iloc[0]
        tot_int = pd.read_sql(text("SELECT COALESCE(SUM(interes_total), 0) as t FROM prestamos WHERE anio = :a"), conn, params={"a": anio_liq})["t"].iloc[0]
    
    col1, col2 = st.columns(2)
    col1.metric(f"Total Ahorros ({anio_liq})", f"C$ {float(tot_ah):,.2f}")
    col2.metric(f"Total Intereses Generados ({anio_liq})", f"C$ {float(tot_int):,.2f}")

# ==========================================
# SECCIÓN 10: CIERRE MENSUAL Y ANUAL
# ==========================================
elif opc_cierre := opcion == "📅 Cierre Mensual y Anual":
    st.title("📅 Cierres Contables")
    st.info("Módulo de auditoría y cierre contable habilitado para la administración general.")

# ==========================================
# SECCIÓN 11: BITÁCORA DE AUDITORÍA
# ==========================================
elif opcion == "🛡️ Bitácora de Auditoría":
    st.title("🛡️ Bitácora de Auditoría del Sistema")
    with motor.connect() as conn:
        df_bit = pd.read_sql(text("SELECT id as \"ID\", fecha as \"Fecha y Hora\", usuario as \"Usuario\", accion as \"Acción Realizada\" FROM bitacora ORDER BY fecha DESC LIMIT 100"), conn)
    if not df_bit.empty:
        st.dataframe(df_bit, use_container_width=True)
    else:
        st.info("La bitácora está vacía.")

# ==========================================
# SECCIÓN 12: MIS PROYECTOS PERSONALES (CON PANEL GENERAL)
# ==========================================
elif opcion == "📂 Mis Proyectos Personales":
    st.title("📂 Espacio de Uso Personal y Préstamos Privados")
    st.caption("Gestión independiente de clientes, préstamos personales, ahorros y gastos propios.")

    p_opcion = st.radio(
        "Selecciona una herramienta personal:",
        [
            "📊 Panel General Personal",
            "👥 Clientes / Socios Personales",
            "💵 Ahorros Personales",
            "🤝 Préstamos Personales",
            "🧮 Simulador Personal",
            "📖 Pagos y Recibos Personales",
            "💸 Egresos y Gastos Personales",
            "📜 Estado de Cuenta Personal"
        ],
        horizontal=True
    )
    st.markdown("---")

    # PANEL GENERAL PERSONAL
    if p_opcion == "📊 Panel General Personal":
        st.subheader("📊 Resumen General de Caja (Personal)")
        with motor.connect() as conn:
            pah = pd.read_sql(text("SELECT COALESCE(SUM(monto), 0) as t FROM personal_ahorros"), conn)["t"].iloc[0]
            ppr = pd.read_sql(text("SELECT COALESCE(SUM(monto_prestado), 0) as t FROM personal_prestamos WHERE estado = 'Activo'"), conn)["t"].iloc[0]
            ppg = pd.read_sql(text("SELECT COALESCE(SUM(monto_pagado), 0) as t FROM personal_pagos"), conn)["t"].iloc[0]
            peg = pd.read_sql(text("SELECT COALESCE(SUM(monto), 0) as t FROM personal_egresos"), conn)["t"].iloc[0]
            
            disp_personal = float(pah) + float(ppg) - float(ppr) - float(peg)

        pc1, pc2, pc3, pc4, pc5 = st.columns(5)
        pc1.metric("💰 Ahorros Personales", f"C$ {float(pah):,.2f}")
        pc2.metric("📉 Préstamos Activos", f"C$ {float(ppr):,.2f}")
        pc3.metric("📥 Cobros Recaudados", f"C$ {float(ppg):,.2f}")
        pc4.metric("💸 Gastos Personales", f"C$ {float(peg):,.2f}")
        pc5.metric("🏦 Disponible en Caja", f"C$ {disp_personal:,.2f}")

    # 1. CLIENTES PERSONALES
    elif p_opcion == "👥 Clientes / Socios Personales":
        st.subheader("Control de Clientes / Socios (Personal)")
        ptab1, ptab2 = st.tabs(["📋 Listado", "➕ Registrar Cliente"])
        
        with ptab1:
            with motor.connect() as conn:
                df_ps = pd.read_sql(text("SELECT id as \"ID\", nombre as \"Nombre\", telefono as \"Teléfono\", fecha_registro as \"Fecha Registro\", estado as \"Estado\" FROM personal_socios ORDER BY id ASC"), conn)
            if not df_ps.empty:
                st.dataframe(df_ps, use_container_width=True)
            else:
                st.info("No hay clientes personales registrados.")
        
        with ptab2:
            with st.form("form_psocio", clear_on_submit=True):
                pnomb = st.text_input("Nombre Completo *")
                ptel = st.text_input("Teléfono / WhatsApp")
                pfecha = st.date_input("Fecha de Registro", datetime.now())
                p_env = st.form_submit_button("Guardar Cliente")
                if p_env:
                    if pnomb.strip():
                        with motor.begin() as conn:
                            conn.execute(text("INSERT INTO personal_socios (nombre, telefono, fecha_registro) VALUES (:n, :t, :f)"), {"n": pnomb, "t": ptel, "f": str(pfecha)})
                        st.success(f"¡Cliente '{pnomb}' registrado con éxito!")
                        st.rerun()
                    else:
                        st.error("El nombre es obligatorio.")

    # 2. AHORROS PERSONALES
    elif p_opcion == "💵 Ahorros Personales":
        st.subheader("Depósitos de Ahorro Personal")
        with motor.connect() as conn:
            df_psoc = pd.read_sql(text("SELECT id, nombre FROM personal_socios WHERE estado = 'Activo'"), conn)
        
        if df_psoc.empty:
            st.warning("Primero registra un cliente/socio en la pestaña anterior.")
        else:
            dict_ps = dict(zip(df_psoc["nombre"], df_psoc["id"]))
            with st.form("form_pahorro", clear_on_submit=True):
                psel = st.selectbox("Seleccionar Socio/Cliente", list(dict_ps.keys()))
                pmonto = st.number_input("Monto del Ahorro (C$)", min_value=1.0, step=10.0)
                pfech = st.date_input("Fecha", datetime.now())
                pnote = st.text_input("Nota u Observación")
                pbtn_ah = st.form_submit_button("Registrar Ahorro Personal")
                
                if pbtn_ah:
                    sid = dict_ps[psel]
                    with motor.begin() as conn:
                        conn.execute(text("INSERT INTO personal_ahorros (socio_id, monto, fecha, nota) VALUES (:s, :m, :f, :n)"), {"s": sid, "m": pmonto, "f": str(pfech), "n": pnote})
                    st.success("¡Ahorro personal registrado correctamente!")
                    st.rerun()
            
            with motor.connect() as conn:
                df_pah_hist = pd.read_sql(text("SELECT a.id, s.nombre as cliente, a.monto, a.fecha, a.nota FROM personal_ahorros a JOIN personal_socios s ON a.socio_id = s.id ORDER BY a.fecha DESC"), conn)
            if not df_pah_hist.empty:
                st.dataframe(df_pah_hist, use_container_width=True)

    # 3. PRÉSTAMOS PERSONALES
    elif p_opcion == "🤝 Préstamos Personales":
        st.subheader("Otorgar Préstamo Personal")
        with motor.connect() as conn:
            df_psoc = pd.read_sql(text("SELECT id, nombre FROM personal_socios WHERE estado = 'Activo'"), conn)
        
        if df_psoc.empty:
            st.warning("Registra un cliente primero.")
        else:
            dict_ps = dict(zip(df_psoc["nombre"], df_psoc["id"]))
            with st.form("form_pprestamo"):
                psoc = st.selectbox("Cliente / Socio", list(dict_ps.keys()))
                pmonto_p = st.number_input("Monto Prestado (C$)", min_value=100.0, step=100.0)
                ptasa = st.number_input("Tasa de Interés Mensual (%)", min_value=0.0, value=5.0)
                pplazo = st.number_input("Plazo (Meses)", min_value=1, value=12, step=1)
                pfech_ini = st.date_input("Fecha de Inicio", datetime.now())
                pbtn_prest = st.form_submit_button("Crear Préstamo Personal")
                
                if pbtn_prest:
                    sid = dict_ps[psoc]
                    interes_tot = pmonto_p * (ptasa / 100.0) * pplazo
                    monto_tot = pmonto_p + interes_tot
                    with motor.begin() as conn:
                        conn.execute(text("""
                            INSERT INTO personal_prestamos (socio_id, monto_prestado, tasa_interes, plazo_meses, interes_total, monto_total, fecha_inicio)
                            VALUES (:s, :mp, :ti, :pl, :it, :mt, :fi)
                        """), {
                            "s": sid, "mp": pmonto_p, "ti": ptasa, "pl": pplazo, "it": interes_tot, "mt": monto_tot, "fi": str(pfech_ini)
                        })
                    st.success("¡Préstamo personal creado con éxito!")
                    st.rerun()

            with motor.connect() as conn:
                df_pp_hist = pd.read_sql(text("SELECT p.id, s.nombre as cliente, p.monto_prestado, p.tasa_interes, p.plazo_meses, p.monto_total, p.fecha_inicio, p.estado FROM personal_prestamos p JOIN personal_socios s ON p.socio_id = s.id ORDER BY p.id DESC"), conn)
            if not df_pp_hist.empty:
                st.dataframe(df_pp_hist, use_container_width=True)

    # 4. SIMULADOR PERSONAL
    elif p_opcion == "🧮 Simulador Personal":
        st.subheader("Simulador de Préstamos Personales")
        s_monto = st.number_input("Monto a simular (C$)", min_value=100.0, value=5000.0, step=500.0)
        s_tasa = st.number_input("Tasa de interés mensual (%)", min_value=0.0, value=5.0, step=0.5)
        s_plazo = st.number_input("Plazo en meses", min_value=1, value=12, step=1)
        
        if st.button("Calcular Simulación"):
            interes_mes = s_monto * (s_tasa / 100.0)
            capital_mes = s_monto / s_plazo
            cuota_total = interes_mes + capital_mes
            total_pagar = s_monto + (interes_mes * s_plazo)
            
            c1, c2, c3 = st.columns(3)
            c1.metric("Cuota Mensual Aprox.", f"C$ {cuota_total:,.2f}")
            c2.metric("Interés Total", f"C$ {interes_mes * s_plazo:,.2f}")
            c3.metric("Monto Total a Pagar", f"C$ {total_pagar:,.2f}")

    # 5. PAGOS Y RECIBOS PERSONALES
    elif p_opcion == "📖 Pagos y Recibos Personales":
        st.subheader("Registrar Abono / Pago y Generar Recibo PDF")
        with motor.connect() as conn:
            df_pactivo = pd.read_sql(text("SELECT p.id, s.nombre, p.monto_total FROM personal_prestamos p JOIN personal_socios s ON p.socio_id = s.id WHERE p.estado = 'Activo'"), conn)
        
        if df_pactivo.empty:
            st.info("No hay préstamos personales activos para abonar.")
        else:
            dict_prest = {f"Préstamo #{row['id']} - {row['nombre']} (Total: C$ {row['monto_total']:,.2f})": row['id'] for _, row in df_pactivo.iterrows()}
            sel_p = st.selectbox("Seleccionar Préstamo", list(dict_prest.keys()))
            pid_sel = dict_prest[sel_p]
            
            with st.form("form_ppago"):
                m_pagado = st.number_input("Monto Pagado (C$)", min_value=1.0, step=10.0)
                m_cap = st.number_input("Aplicado a Capital (C$)", min_value=0.0, step=10.0)
                m_int = st.number_input("Aplicado a Interés (C$)", min_value=0.0, step=10.0)
                f_pago = st.date_input("Fecha de Pago", datetime.now())
                b_pago = st.form_submit_button("Registrar Pago y Generar Recibo")
                
                if b_pago:
                    with motor.begin() as conn:
                        conn.execute(text("""
                            INSERT INTO personal_pagos (prestamo_id, monto_pagado, monto_capital, monto_interes, fecha, tipo)
                            VALUES (:pid, :mp, :mc, :mi, :f, 'Abono')
                        """), {"pid": pid_sel, "mp": m_pagado, "mc": m_cap, "mi": m_int, "f": str(f_pago)})
                    st.success("¡Pago registrado con éxito!")
                    
                    pdf_bytes = generar_recibo_pdf(
                        comprobante_id=f"RECIBO-PER-{pid_sel}",
                        fecha=str(f_pago),
                        socio=sel_p.split("-")[1].split("(")[0].strip(),
                        prestamo_ref=f"Préstamo Personal #{pid_sel}",
                        monto_total=m_pagado,
                        monto_capital=m_cap,
                        monto_interes=m_int,
                        capital_pendiente=0.0
                    )
                    st.download_button(
                        label="📄 Descargar Recibo Oficial en PDF",
                        data=pdf_bytes,
                        file_name=f"recibo_personal_{pid_sel}.pdf",
                        mime="application/pdf"
                    )

    # 6. EGRESOS Y GASTOS PERSONALES
    elif p_opcion == "💸 Egresos y Gastos Personales":
        st.subheader("Control de Gastos y Egresos Personales")
        with st.form("form_pegresos", clear_on_submit=True):
            concepto = st.text_input("Concepto del Gasto *")
            monto_eg = st.number_input("Monto (C$)", min_value=1.0, step=10.0)
            fecha_eg = st.date_input("Fecha", datetime.now())
            resp = st.text_input("Responsable / Nota", value="Personal")
            btn_eg = st.form_submit_button("Guardar Gasto")
            
            if btn_eg:
                if concepto.strip():
                    with motor.begin() as conn:
                        conn.execute(text("INSERT INTO personal_egresos (concepto, monto, fecha, responsable) VALUES (:c, :m, :f, :r)"), {"c": concepto, "m": monto_eg, "f": str(fecha_eg), "r": resp})
                    st.success("¡Gasto registrado correctamente!")
                    st.rerun()
                else:
                    st.error("El concepto es obligatorio.")

        with motor.connect() as conn:
            df_eg_hist = pd.read_sql(text("SELECT id as \"ID\", concepto as \"Concepto\", monto as \"Monto\", fecha as \"Fecha\", responsable as \"Responsable\" FROM personal_egresos ORDER BY fecha DESC"), conn)
        if not df_eg_hist.empty:
            st.dataframe(df_eg_hist, use_container_width=True)

    # 7. ESTADO DE CUENTA PERSONAL
    elif p_opcion == "📜 Estado de Cuenta Personal":
        st.subheader("Estado de Cuenta Consolidado (Personal)")
        with motor.connect() as conn:
            df_psoc = pd.read_sql(text("SELECT id, nombre FROM personal_socios WHERE estado = 'Activo'"), conn)
        
        if df_psoc.empty:
            st.info("No hay clientes personales registrados.")
        else:
            dict_ps = dict(zip(df_psoc["nombre"], df_psoc["id"]))
            psel = st.selectbox("Seleccionar Cliente", list(dict_ps.keys()))
            sid = dict_ps[psel]
            
            with motor.connect() as conn:
                ah_p = pd.read_sql(text("SELECT monto, fecha, nota FROM personal_ahorros WHERE socio_id = :sid"), conn, params={"sid": sid})
                pr_p = pd.read_sql(text("SELECT id, monto_prestado, tasa_interes, monto_total, fecha_inicio, estado FROM personal_prestamos WHERE socio_id = :sid"), conn, params={"sid": sid})
            
            st.markdown("### Ahorros del Cliente")
            st.dataframe(ah_p, use_container_width=True)
            st.markdown("### Préstamos del Cliente")
            st.dataframe(pr_p, use_container_width=True)
