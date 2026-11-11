from sectorista.extraer import ReporteDictado, a_formulario, extraer_con_reglas


def test_reglas_transcripcion_whisper():
    t = ("Reporte de Mayo. Papa en Huancayo, Junín. 100 hectáreas cosechadas. "
         "1.600.000 toneladas. Precio en chacra, un sol con 20 el kilo.")
    f = a_formulario(extraer_con_reglas(t))
    assert f["cultivo"] == "Papa" and f["departamento"] == "Junin" and f["mes"] == 5
    assert f["superficie_cosechada_ha"] == 100 and f["produccion_t"] == 1_600_000
    assert f["precio_s_kg"] == 1.2


def test_conversion_de_unidades_la_hace_python():
    d = ReporteDictado(cultivo="papa", produccion_valor=2400, produccion_unidad="kilos",
                       precio_valor=55.2, precio_unidad="por_quintal")
    f = a_formulario(d)
    assert f["produccion_t"] == 2.4
    assert f["precio_s_kg"] == 1.2
