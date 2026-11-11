"""Catálogo de cultivos y departamentos, con los sinónimos que se dicen en campo."""

import unicodedata

# Nombre canónico -> sinónimos (sin tildes, en minúsculas)
CULTIVOS = {
    "Aceituna": ["aceituna", "olivo", "aceitunas"],
    "Ajo": ["ajo", "ajos"],
    "Algodón rama": ["algodon", "algodon rama"],
    "Arándano": ["arandano", "arandanos", "blueberry"],
    "Arroz cáscara": ["arroz", "arroz cascara", "arroz en cascara"],
    "Cacao en grano": ["cacao", "cacao en grano"],
    "Café en grano": ["cafe", "cafe en grano", "cafe pergamino"],
    "Caña de azúcar": ["cana", "cana de azucar", "cana de azucar para azucar"],
    "Cebolla": ["cebolla", "cebollas"],
    "Limón": ["limon", "limones", "limon sutil"],
    "Maíz amarillo duro": ["maiz amarillo", "maiz amarillo duro", "maiz duro"],
    "Maíz amiláceo": ["maiz amilaceo", "maiz blanco", "maiz amilaceo blanco"],
    "Maíz choclo": ["choclo", "maiz choclo"],
    "Mango": ["mango", "mangos"],
    "Palta": ["palta", "paltas", "aguacate"],
    "Papa": ["papa", "papas", "patata"],
    "Plátano": ["platano", "platanos", "banano"],
    "Quinua": ["quinua", "quinoa"],
    "Tomate": ["tomate", "tomates"],
    "Uva": ["uva", "uvas", "vid"],
    "Yuca": ["yuca", "yucas"],
}

DEPARTAMENTOS = [
    "Amazonas", "Ancash", "Apurimac", "Arequipa", "Ayacucho", "Cajamarca", "Callao",
    "Cusco", "Huancavelica", "Huanuco", "Ica", "Junin", "La Libertad", "Lambayeque",
    "Lima", "Lima Metropolitana", "Loreto", "Madre de Dios", "Moquegua", "Pasco",
    "Piura", "Puno", "San Martin", "Tacna", "Tumbes", "Ucayali",
]

MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto",
         "septiembre", "octubre", "noviembre", "diciembre"]


def sin_tildes(texto):
    """Minúsculas, sin tildes y sin caracteres dañados por la codificación."""
    if texto is None:
        return ""
    texto = str(texto).replace("�", "n")  # la ñ a veces llega dañada en la base
    nfkd = unicodedata.normalize("NFKD", texto)
    return "".join(c for c in nfkd if not unicodedata.combining(c)).lower().strip()


_INDICE_CULTIVOS = {sin_tildes(s): canon for canon, sins in CULTIVOS.items() for s in sins + [canon]}
_INDICE_DEPTOS = {sin_tildes(d): d for d in DEPARTAMENTOS}


def normalizar_cultivo(texto):
    """Devuelve el nombre canónico del cultivo, o None si no se reconoce."""
    clave = sin_tildes(texto)
    clave = clave.replace("(para azucar)", "para azucar").replace("  ", " ").strip()
    if clave in _INDICE_CULTIVOS:
        return _INDICE_CULTIVOS[clave]
    # Coincidencia por el sinónimo más largo contenido en el texto
    candidatos = [s for s in _INDICE_CULTIVOS if s and s in clave]
    if candidatos:
        return _INDICE_CULTIVOS[max(candidatos, key=len)]
    return None


def normalizar_departamento(texto):
    clave = sin_tildes(texto)
    if clave in _INDICE_DEPTOS:
        return _INDICE_DEPTOS[clave]
    candidatos = [k for k in _INDICE_DEPTOS if k in clave]
    if candidatos:
        return _INDICE_DEPTOS[max(candidatos, key=len)]
    return None
