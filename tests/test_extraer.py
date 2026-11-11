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


TEXTO = ("Reporte de Mayo. Papa en Huancayo, Junín. 100 hectáreas cosechadas. "
         "1.600 toneladas. Precio en chacra, un sol con 20 el kilo.")


def test_tope_de_uso_salta_el_llm(monkeypatch):
    import sectorista.extraer as ex

    monkeypatch.setenv("ANTHROPIC_API_KEY", "clave-de-prueba")
    monkeypatch.setattr(ex, "extraer_con_claude", lambda t: (_ for _ in ()).throw(AssertionError("no debía llamarse")))
    f, info = ex.extraer(TEXTO, usar_claude=False, motivo="tope por sesión")
    assert info == {"motor": "reglas", "motivo": "tope por sesión"}
    assert f["produccion_t"] == 1600


def test_si_falla_la_api_usa_reglas_sin_mostrar_el_error(monkeypatch):
    import sectorista.extraer as ex

    def falla(texto):
        raise RuntimeError("detalle interno que no debe verse")

    monkeypatch.setenv("ANTHROPIC_API_KEY", "clave-de-prueba")
    monkeypatch.setattr(ex, "extraer_con_claude", falla)
    f, info = ex.extraer(TEXTO)
    assert info["motor"] == "reglas" and "detalle interno" not in str(info)
    assert f["cultivo"] == "Papa" and f["precio_s_kg"] == 1.2
