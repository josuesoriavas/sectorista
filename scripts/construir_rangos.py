"""Construye los rangos de referencia agregados que usa el validador.

Lee una base mensual de estadística agraria (cultivo x departamento x mes) y
publica SOLO estadísticas agregadas: percentiles de rendimiento y de precio
chacra, y la participación de cada mes en la cosecha anual. La base cruda no se
sube al repositorio (datos/crudo/ está en .gitignore).

Uso:
    python scripts/construir_rangos.py RUTA_A_LA_BASE.csv

Columnas esperadas en la base: ANIO, NOM_TIPO, NOM_CULTIVO, NOM_DEPARTAMENTO,
COD_MES (01-12; 13 y 14 son totales y se descartan), COSECHA_HA, PRODUCCION_TN,
PRECIO_SOLKG.
"""

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sectorista.catalogo import normalizar_cultivo  # noqa: E402

SALIDA = Path(__file__).resolve().parents[1] / "datos" / "referencia"
N_MIN = 8  # mínimo de observaciones para publicar un rango por departamento
ANIOS_RENDIMIENTO = (2004, 2024)  # 2025-2026 tienen meses incompletos
ANIOS_PRECIO = (2021, 2026)  # precios recientes: el nivel de precios cambia con los años
ANIOS_ESTACIONALIDAD = (2010, 2024)


def cargar(ruta, meses=(1, 12)):
    d = pd.read_csv(ruta, dtype=str, encoding="utf-8")
    d = d[d["ANIO"].notna()].copy()
    d["anio"] = d["ANIO"].astype(int)
    d["mes"] = pd.to_numeric(d["COD_MES"])
    d = d[d["mes"].between(*meses)]
    for col in ["COSECHA_HA", "PRODUCCION_TN", "PRECIO_SOLKG"]:
        d[col] = pd.to_numeric(d[col], errors="coerce")
    d["cultivo"] = d["NOM_CULTIVO"].map(normalizar_cultivo)
    d["departamento"] = d["NOM_DEPARTAMENTO"].str.strip()
    d["tipo"] = d["NOM_TIPO"].str.strip().str.lower()
    d = d[d["cultivo"].notna() & (d["departamento"] != "Total nacional")]
    return d


def percentiles(serie):
    q = serie.quantile([0.01, 0.05, 0.25, 0.5, 0.75, 0.95, 0.99])
    return {
        "n": int(serie.size),
        "p01": q[0.01], "p05": q[0.05], "p25": q[0.25], "p50": q[0.5],
        "p75": q[0.75], "p95": q[0.95], "p99": q[0.99],
    }


def recorte_robusto(valores):
    """Descarta valores absurdos con la mediana y la MAD en escala logarítmica.

    La base histórica tiene registros imposibles (por ejemplo, rendimientos de
    millones de kg/ha). Se descartan antes de calcular los rangos.
    """
    log = np.log(valores)
    med = log.median()
    mad = (log - med).abs().median() * 1.4826
    if mad == 0 or np.isnan(mad):
        return valores
    return valores[(log - med).abs() <= 4 * mad]


def rangos_por_variable(d, columna, nombre):
    filas = []
    for cultivo, g in d.groupby("cultivo"):
        limpio = recorte_robusto(g[columna])
        nacional = percentiles(limpio)
        filas.append({"cultivo": cultivo, "departamento": "Nacional", "variable": nombre, **nacional})
        for depto, gd in g.loc[limpio.index].groupby("departamento"):
            if len(gd) >= N_MIN:
                filas.append({"cultivo": cultivo, "departamento": depto, "variable": nombre,
                              **percentiles(gd[columna])})
    return pd.DataFrame(filas)


def construir(ruta):
    d = cargar(ruta)

    # Rendimiento mensual (kg/ha) = producción / superficie cosechada del mes
    r = d[d["anio"].between(*ANIOS_RENDIMIENTO) & (d["COSECHA_HA"] > 0) & (d["PRODUCCION_TN"] > 0)].copy()
    r["rendimiento_kg_ha"] = r["PRODUCCION_TN"] * 1000 / r["COSECHA_HA"]
    rend = rangos_por_variable(r, "rendimiento_kg_ha", "rendimiento_kg_ha")

    # Rendimiento anual (kg/ha), de las filas Ene-Dic (COD_MES 13). Para los cultivos
    # permanentes el rendimiento mensual de la base no es confiable, así que el
    # validador usa el anual repartido según la estacionalidad.
    a = cargar(ruta, meses=(13, 13))
    a = a[(a["COSECHA_HA"] > 0) & (a["PRODUCCION_TN"] > 0)].copy()
    a["rendimiento_anual_kg_ha"] = a["PRODUCCION_TN"] * 1000 / a["COSECHA_HA"]
    anual = pd.DataFrame([
        {"cultivo": c, "departamento": "Nacional", "variable": "rendimiento_anual_kg_ha",
         **percentiles(recorte_robusto(g["rendimiento_anual_kg_ha"]))}
        for c, g in a.groupby("cultivo") if len(g) >= N_MIN
    ])

    # Precio chacra (S/ por kg), años recientes
    p = d[d["anio"].between(*ANIOS_PRECIO) & (d["PRECIO_SOLKG"] > 0)].copy()
    prec = rangos_por_variable(p, "PRECIO_SOLKG", "precio_s_kg")

    # Estacionalidad: qué parte de la producción del año se cosecha en cada mes
    e = d[d["anio"].between(*ANIOS_ESTACIONALIDAD)].copy()
    e["PRODUCCION_TN"] = e["PRODUCCION_TN"].fillna(0)
    total = e.groupby(["cultivo", "departamento", "anio"])["PRODUCCION_TN"].transform("sum")
    e = e[total > 0]
    e["participacion"] = e["PRODUCCION_TN"] / total[total > 0]
    est = (e.groupby(["cultivo", "departamento", "mes"])["participacion"]
             .agg(participacion_media="mean", participacion_max="max", anios="count")
             .reset_index())
    est = est[est["anios"] >= 5]

    tipos = d.groupby("cultivo")["tipo"].first().rename("tipo").reset_index()

    SALIDA.mkdir(parents=True, exist_ok=True)
    rangos = pd.concat([rend, anual, prec], ignore_index=True).merge(tipos, on="cultivo", how="left")
    rangos = rangos.round(4)
    rangos.to_csv(SALIDA / "rangos.csv", index=False, encoding="utf-8")
    est.round(4).to_csv(SALIDA / "estacionalidad.csv", index=False, encoding="utf-8")

    meta = {
        "descripcion": "Rangos agregados para validar reportes de estadística agraria. No contiene registros individuales.",
        "anios_rendimiento": ANIOS_RENDIMIENTO,
        "anios_precio": ANIOS_PRECIO,
        "anios_estacionalidad": ANIOS_ESTACIONALIDAD,
        "minimo_observaciones_por_departamento": N_MIN,
        "cultivos": sorted(rangos["cultivo"].unique().tolist()),
        "departamentos": sorted(d["departamento"].unique().tolist()),
    }
    (SALIDA / "metadatos.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

    # Diagnóstico de la base (solo se imprime; no se publica)
    absurdos = len(r) - sum(len(recorte_robusto(g["rendimiento_kg_ha"])) for _, g in r.groupby("cultivo"))
    print(f"Rangos: {len(rangos)} filas | estacionalidad: {len(est)} filas")
    print(f"Registros con rendimiento descartado por absurdo: {absurdos} de {len(r)} "
          f"({absurdos / len(r):.1%})")
    return rangos, est


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    construir(sys.argv[1])
