"""Validador de reportes de estadística agraria.

Compara cada cifra del reporte con los rangos históricos agregados de
datos/referencia/. Todas las cuentas las hace Python; el LLM solo redacta.

Niveles:
    error   la cifra es imposible o falta un dato obligatorio: no se consolida
    alerta  la cifra es rara: hay que confirmarla con el productor
    ok      dentro de lo esperado
"""

from dataclasses import asdict, dataclass, field
from functools import lru_cache
from pathlib import Path

import pandas as pd

from sectorista.catalogo import MESES, normalizar_cultivo, normalizar_departamento

REFERENCIA = Path(__file__).resolve().parents[1] / "datos" / "referencia"

# Cultivos cuyo rendimiento MENSUAL en la base es confiable (muchas observaciones).
# Para el resto se usa el rendimiento anual repartido según la estacionalidad.
N_MIN_RENDIMIENTO_MENSUAL = 300


@dataclass
class Alerta:
    nivel: str
    campo: str
    mensaje: str
    valor: float | None = None
    rango: tuple | None = None
    sugerencia: dict = field(default_factory=dict)

    def a_dict(self):
        return asdict(self)


@dataclass
class Reporte:
    cultivo: str | None = None
    departamento: str | None = None
    mes: int | None = None
    anio: int | None = None
    superficie_cosechada_ha: float | None = None
    produccion_t: float | None = None
    precio_s_kg: float | None = None
    rendimiento_kg_ha: float | None = None  # solo si el técnico lo dicta aparte
    lugar: str | None = None  # provincia, distrito o agencia, como texto libre

    @classmethod
    def desde_dict(cls, d):
        campos = {k: d.get(k) for k in cls.__dataclass_fields__}
        r = cls(**campos)
        r.cultivo = normalizar_cultivo(r.cultivo) if r.cultivo else None
        r.departamento = normalizar_departamento(r.departamento) if r.departamento else None
        for k in ["superficie_cosechada_ha", "produccion_t", "precio_s_kg", "rendimiento_kg_ha"]:
            v = getattr(r, k)
            setattr(r, k, float(v) if v not in (None, "") else None)
        r.mes = int(r.mes) if r.mes not in (None, "") else None
        r.anio = int(r.anio) if r.anio not in (None, "") else None
        return r


@lru_cache(maxsize=1)
def referencia():
    rangos = pd.read_csv(REFERENCIA / "rangos.csv")
    estac = pd.read_csv(REFERENCIA / "estacionalidad.csv")
    return rangos, estac


def _rango(cultivo, departamento, variable):
    """Rango del departamento si existe; si no, el nacional. Devuelve (fila, ámbito)."""
    rangos, _ = referencia()
    g = rangos[(rangos.cultivo == cultivo) & (rangos.variable == variable)]
    fila = g[g.departamento == departamento]
    if len(fila):
        return fila.iloc[0], departamento
    fila = g[g.departamento == "Nacional"]
    if len(fila):
        return fila.iloc[0], "Nacional"
    return None, None


def _estacionalidad(cultivo, departamento, mes):
    _, estac = referencia()
    g = estac[(estac.cultivo == cultivo) & (estac.departamento == departamento)]
    if g.empty:
        return None, None
    fila = g[g.mes == mes]
    return g, (fila.iloc[0] if len(fila) else None)


def _fmt(x, dec=0):
    return f"{x:,.{dec}f}"


def _corregir_escala(valor, bajo, alto, factores):
    """Si multiplicar por un factor deja el valor en rango, probablemente es un error de unidades."""
    for f in factores:
        if bajo <= valor * f <= alto:
            return f
    return None


def validar(reporte):
    if isinstance(reporte, dict):
        reporte = Reporte.desde_dict(reporte)
    r = reporte
    alertas = []

    # 1. Datos obligatorios y catálogo
    if not r.cultivo:
        alertas.append(Alerta("error", "cultivo", "No se reconoce el cultivo. Repite el nombre."))
    if not r.departamento:
        alertas.append(Alerta("error", "departamento", "No se reconoce el departamento."))
    if not r.mes or not 1 <= r.mes <= 12:
        alertas.append(Alerta("error", "mes", "Falta el mes del reporte."))
    if r.produccion_t is None:
        alertas.append(Alerta("error", "produccion_t", "Falta la producción en toneladas."))
    if any(a.nivel == "error" for a in alertas):
        return alertas

    nombre_mes = MESES[r.mes - 1]
    rangos, _ = referencia()
    tipo = rangos.loc[rangos.cultivo == r.cultivo, "tipo"].iloc[0]

    # 2. Estacionalidad: ¿se cosecha este cultivo aquí en este mes?
    serie, est = _estacionalidad(r.cultivo, r.departamento, r.mes)
    if serie is None:
        alertas.append(Alerta(
            "alerta", "cultivo",
            f"No hay registro histórico de {r.cultivo.lower()} en {r.departamento}. Confirma el cultivo y el lugar."))
    elif est is not None and est.participacion_max < 0.01 and r.produccion_t > 0:
        alertas.append(Alerta(
            "alerta", "mes",
            f"Casi nunca se cosecha {r.cultivo.lower()} en {r.departamento} en {nombre_mes}: "
            f"en {int(est.anios)} años ese mes nunca pasó del {est.participacion_max:.1%} de la cosecha anual.",
            valor=float(est.participacion_max)))

    # 3. Rendimiento implícito = producción / superficie
    if r.superficie_cosechada_ha:
        rend = r.produccion_t * 1000 / r.superficie_cosechada_ha
        mensual, ambito = _rango(r.cultivo, r.departamento, "rendimiento_kg_ha")
        nac_mensual, _ = _rango(r.cultivo, "Nacional", "rendimiento_kg_ha")
        if nac_mensual is not None and nac_mensual.n >= N_MIN_RENDIMIENTO_MENSUAL:
            bajo, alto = mensual.p05, mensual.p95
            min_pl, max_pl = nac_mensual.p01 / 3, nac_mensual.p99 * 2
            base = f"el rango típico de {ambito} es {_fmt(bajo)}–{_fmt(alto)} kg/ha"
        else:
            anual, _ = _rango(r.cultivo, "Nacional", "rendimiento_anual_kg_ha")
            part = est.participacion_media if est is not None else 1 / 12
            part_max = max(est.participacion_max, part) if est is not None else 1 / 6
            bajo, alto = anual.p05 * part * 0.5, anual.p95 * part_max * 1.5
            min_pl, max_pl = 0, anual.p99
            base = (f"para un cultivo {tipo[:-1]} en {nombre_mes} se espera {_fmt(bajo)}–{_fmt(alto)} kg/ha "
                    f"(rendimiento anual típico de {_fmt(anual.p50)} kg/ha repartido según la estacionalidad)")

        if not (min_pl <= rend <= max_pl):
            f = _corregir_escala(rend, bajo, alto, [0.001, 1000, 0.1, 10])
            sug = {"produccion_t": r.produccion_t * f} if f else {}
            pista = (" ¿La producción está en kilos y no en toneladas?" if f == 0.001 else
                     " ¿La producción está en miles de toneladas?" if f == 1000 else "")
            alertas.append(Alerta(
                "error", "produccion_t",
                f"Rendimiento imposible: {_fmt(rend)} kg/ha. {base[0].upper() + base[1:]}.{pista}",
                valor=rend, rango=(bajo, alto), sugerencia=sug))
        elif not (bajo <= rend <= alto):
            alertas.append(Alerta(
                "alerta", "produccion_t",
                f"El rendimiento de {_fmt(rend)} kg/ha está fuera de lo usual: {base}. Confírmalo con el productor.",
                valor=rend, rango=(bajo, alto)))
        else:
            alertas.append(Alerta("ok", "produccion_t", f"Rendimiento de {_fmt(rend)} kg/ha: dentro de lo esperado.",
                                  valor=rend, rango=(bajo, alto)))

        if r.rendimiento_kg_ha and abs(r.rendimiento_kg_ha - rend) / rend > 0.15:
            alertas.append(Alerta(
                "alerta", "rendimiento_kg_ha",
                f"Las cifras no cuadran: {_fmt(r.superficie_cosechada_ha, 1)} ha × {_fmt(r.rendimiento_kg_ha)} kg/ha "
                f"da {_fmt(r.superficie_cosechada_ha * r.rendimiento_kg_ha / 1000, 1)} t, pero se reportaron "
                f"{_fmt(r.produccion_t, 1)} t.",
                valor=r.rendimiento_kg_ha))

    # 4. Precio chacra
    if r.precio_s_kg is not None:
        fila, ambito = _rango(r.cultivo, r.departamento, "precio_s_kg")
        nac, _ = _rango(r.cultivo, "Nacional", "precio_s_kg")
        if fila is not None:
            bajo, alto = fila.p05, fila.p95
            min_pl, max_pl = nac.p01 / 3, nac.p99 * 3
            base = f"en {ambito} el precio chacra usual (2021-2026) es S/ {bajo:.2f}–{alto:.2f} por kg"
            if not (min_pl <= r.precio_s_kg <= max_pl):
                f = _corregir_escala(r.precio_s_kg, bajo, alto, [0.1, 0.01, 10, 0.001])
                sug = {"precio_s_kg": round(r.precio_s_kg * f, 2)} if f else {}
                pista = " ¿Es el precio por tonelada o por saco?" if f == 0.001 else (
                    " ¿Falta o sobra un decimal?" if f else "")
                alertas.append(Alerta("error", "precio_s_kg",
                                      f"Precio imposible: S/ {r.precio_s_kg:.2f} por kg; {base}.{pista}",
                                      valor=r.precio_s_kg, rango=(bajo, alto), sugerencia=sug))
            elif not (bajo <= r.precio_s_kg <= alto):
                alertas.append(Alerta("alerta", "precio_s_kg",
                                      f"Precio fuera de lo usual: S/ {r.precio_s_kg:.2f} por kg; {base}.",
                                      valor=r.precio_s_kg, rango=(bajo, alto)))
            else:
                alertas.append(Alerta("ok", "precio_s_kg",
                                      f"Precio de S/ {r.precio_s_kg:.2f} por kg: dentro de lo esperado.",
                                      valor=r.precio_s_kg, rango=(bajo, alto)))

    return alertas


def estado(alertas):
    niveles = {a.nivel for a in alertas}
    if "error" in niveles:
        return "error"
    if "alerta" in niveles:
        return "alerta"
    return "ok"
