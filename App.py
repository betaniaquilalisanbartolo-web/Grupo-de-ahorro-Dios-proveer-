import hashlib
import io
import os
from datetime import datetime
import pandas as pd
import streamlit as st
from sqlalchemy import create_engine, text

# ==========================================
# 1. CONFIGURACIÃ“N DE PÃGINA
# ==========================================
st.set_page_config(
    page_title="Caja de Ahorro Comunitario",
    page_icon="ðŸ’°",
    layout="wide"
)

# ==========================================
# 2. GESTIÃ“N DE BASE DE DATOS (Supabase / PostgreSQL)
# ==========================================
@st.cache_resource
def obtener_motor():
    db_url = st.secrets["postgres"]["url"]
    return create_engine(db_url, pool_pre_ping=True, pool_recycle=300)

motor = obtener_motor()

def hash_password(password: str, salt: bytes = None) -> str:
    """Genera un hash seguro SHA-256 con salt para almacenar la contraseÃ±a."""
    if salt is None:
        salt = os.urandom(16)
    elif isinstance(salt, str):
        salt = bytes.fromhex(salt)

    pwd_hash = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt, 100000
    )
    return f"{salt.hex()}:{pwd_hash.hex()}"

def verificar_contrasena(
    contrasena_ingresada: str, hash_almacenado: str
) -> bool:
    """Verifica si la contraseÃ±a ingresada coincide con el hash almacenado."""
    try:
        salt_hex, _ = hash_almacenado.split(":")
        salt = bytes.fromhex(salt_hex)
        hash_nuevo = hash_password(contrasena_ingresada, salt)
        return hash_nuevo == hash_almacenado
    except Exception:
        return False

def sincronizar_estados_prestamos():
    """Recalcula y actualiza automÃ¡ticamente los prÃ©stamos cuyos abonos cubren la totalidad del capital o total a pagar."""
    try:
        with motor.begin() as conn:
            conn.execute(
                text("""
                UPDATE prestamos
                SET estado = 'Saldado'
                WHERE id IN (
                    SELECT p.id
                    FROM prestamos p
                    LEFT JOIN (
                        SELECT prestamo_id, 
                               COALESCE(SUM(monto_capital), 0) as total_cap,
                               COALESCE(SUM(monto_pagado), 0) as total_pag
                        FROM pagos
                        GROUP BY prestamo_id
                    ) pg ON p.id = pg.prestamo_id
                    WHERE p.estado = 'Activo' 
                    AND (pg.total_cap >= p.monto_prestado OR pg.total_pag >= p.monto_total)
                );
                """)
            )
    except Exception as e:
        st.error(f"Error al sincronizar estados de prÃ©stamos: {e}")

def init_db():
    with motor.begin() as conn:
        # ConfiguraciÃ³n de sistema / credenciales
        conn.execute(
            text("""
            CREATE TABLE IF NOT EXISTS configuracion (
                clave VARCHAR(50) PRIMARY KEY,
                valor VARCHAR(550) NOT NULL
            );
            """)
        )

        # Insertar contraseÃ±a por defecto ('admin123') cifrada si no existe
        res = conn.execute(
            text(
                "SELECT valor FROM configuracion WHERE clave = 'admin_password'"
            )
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

        # PrÃ©stamos
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

        # Pagos de PrÃ©stamos
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

        # MIGRACIÃ“N AUTOMÃTICA
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
            text(
                "ALTER TABLE pagos ADD COLUMN IF NOT EXISTS tipo VARCHAR(20);"
            )
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

        # BitÃ¡cora de AuditorÃ­a
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

    sincronizar_estados_prestamos()

if "db_inicializada" not in st.session_state:
    init_db()
    st.session_state.db_inicializada = True

# EjecuciÃ³n automÃ¡tica en cada interacciÃ³n para mantener sincronizada la DB
sincronizar_estados_prestamos()

# ==========================================
# 3. FUNCIONES UTILITARIAS Y DE SEGURIDAD
# ==========================================
def obtener_hash_password_bd():
    with motor.connect() as conn:
        res = conn.execute(
            text(
                "SELECT valor FROM configuracion WHERE clave = 'admin_password'"
            )
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
        st.error(f"Error al registrar en bitÃ¡cora: {e}")

def to_excel(df: pd.DataFrame) -> bytes:
    salida = io.BytesIO()
    try:
        with pd.ExcelWriter(salida, engine="openpyxl") as writer:
            df.to_excel(writer, index=False, sheet_name="Reporte")
        salida.seek(0)
    except ModuleNotFoundError:
        st.error("Error: La librerÃ­a 'openpyxl' no estÃ¡ instalada.")
        return b""
    return salida.getvalue()

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
# 4. AUTENTICACIÃ“N / CONTROL DE ACCESO
# ==========================================
if "autenticado" not in st.session_state:
    st.session_state.autenticado = False

st.sidebar.title("ðŸ”‘ Control de Acceso")

if not st.session_state.autenticado:
    password_input = st.sidebar.text_input(
        "ContraseÃ±a de Administrador", type="password"
    )
    if st.sidebar.button("Iniciar sesiÃ³n"):
        hash_almacenado = obtener_hash_password_bd()
        if hash_almacenado and verificar_contrasena(
            password_input, hash_almacenado
        ):
            st.session_state.autenticado = True
            registrar_bitacora("Inicio de sesiÃ³n exitosa como Administrador.")
            st.sidebar.success("Â¡Acceso concedido!")
            st.rerun()
        else:
            st.sidebar.error("ContraseÃ±a incorrecta.")

    st.warning(
        "âš ï¸ Debes iniciar sesiÃ³n como Administrador en la barra lateral para"
        " acceder al sistema."
    )
    st.stop()
else:
    st.sidebar.success("SesiÃ³n activa como Administrador")
    with st.sidebar.expander("ðŸ”‘ Cambiar ContraseÃ±a"):
        pwd_actual = st.text_input(
            "ContraseÃ±a Actual", type="password", key="pwd_act"
        )
        pwd_nueva = st.text_input(
            "Nueva ContraseÃ±a", type="password", key="pwd_nuev"
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
                    registrar_bitacora("Cambio de contraseÃ±a de administrador.")
                    st.success(
                        "ContraseÃ±a actualizada e encriptada correctamente."
                    )
                else:
                    st.error(
                        "La nueva contraseÃ±a debe tener al menos 4 caracteres."
                    )
            else:
                st.error("La contraseÃ±a actual es incorrecta.")

    if st.sidebar.button("Cerrar sesiÃ³n"):
        st.session_state.autenticado = False
        st.rerun()

# ==========================================
# 5. MENÃš NAVEGACIÃ“N LATERAL
# ==========================================
st.sidebar.markdown("---")
st.sidebar.title("ðŸ›ï¸ MenÃº Principal")
opcion = st.sidebar.radio(
    "Selecciona una secciÃ³n:",
    [
        "ðŸ“Š Panel General",
        "ðŸ‘¥ Socios",
        "ðŸ’µ Ahorros y Cuotas",
        "ðŸ¤ PrÃ©stamos",
        "ðŸ§® Simulador de PrÃ©stamos",
        "ðŸ“– Pagos de PrÃ©stamos",
        "ðŸ’¸ Egresos y Gastos",
        "ðŸ“œ Estado de Cuenta",
        "ðŸŽ‰ LiquidaciÃ³n Anual",
        "ðŸ“… Cierre Mensual y Anual",
        "ðŸ›¡ï¸ BitÃ¡cora de AuditorÃ­a",
    ],
)

# ==========================================
# SECCIÃ“N 1: PANEL GENERAL (DASHBOARD)
# ==========================================
if opcion == "ðŸ“Š Panel General":
    st.title("ðŸ“Š Panel General de la Caja de Ahorro")
    st.caption("Resumen financiero consolidado en CÃ³rdoba (C$).")

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
            text("SELECT COALESCE(SUM(monto_pagado), 0) as total FROM pagos"), conn
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

        # Consultas SQL optimizadas para PostgreSQL
        query_mora = """
        SELECT p.id, s.nombre, p.monto_prestado, p.fecha_inicio, p.plazo_meses
        FROM prestamos p
        JOIN socios s ON p.socio_id = s.id
        WHERE p.estado = 'Activo' AND (p.fecha_inicio + MAKE_INTERVAL(months => p.plazo_meses)) < CURRENT_DATE
        """
        df_mora = pd.read_sql(text(query_mora), conn)

        consulta_por_vencer = """
        SELECT p.id, s.nombre, p.monto_prestado, p.fecha_inicio, (p.fecha_inicio + MAKE_INTERVAL(months => p.plazo_meses)) as fecha_vencimiento
        FROM prestamos p
        JOIN socios s ON p.socio_id = s.id
        WHERE p.estado = 'Activo' AND (p.fecha_inicio + MAKE_INTERVAL(months => p.plazo_meses)) >= CURRENT_DATE 
        AND (p.fecha_inicio + MAKE_INTERVAL(months => p.plazo_meses)) <= (CURRENT_DATE + INTERVAL '30 days')
        """
        df_por_vencer = pd.read_sql(text(consulta_por_vencer), conn)

        df_mora_sum = pd.read_sql(
            text("""
            SELECT COALESCE(SUM(monto_prestado), 0) as total FROM prestamos
            WHERE estado = 'Activo' AND (fecha_inicio + MAKE_INTERVAL(months => plazo_meses)) < CURRENT_DATE
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
    col1.metric("ðŸ’µ Fondo Total Ahorrado", f"C$ {total_ahorrado:,.2f}")
    col2.metric("ðŸ“‰ Capital Prestado Activo", f"C$ {total_prestado:,.2f}")
    col3.metric("ðŸ“¥ Cobros/Abonos Totales", f"C$ {total_recaudado:,.2f}")
    col4.metric("ðŸ’¸ Egresos / Gastos", f"C$ {total_egresos:,.2f}")
    col5.metric("ðŸ›ï¸ Disponible en Caja", f"C$ {fondo_caja:,.2f}")

    col_a1, col_a2 = st.columns(2)
    with col_a1:
        if not df_mora.empty:
            st.error(
                f"âš ï¸ **AtenciÃ³n:** Se identificaron **{len(df_mora)}"
                f" prÃ©stamo(s) en MORA** (Ãndice de Mora: **{ratio_mora:.1f}%**)."
            )
            with st.expander("ðŸ‘ï¸ Ver PrÃ©stamos en Mora"):
                st.dataframe(df_mora, use_container_width=True)
        else:
            st.success("âœ… **Sin morosidad:** Cartera de prÃ©stamos al dÃ­a.")

    with col_a2:
        if not df_por_vencer.empty:
            st.warning(
                f"ðŸ”” **Alerta Temprana:** **{len(df_por_vencer)} prÃ©stamo(s)**"
                " vencerÃ¡n en los prÃ³ximos 30 dÃ­as."
            )
            with st.expander("ðŸ‘ï¸ Ver PrÃ©stamos PrÃ³ximos a Vencer"):
                st.dataframe(df_por_vencer, use_container_width=True)
        else:
            st.info("â„¹ï¸ No hay prÃ©stamos por vencer en los prÃ³ximos 30 dÃ­as.")

    st.markdown("---")
    col_dl1, col_dl2 = st.columns([3, 1])
    with col_dl1:
        st.subheader("ðŸ“Š MÃ©tricas RÃ¡pidas")
        st.info(f"ðŸ‘¥ **Socios Activos:** {total_socios} socios registrados.")

    with col_dl2:
        anio_exp = st.selectbox(
            "Seleccionar aÃ±o para filtro (Opcional):",
            ["Todos"] + list(range(2020, 2101)),
            index=0,
        )
        anio_val = None if anio_exp == "Todos" else int(anio_exp)
        st.download_button(
            label="ðŸ“¦ Exportar Copia Completa (Excel)",
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
# SECCIÃ“N 2: GESTIÃ“N DE SOCIOS
# ==========================================
elif opcion == "ðŸ‘¥ Socios":
    st.title("ðŸ‘¥ Control de Socios")

    tab1, tab2, tab3 = st.tabs(
        [
            "ðŸ“‹ Listado de Socios",
            "âž• Registrar Nuevo Socio",
            "âœï¸ Editar / Eliminar Socio",
        ]
    )

    with tab1:
        st.subheader("Socios Registrados")
        with motor.connect() as conn:
            df_socios = pd.read_sql(
                text(
                    'SELECT id as "ID", nombre as "Nombre", telefono as'
                    ' "TelÃ©fono", fecha_registro as "Fecha Registro", estado as'
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
                            f' target="_blank">ðŸ’¬ Contactar WhatsApp ({tel})</a>'
                        )
                return "Sin telÃ©fono"

            df_socios["AcciÃ³n WhatsApp"] = df_socios["TelÃ©fono"].apply(
                crear_link_wa
            )
            st.write(
                df_socios.to_html(escape=False, index=False),
                unsafe_allow_html=True,
            )
            st.markdown("<br>", unsafe_allow_html=True)
            st.download_button(
                label="ðŸ“¥ Exportar Socios a Excel",
                data=to_excel(
                    df_socios.drop(
                        columns=["AcciÃ³n WhatsApp"], errors="ignore"
                    )
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
            telefono = st.text_input("NÃºmero de TelÃ©fono / WhatsApp")
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
                    st.success(f"Â¡Socio '{nombre}' registrado correctamente!")
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
            socio_sel = st.selectbox(
                "Selecciona el Socio:", list(dict_s_edit.keys())
            )
            id_socio_sel = dict_s_edit[socio_sel]
            datos_socio = df_s_edit[
                df_s_edit["id"] == id_socio_sel
            ].iloc[0]

            with st.form("form_edit_socio"):
                e_nombre = st.text_input(
                    "Nombre Completo", value=datos_socio["nombre"]
                )
                e_telefono = st.text_input(
                    "TelÃ©fono / WhatsApp", value=datos_socio["telefono"] or ""
                )
                fecha_orig = pd.to_datetime(
                    datos_socio["fecha_registro"]
                ).date()
                e_fecha = st.date_input("Fecha de Registro", value=fecha_orig)
                e_estado = st.selectbox(
                    "Estado",
                    ["Activo", "Inactivo"],
                    index=0 if datos_socio["estado"] == "Activo" else 1,
                )

                col_b1, col_b2 = st.columns(2)
                with col_b1:
                    btn_guardar_edit = st.form_submit_button(
                        "ðŸ’¾ Guardar Cambios"
                    )
                with col_b2:
                    btn_eliminar_socio = st.form_submit_button(
                        "ðŸ—‘ï¸ Eliminar Socio"
                    )

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
                        "ActualizaciÃ³n de datos del socio ID"
                        f" {id_socio_sel}: {e_nombre}"
                    )
                    st.success("Â¡Datos del socio actualizados exitosamente!")
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
                        f"EliminaciÃ³n de socio ID {id_socio_sel}:"
                        f" {datos_socio['nombre']}"
                    )
                    st.warning(
                        f"Socio ID #{id_socio_sel} y sus registros"
                        " vinculados han sido eliminados."
                    )
                    st.rerun()

# ==========================================
# SECCIÃ“N 3: AHORROS Y CUOTAS
# ==========================================
elif opcion == "ðŸ’µ Ahorros y Cuotas":
    st.title("ðŸ’µ Registro de Ahorros")

    with motor.connect() as conn:
        df_socios = pd.read_sql(
            text(
                "SELECT id, nombre FROM socios WHERE estado = 'Activo' ORDER BY"
                " nombre ASC"
            ),
            conn,
        )

    if df_socios.empty:
        st.warning("Primero debes registrar socios en la secciÃ³n 'ðŸ‘¥ Socios'.")
    else:
        tab1, tab2, tab3 = st.tabs(
            [
                "âž• Depositar Ahorro",
                "ðŸ“œ Historial de Ahorros",
                "âœï¸ Editar / Corregir Ahorro",
            ]
        )
        dict_socios = dict(zip(df_socios["nombre"], df_socios["id"]))

        with tab1:
            st.subheader("Registrar Nueva AportaciÃ³n")
            with st.form("form_ahorro", clear_on_submit=True):
                socio_nom = st.selectbox(
                    "Selecciona el Socio *", list(dict_socios.keys())
                )
                monto_ahorro = st.number_input(
                    "Monto Ahorrado (C$) *", min_value=1.0, step=10.0
                )
                fecha_ahorro = st.date_input("Fecha del DepÃ³sito", datetime.now())
                nota_ahorro = st.text_input("Nota / ObservaciÃ³n (Opcional)")
                btn_ahorro = st.form_submit_button("Registrar DepÃ³sito")

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
                        f"DepÃ³sito de ahorro C$ {monto_ahorro} registrado para"
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
                    label="ðŸ“¥ Exportar Ahorros a Excel",
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
                    "Selecciona el depÃ³sito a editar:", list(dict_edit_a.keys())
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
                        btn_update_a = st.form_submit_button(
                            "ðŸ’¾ Guardar Cambios"
                        )
                    with col_btn2:
                        btn_delete_a = st.form_submit_button(
                            "ðŸ—‘ï¸ Eliminar Registro"
                        )

                    if btn_update_a:
                        with motor.begin() as conn:
                            conn.execute(
                                text(
                                    "UPDATE ahorros SET socio_id = :socio_id,"
                                    " monto = :monto, fecha = :fecha, nota ="
                                    " :nota, anio = :anio WHERE id = :id"
                                ),
                                {
                                    "socio_id": dict_socios[e_socio_nom],
                                    "monto": e_monto,
                                    "fecha": str(e_fecha),
                                    "nota": e_nota,
                                    "anio": e_fecha.year,
                                    "id": id_a_sel,
                                },
                            )
                        registrar_bitacora(
                            f"ActualizaciÃ³n de ahorro ID {id_a_sel}"
                        )
                        st.success("Â¡Registro de ahorro actualizado!")
                        st.rerun()

                    if btn_delete_a:
                        with motor.begin() as conn:
                            conn.execute(
                                text("DELETE FROM ahorros WHERE id = :id"),
                                {"id": id_a_sel},
                            )
                        registrar_bitacora(
                            f"EliminaciÃ³n de ahorro ID {id_a_sel}"
                        )
                        st.warning("Registro de ahorro eliminado correctamente.")
                        st.rerun()

# ==========================================
# SECCIÃ“N 4: PRÃ‰STAMOS
# ==========================================
elif opcion == "ðŸ¤ PrÃ©stamos":
    st.title("ðŸ¤ GestiÃ³n de PrÃ©stamos")

    with motor.connect() as conn:
        df_socios = pd.read_sql(
            text(
                "SELECT id, nombre FROM socios WHERE estado = 'Activo' ORDER BY"
                " nombre ASC"
            ),
            conn,
        )

    if df_socios.empty:
        st.warning("Registra socios antes de procesar prÃ©stamos.")
    else:
        dict_socios = dict(zip(df_socios["nombre"], df_socios["id"]))
        tab1, tab2, tab3, tab4 = st.tabs(
            [
                "âž• Nuevo PrÃ©stamo",
                "ðŸ“œ Historial",
                "ðŸ“… Reporte Mensual",
                "âœï¸ Editar / Eliminar PrÃ©stamo",
            ]
        )

        with tab1:
            st.subheader("Nuevo PrÃ©stamo")
            col1, col2 = st.columns(2)
            with col1:
                socio_prestamo = st.selectbox(
                    "Socio Solicitante", list(dict_socios.keys())
                )
                monto_solicitado = st.number_input(
                    "Monto del PrÃ©stamo (C$)", min_value=10.0, step=50.0
                )
                tasa_interes = st.number_input(
                    "Tasa de InterÃ©s Mensual (%)",
                    min_value=0.0,
                    value=5.0,
                    step=0.5,
                )
            with col2:
                plazo_meses = st.number_input(
                    "Plazo en Meses", min_value=1, max_value=36, value=6
                )
                fecha_prestamo = st.date_input("Fecha de EmisiÃ³n", datetime.now())

            interes_mensual = monto_solicitado * (tasa_interes / 100)
            interes_total = interes_mensual * plazo_meses
            monto_total_pagar = monto_solicitado + interes_total
            cuota_mensual = monto_total_pagar / plazo_meses

            st.info(f"""
            **Resumen del PrÃ©stamo:**
            * **InterÃ©s Total Calculado:** C$ {interes_total:,.2f}
            * **Monto Total a Devolver:** C$ {monto_total_pagar:,.2f}
            * **Cuota Mensual Estimada:** C$ {cuota_mensual:,.2f} / mes
            """)

            if st.button("Aprobar y Registrar PrÃ©stamo"):
                socio_id = dict_socios[socio_prestamo]
                anio_curr = fecha_prestamo.year
                with motor.begin() as conn:
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
                            "interes_total": interes_total,
                            "monto_total": monto_total_pagar,
                            "fecha_inicio": str(fecha_prestamo),
                            "anio": anio_curr,
                        },
                    )
                registrar_bitacora(
                    f"AprobaciÃ³n de prÃ©stamo C$ {monto_solicitado} para socio"
                    f" {socio_prestamo}"
                )
                st.success(
                    f"PrÃ©stamo registrado exitosamente para {socio_prestamo}"
                )
                st.rerun()

        with tab2:
            st.subheader("Historial General de PrÃ©stamos")
            query_p = """
            SELECT p.id as "ID", s.nombre as "Socio", p.monto_prestado as "Monto Prestado (C$)", 
                   p.tasa_interes as "Tasa (%)", p.plazo_meses as "Plazo (Meses)", 
                   p.interes_total as "InterÃ©s Total (C$)", p.monto_total as "Total a Pagar (C$)", 
                   p.fecha_inicio as "Fecha", p.estado as "Estado"
            FROM prestamos p
            JOIN socios s ON p.socio_id = s.id
            ORDER BY p.id DESC
            """
            with motor.connect() as conn:
                df_prestamos_hist = pd.read_sql(text(query_p), conn)

            st.dataframe(df_prestamos_hist, use_container_width=True)

            if not df_prestamos_hist.empty:
                st.download_button(
                    label="ðŸ“¥ Exportar PrÃ©stamos a Excel",
                    data=to_excel(df_prestamos_hist),
                    file_name=(
                        "reporte_prestamos_"
                        f"{datetime.now().strftime('%Y%m%d')}.xlsx"
                    ),
                    mime=(
                        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                    ),
                )

        with tab3:
            st.subheader("ðŸ“… Reporte Mensual Exclusivo de PrÃ©stamos")
            st.caption(
                "Filtra la cartera activa/emitida en el mes e indica la"
                " comparaciÃ³n entre el InterÃ©s Mensual esperado (%) vs. el"
                " InterÃ©s cobrado (Cumplido)."
            )

            col_m1, col_m2 = st.columns(2)
            with col_m1:
                mes_rep = st.selectbox(
                    "Seleccionar Mes:",
                    list(range(1, 13)),
                    index=datetime.now().month - 1,
                    key="rep_mes_p",
                )
            with col_m2:
                anio_rep = st.number_input(
                    "Seleccionar AÃ±o:",
                    min_value=2020,
                    max_value=2100,
                    value=datetime.now().year,
                    key="rep_anio_p",
                )

            query_reporte_mensual = """
            SELECT p.id AS "ID PrÃ©stamo", s.nombre AS "Socio", p.monto_prestado AS "Capital (C$)", 
                   p.tasa_interes AS "Tasa (%)", p.plazo_meses AS "Plazo (Meses)", 
                   (p.monto_prestado * (p.tasa_interes / 100.0)) AS "InterÃ©s Mensual Esperado (C$)", 
                   COALESCE(SUM(pg.monto_interes), 0.00) AS "InterÃ©s Cobrado en Mes (C$)", 
                   COALESCE(SUM(pg.monto_pagado), 0.00) AS "Total Cobrado en Mes (C$)", 
                   p.fecha_inicio AS "Fecha EmisiÃ³n", p.estado AS "Estado"
            FROM prestamos p
            JOIN socios s ON p.socio_id = s.id
            LEFT JOIN pagos pg ON p.id = pg.prestamo_id AND EXTRACT(MONTH FROM pg.fecha) = :mes AND EXTRACT(YEAR FROM pg.fecha) = :anio
            WHERE EXTRACT(MONTH FROM p.fecha_inicio) = :mes AND EXTRACT(YEAR FROM p.fecha_inicio) = :anio
            GROUP BY p.id, s.nombre, p.monto_prestado, p.tasa_interes, p.plazo_meses, p.fecha_inicio, p.estado
            ORDER BY p.id DESC
            """
            with motor.connect() as conn:
                df_rep_p = pd.read_sql(
                    text(query_reporte_mensual),
                    conn,
                    params={"mes": mes_rep, "anio": anio_rep},
                )

            if df_rep_p.empty:
                st.info(
                    "No se registraron prÃ©stamos vigentes o emitidos en el mes"
                    f" {mes_rep}/{anio_rep}."
                )
            else:
                m_cap = df_rep_p["Capital (C$)"].sum()
                m_int_mensual_esperado = df_rep_p[
                    "InterÃ©s Mensual Esperado (C$)"
                ].sum()
                m_int_cobrado_mes = df_rep_p[
                    "InterÃ©s Cobrado en Mes (C$)"
                ].sum()
                pct_cumplimiento = (
                    (m_int_cobrado_mes / m_int_mensual_esperado * 100)
                    if m_int_mensual_esperado > 0
                    else 0.0
                )

                col_r1, col_r2, col_r3, col_r4 = st.columns(4)
                col_r1.metric("ðŸ’µ Total Capital Prestado", f"C$ {m_cap:,.2f}")
                col_r2.metric(
                    "ðŸ“ˆ InterÃ©s Mensual Esperado",
                    f"C$ {m_int_mensual_esperado:,.2f}",
                )
                col_r3.metric(
                    "ðŸ“¥ InterÃ©s Cobrado (Mes)",
                    f"C$ {m_int_cobrado_mes:,.2f}",
                )
                col_r4.metric(
                    "ðŸ“Š Cumplimiento de InterÃ©s",
                    f"{pct_cumplimiento:.1f}%",
                )

                st.markdown("---")
                st.dataframe(df_rep_p, use_container_width=True)

                st.download_button(
                    label=(
                        "ðŸ“¥ Descargar Reporte de PrÃ©stamos"
                        f" ({mes_rep}-{anio_rep})"
                    ),
                    data=to_excel(df_rep_p),
                    file_name=f"reporte_prestamos_{mes_rep}_{anio_rep}.xlsx",
                    mime=(
                        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                    ),
                )

        with tab4:
            st.subheader("Modificar o Eliminar PrÃ©stamo")
            query_edit_p = """
            SELECT p.id, s.nombre || ' - PrÃ©stamo #' || p.id || ' (C$' || p.monto_prestado || ')' as label, 
                   p.socio_id, p.monto_prestado, p.tasa_interes, p.plazo_meses, p.fecha_inicio, p.estado
            FROM prestamos p
            JOIN socios s ON p.socio_id = s.id
            ORDER BY p.id DESC
            """
            with motor.connect() as conn:
                df_edit_p = pd.read_sql(text(query_edit_p), conn)

            if df_edit_p.empty:
                st.info("No hay prÃ©stamos para editar o eliminar.")
            else:
                dict_edit_p = dict(zip(df_edit_p["label"], df_edit_p["id"]))
                prestamo_sel_e = st.selectbox(
                    "Selecciona el PrÃ©stamo:", list(dict_edit_p.keys())
                )
                id_p_sel = dict_edit_p[prestamo_sel_e]
                reg_p = df_edit_p[df_edit_p["id"] == id_p_sel].iloc[0]

                with st.form("form_edit_prestamo"):
                    e_monto_p = st.number_input(
                        "Monto Prestado (C$)",
                        value=float(reg_p["monto_prestado"]),
                        min_value=10.0,
                        step=50.0,
                    )
                    e_tasa_p = st.number_input(
                        "Tasa InterÃ©s (%)",
                        value=float(reg_p["tasa_interes"]),
                        min_value=0.0,
                        step=0.5,
                    )
                    e_plazo_p = st.number_input(
                        "Plazo (Meses)",
                        value=int(reg_p["plazo_meses"]),
                        min_value=1,
                        max_value=36,
                    )
                    f_p_orig = pd.to_datetime(reg_p["fecha_inicio"]).date()
                    e_fecha_p = st.date_input("Fecha Inicio", value=f_p_orig)
                    e_estado_p = st.selectbox(
                        "Estado del PrÃ©stamo",
                        ["Activo", "Saldado", "Cancelado"],
                        index=["Activo", "Saldado", "Cancelado"].index(
                            reg_p["estado"]
                        ),
                    )

                    e_int_m = e_monto_p * (e_tasa_p / 100)
                    e_int_tot = e_int_m * e_plazo_p
                    e_monto_tot = e_monto_p + e_int_tot

                    col_btn1, col_btn2 = st.columns(2)
                    with col_btn1:
                        btn_guardar_p = st.form_submit_button(
                            "ðŸ’¾ Guardar Cambios"
                        )
                    with col_btn2:
                        btn_eliminar_p = st.form_submit_button(
                            "ðŸ—‘ï¸ Eliminar PrÃ©stamo"
                        )

                    if btn_guardar_p:
                        with motor.begin() as conn:
                            conn.execute(
                                text("""
                                UPDATE prestamos
                                SET monto_prestado = :monto, tasa_interes = :tasa, plazo_meses = :plazo,
                                    interes_total = :int_tot, monto_total = :monto_tot, fecha_inicio = :fecha,
                                    estado = :estado, anio = :anio
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
                                    "id": id_p_sel,
                                },
                            )
                        registrar_bitacora(f"EdiciÃ³n de prÃ©stamo ID {id_p_sel}")
                        st.success("Â¡PrÃ©stamo modificado correctamente!")
                        st.rerun()

                    if btn_eliminar_p:
                        with motor.begin() as conn:
                            conn.execute(
                                text("DELETE FROM pagos WHERE prestamo_id = :id"),
                                {"id": id_p_sel},
                            )
                            conn.execute(
                                text("DELETE FROM prestamos WHERE id = :id"),
                                {"id": id_p_sel},
                            )
                        registrar_bitacora(
                            f"EliminaciÃ³n de prÃ©stamo ID {id_p_sel}"
                        )
                        st.warning("PrÃ©stamo eliminado correctamente.")
                        st.rerun()

# ==========================================
# SECCIÃ“N 5: SIMULADOR DE PRÃ‰STAMOS
# ==========================================
elif opcion == "ðŸ§® Simulador de PrÃ©stamos":
    st.title("ðŸ§® Simulador Libre de PrÃ©stamos")
    st.caption(
        "Calculadora previa para estimar amortizaciones sin alterar la base de"
        " datos."
    )

    col1, col2 = st.columns(2)
    with col1:
        sim_monto = st.number_input(
            "Monto a Simular (C$)",
            min_value=100.0,
            value=5000.0,
            step=100.0,
        )
        sim_tasa = st.number_input(
            "Tasa InterÃ©s Mensual (%)", min_value=0.0, value=5.0, step=0.5
        )
    with col2:
        sim_plazo = st.number_input(
            "Plazo en Meses", min_value=1, max_value=48, value=6
        )
        sim_tipo = st.selectbox(
            "MÃ©todo de InterÃ©s",
            [
                "InterÃ©s Simple (Sistemas Comunitarios)",
                "AmortizaciÃ³n Cuota Fija (FrancÃ©s)",
            ],
        )

    st.markdown("---")

    if sim_tipo == "InterÃ©s Simple (Sistemas Comunitarios)":
        int_mensual = sim_monto * (sim_tasa / 100)
        int_total = int_mensual * sim_plazo
        monto_total = sim_monto + int_total
        cuota_mensual = monto_total / sim_plazo

        c1, c2, c3 = st.columns(3)
        c1.metric("ðŸ“Š InterÃ©s Total", f"C$ {int_total:,.2f}")
        c2.metric("ðŸ’µ Total a Pagar", f"C$ {monto_total:,.2f}")
        c3.metric("ðŸ“… Cuota Mensual Fija", f"C$ {cuota_mensual:,.2f}")

        cronograma = []
        for i in range(1, sim_plazo + 1):
            cronograma.append({
                "Mes / Cuota": f"Mes {i}",
                "Abono Capital (C$)": round(sim_monto / sim_plazo, 2),
                "InterÃ©s (C$)": round(int_mensual, 2),
                "Cuota Total (C$)": round(cuota_mensual, 2),
            })
        st.dataframe(pd.DataFrame(cronograma), use_container_width=True)

    else:
        r = sim_tasa / 100
        if r > 0:
            cuota = (
                sim_monto
                * (r * (1 + r) ** sim_plazo)
                / (((1 + r) ** sim_plazo) - 1)
            )
        else:
            cuota = sim_monto / sim_plazo

        cronograma = []
        saldo = sim_monto
        tot_int = 0
        for i in range(1, sim_plazo + 1):
            interes_p = saldo * r
            capital_p = cuota - interes_p
            saldo -= capital_p
            tot_int += interes_p
            cronograma.append({
                "Mes / Cuota": f"Mes {i}",
                "Cuota Fija (C$)": round(cuota, 2),
                "InterÃ©s (C$)": round(interes_p, 2),
                "Abono Capital (C$)": round(capital_p, 2),
                "Saldo Pendiente (C$)": round(max(0, saldo), 2),
            })

        c1, c2, c3 = st.columns(3)
        c1.metric("ðŸ“Š InterÃ©s Total Estimado", f"C$ {tot_int:,.2f}")
        c2.metric("ðŸ’µ Total a Pagar", f"C$ {(sim_monto + tot_int):,.2f}")
        c3.metric("ðŸ“… Cuota Mensual Fija", f"C$ {cuota:,.2f}")

        st.dataframe(pd.DataFrame(cronograma), use_container_width=True)

# ==========================================
# SECCIÃ“N 6: REGISTRO DE PAGOS DE PRÃ‰STAMOS
# ==========================================
elif opcion == "ðŸ“– Pagos de PrÃ©stamos":
    st.title("ðŸ“– Registro de Abonos y Pagos")

    tab1, tab2, tab3 = st.tabs(
        ["âž• Registrar Abono", "ðŸ“œ Historial de Pagos", "âœï¸ Editar / Borrar Pago"]
    )

    with tab1:
        query_activos = """
        SELECT p.id, s.nombre || ' - PrÃ©stamo #' || p.id || ' (C$' || p.monto_prestado || ' capital)' as label, 
               p.monto_prestado, p.interes_total, p.plazo_meses, p.monto_total, s.nombre as socio_nombre
        FROM prestamos p
        JOIN socios s ON p.socio_id = s.id
        WHERE p.estado = 'Activo'
        """
        with motor.connect() as conn:
            df_prestamos_act = pd.read_sql(text(query_activos), conn)

        if df_prestamos_act.empty:
            st.info("No hay prÃ©stamos activos pendientes de pago.")
        else:
            dict_prestamos = dict(
                zip(df_prestamos_act["label"], df_prestamos_act["id"])
            )
            
            # Formulario de registro de pago
            with st.form("form_pago", clear_on_submit=True):
                prestamo_sel = st.selectbox(
                    "Selecciona el PrÃ©stamo *", list(dict_prestamos.keys())
                )
                p_id = dict_prestamos[prestamo_sel]
                datos_p = df_prestamos_act[
                    df_prestamos_act["id"] == p_id
                ].iloc[0]

                # Calcular estado actual del capital prestado
                with motor.connect() as conn:
                    df_cap_actual = pd.read_sql(
                        text(
                            "SELECT COALESCE(SUM(monto_capital), 0) as"
                            " cap_pagado, COALESCE(SUM(monto_pagado), 0) as"
                            " tot_pagado FROM pagos WHERE prestamo_id = :p_id"
                        ),
                        conn,
                        params={"p_id": p_id},
                    )

                capital_pagado_prev = float(df_cap_actual["cap_pagado"].iloc[0])
                capital_pendiente = (
                    float(datos_p["monto_prestado"]) - capital_pagado_prev
                )

                interes_mensual_est = round(
                    float(datos_p["interes_total"]) / int(datos_p["plazo_meses"]),
                    2,
                )
                capital_mensual_est = round(
                    float(datos_p["monto_prestado"]) / int(datos_p["plazo_meses"]),
                    2,
                )
                cuota_completa_est = capital_mensual_est + interes_mensual_est

                tipo_pago = st.selectbox(
                    "Tipo de Abono",
                    [
                        "Completo (Cuota Mensual)",
                        "Solo InterÃ©s",
                        "Abono a Capital",
                        "CancelaciÃ³n Total Anticipada",
                    ],
                )

                if tipo_pago == "Completo (Cuota Mensual)":
                    monto_sugerido = cuota_completa_est
                elif tipo_pago == "Solo InterÃ©s":
                    monto_sugerido = interes_mensual_est
                elif tipo_pago == "Abono a Capital":
                    monto_sugerido = capital_mensual_est
                else:
                    monto_sugerido = max(0.0, capital_pendiente)

                st.caption(
                    "ðŸ’¡ **Capital pendiente actual de este prÃ©stamo:** C$"
                    f" {capital_pendiente:,.2f}"
                )

                monto_pago = st.number_input(
                    "Monto del Pago/Abono (C$) *",
                    min_value=1.0,
                    value=float(monto_sugerido),
                    step=10.0,
                )
                fecha_pago = st.date_input("Fecha del Pago", datetime.now())
                btn_pago = st.form_submit_button("Registrar Pago")

            # Procesamiento tras enviar el formulario
            if btn_pago:
                if tipo_pago == "Completo (Cuota Mensual)":
                    if monto_pago >= interes_mensual_est:
                        m_interes = interes_mensual_est
                        m_capital = monto_pago - m_interes
                    else:
                        m_interes = monto_pago
                        m_capital = 0.0
                    tipo_db = "Completo"
                elif tipo_pago == "Solo InterÃ©s":
                    m_interes = monto_pago
                    m_capital = 0.0
                    tipo_db = "InterÃ©s"
                else:
                    m_capital = monto_pago
                    m_interes = 0.0
                    tipo_db = (
                        "Capital" if tipo_pago == "Abono a Capital" else "CancelaciÃ³n"
                    )

                with motor.begin() as conn:
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
                            "tipo": tipo_db,
                        },
                    )
                    pago_id_nuevo = res_p.fetchone()[0]

                    # Verificar si el capital se ha liquidado totalmente
                    df_total_p = pd.read_sql(
                        text(
                            "SELECT COALESCE(SUM(monto_capital), 0) as"
                            " cap_sum, COALESCE(SUM(monto_pagado), 0) as"
                            " tot_sum FROM pagos WHERE prestamo_id = :p_id"
                        ),
                        conn,
                        params={"p_id": p_id},
                    )
                    cap_pagado_total = float(df_total_p["cap_sum"].iloc[0])
                    tot_pagado_total = float(df_total_p["tot_sum"].iloc[0])

                    es_saldado = (
                        cap_pagado_total >= float(datos_p["monto_prestado"])
                    ) or (
                        tot_pagado_total >= float(datos_p["monto_total"])
                    )

                    if es_saldado or tipo_pago == "CancelaciÃ³n Total Anticipada":
                        conn.execute(
                            text(
                                "UPDATE prestamos SET estado = 'Saldado'"
                                " WHERE id = :p_id"
                            ),
                            {"p_id": p_id},
                        )
                        registrar_bitacora(
                            f"PrÃ©stamo ID {p_id} de"
                            f" {datos_p['socio_nombre']} saldado / cancelado"
                            " anticipadamente."
                        )
                        st.balloons()
                        st.success(
                            "ðŸŽ‰ Â¡El prÃ©stamo ha sido cancelado/saldado"
                            " completamente!"
                        )
                    else:
                        registrar_bitacora(
                            f"Abono de C$ {monto_pago} (Cap: C$"
                            f" {m_capital}, Int: C$ {m_interes}) para"
                            f" prÃ©stamo ID {p_id}"
                        )
                        st.success(
                            "Abono registrado: C$"
                            f" {m_capital:,.2f} a Capital y C$"
                            f" {m_interes:,.2f} a InterÃ©s."
                        )

                capital_restante_despues = max(
                    0.0,
                    float(datos_p["monto_prestado"]) - (capital_pagado_prev + m_capital),
                )

                st.markdown("---")
                st.subheader("ðŸ§¾ Recibo Oficial de Pago Generado")
                df_recibo = pd.DataFrame([{
                    "ID Comprobante": f"REC-{pago_id_nuevo:05d}",
                    "Fecha Pago": str(fecha_pago),
                    "Socio": datos_p["socio_nombre"],
                    "PrÃ©stamo Ref.": f"PrÃ©stamo #{p_id}",
                    "Monto Pagado": f"C$ {monto_pago:,.2f}",
                    "Abono Capital": f"C$ {m_capital:,.2f}",
                    "Abono InterÃ©s": f"C$ {m_interes:,.2f}",
                    "Capital Pendiente": f"C$ {capital_restante_despues:,.2f}",
                }])
                st.dataframe(df_recibo, use_container_width=True)

                # CORRECCIÃ“N: BotÃ³n de descarga fuera del bloque st.form(...)
                st.download_button(
                    label="ðŸ“„ Descargar Recibo Oficial (Excel)",
                    data=to_excel(df_recibo),
                    file_name=(
                        f"recibo_pago_{pago_id_nuevo}_"
                        f"{datetime.now().strftime('%Y%m%d')}.xlsx"
                    ),
                    mime=(
                        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                    ),
                )

    with tab2:
        st.subheader("Historial de Pagos Recibidos")
        query_pagos = """
        SELECT pg.id as "ID", s.nombre as "Socio", pg.prestamo_id as "ID PrÃ©stamo", 
               pg.monto_pagado as "Monto Total Pagado (C$)", COALESCE(pg.monto_capital, 0.00) as "Abono Capital (C$)", 
               COALESCE(pg.monto_interes, 0.00) as "Abono InterÃ©s (C$)", pg.tipo as "Tipo", pg.fecha as "Fecha"
        FROM pagos pg
        JOIN prestamos p ON pg.prestamo_id = p.id
        JOIN socios s ON p.socio_id = s.id
        ORDER BY pg.id DESC
        """
        with motor.connect() as conn:
            df_pagos_hist = pd.read_sql(text(query_pagos), conn)

        st.dataframe(df_pagos_hist, use_container_width=True)

        if not df_pagos_hist.empty:
            st.download_button(
                label="ðŸ“¥ Exportar Pagos a Excel",
                data=to_excel(df_pagos_hist),
                file_name=(
                    f"reporte_pagos_{datetime.now().strftime('%Y%m%d')}.xlsx"
                ),
                mime=(
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                ),
            )

    with tab3:
        st.subheader("Editar o Eliminar un Pago")
        query_edit_pg = """
        SELECT pg.id, s.nombre || ' - Pago #' || pg.id || ' (C$' || pg.monto_pagado || ')' as label, 
               pg.monto_pagado, COALESCE(pg.monto_capital, 0.00) as monto_capital, 
               COALESCE(pg.monto_interes, 0.00) as monto_interes, pg.tipo, pg.fecha, pg.prestamo_id
        FROM pagos pg
        JOIN prestamos p ON pg.prestamo_id = p.id
        JOIN socios s ON p.socio_id = s.id
        ORDER BY pg.id DESC
        """
        with motor.connect() as conn:
            df_edit_pg = pd.read_sql(text(query_edit_pg), conn)

        if df_edit_pg.empty:
            st.info("No hay pagos para editar.")
        else:
            dict_edit_pg = dict(zip(df_edit_pg["label"], df_edit_pg["id"]))
            pago_sel_e = st.selectbox(
                "Selecciona el Pago:", list(dict_edit_pg.keys())
            )
            id_pg_sel = dict_edit_pg[pago_sel_e]
            reg_pg = df_edit_pg[df_edit_pg["id"] == id_pg_sel].iloc[0]

            with st.form("form_edit_pago"):
                e_monto_pg = st.number_input(
                    "Monto Total Pagado (C$)",
                    value=float(reg_pg["monto_pagado"]),
                    min_value=1.0,
                    step=10.0,
                )
                e_cap_pg = st.number_input(
                    "Monto Aportado a Capital (C$)",
                    value=float(reg_pg["monto_capital"] or 0.0),
                    min_value=0.0,
                    step=10.0,
                )
                e_int_pg = st.number_input(
                    "Monto Aportado a InterÃ©s (C$)",
                    value=float(reg_pg["monto_interes"] or 0.0),
                    min_value=0.0,
                    step=10.0,
                )

                tipos_validos = ["Capital", "InterÃ©s", "Completo", "CancelaciÃ³n"]
                tipo_actual = (
                    reg_pg["tipo"] if reg_pg["tipo"] in tipos_validos else "Completo"
                )
                e_tipo_pg = st.selectbox(
                    "Tipo",
                    tipos_validos,
                    index=tipos_validos.index(tipo_actual),
                )
                f_pg_orig = pd.to_datetime(reg_pg["fecha"]).date()
                e_fecha_pg = st.date_input("Fecha de Pago", value=f_pg_orig)

                c_btn1, c_btn2 = st.columns(2)
                with c_btn1:
                    btn_upd_pg = st.form_submit_button("ðŸ’¾ Guardar Cambios")
                with c_btn2:
                    btn_del_pg = st.form_submit_button("ðŸ—‘ï¸ Eliminar Pago")

                if btn_upd_pg:
                    with motor.begin() as conn:
                        conn.execute(
                            text(
                                "UPDATE pagos SET monto_pagado = :monto,"
                                " monto_capital = :cap, monto_interes = :int,"
                                " tipo = :tipo, fecha = :fecha WHERE id = :id"
                            ),
                            {
                                "monto": e_monto_pg,
                                "cap": e_cap_pg,
                                "int": e_int_pg,
                                "tipo": e_tipo_pg,
                                "fecha": str(e_fecha_pg),
                                "id": id_pg_sel,
                            },
                        )
                    registrar_bitacora(f"ActualizaciÃ³n de pago ID {id_pg_sel}")
                    st.success("Â¡Pago actualizado!")
                    st.rerun()

                if btn_del_pg:
                    with motor.begin() as conn:
                        conn.execute(
                            text("DELETE FROM pagos WHERE id = :id"),
                            {"id": id_pg_sel},
                        )
                    registrar_bitacora(f"EliminaciÃ³n de pago ID {id_pg_sel}")
                    st.warning("Pago eliminado.")
                    st.rerun()

# ==========================================
# SECCIÃ“N 7: EGRESOS Y GASTOS OPERATIVOS
# ==========================================
elif opcion == "ðŸ’¸ Egresos y Gastos":
    st.title("ðŸ’¸ Control de Egresos y Gastos Operativos")
    st.caption("Registro de gastos administrativos o imprevistos de la caja.")

    tab1, tab2 = st.tabs(["âž• Registrar Egreso", "ðŸ“œ Historial de Egresos"])

    with tab1:
        with st.form("form_egreso", clear_on_submit=True):
            concepto = st.text_input("Concepto / DescripciÃ³n del Gasto *")
            monto_e = st.number_input(
                "Monto Gastado (C$) *", min_value=1.0, step=10.0
            )
            fecha_e = st.date_input("Fecha del Gasto", datetime.now())
            resp_e = st.text_input("Autorizado / Responsable")
            btn_egreso = st.form_submit_button("Guardar Egreso")

            if btn_egreso:
                if concepto.strip() == "":
                    st.error("El concepto del egreso es obligatorio.")
                else:
                    with motor.begin() as conn:
                        conn.execute(
                            text(
                                "INSERT INTO egresos (concepto, monto, fecha,"
                                " responsable) VALUES (:c, :m, :f, :r)"
                            ),
                            {
                                "c": concepto,
                                "m": monto_e,
                                "f": str(fecha_e),
                                "r": resp_e,
                            },
                        )
                    registrar_bitacora(
                        f"Registro de egreso: {concepto} por C$ {monto_e}"
                    )
                    st.success("Egreso registrado correctamente.")
                    st.rerun()

    with tab2:
        query_e = (
            'SELECT id as "ID", concepto as "Concepto", monto as "Monto (C$)",'
            ' fecha as "Fecha", responsable as "Responsable" FROM egresos'
            " ORDER BY id DESC"
        )
        with motor.connect() as conn:
            df_egresos_h = pd.read_sql(text(query_e), conn)

        st.dataframe(df_egresos_h, use_container_width=True)

        if not df_egresos_h.empty:
            st.download_button(
                label="ðŸ“¥ Exportar Egresos a Excel",
                data=to_excel(df_egresos_h),
                file_name=(
                    f"reporte_egresos_{datetime.now().strftime('%Y%m%d')}.xlsx"
                ),
                mime=(
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                ),
            )

# ==========================================
# SECCIÃ“N 8: ESTADO DE CUENTA
# ==========================================
elif opcion == "ðŸ“œ Estado de Cuenta":
    st.title("ðŸ“œ Estado de Cuenta Individual")
    st.caption(
        "Consulta e imprime la ficha detallada de ahorro y prÃ©stamos por socio."
    )

    with motor.connect() as conn:
        df_socios = pd.read_sql(
            text("SELECT id, nombre FROM socios ORDER BY nombre ASC"), conn
        )

    if df_socios.empty:
        st.warning("No hay socios registrados.")
    else:
        dict_socios = dict(zip(df_socios["nombre"], df_socios["id"]))
        socio_sel = st.selectbox(
            "Selecciona un Socio para generar Estado de Cuenta",
            list(dict_socios.keys()),
        )
        s_id = dict_socios[socio_sel]

        with motor.connect() as conn:
            df_ahorro_socio = pd.read_sql(
                text(
                    "SELECT COALESCE(SUM(monto), 0) as total FROM ahorros WHERE"
                    " socio_id = :id"
                ),
                conn,
                params={"id": s_id},
            )
            total_ahorrado_socio = float(df_ahorro_socio["total"].iloc[0])

            # PrÃ©stamos Activos (Suma estricta del Capital Pendiente real)
            df_prestamo_socio = pd.read_sql(
                text("""
                SELECT COALESCE(SUM(GREATEST(0, p.monto_prestado - COALESCE(pg.total_cap, 0))), 0) as total 
                FROM prestamos p
                LEFT JOIN (
                    SELECT prestamo_id, COALESCE(SUM(monto_capital), 0) as total_cap
                    FROM pagos GROUP BY prestamo_id
                ) pg ON p.id = pg.prestamo_id
                WHERE p.socio_id = :id AND p.estado = 'Activo'
                """),
                conn,
                params={"id": s_id},
            )
            total_prestado_socio = float(df_prestamo_socio["total"].iloc[0])

        st.markdown("---")
        st.markdown(f"## ðŸ›ï¸ Estado de Cuenta - **{socio_sel}**")
        st.markdown(
            "**Fecha de emisiÃ³n:**"
            f" {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        )

        c1, c2 = st.columns(2)
        c1.metric("ðŸ’µ Capital Total Ahorrado", f"C$ {total_ahorrado_socio:,.2f}")
        c2.metric(
            "ðŸ“‰ PrÃ©stamos Activos (Capital Pendiente)",
            f"C$ {total_prestado_socio:,.2f}",
        )

        st.markdown("### ðŸ“œ Detalle de Ahorros")
        with motor.connect() as conn:
            df_ahorros_det = pd.read_sql(
                text(
                    'SELECT fecha as "Fecha", monto as "Monto (C$)", nota as'
                    ' "Nota" FROM ahorros WHERE socio_id = :id ORDER BY fecha'
                    " DESC"
                ),
                conn,
                params={"id": s_id},
            )
        st.dataframe(df_ahorros_det, use_container_width=True)

        st.markdown("### ðŸ¤ Detalle de PrÃ©stamos")
        with motor.connect() as conn:
            df_prestamos_det = pd.read_sql(
                text("""
                SELECT p.id as "ID PrÃ©stamo", p.monto_prestado as "Capital Inicial (C$)", 
                       p.interes_total as "InterÃ©s Total (C$)", p.monto_total as "Total Estimado (C$)", 
                       p.tasa_interes as "Tasa (%)",
                       COALESCE(SUM(pg.monto_capital), 0.00) as "Capital Pagado (C$)", 
                       GREATEST(0.00, (p.monto_prestado - COALESCE(SUM(pg.monto_capital), 0.00))) as "Capital Pendiente (C$)",
                       CASE 
                           WHEN (p.monto_prestado - COALESCE(SUM(pg.monto_capital), 0.00)) <= 0 THEN 'Saldado'
                           ELSE p.estado 
                       END as "Estado",
                       p.fecha_inicio as "Fecha Inicio"
                FROM prestamos p
                LEFT JOIN pagos pg ON p.id = pg.prestamo_id
                WHERE p.socio_id = :id
                GROUP BY p.id, p.monto_prestado, p.interes_total, p.monto_total, p.tasa_interes, p.estado, p.fecha_inicio
                ORDER BY p.id DESC
                """),
                conn,
                params={"id": s_id},
            )
        st.dataframe(df_prestamos_det, use_container_width=True)

        st.markdown("### ðŸ’³ Detalle de Abonos y Cancelaciones de PrÃ©stamos")
        with motor.connect() as conn:
            df_pagos_det = pd.read_sql(
                text("""
                SELECT pg.fecha as "Fecha", pg.prestamo_id as "ID PrÃ©stamo Ref.", 
                       pg.monto_pagado as "Monto Pagado (C$)", 
                       COALESCE(pg.monto_interes, 0.00) as "Abono a InterÃ©s (C$)",
                       COALESCE(pg.monto_capital, 0.00) as "Abono a Capital (C$)", 
                       pg.tipo as "Tipo de Pago / Detalle"
                FROM pagos pg
                JOIN prestamos p ON pg.prestamo_id = p.id
                WHERE p.socio_id = :id
                ORDER BY pg.fecha DESC, pg.id DESC
                """),
                conn,
                params={"id": s_id},
            )

        if df_pagos_det.empty:
            st.info("El socio no registra pagos o abonos a prÃ©stamos.")
        else:
            st.dataframe(df_pagos_det, use_container_width=True)

        if not df_ahorros_det.empty or not df_prestamos_det.empty:
            output_socio = io.BytesIO()
            with pd.ExcelWriter(output_socio, engine="openpyxl") as writer:
                df_ahorros_det.to_excel(
                    writer, index=False, sheet_name="Ahorros"
                )
                df_prestamos_det.to_excel(
                    writer, index=False, sheet_name="Prestamos"
                )
                if not df_pagos_det.empty:
                    df_pagos_det.to_excel(
                        writer, index=False, sheet_name="Abonos_Prestamos"
                    )
            output_socio.seek(0)

            st.download_button(
                label=(
                    "ðŸ“¥ Imprimir / Descargar Estado de Cuenta de"
                    f" {socio_sel} (Excel)"
                ),
                data=output_socio.getvalue(),
                file_name=(
                    f"estado_cuenta_{socio_sel.replace(' ', '_')}_"
                    f"{datetime.now().strftime('%Y%m%d')}.xlsx"
                ),
                mime=(
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                ),
            )

# ==========================================
# SECCIÃ“N 9: LIQUIDACIÃ“N ANUAL DE SOCIOS (PONDERADA MES A MES)
# ==========================================
elif opcion == "ðŸŽ‰ LiquidaciÃ³n Anual":
    st.title("ðŸŽ‰ CÃ¡lculo de LiquidaciÃ³n AutomÃ¡tica de Fin de AÃ±o")
    st.caption(
        "Reparto transparente del capital acumulado e intereses repartidos"
        " segÃºn el tiempo real de permanencia de los ahorros mes a mes."
    )

    col_l1, col_l2 = st.columns(2)
    with col_l1:
        anio_liq = st.number_input(
            "Seleccionar AÃ±o de LiquidaciÃ³n:",
            min_value=2020,
            max_value=2100,
            value=datetime.now().year,
            key="anio_liq_input",
        )
    with col_l2:
        meses_etiquetas = [
            'Ene', 'Feb', 'Mar', 'Abr', 'May', 'Jun', 'Jul', 'Ago', 'Sep', 'Oct', 'Nov', 'Dic'
        ]
        mes_corte = st.selectbox(
            "Mes de Corte (ProyecciÃ³n):",
            list(range(1, 13)),
            index=11,
            format_func=lambda x: f"Mes {x} ({meses_etiquetas[x-1]})",
        )

    with motor.connect() as conn:
        df_tot_ahorro = pd.read_sql(
            text(
                "SELECT COALESCE(SUM(monto), 0) as total FROM ahorros WHERE"
                " EXTRACT(YEAR FROM fecha) = :a AND EXTRACT(MONTH FROM fecha) <="
                " :m"
            ),
            conn,
            params={"a": anio_liq, "m": mes_corte},
        )
        gran_total_ahorrado = float(df_tot_ahorro["total"].iloc[0])

        df_tot_intereses = pd.read_sql(
            text(
                "SELECT COALESCE(SUM(COALESCE(monto_interes, 0)), 0) as total"
                " FROM pagos WHERE EXTRACT(YEAR FROM fecha) = :a AND"
                " EXTRACT(MONTH FROM fecha) <= :m"
            ),
            conn,
            params={"a": anio_liq, "m": mes_corte},
        )
        total_intereses_ganados = float(df_tot_intereses["total"].iloc[0])

        df_tot_egresos = pd.read_sql(
            text(
                "SELECT COALESCE(SUM(monto), 0) as total FROM egresos WHERE"
                " EXTRACT(YEAR FROM fecha) = :a AND EXTRACT(MONTH FROM fecha) <="
                " :m"
            ),
            conn,
            params={"a": anio_liq, "m": mes_corte},
        )
        total_gastos = float(df_tot_egresos["total"].iloc[0])

    utilidad_neta = total_intereses_ganados - total_gastos

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("ðŸ’µ Fondo Total Ahorrado", f"C$ {gran_total_ahorrado:,.2f}")
    c2.metric("ðŸ“ˆ Intereses Ganados", f"C$ {total_intereses_ganados:,.2f}")
    c3.metric("ðŸ’¸ Egresos de Caja", f"C$ {total_gastos:,.2f}")
    c4.metric("ðŸ›ï¸ Utilidad Neta a Repartir", f"C$ {utilidad_neta:,.2f}")

    st.markdown("---")

    if gran_total_ahorrado == 0:
        st.warning(
            "No hay aportaciones de ahorros registrados en este perÃ­odo para"
            " calcular la liquidaciÃ³n."
        )
    else:
        query_ahorros_mes = """
        SELECT s.id as socio_id, s.nombre as socio, EXTRACT(MONTH FROM a.fecha)::INTEGER as mes, SUM(a.monto) as monto_mes
        FROM socios s
        JOIN ahorros a ON s.id = a.socio_id
        WHERE s.estado = 'Activo' AND EXTRACT(YEAR FROM a.fecha) = :a AND EXTRACT(MONTH FROM a.fecha) <= :m
        GROUP BY s.id, s.nombre, EXTRACT(MONTH FROM a.fecha)
        """
        with motor.connect() as conn:
            df_a_mes = pd.read_sql(
                text(query_ahorros_mes),
                conn,
                params={"a": anio_liq, "m": mes_corte},
            )
            df_socios_act = pd.read_sql(
                text(
                    "SELECT id as socio_id, nombre as socio FROM socios WHERE"
                    " estado = 'Activo' ORDER BY nombre ASC"
                ),
                conn,
            )

        meses_nombres = {
            1: "Ene", 2: "Feb", 3: "Mar", 4: "Abr", 5: "May", 6: "Jun",
            7: "Jul", 8: "Ago", 9: "Sep", 10: "Oct", 11: "Nov", 12: "Dic"
        }

        if not df_a_mes.empty:
            df_pivot = df_a_mes.pivot(
                index="socio_id", columns="mes", values="monto_mes"
            ).fillna(0)
        else:
            df_pivot = pd.DataFrame()

        for m in range(1, 13):
            if m not in df_pivot.columns:
                df_pivot[m] = 0.0

        df_liq_base = df_socios_act.merge(
            df_pivot, on="socio_id", how="left"
        ).fillna(0)

        df_liq_base["Ahorro_Ponderado"] = 0.0
        df_liq_base["Ahorro_Total"] = 0.0

        for m in range(1, mes_corte + 1):
            meses_permanencia = mes_corte - m + 1
            df_liq_base["Ahorro_Ponderado"] += df_liq_base[m] * meses_permanencia
            df_liq_base["Ahorro_Total"] += df_liq_base[m]

        total_ponderado_general = df_liq_base["Ahorro_Ponderado"].sum()

        if total_ponderado_general > 0:
            df_liq_base["ParticipaciÃ³n (%)"] = (
                df_liq_base["Ahorro_Ponderado"] / total_ponderado_general
            ) * 100
        else:
            df_liq_base["ParticipaciÃ³n (%)"] = 0.0

        df_liq_base["Ganancia Neta (C$)"] = (
            df_liq_base["ParticipaciÃ³n (%)"] / 100
        ) * utilidad_neta
        df_liq_base["Total a Entregar (C$)"] = (
            df_liq_base["Ahorro_Total"] + df_liq_base["Ganancia Neta (C$)"]
        )

        cols_meses_rename = {m: meses_nombres[m] for m in range(1, 13)}
        df_display_liq = df_liq_base.rename(columns=cols_meses_rename)

        st.subheader("ðŸ“… Detalle de Ahorros Mensuales y PonderaciÃ³n")

        df_ui = df_display_liq.copy()
        for m_nom in meses_nombres.values():
            df_ui[m_nom] = df_ui[m_nom].map("C$ {:,.2f}".format)

        df_ui["Ahorro_Total"] = df_ui["Ahorro_Total"].map("C$ {:,.2f}".format)
        df_ui["ParticipaciÃ³n (%)"] = df_ui["ParticipaciÃ³n (%)"].map(
            "{:,.2f}%".format
        )
        df_ui["Ganancia Neta (C$)"] = df_ui["Ganancia Neta (C$)"].map(
            "C$ {:,.2f}".format
        )
        df_ui["Total a Entregar (C$)"] = df_ui["Total a Entregar (C$)"].map(
            "C$ {:,.2f}".format
        )

        df_ui = df_ui.rename(columns={
            "socio_id": "ID",
            "socio": "Socio",
            "Ahorro_Total": "Capital Total Ahorrado (C$)",
        })

        columnas_ordenadas = (
            ["ID", "Socio"]
            + list(meses_nombres.values())
            + [
                "Capital Total Ahorrado (C$)",
                "ParticipaciÃ³n (%)",
                "Ganancia Neta (C$)",
                "Total a Entregar (C$)",
            ]
        )

        st.dataframe(df_ui[columnas_ordenadas], use_container_width=True)

        st.download_button(
            label="ðŸ“¥ Exportar Tabla Completa de LiquidaciÃ³n a Excel",
            data=to_excel(df_display_liq),
            file_name=(
                f"liquidacion_anual_{anio_liq}_"
                f"{datetime.now().strftime('%Y%m%d')}.xlsx"
            ),
            mime=(
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            ),
        )

        st.success(
            "â„¹ï¸ **CÃ¡lculo Equitativo Aplicado:** Los rendimientos se"
            " distribuyen considerando tanto el monto ahorrado como los meses"
            " que dicho capital permaneciÃ³ en la caja social (PonderaciÃ³n Mes"
            " a Mes)."
        )

# ==========================================
# SECCIÃ“N 10: CIERRE MENSUAL Y REINICIO ANUAL
# ==========================================
elif opcion == "ðŸ“… Cierre Mensual y Anual":
    st.title("ðŸ“… MÃ³dulo de Cierre Mensual y Anual")
    st.caption("Control mensual de caja e historial de liquidaciones cerradas.")

    tab1, tab2 = st.tabs(["ðŸ“… Cierre Mensual", "ðŸ”„ Reinicio de Ciclo Anual"])

    with tab1:
        st.subheader("Resumen Mensual")
        col_m1, col_m2 = st.columns(2)
        with col_m1:
            mes_sel = st.selectbox(
                "Seleccionar Mes",
                list(range(1, 13)),
                index=datetime.now().month - 1,
            )
        with col_m2:
            anio_sel = st.number_input(
                "Seleccionar AÃ±o",
                min_value=2020,
                max_value=2100,
                value=datetime.now().year,
            )

        query_mensual_ahorro = """
        SELECT COALESCE(SUM(monto), 0) as total FROM ahorros
        WHERE EXTRACT(MONTH FROM fecha) = :mes AND EXTRACT(YEAR FROM fecha) = :anio
        """
        query_mensual_pagos = """
        SELECT COALESCE(SUM(monto_pagado), 0) as total FROM pagos
        WHERE EXTRACT(MONTH FROM fecha) = :mes AND EXTRACT(YEAR FROM fecha) = :anio
        """

        with motor.connect() as conn:
            tot_ahorro_m = float(
                pd.read_sql(
                    text(query_mensual_ahorro),
                    conn,
                    params={"mes": mes_sel, "anio": anio_sel},
                )["total"].iloc[0]
            )
            tot_pagos_m = float(
                pd.read_sql(
                    text(query_mensual_pagos),
                    conn,
                    params={"mes": mes_sel, "anio": anio_sel},
                )["total"].iloc[0]
            )

        st.metric(
            f"ðŸ’µ Ahorros del Mes ({mes_sel}/{anio_sel})",
            f"C$ {tot_ahorro_m:,.2f}",
        )
        st.metric(
            "ðŸ“¥ Pagos/Cobros Recibidos en el Mes"
            f" ({mes_sel}/{anio_sel})",
            f"C$ {tot_pagos_m:,.2f}",
        )

    with tab2:
        st.subheader("âš ï¸ Cerrar AÃ±o Lectivo y Reiniciar Ciclo")
        st.warning(
            "Al ejecutar el Cierre Anual, se registrarÃ¡ el resumen en el"
            " historial. Los saldos de ahorro, pagos y prÃ©stamos se reiniciarÃ¡n"
            " para empezar un nuevo ciclo manteniendo los socios activos."
        )

        anio_cierre = st.number_input(
            "AÃ±o a Cerrar",
            min_value=2020,
            max_value=2100,
            value=datetime.now().year,
            key="cierre_anio",
        )

        if st.button("ðŸš€ Ejecutar Cierre y Reiniciar AÃ±o"):
            with motor.connect() as conn:
                df_tot_a = pd.read_sql(
                    text("SELECT COALESCE(SUM(monto), 0) as total FROM ahorros"),
                    conn,
                )
                tot_a = float(df_tot_a["total"].iloc[0])

                df_tot_i = pd.read_sql(
                    text(
                        "SELECT COALESCE(SUM(COALESCE(monto_interes, 0)), 0) as"
                        " total FROM pagos"
                    ),
                    conn,
                )
                tot_i = float(df_tot_i["total"].iloc[0])

            with motor.begin() as conn:
                conn.execute(
                    text(
                        "INSERT INTO cierres_anuales (anio, total_ahorrado,"
                        " total_intereses) VALUES (:anio, :tot_a, :tot_i)"
                    ),
                    {"anio": anio_cierre, "tot_a": tot_a, "tot_i": tot_i},
                )
                conn.execute(text("DELETE FROM pagos;"))
                conn.execute(text("DELETE FROM prestamos;"))
                conn.execute(text("DELETE FROM ahorros;"))
                conn.execute(text("DELETE FROM egresos;"))

            registrar_bitacora(
                f"Ejecutado Cierre Anual correspondiente al aÃ±o {anio_cierre}"
            )
            st.success(
                f"Â¡El aÃ±o {anio_cierre} ha sido cerrado correctamente! El"
                " sistema estÃ¡ listo para el nuevo ciclo."
            )
            st.rerun()

    st.markdown("---")
    st.subheader("ðŸ“š Historial de Cierres Anuales")
    with motor.connect() as conn:
        df_hist_cierres = pd.read_sql(
            text(
                'SELECT id as "ID", anio as "AÃ±o", total_ahorrado as "Total'
                ' Ahorrado (C$)", total_intereses as "Intereses (C$)",'
                ' fecha_cierre as "Fecha de Cierre" FROM cierres_anuales ORDER'
                " BY anio DESC"
            ),
            conn,
        )
    st.dataframe(df_hist_cierres, use_container_width=True)

# ==========================================
# SECCIÃ“N 11: BITÃCORA DE AUDITORÃA
# ==========================================
elif opcion == "ðŸ›¡ï¸ BitÃ¡cora de AuditorÃ­a":
    st.title("ðŸ›¡ï¸ BitÃ¡cora y Registro de Movimientos del Sistema")
    st.caption(
        "Registro de auditorÃ­a de todas las acciones y modificaciones"
        " realizadas por los administradores."
    )

    with motor.connect() as conn:
        df_bit = pd.read_sql(
            text(
                'SELECT id as "ID", fecha as "Fecha y Hora", usuario as'
                ' "Usuario", accion as "DescripciÃ³n" FROM bitacora'
                " ORDER BY id DESC LIMIT 500"
            ),
            conn,
        )

    if not df_bit.empty:
        filtro_bit = st.text_input(
            "ðŸ” Buscar en la bitÃ¡cora (ej: 'EliminaciÃ³n', 'socio', 'Abono'):"
        )
        if filtro_bit.strip() != "":
            df_bit = df_bit[
                df_bit["DescripciÃ³n"].str.contains(
                    filtro_bit, case=False, na=False
                )
            ]

        st.dataframe(df_bit, use_container_width=True)

        st.download_button(
            label="ðŸ“¥ Exportar BitÃ¡cora a Excel",
            data=to_excel(df_bit),
            file_name=(
                f"reporte_bitacora_{datetime.now().strftime('%Y%m%d')}.xlsx"
            ),
            mime=(
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            ),
    )
