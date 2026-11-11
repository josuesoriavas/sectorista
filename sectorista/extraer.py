"""De la transcripción al formulario.

Claude extrae los campos tal como los dictó el técnico (valor y unidad), con una
salida estructurada validada por Pydantic. Las conversiones de unidades las hace
Python. Si no hay API key o la llamada falla, se usa un extractor por reglas
para que el demo nunca se caiga.
"""

import os
import re
from typing import Literal, Optional

from pydantic import BaseModel, Field

from sectorista.catalogo import (CULTIVOS, DEPARTAMENTOS, MESES, normalizar_cultivo,
                                 normalizar_departamento, sin_tildes)

MODELO = os.getenv("CLAUDE_MODELO", "claude-opus-5-5")
KG_POR_QUINTAL = 46  # quintal usado en el Perú

SISTEMA = """Eres el asistente de un técnico de estadística agraria del Perú.
Recibes la transcripción de un reporte dictado en campo y llenas el formulario.

Reglas:
- Copia las cifras tal como se dijeron, con su unidad. No conviertas unidades ni hagas cuentas.
- Si un dato no se dijo, déjalo vacío. No inventes ni completes con valores típicos.
- "cultivo" y "departamento" van en el nombre más estándar posible (por ejemplo "limón", "Piura").
- "lugar" es la provincia, distrito, caserío o agencia agraria que se mencione.
- Los números dichos con palabras van como número ("dos mil cuatrocientos" = 2400; "uno ochenta" en un precio = 1.80).
- "superficie_cosechada_ha" es la superficie cosechada en hectáreas.
- Si el técnico dice "kilos" para la producción, la unidad es "kilos"; si no dice unidad, "no_dicha".
- En "notas" van observaciones del técnico (plagas, lluvias, heladas, etc.), en una frase corta."""


class ReporteDictado(BaseModel):
    cultivo: Optional[str] = Field(None, description="Cultivo reportado")
    departamento: Optional[str] = Field(None, description="Departamento del Perú")
    lugar: Optional[str] = Field(None, description="Provincia, distrito o agencia agraria")
    mes: Optional[int] = Field(None, description="Mes del reporte, de 1 a 12")
    anio: Optional[int] = Field(None, description="Año del reporte")
    superficie_cosechada_ha: Optional[float] = None
    produccion_valor: Optional[float] = None
    produccion_unidad: Literal["toneladas", "kilos", "quintales", "no_dicha"] = "no_dicha"
    precio_valor: Optional[float] = None
    precio_unidad: Literal["por_kilo", "por_tonelada", "por_quintal", "no_dicha"] = "no_dicha"
    rendimiento_kg_ha: Optional[float] = Field(None, description="Solo si el técnico dicta el rendimiento aparte")
    notas: Optional[str] = None


def a_formulario(d: ReporteDictado):
    """Convierte unidades con Python y devuelve el formulario que recibe el validador."""
    prod = d.produccion_valor
    if prod is not None:
        prod = {"kilos": prod / 1000, "quintales": prod * KG_POR_QUINTAL / 1000}.get(d.produccion_unidad, prod)
    precio = d.precio_valor
    if precio is not None:
        precio = {"por_tonelada": precio / 1000, "por_quintal": precio / KG_POR_QUINTAL}.get(d.precio_unidad, precio)
    return {
        "cultivo": normalizar_cultivo(d.cultivo) or d.cultivo,
        "departamento": normalizar_departamento(d.departamento) or d.departamento,
        "lugar": d.lugar,
        "mes": d.mes, "anio": d.anio,
        "superficie_cosechada_ha": d.superficie_cosechada_ha,
        "produccion_t": round(prod, 3) if prod is not None else None,
        "precio_s_kg": round(precio, 3) if precio is not None else None,
        "rendimiento_kg_ha": d.rendimiento_kg_ha,
        "notas": d.notas,
    }


def extraer_con_claude(texto):
    import anthropic

    client = anthropic.Anthropic()
    respuesta = client.beta.messages.parse(
        model=MODELO,
        max_tokens=2000,
        system=SISTEMA,
        messages=[{"role": "user", "content": f"Transcripción del reporte:\n\n{texto}"}],
        output_format=ReporteDictado,
        output_config={"effort": "low"},
        # Si el modelo declina por un filtro de seguridad, la API reintenta con otro modelo
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
    )
    if respuesta.stop_reason == "refusal" or respuesta.parsed_output is None:
        raise RuntimeError(f"Claude no devolvió el formulario (stop_reason={respuesta.stop_reason})")
    uso = respuesta.usage
    return respuesta.parsed_output, {"tokens_entrada": uso.input_tokens, "tokens_salida": uso.output_tokens}


# ---------- Extractor por reglas (respaldo sin API) ----------

_NUM = r"(\d+(?:[.,]\d+)*)"


def _numero(txt):
    """'2,400' -> 2400 ; '1,80' -> 1.8 ; '2.400' -> 2400 ; '1.80' -> 1.8"""
    txt = txt.strip()
    if re.fullmatch(r"\d{1,3}([.,]\d{3})+", txt):
        return float(re.sub(r"[.,]", "", txt))
    return float(txt.replace(",", "."))


def _buscar_palabra(texto, opciones):
    t = f" {sin_tildes(texto)} "
    halladas = [(len(o), o) for o in opciones if re.search(rf"\b{re.escape(o)}\b", t)]
    return max(halladas)[1] if halladas else None


def extraer_con_reglas(texto):
    t = sin_tildes(texto)
    sinonimos = {s: c for c, sins in CULTIVOS.items() for s in sins}
    cultivo = _buscar_palabra(t, list(sinonimos))
    depto = _buscar_palabra(t, [sin_tildes(d) for d in DEPARTAMENTOS])
    mes = _buscar_palabra(t, MESES)

    sup = re.search(_NUM + r"\s*(?:hectareas|hectarea|ha)\b", t)
    prod = re.search(_NUM + r"\s*(toneladas|tonelada|t|kilos|kilogramos|kg|quintales)\b", t)
    precio = re.search(r"(?:a|precio(?: de)?(?: chacra)?(?: de)?|s/\.?)\s*" + _NUM +
                       r"\s*(?:soles|sol)?\s*(?:el|por|x)?\s*(kilo|kg|tonelada|quintal)?", t)

    # Precio dicho con palabras: "un sol con veinte", "dos soles con 10 céntimos"
    palabras = {"un": 1, "uno": 1, "dos": 2, "tres": 3, "cuatro": 4, "cinco": 5, "seis": 6, "siete": 7,
                "ocho": 8, "nueve": 9, "diez": 10}
    hablado = re.search(r"\b(\d+|un|uno|dos|tres|cuatro|cinco|seis|siete|ocho|nueve|diez)\s+soles?\s+con\s+(\d{1,2})\b", t)
    if hablado and not precio:
        entero = palabras.get(hablado.group(1)) or int(hablado.group(1))
        precio_hablado = entero + int(hablado.group(2)) / 100
    else:
        precio_hablado = None

    unidad = {"kilos": "kilos", "kilogramos": "kilos", "kg": "kilos", "quintales": "quintales"}
    d = ReporteDictado(
        cultivo=sinonimos.get(cultivo) if cultivo else None,
        departamento=depto,
        mes=MESES.index(mes) + 1 if mes else None,
        superficie_cosechada_ha=_numero(sup.group(1)) if sup else None,
        produccion_valor=_numero(prod.group(1)) if prod else None,
        produccion_unidad=unidad.get(prod.group(2), "toneladas") if prod else "no_dicha",
        precio_valor=_numero(precio.group(1)) if precio else precio_hablado,
        precio_unidad={"tonelada": "por_tonelada", "quintal": "por_quintal"}.get(
            precio.group(2) if precio else None, "por_kilo") if (precio or precio_hablado) else "no_dicha",
    )
    return d


def extraer(texto):
    """Devuelve (formulario, info). info dice qué motor se usó y, si aplica, los tokens."""
    if os.getenv("ANTHROPIC_API_KEY"):
        try:
            dictado, uso = extraer_con_claude(texto)
            return a_formulario(dictado), {"motor": "claude", "modelo": MODELO, **uso}
        except Exception as e:  # el demo no se cae: se usa el respaldo por reglas
            return a_formulario(extraer_con_reglas(texto)), {"motor": "reglas", "error": str(e)[:200]}
    return a_formulario(extraer_con_reglas(texto)), {"motor": "reglas", "error": "sin ANTHROPIC_API_KEY"}
