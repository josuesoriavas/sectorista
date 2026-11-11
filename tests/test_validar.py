from sectorista.catalogo import normalizar_cultivo, normalizar_departamento
from sectorista.validar import estado, validar


def base(**cambios):
    r = {"cultivo": "papa", "departamento": "Junín", "mes": 5, "anio": 2026,
         "superficie_cosechada_ha": 100, "produccion_t": 1600, "precio_s_kg": 1.2}
    r.update(cambios)
    return r


def test_catalogo_reconoce_sinonimos():
    assert normalizar_cultivo("limón sutil") == "Limón"
    assert normalizar_cultivo("Ca�a de azucar (para azucar)") == "Caña de azúcar"
    assert normalizar_departamento("junín") == "Junin"


def test_reporte_normal_pasa():
    assert estado(validar(base())) == "ok"


def test_falta_produccion_es_error():
    a = validar(base(produccion_t=None))
    assert estado(a) == "error" and a[0].campo == "produccion_t"


def test_produccion_en_kilos_sugiere_toneladas():
    a = validar(base(produccion_t=1_600_000))  # 1.6 millones "toneladas" en 100 ha
    err = [x for x in a if x.campo == "produccion_t"][0]
    assert err.nivel == "error"
    assert err.sugerencia == {"produccion_t": 1600}


def test_rendimiento_raro_es_alerta():
    a = validar(base(produccion_t=5000))  # 50 t/ha de papa en Junín
    assert [x.nivel for x in a if x.campo == "produccion_t"] == ["alerta"]


def test_precio_con_decimal_corrido():
    a = validar(base(precio_s_kg=120))
    err = [x for x in a if x.campo == "precio_s_kg"][0]
    assert err.nivel == "error" and err.sugerencia == {"precio_s_kg": 1.2}


def test_cultivo_permanente_usa_estacionalidad():
    a = validar({"cultivo": "limón", "departamento": "Piura", "mes": 3,
                 "superficie_cosechada_ha": 120, "produccion_t": 120, "precio_s_kg": 1.1})
    assert estado(a) == "ok"


def test_cuentas_que_no_cuadran():
    a = validar(base(rendimiento_kg_ha=25000))
    assert any(x.campo == "rendimiento_kg_ha" and x.nivel == "alerta" for x in a)
