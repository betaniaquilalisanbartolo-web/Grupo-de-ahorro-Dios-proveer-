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
        # Configuración de sistema / credenciales
        conn.execute(
            text("""
            CREATE TABLE IF NOT EXISTS configuracion (
                clave VARCHAR(50) PRIMARY KEY,
                valor VARCHAR(550) NOT NULL
            );
        """)
        )

        # Insertar contraseña por defecto ('admin123') cifrada si no existe
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

        # Socios
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

        # Ahorros
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

        # Préstamos
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

        # Pagos de Préstamos
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

        # MIGRACIÓN AUTOMÁTICA
        conn.execute(
            text(
                "ALTER TABLE pagos ADD COLUMN IF NOT EXISTS monto_capital"
                " NUMERIC(12, 2) DEFAULT 0.00;"
            )
        )
        conn.execute(
            text(
                "ALTER TABLE pagos ADD COLUMN IF NOT EXISTS monto_interes"
                " NUMERIC(12, 2) DEFAULT 0.00;"
            )
        )
        conn.execute(
            text("ALTER TABLE pagos ADD COLUMN IF NOT EXISTS tipo VARCHAR(20);")
        )

        # Egresos y Gastos Operativos
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

        # Cierres Anuales
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

        # Bitácora de Auditoría
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
    """Genera un archivo PDF elegante del recibo oficial de pago usando ReportLab."""
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

    story.append(Paragraph("<b>CAJA DE AHORRO COMUNITARIO</b>", style_header))
    story.append(
        Paragraph("Comprobante Oficial de Pago de Préstamo", style_sub)
    )
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
            Paragraph("<b>Socio / Beneficiario:</b>", style_bold),
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
            Paragraph("Pago de Interés Mensual", style_body),
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
            Paragraph("<b>Firma Entregado (Socio)</b>", style_sub),
            Paragraph("<b>Firma Recibido (Caja)</b>", style_sub),
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
                    "SELECT * FROM ahorros WHERE EXTRACT(YEAR FROM fecha) ="
                    " :a"
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
    ],
)

# ==========================================
# SECCIÓN 1: PANEL GENERAL (DASHBOARD)
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
                    f"Depósito de ahorro C$ {monto_ahorro} registrado para"
                    f" socio {socio_nom}"
                )
                st.success(
                    f"Ahorro de C$ {monto_ahorro:,.2f} registrado para"
                    f" {socio_nom}."
                )
                st.rerun()

        with tab2:
            st.subheader("Historial General de Aportaciones")
            query_ahorros = """
                SELECT a.id as "ID", s.nombre as "Socio", a.monto as "Monto (C$)", a.fecha as "Fecha", a.nota as "Nota"
                FROM ahorros a
                JOIN socios s ON a.socio_id = s.id
                ORDER BY a.fecha DESC, a.id DESC
                """
            with motor.connect() as conn:
                df_hist_ahorros = pd.read_sql(text(query_ahorros), conn)
            st.dataframe(df_hist_ahorros, use_container_width=True)
            if not df_hist_ahorros.empty:
                st.download_button(
                    label="📥 Exportar Ahorros a Excel",
                    data=to_excel(df_hist_ahorros),
                    file_name=(
                        f"reporte_ahorros_{datetime.now().strftime('%Y%m%d')}.xlsx"
                    ),
                    mime=(
                        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                    ),
                )

        with tab3:
            st.subheader("Corregir o Eliminar Registro de Ahorro")
            query_edit_a = """
                SELECT a.id, s.nombre || ' - C$' || a.monto || ' (' || a.fecha || ')' as label, a.socio_id, a.monto, a.fecha, a.nota
                FROM ahorros a
                JOIN socios s ON a.socio_id = s.id
                ORDER BY a.id DESC
                """
            with motor.connect() as conn:
                df_edit_a = pd.read_sql(text(query_edit_a), conn)

            if df_edit_a.empty:
                st.info("No hay registros de ahorro para modificar.")
            else:
                dict_edit_a = dict(zip(df_edit_a["label"], df_edit_a["id"]))
                ahorro_sel = st.selectbox(
                    "Selecciona el depósito a editar:", list(dict_edit_a.keys())
                )
                id_a_sel = dict_edit_a[ahorro_sel]
                reg_a = df_edit_a[df_edit_a["id"] == id_a_sel].iloc[0]

                with st.form("form_edit_ahorro"):
                    socio_idx = (
                        list(dict_socios.values()).index(reg_a["socio_id"])
                        if reg_a["socio_id"] in dict_socios.values()
                        else 0
                    )
                    e_socio_nom = st.selectbox(
                        "Socio", list(dict_socios.keys()), index=socio_idx
                    )
                    e_monto = st.number_input(
                        "Monto (C$)",
                        value=float(reg_a["monto"]),
                        min_value=1.0,
                        step=10.0,
                    )
                    f_a_orig = pd.to_datetime(reg_a["fecha"]).date()
                    e_fecha = st.date_input("Fecha", value=f_a_orig)
                    e_nota = st.text_input("Nota", value=reg_a["nota"] or "")

                    col_btn1, col_btn2 = st.columns(2)
                    with col_btn1:
                        btn_update_a = st.form_submit_button("💾 Guardar Cambios")
                    with col_btn2:
                        btn_delete_a = st.form_submit_button("🗑️ Eliminar Registro")

                    if btn_update_a:
                        with motor.begin() as conn:
                            conn.execute(
                                text(
                                    "UPDATE ahorros SET socio_id = :socio_id,"
                                    " monto = :monto, fecha = :fecha, nota ="
                                    " :nota WHERE id = :id"
                                ),
                                {
                                    "socio_id": dict_socios[e_socio_nom],
                                    "monto": e_monto,
                                    "fecha": str(e_fecha),
                                    "nota": e_nota,
                                    "id": id_a_sel,
                                },
                            )
                        registrar_bitacora(
                            f"Actualización de depósito de ahorro ID {id_a_sel}"
                        )
                        st.success("¡Depósito actualizado correctamente!")
                        st.rerun()

                    if btn_delete_a:
                        with motor.begin() as conn:
                            conn.execute(
                                text("DELETE FROM ahorros WHERE id = :id"),
                                {"id": id_a_sel},
                            )
                        registrar_bitacora(
                            f"Eliminación de depósito de ahorro ID {id_a_sel}"
                        )
                        st.warning("Registro de ahorro eliminado.")
                        st.rerun()

# ==========================================
# SECCIÓN 4: PRÉSTAMOS
# ==========================================
elif opcion == "🤝 Préstamos":
    st.title("🤝 Módulo de Préstamos")
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
                "➕ Otorgar Préstamo",
                "📋 Listado de Préstamos",
                "✏️ Editar / Administrar Préstamo",
            ]
        )
        dict_socios = dict(zip(df_socios["nombre"], df_socios["id"]))

        with tab1:
            st.subheader("Otorgar Nuevo Préstamo")
            with st.form("form_prestamo", clear_on_submit=True):
                socio_nom = st.selectbox(
                    "Socio Solicitante *", list(dict_socios.keys())
                )
                monto_prestado = st.number_input(
                    "Monto Solicitado (C$) *", min_value=100.0, step=500.0, value=10000.0
                )
                tasa_interes = st.number_input(
                    "Tasa de Interés Mensual (%) *", min_value=0.0, step=0.5, value=5.0
                )
                plazo_meses = st.number_input(
                    "Plazo (Meses) *", min_value=1, step=1, value=6
                )
                fecha_inicio = st.date_input("Fecha de Desembolso", datetime.now())
                btn_prestamo = st.form_submit_button("Desembolsar Préstamo")

            if btn_prestamo:
                socio_id = dict_socios[socio_nom]
                interes_total = (
                    monto_prestado * (tasa_interes / 100.0) * plazo_meses
                )
                monto_total = monto_prestado + interes_total
                anio_curr = fecha_inicio.year

                with motor.begin() as conn:
                    conn.execute(
                        text(
                            "INSERT INTO prestamos (socio_id, monto_prestado,"
                            " tasa_interes, plazo_meses, interes_total,"
                            " monto_total, fecha_inicio, anio) VALUES"
                            " (:socio_id, :monto_prestado, :tasa_interes,"
                            " :plazo_meses, :interes_total, :monto_total,"
                            " :fecha_inicio, :anio)"
                        ),
                        {
                            "socio_id": socio_id,
                            "monto_prestado": monto_prestado,
                            "tasa_interes": tasa_interes,
                            "plazo_meses": int(plazo_meses),
                            "interes_total": interes_total,
                            "monto_total": monto_total,
                            "fecha_inicio": str(fecha_inicio),
                            "anio": anio_curr,
                        },
                    )
                registrar_bitacora(
                    f"Préstamo de C$ {monto_prestado:,.2f} otorgado a {socio_nom}"
                )
                st.success(
                    f"¡Préstamo registrado con éxito para {socio_nom} por C$"
                    f" {monto_prestado:,.2f}!"
                )
                st.rerun()

        with tab2:
            st.subheader("Historial de Préstamos Registrados")
            query_prestamos = """
                SELECT p.id as "ID", s.nombre as "Socio", p.monto_prestado as "Monto (C$)", 
                       p.tasa_interes as "Tasa (%)", p.plazo_meses as "Plazo (Meses)", 
                       p.interes_total as "Interés Total (C$)", p.monto_total as "Total a Pagar (C$)", 
                       p.fecha_inicio as "Fecha Inicio", p.estado as "Estado"
                FROM prestamos p
                JOIN socios s ON p.socio_id = s.id
                ORDER BY p.id DESC
                """
            with motor.connect() as conn:
                df_hist_p = pd.read_sql(text(query_prestamos), conn)
            st.dataframe(df_hist_p, use_container_width=True)
            if not df_hist_p.empty:
                st.download_button(
                    label="📥 Exportar Préstamos a Excel",
                    data=to_excel(df_hist_p),
                    file_name=(
                        f"reporte_prestamos_{datetime.now().strftime('%Y%m%d')}.xlsx"
                    ),
                    mime=(
                        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                    ),
                )

        with tab3:
            st.subheader("Administrar o Cambiar Estado de Préstamo")
            with motor.connect() as conn:
                df_p_admin = pd.read_sql(
                    text(
                        "SELECT p.id, s.nombre || ' - Préstamo #' || p.id || ' (C$' || p.monto_prestado || ')' as label, p.estado FROM prestamos p JOIN socios s ON p.socio_id = s.id ORDER BY p.id DESC"
                    ),
                    conn,
                )

            if df_p_admin.empty:
                st.info("No hay préstamos para administrar.")
            else:
                dict_p_admin = dict(zip(df_p_admin["label"], df_p_admin["id"]))
                p_sel_lbl = st.selectbox(
                    "Selecciona el Préstamo:", list(dict_p_admin.keys())
                )
                id_p_sel = dict_p_admin[p_sel_lbl]
                estado_actual = df_p_admin[df_p_admin["id"] == id_p_sel].iloc[0][
                    "estado"
                ]

                with st.form("form_admin_prestamo"):
                    nuevo_estado = st.selectbox(
                        "Cambiar Estado del Préstamo",
                        ["Activo", "Saldado", "Cancelado"],
                        index=0 if estado_actual == "Activo" else (1 if estado_actual == "Saldado" else 2),
                    )
                    btn_up_p = st.form_submit_button("Actualizar Estado")

                    if btn_up_p:
                        with motor.begin() as conn:
                            conn.execute(
                                text(
                                    "UPDATE prestamos SET estado = :est WHERE id = :id"
                                ),
                                {"est": nuevo_estado, "id": id_p_sel},
                            )
                        registrar_bitacora(
                            f"Estado del préstamo #{id_p_sel} cambiado a '{nuevo_estado}'"
                        )
                        st.success(
                            f"¡Estado del préstamo #{id_p_sel} actualizado a"
                            f" '{nuevo_estado}'!"
                        )
                        st.rerun()

# ==========================================
# SECCIÓN 5: SIMULADOR DE PRÉSTAMOS
# ==========================================
elif opcion == "🧮 Simulador de Préstamos":
    st.title("🧮 Simulador Financiero de Préstamos")
    st.markdown(
        "Calcula las cuotas, intereses y el plan de pagos estimado antes de"
        " otorgar un crédito."
    )

    col_s1, col_s2, col_s3 = st.columns(3)
    with col_s1:
        monto_sim = st.number_input(
            "Monto a Simular (C$)", min_value=100.0, step=500.0, value=20000.0
        )
    with col_s2:
        tasa_sim = st.number_input(
            "Tasa de Interés Mensual (%)", min_value=0.0, step=0.5, value=5.0
        )
    with col_s3:
        plazo_sim = st.number_input(
            "Plazo en Meses", min_value=1, step=1, value=6
        )

    interes_mensual_calc = monto_sim * (tasa_sim / 100.0)
    interes_total_calc = interes_mensual_calc * plazo_sim
    monto_total_calc = monto_sim + interes_total_calc
    cuota_mensual_calc = monto_total_calc / plazo_sim

    st.markdown("---")
    res_c1, res_c2, res_c3 = st.columns(3)
    res_c1.metric("💵 Interés Mensual Fijo", f"C$ {interes_mensual_calc:,.2f}")
    res_c2.metric("📈 Interés Total del Plazo", f"C$ {interes_total_calc:,.2f}")
    res_c3.metric("💳 Cuota Total Sugerida", f"C$ {cuota_mensual_calc:,.2f}")

    with st.expander("📅 Ver Tabla de Amortización Teórica"):
        tabla_amort = []
        cap_pendiente = monto_sim
        amort_mensual = monto_sim / plazo_sim
        for mes in range(1, int(plazo_sim) + 1):
            tabla_amort.append({
                "Mes": mes,
                "Capital a Pagar (C$)": round(amort_mensual, 2),
                "Interés (C$)": round(interes_mensual_calc, 2),
                "Cuota Total (C$)": round(amort_mensual + interes_mensual_calc, 2),
                "Capital Pendiente (C$)": round(
                    max(0.0, cap_pendiente - (amort_mensual * mes)), 2
                ),
            })
        st.dataframe(pd.DataFrame(tabla_amort), use_container_width=True)

# ==========================================
# SECCIÓN 6: PAGOS DE PRÉSTAMOS (CORREGIDA)
# ==========================================
elif opcion == "📖 Pagos de Préstamos":
    st.title("📖 Registro de Abonos y Pagos")
    
    with motor.connect() as conn:
        df_prestamos_activos = pd.read_sql(
            text("""
                SELECT p.id, s.nombre, p.monto_prestado, p.tasa_interes, p.plazo_meses, p.fecha_inicio
                FROM prestamos p
                JOIN socios s ON p.socio_id = s.id
                WHERE p.estado = 'Activo'
                ORDER BY p.id DESC
            """), conn
        )

    if df_prestamos_activos.empty:
        st.info("No hay préstamos activos para registrar pagos.")
    else:
        tab1, tab2, tab3 = st.tabs(
            [
                "➕ Registrar Abono",
                "📜 Historial de Pagos",
                "✏️ Editar / Borrar Pago",
            ]
        )

        dict_prestamos = {
            f"{row['nombre']} - Préstamo #{row['id']} (C${row['monto_prestado']} capital)": row['id']
            for _, row in df_prestamos_activos.iterrows()
        }

        with tab1:
            st.subheader("Registrar Nuevo Pago o Abono")
            prestamo_sel_label = st.selectbox("Selecciona el Préstamo *", list(dict_prestamos.keys()))
            prestamo_id_sel = dict_prestamos[prestamo_sel_label]

            with motor.connect() as conn:
                p_info = df_prestamos_activos[df_prestamos_activos['id'] == prestamo_id_sel].iloc[0]
                df_pagos_prestamo = pd.read_sql(
                    text("SELECT COALESCE(SUM(monto_capital), 0) as total_capital FROM pagos WHERE prestamo_id = :pid"),
                    conn, params={"pid": prestamo_id_sel}
                )
                capital_pagado_hist = float(df_pagos_prestamo['total_capital'].iloc[0])
                capital_pendiente = float(p_info['monto_prestado']) - capital_pagado_hist

            st.info(f"💡 Capital pendiente actual de este préstamo: **C$ {capital_pendiente:,.2f}**")

            with st.form("form_registro_pago"):
                tipo_abono = st.selectbox(
                    "Tipo de Abono *",
                    ["Completo (Cuota Mensual)", "Solo Interés", "Abono a Capital", "Cancelación Total Anticipada"]
                )
                
                # Monto completamente editable sin restricciones automáticas que alteren el valor
                monto_ingresado = st.number_input(
                    "Monto del Pago/Abono (C$) *",
                    min_value=1.0,
                    value=float(capital_pendiente) if tipo_abono == "Cancelación Total Anticipada" else 100.0,
                    step=100.0,
                    format="%.2f"
                )
                
                fecha_pago = st.date_input("Fecha del Pago", datetime.now())
                btn_registrar_pago = st.form_submit_button("Registrar Pago")

            if btn_registrar_pago:
                monto_capital = 0.0
                monto_interes = 0.0
                saldar_prestamo = False

                if tipo_abono == "Cancelación Total Anticipada":
                    monto_capital = capital_pendiente
                    monto_interes = max(0.0, monto_ingresado - monto_capital)
                    monto_pagado_final = monto_capital + monto_interes
                    saldar_prestamo = True
                elif tipo_abono == "Abono a Capital":
                    monto_capital = monto_ingresado
                    monto_interes = 0.0
                    monto_pagado_final = monto_capital
                elif tipo_abono == "Solo Interés":
                    monto_capital = 0.0
                    monto_interes = monto_ingresado
                    monto_pagado_final = monto_interes
                else:  # Completo (Cuota Mensual)
                    monto_capital = min(monto_ingresado, capital_pendiente)
                    monto_interes = max(0.0, monto_ingresado - monto_capital)
                    monto_pagado_final = monto_ingresado
                    if capital_pendiente - monto_capital <= 0:
                        saldar_prestamo = True

                with motor.begin() as conn:
                    conn.execute(
                        text("""
                            INSERT INTO pagos (prestamo_id, monto_pagado, monto_capital, monto_interes, fecha, tipo)
                            VALUES (:pid, :mpag, :mcap, :mint, :fec, :tip)
                        """),
                        {
                            "pid": prestamo_id_sel,
                            "mpag": monto_pagado_final,
                            "mcap": monto_capital,
                            "mint": monto_interes,
                            "fec": str(fecha_pago),
                            "tip": tipo_abono
                        }
                    )

                    if saldar_prestamo or (capital_pendiente - monto_capital <= 0):
                        conn.execute(
                            text("UPDATE prestamos SET estado = 'Saldado' WHERE id = :pid"),
                            {"pid": prestamo_id_sel}
                        )

                registrar_bitacora(f"Pago registrado de C$ {monto_pagado_final:,.2f} para préstamo #{prestamo_id_sel}")
                st.success(f"¡Abono registrado con éxito! C$ {monto_capital:,.2f} a Capital y C$ {monto_interes:,.2f} a Interés.")
                st.rerun()

        with tab2:
            st.subheader("Historial de Pagos Recibidos")
            query_hist_pagos = """
                SELECT pg.id as "ID", p.id as "Préstamo #", s.nombre as "Socio", 
                       pg.monto_pagado as "Monto Pagado (C$)", pg.monto_capital as "Capital (C$)", 
                       pg.monto_interes as "Interés (C$)", pg.fecha as "Fecha", pg.tipo as "Tipo"
                FROM pagos pg
                JOIN prestamos p ON pg.prestamo_id = p.id
                JOIN socios s ON p.socio_id = s.id
                ORDER BY pg.fecha DESC, pg.id DESC
                """
            with motor.connect() as conn:
                df_hist_pagos = pd.read_sql(text(query_hist_pagos), conn)
            st.dataframe(df_hist_pagos, use_container_width=True)
            if not df_hist_pagos.empty:
                st.download_button(
                    label="📥 Exportar Pagos a Excel",
                    data=to_excel(df_hist_pagos),
                    file_name=(
                        f"reporte_pagos_{datetime.now().strftime('%Y%m%d')}.xlsx"
                    ),
                    mime=(
                        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                    ),
                )

        with tab3:
            st.subheader("Modificar o Eliminar un Pago")
            with motor.connect() as conn:
                df_edit_p = pd.read_sql(
                    text("""
                        SELECT pg.id, s.nombre || ' - Pág #' || pg.id || ' (C$' || pg.monto_pagado || ')' as label
                        FROM pagos pg
                        JOIN prestamos p ON pg.prestamo_id = p.id
                        JOIN socios s ON p.socio_id = s.id
                        ORDER BY pg.id DESC
                    """), conn
                )

            if df_edit_p.empty:
                st.info("No hay pagos registrados para editar.")
            else:
                dict_edit_p = dict(zip(df_edit_p["label"], df_edit_p["id"]))
                pago_sel_lbl = st.selectbox("Selecciona el Pago:", list(dict_edit_p.keys()))
                id_pago_sel = dict_edit_p[pago_sel_lbl]

                with st.form("form_del_pago"):
                    st.warning("⚠️ Si eliminas un pago, el capital pendiente del préstamo se recalculará automáticamente.")
                    btn_borrar_pago = st.form_submit_button("🗑️ Eliminar este Pago")

                    if btn_borrar_pago:
                        with motor.begin() as conn:
                            # Obtener prestamo_id antes de borrar
                            res_pid = conn.execute(
                                text("SELECT prestamo_id FROM pagos WHERE id = :id"),
                                {"id": id_pago_sel}
                            ).fetchone()
                            
                            conn.execute(
                                text("DELETE FROM pagos WHERE id = :id"),
                                {"id": id_pago_sel}
                            )

                            if res_pid:
                                # Si el préstamo estaba saldado, volver a pasarlo a 'Activo' por si se elimina el pago de cancelación
                                conn.execute(
                                    text("UPDATE prestamos SET estado = 'Activo' WHERE id = :pid"),
                                    {"pid": res_pid[0]}
                                )

                        registrar_bitacora(f"Eliminación del pago ID {id_pago_sel}")
                        st.success("¡Pago eliminado correctamente y estado del préstamo recalculado!")
                        st.rerun()

# ==========================================
# SECCIÓN 7: EGRESOS Y GASTOS
# ==========================================
elif opcion == "💸 Egresos y Gastos":
    st.title("💸 Control de Egresos y Gastos Operativos")
    tab1, tab2 = st.tabs(["➕ Registrar Egreso", "📜 Historial de Egresos"])

    with tab1:
        with st.form("form_egreso", clear_on_submit=True):
            concepto = st.text_input("Concepto del Gasto *")
            monto_egreso = st.number_input("Monto (C$) *", min_value=1.0, step=10.0)
            fecha_egreso = st.date_input("Fecha del Gasto", datetime.now())
            responsable = st.text_input("Responsable / Autorizado por")
            btn_egreso = st.form_submit_button("Guardar Egreso")

        if btn_egreso:
            if concepto.strip() == "":
                st.error("El concepto del egreso es obligatorio.")
            else:
                with motor.begin() as conn:
                    conn.execute(
                        text(
                            "INSERT INTO egresos (concepto, monto, fecha,"
                            " responsable) VALUES (:concepto, :monto, :fecha,"
                            " :responsable)"
                        ),
                        {
                            "concepto": concepto,
                            "monto": monto_egreso,
                            "fecha": str(fecha_egreso),
                            "responsable": responsable,
                        },
                    )
                registrar_bitacora(f"Egreso registrado: {concepto} por C$ {monto_egreso}")
                st.success(f"¡Egreso de C$ {monto_egreso:,.2f} registrado con éxito!")
                st.rerun()

    with tab2:
        with motor.connect() as conn:
            df_egresos = pd.read_sql(
                text(
                    'SELECT id as "ID", concepto as "Concepto", monto as'
                    ' "Monto (C$)", fecha as "Fecha", responsable as'
                    ' "Responsable" FROM egresos ORDER BY fecha DESC'
                ),
                conn,
            )
        st.dataframe(df_egresos, use_container_width=True)
        if not df_egresos.empty:
            st.download_button(
                label="📥 Exportar Egresos a Excel",
                data=to_excel(df_egresos),
                file_name=(
                    f"reporte_egresos_{datetime.now().strftime('%Y%m%d')}.xlsx"
                ),
                mime=(
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                ),
            )

# ==========================================
# SECCIÓN 8: ESTADO DE CUENTA
# ==========================================
elif opcion == "📜 Estado de Cuenta":
    st.title("📜 Estado de Cuenta por Socio")
    with motor.connect() as conn:
        df_socios = pd.read_sql(
            text("SELECT id, nombre FROM socios ORDER BY nombre ASC"), conn
        )

    if df_socios.empty:
        st.info("No hay socios registrados.")
    else:
        dict_socios_ec = dict(zip(df_socios["nombre"], df_socios["id"]))
        socio_sel_ec = st.selectbox(
            "Selecciona el Socio para ver su Estado de Cuenta:",
            list(dict_socios_ec.keys()),
        )
        id_socio_ec = dict_socios_ec[socio_sel_ec]

        with motor.connect() as conn:
            df_a_socio = pd.read_sql(
                text(
                    'SELECT id as "ID", monto as "Ahorro (C$)", fecha as'
                    ' "Fecha", nota as "Nota" FROM ahorros WHERE socio_id ='
                    ' :sid ORDER BY fecha DESC'
                ),
                conn,
                params={"sid": id_socio_ec},
            )
            df_p_socio = pd.read_sql(
                text(
                    'SELECT id as "Préstamo #", monto_prestado as "Monto (C$)",'
                    ' tasa_interes as "Tasa (%)", plazo_meses as "Plazo",'
                    ' monto_total as "Total (C$)", fecha_inicio as "Fecha",'
                    ' estado as "Estado" FROM prestamos WHERE socio_id = :sid'
                    ' ORDER BY id DESC'
                ),
                conn,
                params={"sid": id_socio_ec},
            )

        st.subheader(f"Ahorros de {socio_sel_ec}")
        st.dataframe(df_a_socio, use_container_width=True)
        total_ahorros_socio = (
            df_a_socio["Ahorro (C$)"].sum() if not df_a_socio.empty else 0.0
        )
        st.success(f"💰 Total Ahorrado por el Socio: **C$ {total_ahorros_socio:,.2f}**")

        st.markdown("---")
        st.subheader(f"Préstamos de {socio_sel_ec}")
        st.dataframe(df_p_socio, use_container_width=True)

# ==========================================
# SECCIÓN 9: LIQUIDACIÓN ANUAL
# ==========================================
elif opcion == "🎉 Liquidación Anual":
    st.title("🎉 Módulo de Liquidación Anual")
    st.markdown(
        "Calcula la distribución de rendimientos y el cierre de fin de año"
        " para los socios."
    )

    anio_liq = st.selectbox(
        "Selecciona el Año de Liquidación:",
        list(range(datetime.now().year, 2019, -1)),
    )

    with motor.connect() as conn:
        df_tot_ahorros = pd.read_sql(
            text(
                "SELECT COALESCE(SUM(monto), 0) as total FROM ahorros WHERE"
                " anio = :anio"
            ),
            conn,
            params={"anio": anio_liq},
        )
        total_ahorro_anio = float(df_tot_ahorros["total"].iloc[0])

        df_tot_intereses = pd.read_sql(
            text(
                "SELECT COALESCE(SUM(monto_interes), 0) as total FROM pagos pg"
                " JOIN prestamos p ON pg.prestamo_id = p.id WHERE"
                " EXTRACT(YEAR FROM pg.fecha) = :anio"
            ),
            conn,
            params={"anio": anio_liq},
        )
        total_intereses_anio = float(df_tot_intereses["total"].iloc[0])

    col_l1, col_l2 = st.columns(2)
    col_l1.metric(
        f"💰 Total Ahorros ({anio_liq})", f"C$ {total_ahorro_anio:,.2f}"
    )
    col_l2.metric(
        f"📈 Intereses Recaudados ({anio_liq})",
        f"C$ {total_intereses_anio:,.2f}",
    )

    st.markdown("---")
    if st.button("🔒 Procesar y Guardar Cierre de Liquidación Anual"):
        with motor.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO cierres_anuales (anio, total_ahorrado,"
                    " total_intereses) VALUES (:anio, :ta, :ti)"
                ),
                {
                    "anio": anio_liq,
                    "ta": total_ahorro_anio,
                    "ti": total_intereses_anio,
                },
            )
        registrar_bitacora(f"Liquidación anual procesada para el año {anio_liq}")
        st.success(
            f"¡Liquidación del año {anio_liq} guardada en el historial con"
            " éxito!"
        )

# ==========================================
# SECCIÓN 10: CIERRE MENSUAL Y ANUAL
# ==========================================
elif opcion == "📅 Cierre Mensual y Anual":
    st.title("📅 Módulo de Cierre Mensual y Anual")
    st.markdown(
        "Control mensual de caja e historial de liquidaciones cerradas."
    )

    col_c1, col_c2 = st.columns(2)
    with col_c1:
        mes_sel = st.selectbox("Seleccionar Mes", list(range(1, 13)), index=datetime.now().month - 1)
    with col_c2:
        anio_sel = st.selectbox(
            "Seleccionar Año", list(range(2025, 2031)), index=1
        )

    with motor.connect() as conn:
        df_ahorros_mes = pd.read_sql(
            text(
                "SELECT COALESCE(SUM(monto), 0) as total FROM ahorros WHERE"
                " EXTRACT(MONTH FROM fecha) = :mes AND EXTRACT(YEAR FROM"
                " fecha) = :anio"
            ),
            conn,
            params={"mes": mes_sel, "anio": anio_sel},
        )
        ahorros_mes = float(df_ahorros_mes["total"].iloc[0])

        df_pagos_mes = pd.read_sql(
            text(
                "SELECT COALESCE(SUM(monto_pagado), 0) as total FROM pagos"
                " WHERE EXTRACT(MONTH FROM fecha) = :mes AND EXTRACT(YEAR"
                " FROM fecha) = :anio"
            ),
            conn,
            params={"mes": mes_sel, "anio": anio_sel},
        )
        pagos_mes = float(df_pagos_mes["total"].iloc[0])

    st.markdown("### Resumen Mensual")
    st.metric(f"💰 Ahorros del Mes ({mes_sel}/{anio_sel})", f"C$ {ahorros_mes:,.2f}")
    st.metric(
        f"📥 Pagos/Cobros Recibidos en el Mes ({mes_sel}/{anio_sel})",
        f"C$ {pagos_mes:,.2f}",
    )

    st.markdown("---")
    st.subheader("📜 Historial de Cierres Anuales")
    with motor.connect() as conn:
        df_cierres = pd.read_sql(
            text(
                'SELECT id as "ID", anio as "Año", total_ahorrado as'
                ' "Total Ahorrado (C$)", total_intereses as "Intereses (C$)",'
                ' fecha_cierre as "Fecha de Cierre" FROM cierres_anuales'
                ' ORDER BY anio DESC'
            ),
            conn,
        )
    st.dataframe(df_cierres, use_container_width=True)

# ==========================================
# SECCIÓN 11: BITÁCORA DE AUDITORÍA
# ==========================================
elif opcion == "🛡️ Bitácora de Auditoría":
    st.title("🛡️ Bitácora de Auditoría y Seguridad")
    st.markdown(
        "Registro de todas las acciones importantes realizadas en el sistema."
    )

    with motor.connect() as conn:
        df_bitacora = pd.read_sql(
            text(
                'SELECT id as "ID", fecha as "Fecha y Hora", usuario as'
                ' "Usuario", accion as "Acción Realizada" FROM bitacora ORDER'
                ' BY fecha DESC LIMIT 100'
            ),
            conn,
        )

    st.dataframe(df_bitacora, use_container_width=True)
    if not df_bitacora.empty:
        st.download_button(
            label="📥 Exportar Bitácora a Excel",
            data=to_excel(df_bitacora),
            file_name=(
                f"reporte_bitacora_{datetime.now().strftime('%Y%m%d')}.xlsx"
            ),
            mime=(
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            ),
            )
