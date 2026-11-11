"""Transcripción del audio con Whisper (faster-whisper), en CPU y sin internet.

El modelo corre dentro de la app: el audio del reporte no sale del servidor, y en
una versión instalada en la agencia agraria tampoco saldría de la laptop.
"""

import os
from functools import lru_cache

MODELO = os.getenv("WHISPER_MODELO", "small")

# Vocabulario del dominio: ayuda a Whisper a escribir bien cultivos, lugares y unidades
PISTA = ("Reporte de estadística agraria. Cultivo: papa, limón, palta, plátano, mango, arroz cáscara, "
         "maíz amarillo duro, maíz amiláceo, choclo, cebolla, quinua, yuca, uva, café, cacao. "
         "Piura, Chulucanas, Junín, Huancayo, Cusco, Puno, La Libertad, Lambayeque. "
         "Hectáreas cosechadas, toneladas, kilos, quintales, precio en chacra, soles por kilo.")


@lru_cache(maxsize=1)
def _modelo():
    from faster_whisper import WhisperModel

    return WhisperModel(MODELO, device="cpu", compute_type="int8")


def transcribir(ruta_audio):
    segmentos, info = _modelo().transcribe(
        ruta_audio, language="es", vad_filter=True, initial_prompt=PISTA, beam_size=5,
    )
    texto = " ".join(s.text.strip() for s in segmentos).strip()
    return texto, {"modelo_whisper": MODELO, "duracion_s": round(info.duration, 1)}
