"""Sectorista: el técnico dicta el reporte, el sistema lo estructura y lo valida en el momento."""

import io
import os
import tempfile
import threading
from datetime import date
from pathlib import Path

import pandas as pd
import streamlit as st
from dotenv import load_dotenv

load_dotenv()
try:  # en Streamlit Cloud la clave y la configuración van en Settings > Secrets
    for clave in ["ANTHROPIC_API_KEY", "WHISPER_MODELO", "CLAUDE_MODELO", "LIMITE_LLM_SESION", "LIMITE_LLM_DIARIO"]:
        if clave in st.secrets:
            os.environ[clave] = str(st.secrets[clave])
except Exception:
    pass

from sectorista.catalogo import CULTIVOS, DEPARTAMENTOS, MESES  # noqa: E402
from sectorista.extraer import extraer  # noqa: E402
from sectorista.validar import estado, validar  # noqa: E402

RAIZ = Path(__file__).parent
EJEMPLOS = RAIZ / "datos" / "ejemplos"
COLOR = {"error": "🔴", "alerta": "🟠", "ok": "🟢"}
# Topes del LLM en el demo público: cualquiera puede abrir la URL, así que se limita el gasto
LIMITE_SESION = int(os.getenv("LIMITE_LLM_SESION", "15"))
LIMITE_DIARIO = int(os.getenv("LIMITE_LLM_DIARIO", "150"))
TEXTO_ESTADO = {"error": "No se puede consolidar", "alerta": "Confirmar con el productor", "ok": "Listo para consolidar"}

st.set_page_config(page_title="Sectorista", page_icon="🌾", layout="wide")
st.session_state.setdefault("registros", [])

st.title("🌾 Sectorista")
st.markdown("**El técnico dicta el reporte de cosecha; Sectorista lo pasa al formulario y marca las cifras raras "
            "en el momento, comparándolas con la historia de la estadística agraria.**")

with st.sidebar:
    st.header("Agencia agraria")
    agencia = st.text_input("Agencia", "Agencia Agraria Chulucanas")
    tecnico = st.text_input("Técnico", "Técnico de campo")
    st.divider()
    st.caption("Motores")
    st.write(("🟢 Formulario: Claude (salidas estructuradas), con respaldo por reglas" if os.getenv("ANTHROPIC_API_KEY")
              else "🟢 Formulario: extractor por reglas (sin API key)"))
    if os.getenv("ANTHROPIC_API_KEY"):
        st.caption(f"Tope del demo público: {LIMITE_SESION} reportes con LLM por sesión y {LIMITE_DIARIO} al día.")
    st.write(f"🟢 Whisper `{os.getenv('WHISPER_MODELO', 'small')}` en CPU")
    st.caption("Los rangos de referencia son percentiles agregados por cultivo, departamento y mes. "
               "No contienen registros individuales.")


@st.cache_resource
def _uso_diario():
    """Contador compartido por todas las sesiones del servidor."""
    return {"fecha": None, "n": 0, "lock": threading.Lock()}


def reservar_llm():
    """Devuelve (se_puede_usar, motivo). Aplica el tope por sesión y el tope diario."""
    if not os.getenv("ANTHROPIC_API_KEY"):
        return False, "sin API key"
    if st.session_state.get("llm_sesion", 0) >= LIMITE_SESION:
        return False, f"se llegó al tope de {LIMITE_SESION} reportes con LLM por sesión"
    uso = _uso_diario()
    with uso["lock"]:
        if uso["fecha"] != date.today():
            uso["fecha"], uso["n"] = date.today(), 0
        if uso["n"] >= LIMITE_DIARIO:
            return False, "se llegó al tope diario de uso del LLM en el demo"
        uso["n"] += 1
    st.session_state["llm_sesion"] = st.session_state.get("llm_sesion", 0) + 1
    return True, ""


def mostrar_alertas(alertas):
    for a in alertas:
        st.markdown(f"{COLOR[a.nivel]} {a.mensaje}")


def formulario(datos, clave):
    """Formulario editable con lo que extrajo el sistema."""
    c1, c2, c3 = st.columns(3)
    cultivos = list(CULTIVOS)
    cultivo = c1.selectbox("Cultivo", cultivos, key=f"{clave}_cul",
                           index=cultivos.index(datos["cultivo"]) if datos.get("cultivo") in cultivos else None)
    depto = c2.selectbox("Departamento", DEPARTAMENTOS, key=f"{clave}_dep",
                         index=DEPARTAMENTOS.index(datos["departamento"]) if datos.get("departamento") in DEPARTAMENTOS else None)
    mes = c3.selectbox("Mes", range(1, 13), format_func=lambda m: MESES[m - 1].capitalize(), key=f"{clave}_mes",
                       index=(datos.get("mes") or date.today().month) - 1)
    c4, c5, c6 = st.columns(3)
    ha = c4.number_input("Superficie cosechada (ha)", min_value=0.0, value=datos.get("superficie_cosechada_ha"),
                         key=f"{clave}_ha", step=1.0)
    prod = c5.number_input("Producción (t)", min_value=0.0, value=datos.get("produccion_t"), key=f"{clave}_t", step=1.0)
    precio = c6.number_input("Precio chacra (S/ por kg)", min_value=0.0, value=datos.get("precio_s_kg"),
                             key=f"{clave}_p", step=0.05, format="%.2f")
    lugar = st.text_input("Lugar (provincia, distrito o caserío)", datos.get("lugar") or "", key=f"{clave}_lug")
    return {"cultivo": cultivo, "departamento": depto, "mes": mes, "anio": date.today().year,
            "superficie_cosechada_ha": ha, "produccion_t": prod, "precio_s_kg": precio, "lugar": lugar}


voz, excel, tablero = st.tabs(["🎙️ Reporte por voz", "📄 Validar Excel de la agencia", "📊 Tablero de la agencia"])

# ---------------- 1. Reporte por voz ----------------
with voz:
    izq, der = st.columns([1, 1], gap="large")
    with izq:
        st.subheader("1. Dicta el reporte")
        audio = st.audio_input("Graba: cultivo, lugar, mes, hectáreas cosechadas, producción y precio en chacra")
        ejemplos = sorted(EJEMPLOS.glob("*.wav")) if EJEMPLOS.exists() else []
        if ejemplos:
            elegido = st.selectbox("…o usa un audio de ejemplo", [None] + ejemplos,
                                   format_func=lambda p: "—" if p is None else p.stem.replace("_", " "))
            if elegido:
                st.audio(str(elegido))
        else:
            elegido = None
        texto_manual = st.text_area("…o escribe el reporte (si no hay micrófono)", height=80,
                                    placeholder="Limón en Chulucanas, Piura, marzo. 120 hectáreas cosechadas, "
                                                "240 toneladas, a 1.80 soles el kilo.")

        if st.button("Procesar reporte", type="primary", use_container_width=True):
            texto, info_voz = None, {}
            if audio is not None or elegido:
                from sectorista.transcribir import transcribir

                with st.spinner("Transcribiendo con Whisper…"):
                    if audio is not None:
                        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
                            f.write(audio.getvalue())
                            ruta = f.name
                    else:
                        ruta = str(elegido)
                    texto, info_voz = transcribir(ruta)
            elif texto_manual.strip():
                texto = texto_manual.strip()
            if not texto:
                st.warning("Graba un audio, elige un ejemplo o escribe el reporte.")
            else:
                usar_llm, motivo = reservar_llm()
                with st.spinner("Llenando el formulario…"):
                    datos, info = extraer(texto, usar_claude=usar_llm, motivo=motivo)
                st.session_state["actual"] = {"texto": texto, "datos": datos, "info": {**info_voz, **info}}
                st.session_state["n_reporte"] = st.session_state.get("n_reporte", 0) + 1

        if "actual" in st.session_state:
            act = st.session_state["actual"]
            st.markdown("**Transcripción**")
            st.info(act["texto"])
            motor = act["info"].get("motor")
            if motor == "claude":
                st.caption(f"Formulario llenado por: Claude ({act['info'].get('modelo', '')}, salidas estructuradas)"
                           f" · {act['info']['tokens_entrada']} + {act['info']['tokens_salida']} tokens")
            else:
                motivo = act["info"].get("motivo")
                st.caption("Formulario llenado por: extractor por reglas" + (f" ({motivo})" if motivo else ""))

    with der:
        st.subheader("2. Revisa y valida")
        if "actual" not in st.session_state:
            st.caption("Aquí aparece el formulario lleno y la validación de cada cifra.")
        else:
            act = st.session_state["actual"]
            clave = f"r{st.session_state['n_reporte']}"
            datos = formulario(act["datos"], clave)
            alertas = validar(datos)
            est = estado(alertas)
            st.markdown(f"### {COLOR[est]} {TEXTO_ESTADO[est]}")
            mostrar_alertas(alertas)
            for a in alertas:
                for campo, valor in a.sugerencia.items():
                    if st.button(f"Corregir: usar {valor:,.2f} en {campo.replace('_', ' ')}", key=f"{clave}_{campo}"):
                        st.session_state["actual"]["datos"] = {**datos, campo: valor}
                        st.session_state["n_reporte"] += 1
                        st.rerun()
            if st.button("Registrar en la agencia", disabled=est == "error", use_container_width=True):
                st.session_state["registros"].append({
                    **datos, "estado": est, "agencia": agencia, "tecnico": tecnico,
                    "observaciones": " | ".join(a.mensaje for a in alertas if a.nivel != "ok"),
                })
                st.success("Reporte registrado. Revisa el tablero de la agencia.")

# ---------------- 2. Validar Excel ----------------
COLUMNAS = ["cultivo", "departamento", "lugar", "mes", "superficie_cosechada_ha", "produccion_t", "precio_s_kg"]

with excel:
    st.subheader("Valida el Excel mensual de la agencia antes de enviarlo")
    st.markdown("Hoy los reportes viajan en Excel y los errores aparecen meses después, en el análisis. "
                "Sube el archivo y Sectorista revisa cada fila contra la historia.")
    plantilla = EJEMPLOS / "reporte_agencia_ejemplo.xlsx"
    if plantilla.exists():
        st.download_button("Descargar Excel de ejemplo", plantilla.read_bytes(), file_name=plantilla.name)
    archivo = st.file_uploader("Excel o CSV con las columnas: " + ", ".join(COLUMNAS), type=["xlsx", "csv"])
    if archivo is None and plantilla.exists() and st.toggle("Probar con el Excel de ejemplo"):
        archivo = plantilla
    if archivo is not None:
        nombre = getattr(archivo, "name", str(archivo))
        df = pd.read_csv(archivo) if str(nombre).endswith(".csv") else pd.read_excel(archivo)
        faltan = [c for c in ["cultivo", "departamento", "mes", "produccion_t"] if c not in df.columns]
        if faltan:
            st.error(f"Faltan columnas: {', '.join(faltan)}")
        else:
            res = []
            for _, fila in df.iterrows():
                d = {c: (None if pd.isna(fila.get(c)) else fila.get(c)) for c in COLUMNAS}
                al = validar(d)
                res.append({"estado": f"{COLOR[estado(al)]} {estado(al)}",
                            "observaciones": " | ".join(a.mensaje for a in al if a.nivel != "ok") or "—"})
            salida = pd.concat([pd.DataFrame(res), df], axis=1)
            n = salida["estado"].str.split().str[-1].value_counts()
            m1, m2, m3 = st.columns(3)
            m1.metric("🟢 Listas", int(n.get("ok", 0)))
            m2.metric("🟠 Por confirmar", int(n.get("alerta", 0)))
            m3.metric("🔴 Con error", int(n.get("error", 0)))
            st.dataframe(salida, use_container_width=True, hide_index=True)
            buf = io.BytesIO()
            salida.to_excel(buf, index=False)
            st.download_button("Descargar Excel validado", buf.getvalue(), file_name="reporte_validado.xlsx")

# ---------------- 3. Tablero ----------------
with tablero:
    regs = pd.DataFrame(st.session_state["registros"])
    st.subheader(f"Reportes registrados hoy · {agencia}")
    if regs.empty:
        st.caption("Todavía no hay reportes registrados en esta sesión.")
    else:
        c1, c2, c3 = st.columns(3)
        c1.metric("Reportes", len(regs))
        c2.metric("Confirmados con el productor", int((regs.estado == "alerta").sum()))
        c3.metric("Producción registrada (t)", f"{regs.produccion_t.fillna(0).sum():,.1f}")
        st.dataframe(regs, use_container_width=True, hide_index=True)
