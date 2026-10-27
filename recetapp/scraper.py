#!/usr/bin/env python3
"""Scraper Maestro Multi-Farmacia SIN LÍMITES de paginación, con espera paciente y curación.

Cadenas soportadas (Extracción total hasta agotar botón/paginación):
- La Rebaja (VTEX API)
- Habib Droguerías (Árbol VTEX + Playwright botón Mostrar más sin límite)
- La Economía (Playwright paginación real sin límite)
- Farmatodo (Playwright botón Cargar más con espera paciente anti-corte)
- Cruz Verde (Playwright anti-modal + botón Ver más productos sin límite + URLs por SKU)
"""

import argparse
import csv
import datetime
import html
import json
import logging
import random
import re
import ssl
import string
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from html.parser import HTMLParser
from pathlib import Path

# ==============================================================================
# CONFIGURACIÓN DE ARCHIVOS Y LOGGING
# ==============================================================================
BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)

SALIDA = DATA_DIR / "scrapeado-hoy.csv"
ARCHIVO_LOG = DATA_DIR / "scraper.log"

logger = logging.getLogger("RecetAppScraper")
logger.setLevel(logging.DEBUG)

fmt_archivo = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
fh = logging.FileHandler(ARCHIVO_LOG, mode="a", encoding="utf-8")
fh.setLevel(logging.DEBUG)
fh.setFormatter(fmt_archivo)
logger.addHandler(fh)

fmt_consola = logging.Formatter("%(message)s")
ch = logging.StreamHandler(sys.stdout)
ch.setLevel(logging.INFO)
ch.setFormatter(fmt_consola)
logger.addHandler(ch)

# ==============================================================================
# CONFIGURACIÓN GENERAL Y DICCIONARIOS DE CURACIÓN
# ==============================================================================
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)
PAUSA_S = 1.5

COLUMNAS = [
    "fecha", "farmacia", "codigo", "principio_activo", "concentracion", "producto",
    "marca", "presentacion", "unidades", "precio", "precio_lista", "precio_unidad", "url",
]

RE_CONCENTRACION = re.compile(
    r"(\d+(?:[.,]\d+)?)\s*(MCG|MG|G|GR|KG|UI|%|ML|L|CC|OZ)(?![A-Z])",
    re.IGNORECASE,
)
RE_UNIDADES = re.compile(
    r"\b(?:CAJA\s*|PAQUETE\s*|PQT\s*|FCO\s*|FRASCO\s*|TUBO\s*|TUB\s*|POTE\s*|SOBRE\s*)?"
    r"(?:X|POR|DE)?\s*(\d+)\s*"
    r"(?:TAB|CAP|COMP|GRAG|CAPS|TABLETAS?|CAPSULAS?|CÁPSULAS?|COMPRIMIDOS?|"
    r"UNIDADES?|UNDS?|SOBRES?|FRASCOS?|AMPOLLAS?|AMP|GRAGEAS?|GOMAS?|PAÑALES|PANALES|TOALLAS)\b"
    r"|\b(?:CAJA|FRASCO|FCO|TUBO|TUB|POTE)\s*(?:X|POR)\s*(\d+)\b"
    r"|\bX\s*(\d+)\s*(?:UND|UNIDADES|TAB|CAP|SOBRES|GRAG)?\b",
    re.IGNORECASE,
)

PRINCIPIOS_BASURA = {
    "0 NO CODIFICADO 0", "NO CODIFICADO", "0", "N/A", "NA", "SIN CLASIFICAR",
    "NO APLICA", "NINGUNO", "VARIOS", "OTROS", "SIN PRINCIPIO ACTIVO", "NULL",
    "GENERAL", "A BATERIAS", "A PRUEBA DE AGUA",
}

MACROCATEGORIAS = {
    "MEDICAMENTOS Y FARMACIA",
    "CUIDADO PERSONAL Y ASEO",
    "DERMOCOSMÉTICA Y BELLEZA",
    "NUTRICIÓN Y SUPLEMENTOS",
    "BEBÉ Y MATERNIDAD",
    "DISPOSITIVOS Y BOTIQUÍN",
    "ALIMENTOS Y BEBIDAS",
    "SALUD SEXUAL",
    "ACCESORIOS Y HOGAR",
}

MARCAS_CONOCIDAS = [
    "TECNOQUIMICAS", "LA SANTE", "GENFAR", "PROCAPS", "COASPHARMA", "LAPROFF",
    "ECAR", "BUSSIE", "MEMPHIS", "BIOQUIFAR", "VITALIS", "HUMAX", "WINTHROP",
    "SANOFI", "PFIZER", "BAYER", "NOVARTIS", "ROCHE", "ASTRAZENECA", "ABBOTT",
    "GSK", "GLAXOSMITHKLINE", "MERCK", "MSD", "BOEHRINGER", "GRUNENTHAL", "MEGALABS",
    "SIEGFRIED", "CHALVER", "SYNTHESIS", "LAFRANCOL", "BIOPAS", "EUROFARMA",
    "SEVEN PHARMA", "FARMA DE COLOMBIA", "NOVAMED", "BAGO", "LEGRAND",
    "ROPSOHN", "TECNOFARMA", "MEDICK", "LISTERINE", "COLGATE",
    "ORAL B", "ORAL-B", "SENSODYNE", "COREGA", "EUCERIN", "LA ROCHE POSAY",
    "LA ROCHE-POSAY", "ISDIN", "VICHY", "CETAPHIL", "CERAVE", "AVENE", "BIODERMA",
    "NEUTROGENA", "NIVEA", "DOVE", "REXONA", "GILLETTE", "HUGGIES", "PEQUEÑIN",
    "PEQUENIN", "WINNY", "PAMPERS", "JOHNSON", "JOHNSON'S", "SIMILAC", "ENFAMIL",
    "NAN", "ENSURE", "GLUCERNA", "PEDIASURE", "PEDIALYTE", "ELECTROLIT", "HIDRAPLUS",
    "DOLEX", "ADVIL", "MOTRIN", "TYLENOL", "ASPIRINA", "BONFIEST", "ALKA SELTZER",
    "SAL DE FRUTAS LUA", "GAVISCON", "MILPAX", "MYLANTA", "BUSCAPINA", "ENTEROGERMINA",
    "VICK", "NORAVER", "NOXCUR", "PAX", "MAREOL", "LOMOTIL", "REDOXON", "CEBION",
    "CENTRUM", "PHARMATON", "NEUROBION", "BEDOYECTA", "TARRITO ROJO", "COLA GRANULADA",
    "GELICART", "CALTRATE", "FINIGAX", "ESPAVEN", "COLYPAN", "EUTIROX", "GLUCOPHAGE",
    "COLMED", "HALEON", "KENVUE", "PROCTER & GAMBLE", "SENSOBIO", "MK", "TQ",
]

CATEGORIAS_SEMI_LA_ECONOMIA = [
    ("Medicamentos Genéricos", "medicamentos/genericos/01/01002"),
    ("Medicamentos Comerciales", "medicamentos/medicamentos/01/01001"),
    ("Terapia Crónica", "medicamentos/terapia-cronica/01/01003"),
    ("Medicamentos Regulados", "medicamentos/regulados/01/01004"),
    ("Gastrointestinal", "botiquin/gastrointestinal/03/03001"),
    ("Primeros Auxilios", "botiquin/cuidado-de-la-herida/03/03002"),
    ("Alivio del Dolor", "botiquin/alivio-del-dolor/03/03003"),
    ("Gripa y Tos", "botiquin/gripa-tos/03/03004"),
    ("Vitaminas y Suplementos", "botiquin/vitaminas-minerales-y-suplementos/03/03005"),
    ("Salud Sexual", "botiquin/salud-sexual/03/03006"),
    ("Dermatológicos", "botiquin/dermatologicos/03/03007"),
    ("Ojos y Oído", "botiquin/ojos-y-oido/03/03008"),
    ("Cuidado del Cabello", "salud-y-belleza/cuidado-del-cabello/02/02001"),
    ("Higiene Oral", "salud-y-belleza/higiene-oral/02/02002"),
    ("Higiene Personal", "salud-y-belleza/higiene-personal/02/02003"),
    ("Cuidado de la Piel", "salud-y-belleza/cuidado-de-la-piel/02/02007"),
    ("Cuidado del Bebé", "salud-y-belleza/cuidado-del-bebe/02/02008"),
]

CATEGORIAS_CRUZ_VERDE = [
    ("Medicamentos", "/medicamentos/"),
    ("Dermocosméticos", "/dermocosmeticos/"),
    ("Bebé y Maternidad", "/bebe-y-maternidad/"),
    ("Belleza", "/belleza/"),
    ("Cuidado Personal", "/cuidado-personal/"),
    ("Salud Sexual", "/salud-sexual/"),
    ("Bienestar y Nutrición", "/bienestar-y-nutricion/"),
    ("Bienestar Deportivo", "/nutricion-deportiva-y-saludable/"),
    ("Alimentos y Bebidas", "/alimentos-y-bebidas/"),
]

CATEGORIAS_HABIB_RESPALDO = [
    ("Accesorios General", "/accesorios-y-otros/accesorios-general"),
    ("Cuidado Personal", "/cuidado-personal"),
    ("Comestibles", "/comestibles"),
    ("Cuidado del Bebe", "/cuidado-del-bebe-y-maternidad"),
    ("Dermocosmética", "/dermocosmetica"),
    ("Droguería y Medicamentos", "/drogueria-y-medicamentos"),
    ("Equipos y Dispositivos Médicos", "/equipos-y-dispositivos-medicos"),
    ("Naturales y Homeopáticos", "/naturales-y-homeopaticos"),
    ("Nutrición", "/nutricion"),
]

CATEGORIAS_TUDROGUERIA = [
    ("Bebé y Mamá", "/bebe-y-mama"),
    ("Cosmética", "/cosmetica"),
    ("Cuidado Personal", "/cuidado-personal"),
    ("Salud", "/salud"),
    ("Droguería", "/drogueria"),
    ("Bebidas y Comidas", "/bebidas-y-comidas"),
    ("Aseo y Hogar", "/aseo-y-hogar"),
]

CATEGORIAS_FARMATODO = [
    ("Tratamiento de la gripa", "/categorias/salud-y-medicamentos/tratamiento-de-la-gripa"),
    ("Salud y medicamentos", "/categorias/salud-y-medicamentos/salud-y-medicamentos"),
    ("Alivio del dolor", "/categorias/salud-y-medicamentos/alivio-del-dolor"),
    ("Salud digestiva", "/categorias/salud-y-medicamentos/salud-digestiva"),
    ("Botiquín y primeros auxilios", "/categorias/salud-y-medicamentos/botiquin-y-primeros-auxilios"),
    ("Dermatológicos", "/categorias/salud-y-medicamentos/dermatologicos"),
    ("Cuidado de los pies y antimicóticos", "/categorias/salud-y-medicamentos/cuidado-de-los-pies-y-antimicoticos"),
    ("Incontinencia", "/categorias/salud-y-medicamentos/incontinencia"),
    ("Rehabilitación y equipos médicos", "/categorias/salud-y-medicamentos/rehabilitacion-y-equipos-medicos"),
    ("Cuidado de la vista", "/categorias/salud-y-medicamentos/cuidado-de-la-vista"),
    ("Nutrición", "/categorias/bienestar-y-nutricion-deportiva/nutricion"),
    ("Suplementos dietarios", "/categorias/bienestar-y-nutricion-deportiva/suplementos-dietarios"),
    ("Suplementos deportivos", "/categorias/bienestar-y-nutricion-deportiva/suplementos-deportivos"),
    ("Complementos deportivos", "/categorias/bienestar-y-nutricion-deportiva/complementos-deportivos"),
    ("Accesorios deportivos", "/categorias/bienestar-y-nutricion-deportiva/accesorios-deportivos"),
    ("Ojos", "/categorias/belleza/ojos"),
    ("Rostro", "/categorias/belleza/rostro"),
    ("Labios", "/categorias/belleza/labios"),
    ("Uñas", "/categorias/belleza/unas"),
    ("Accesorios de maquillaje", "/categorias/belleza/accesorios-de-maquillaje"),
    ("Cuidado de la piel", "/categorias/belleza/cuidado-de-la-piel"),
    ("Formula infantiles", "/categorias/cuidado-del-bebe/formulas-infantiles"),
    ("Compotas y cereales", "/categorias/cuidado-del-bebe/compotas-y-cereales"),
    ("Pañales y toallitas", "/categorias/cuidado-del-bebe/panales-y-toallitas"),
    ("Higiene del bebé", "/categorias/cuidado-del-bebe/higiene-del-bebe"),
    ("Lactancia y Alimentación", "/categorias/cuidado-del-bebe/lactancia-y-alimentacion"),
    ("Artículos de Maternidad", "/categorias/cuidado-del-bebe/articulos-de-maternidad"),
    ("Accesorios bebé", "/categorias/cuidado-del-bebe/accesorios-bebe"),
    ("Cuidado del cabello", "/categorias/cuidado-personal/cuidado-del-cabello"),
    ("Cuidado bucal", "/categorias/cuidado-personal/cuidado-bucal"),
    ("Higiene personal", "/categorias/cuidado-personal/higiene-personal"),
    ("Protección femenina", "/categorias/cuidado-personal/proteccion-femenina"),
    ("Afeitado Hombre", "/categorias/cuidado-personal/afeitado-hombre"),
    ("Depilación Mujer", "/categorias/cuidado-personal/depilacion-mujer"),
    ("Bienestar sexual", "/categorias/cuidado-personal/bienestar-sexual"),
    ("Cuidado de la piel", "/categorias/cuidado-personal/cuidado-de-la-piel"),
    ("Facial", "/categorias/dermocosmetica/facial"),
    ("Protección Solar", "/categorias/dermocosmetica/proteccion-solar"),
    ("Corporal", "/categorias/dermocosmetica/corporal"),
    ("Capilar", "/categorias/dermocosmetica/capilar"),
    ("Higiene Personal Dermocosmética", "/categorias/dermocosmetica/higiene-personal-dermocosmetica"),
    ("Maquillaje", "/categorias/dermocosmetica/maquillaje"),
]

PRINCIPIOS_CONOCIDOS = {
    "ACETAMINOFEN", "IBUPROFENO", "LOSARTAN", "ATORVASTATINA", "METFORMINA",
    "OMEPRAZOL", "LORATADINA", "AMLODIPINO", "NAPROXENO", "DICLOFENACO",
    "AMOXICILINA", "AZITROMICINA", "CIPROFLOXACINO", "CEFALEXINA", "FLUCONAZOL",
    "ALBENDAZOL", "IVERMECTINA", "METRONIDAZOL", "ESOMEPRAZOL", "PANTOPRAZOL",
    "LANZOPRAZOL", "CETIRIZINA", "DESLORATADINA", "FEXOFENADINA", "MONTELUKAST",
    "SALBUTAMOL", "ENALAPRIL", "CAPTOPRIL", "VALSARTAN", "CANDESARTAN",
    "TELMISARTAN", "IRBESARTAN", "CARVEDILOL", "METOPROLOL", "PROPRANOLOL",
    "BISOPROLOL", "NEBIVOLOL", "FUROSEMIDA", "HIDROCLOROTIAZIDA", "ESPIRONOLACTONA",
    "ROSUVASTATINA", "SIMVASTATINA", "LOVASTATINA", "FENOFIBRATO", "GEMFIBROZILO",
    "EZETIMIBA", "ASA", "ACIDO ACETILSALICILICO", "CLOPIDOGREL", "WARFARINA",
    "RIVAROXABAN", "APIXABAN", "GLIBENCLAMIDA", "GLIMEPIRIDA", "SITAGLIPTINA",
    "VILDAGLIPTINA", "EMPAGLIFLOZINA", "DAPAGLIFLOZINA", "LEVOTIROXINA", "PREDNISOLONA",
    "PREDNISONA", "DEXAMETASONA", "BETAMETASONA", "DEFLAZACORT", "MELOXICAM",
    "CELECOXIB", "ETORICOXIB", "NIMESULIDA", "KETOPROFENO", "KETOROLACO",
    "TRAMADOL", "CODEINA", "PREGABALINA", "GABAPENTINA", "CARBAMAZEPINA",
    "ACIDO VALPROICO", "LEVETIRACETAM", "FENITOINA", "LAMOTRIGINA", "TOPIRAMATO",
    "FLUOXETINA", "SERTRALINA", "ESCITALOPRAM", "PAROXETINA", "VENLAFAXINA",
    "DULOXETINA", "TRAZODONA", "AMITRIPTILINA", "CLONAZEPAM", "ALPRAZOLAM",
    "LORAZEPAM", "ZOLPIDEM", "QUETIAPINA", "RISPERIDONA", "OLANZAPINA",
    "ARIPIPRAZOL", "HALOPERIDOL", "MEMANTINA", "DONEPECILO", "TAMSULOSINA",
    "FINASTERIDA", "DUTASTERIDA", "SILDENAFIL", "TADALAFIL", "ALOPURINOL",
    "COLCHICINA", "CALCIO", "CITRATO DE MAGNESIO", "MAGNESIO", "COLAGENO",
    "VITAMINA C", "VITAMINA D", "VITAMINA E", "ACIDO FOLICO", "SULFATO FERROSO",
    "SULFATO DE ZINC", "SULF DE ZINC", "SUCRALFATO", "BISMUTO", "FAMOTIDINA",
    "RANITIDINA", "LOPERAMIDA", "RACECADOTRILO", "HIOSCINA", "TRIMEBUTINA",
    "SIMETICONA", "ALGINATO DE SODIO", "HIDROXIDO DE ALUMINIO", "HIDROXIDO DE MAGNESIO",
    "MOSAPRIDA", "LEVOSULPIRIDA", "DOMPERIDONA", "METOCLOPRAMIDA", "ONDANSETRON",
    "OLOPATADINA", "TIMOLOL", "DORZOLAMIDA", "LATANOPROST", "BRIMONIDINA",
    "CARBOXIMETILCELULOSA", "HIALURONATO DE SODIO", "CLOTRIMAZOL", "KETOCONAZOL",
    "TERBINAFINA", "MICONAZOL", "ACICLOVIR", "MUPIROCINA", "ACIDO FUSIDICO",
    "HIDROCORTISONA", "CLOBETASOL", "DESONIDA", "TRETINOINA", "ADAPALENO",
    "PEROXIDO DE BENZOILO", "MINOXIDIL", "FINASTERIDE",
}

MARCAS_A_PRINCIPIO = {
    "DOLEX": "ACETAMINOFEN", "CRONOFEN": "ACETAMINOFEN", "WINADOL": "ACETAMINOFEN",
    "TYLENOL": "ACETAMINOFEN", "ADVIL": "IBUPROFENO", "MOTRIN": "IBUPROFENO",
    "CALMIDOL": "IBUPROFENO", "SUGASTRIN": "SUCRALFATO", "GASTRUM": "FAMOTIDINA",
    "BISMUCAR": "SUBSALICILATO DE BISMUTO", "SULZINC": "SULFATO DE ZINC",
    "ZINPLUVIT": "SULFATO DE ZINC", "GAVISCON": "ALGINATO DE SODIO / BICARBONATO",
    "MILPAX": "ALGINATO DE SODIO / BICARBONATO", "MYLANTA": "HIDROXIDO DE ALUMINIO / MAGNESIO",
    "ALKA SELTZER": "ACIDO ACETILSALICILICO / BICARBONATO", "BUSCAPINA": "HIOSCINA",
    "COLYPAN": "TRIMEBUTINA", "EUTIROX": "LEVOTIROXINA", "TIROXIN": "LEVOTIROXINA",
    "GLUCOPHAGE": "METFORMINA", "LIPITOR": "ATORVASTATINA", "CRESTOR": "ROSUVASTATINA",
    "NEXIUM": "ESOMEPRAZOL", "LOSEC": "OMEPRAZOL", "CLARITYNE": "LORATADINA",
    "ZYRTEC": "CETIRIZINA", "AERIUS": "DESLORATADINA", "ALLEGRA": "FEXOFENADINA",
    "PEDIALYTE": "SALES DE REHIDRATACION ORAL", "ELECTROLIT": "SALES DE REHIDRATACION ORAL",
    "HIDRAPLUS": "SALES DE REHIDRATACION ORAL", "ENTEROGERMINA": "ESPORAS DE BACILLUS CLAUSII",
    "GELICART": "COLAGENO HIDROLIZADO", "NEUROBION": "COMPLEJO B (B1 / B6 / B12)",
    "OFTIPAT": "OLOPATADINA", "OXY": "PEROXIDO DE BENZOILO",
}

FARMACIAS_CONFIG = {
    "larebaja": {
        "nombre": "La Rebaja",
        "tipo": "vtex",
        "base_url": "https://www.larebajavirtual.com",
        "endpoint": "/api/catalog_system/pub/products/search",
    },
    "habib": {
        "nombre": "Habib Droguerías",
        "tipo": "playwright_habib",
        "base_url": "https://www.habibdroguerias.com",
        "endpoint": "/accesorios-y-otros/accesorios-general",
    },
    "laeconomia": {
        "nombre": "La Economía",
        "tipo": "playwright_laeconomia",
        "base_url": "https://www.droguerialaeconomia.com",
        "endpoint": "/ca/medicamentos/01",
    },
    "farmatodo": {
        "nombre": "Farmatodo",
        "tipo": "playwright_farmatodo",
        "base_url": "https://www.farmatodo.com.co",
        "endpoint": "/buscar",
    },
    "cruzverde": {
        "nombre": "Cruz Verde",
        "tipo": "playwright_cruzverde",
        "base_url": "https://www.cruzverde.com.co",
        "endpoint": "/medicamentos/vitymin/",
    },

    "tudrogueria": {
        "nombre": "Tu Droguería Virtual",
        "tipo": "playwright_tudrogueria",
        "base_url": "https://www.tudrogueriavirtual.com",
        "endpoint": "/drogueria",
    },
}


# ==============================================================================
# FUNCIONES AUXILIARES GLOBALES
# ==============================================================================
def limpiar_precio_cop(texto):
    solo_digitos = re.sub(r"[^\d]", "", texto or "")
    return float(solo_digitos) if solo_digitos else 0.0


def limpiar_acentos(texto):
    return (
        str(texto or "")
        .upper()
        .replace("Á", "A").replace("É", "E").replace("Í", "I").replace("Ó", "O").replace("Ú", "U")
    )


def clasificar_macrocategoria(texto_categoria, nombre_producto=""):
    """Unifica miles de subcategorías dispersas en 9 Macrocategorías limpias."""
    t = limpiar_acentos(texto_categoria)
    p = limpiar_acentos(nombre_producto)
    junto = f"{t} {p}"

    if any(k in junto for k in [
        "BEBE", "MATERNIDAD", "PANAL", "PAÑAL", "PAÑITOS", "PANITOS", "LACTANCIA",
        "BIBERON", "CHUPO", "FORMULA INFANTIL", "FORMULAS INFANTILES", "COMPOTA", "ANTIPANALITIS"
    ]):
        return "BEBÉ Y MATERNIDAD"

    if any(k in junto for k in [
        "SEXUAL", "PRESERVATIVO", "CONDON", "LUBRICANTE", "ERECTIL", "PRUEBA DE EMBARAZO", "PRUEBAS DE EMBARAZO"
    ]):
        return "SALUD SEXUAL"

    if any(k in junto for k in [
        "DERMO", "FACIAL", "SOLAR", "BLOQUEADOR", "ROSTRO", "LABIOS", "LABIAL",
        "UÑAS", "UNAS", "MAQUILLAJE", "COSMETIC", "PERFUMERIA", "PERFUME", "AGUA MICELAR"
    ]):
        return "DERMOCOSMÉTICA Y BELLEZA"

    if any(k in junto for k in [
        "CABELLO", "CAPILAR", "SHAMPOO", "ACONDICIONADOR", "ORAL", "BUCAL", "DENTAL",
        "CEPILLO", "CREMA DENTAL", "ENJUAGUE", "SEDA DENTAL", "HIGIENE", "ASEO PERSONAL",
        "DESODORANTE", "JABON", "AFEITAD", "DEPILAC", "INCONTINENCIA", "TALCO", "REPELENTE",
        "PROTECCION FEMENINA", "TOALLAS HIGIENICAS", "PROTECTORES DIARIOS", "COPITOS", "CUIDADO CORPORAL"
    ]):
        return "CUIDADO PERSONAL Y ASEO"

    if any(k in junto for k in [
        "VITAMINA", "SUPLEMENTO", "NUTRICION", "MULTIVITAMIN", "PROTEINA", "COLAGENO",
        "COMPLEMENTO", "DEPORTIV", "ELECTROLIT", "HIDRATACION", "MINERAL", "OMEGA"
    ]):
        return "NUTRICIÓN Y SUPLEMENTOS"

    if any(k in junto for k in [
        "BOTIQUIN", "AUXILIO", "ORTOPEDIA", "TENSIOMETRO", "GLUCOMETR", "TERMOMETRO",
        "OXIMETRO", "NEBULIZADOR", "INHALOCAMARA", "JERINGA", "GASA", "CURA", "APOSITO",
        "VENDA", "ALCOHOL", "ALGODON", "TAPABOCA", "GUANTE", "EQUIPO", "DISPOSITIVO",
        "CANULA", "CATETER", "MULETA", "SILLA DE RUEDAS", "CAMINADOR", "MEDIAS DE COMPRESION",
        "BAJALENGUAS", "ESPADRAPO", "MICROPORE", "BASCULA"
    ]):
        return "DISPOSITIVOS Y BOTIQUÍN"

    if any(k in junto for k in [
        "COMESTIBLE", "ALIMENTO", "BEBIDA", "PASABOCA", "CAFE", "CHOCOLATE", "CONFITERIA",
        "ENLATADO", "SNACK", "GALLETA", "ENDULZANTE", "MIEL", "MERMELADA", "CEREAL",
        "FRUTOS SECOS", "HELADO", "CONGELADO", "LACTEO", "ACEITE DE OLIVA", "VINAGRE", "SALSA"
    ]):
        return "ALIMENTOS Y BEBIDAS"

    if any(k in junto for k in [
        "ACCESORIO", "HOGAR", "LIMPIEZA", "AMBIENTADOR", "DETERGENTE", "LIBRO", "REVISTA", "PILA", "PASTILLERO"
    ]):
        return "ACCESORIOS Y HOGAR"

    return "MEDICAMENTOS Y FARMACIA"


# ==============================================================================
# CLIENTE HTTP CON LOGGING DETALLADO Y PROTECCIÓN ANTI-BLOQUEO
# ==============================================================================
class ClienteHTTP:
    def __init__(self, pausa_s=PAUSA_S):
        self.pausa_s = pausa_s
        self.ultima_peticion = 0.0
        self.ctx = ssl.create_default_context()
        self.ctx.check_hostname = False
        self.ctx.verify_mode = ssl.CERT_NONE

    def pedir(self, url, headers_extra=None):
        pausa_objetivo = self.pausa_s + random.uniform(0.1, 0.45)
        transcurrido = time.time() - self.ultima_peticion
        if transcurrido < pausa_objetivo:
            time.sleep(pausa_objetivo - transcurrido)

        parsed = urllib.parse.urlparse(url)
        origen = f"{parsed.scheme}://{parsed.netloc}"

        headers = {
            "User-Agent": USER_AGENT,
            "Accept": "application/json, text/html, application/xhtml+xml, */*;q=0.8",
            "Accept-Language": "es-CO,es;q=0.9,en;q=0.8",
            "Referer": origen + "/",
            "Origin": origen,
        }
        if headers_extra:
            headers.update(headers_extra)

        req = urllib.request.Request(url, headers=headers)
        for intento in range(1, 4):
            try:
                self.ultima_peticion = time.time()
                logger.debug(f"GET {url} (intento {intento})")
                with urllib.request.urlopen(req, timeout=30, context=self.ctx) as resp:
                    cuerpo = resp.read().decode("utf-8", errors="replace")
                    logger.debug(f"HTTP {resp.status} OK ({len(cuerpo)} bytes) <- {url}")
                    return cuerpo, resp.headers

            except urllib.error.HTTPError as e:
                logger.warning(f"  [!] HTTP {e.code} ({e.reason}) en {url} | Intento {intento}/3")
                if e.code in (403, 429, 500, 502, 503, 504) and intento < 3:
                    espera = 10 * intento if e.code in (403, 429) else 4 * intento
                    time.sleep(espera)
                    continue
                raise

            except Exception as e:
                logger.warning(f"  [!] Error de red ({type(e).__name__}: {e}) en {url} | Intento {intento}/3")
                if intento < 3:
                    time.sleep(4 * intento)
                    continue
                raise


# ==============================================================================
# 1. MOTOR VTEX COMPLETO (LA REBAJA) - SIN LÍMITE
# ==============================================================================
def obtener_todas_categorias_vtex(cliente, base_url):
    url_arbol = f"{base_url}/api/catalog_system/pub/category/tree/3"
    try:
        texto, _ = cliente.pedir(url_arbol)
        arbol = json.loads(texto)
    except Exception as e:
        logger.error(f"  [!] Falló descarga de árbol VTEX: {e}. Usando A-Z.")
        return []

    filtros = []

    def recorrer(nodos, ruta_ids=""):
        for n in nodos:
            id_cat = n.get("id")
            if not id_cat:
                continue
            nueva_ruta = f"{ruta_ids}/{id_cat}" if ruta_ids else str(id_cat)
            hijos = n.get("children") or []
            if hijos and len(nueva_ruta.split("/")) < 2:
                recorrer(hijos, nueva_ruta)
            else:
                filtros.append((n.get("name", nueva_ruta), f"C:/{nueva_ruta}/"))

    if isinstance(arbol, list):
        recorrer(arbol)
    logger.info(f"  Categorías descubiertas en VTEX: {len(filtros)}")
    return filtros


def iterar_catalogo_vtex(cliente, config, max_paginas=None):
    base = config["base_url"]
    ruta = config["endpoint"]
    bloques = obtener_todas_categorias_vtex(cliente, base)
    if not bloques:
        bloques = [(f"Letra {letra.upper()}", f"ft={letra}") for letra in string.ascii_lowercase]

    for nombre_bloque, filtro in bloques:
        desde, paginas = 0, 0
        # 2500 es el tope técnico duro de la API de búsqueda de VTEX por consulta
        while desde < 2500:
            if max_paginas is not None and paginas >= max_paginas:
                break
            if filtro.startswith("C:/"):
                params = urllib.parse.urlencode({"fq": filtro, "_from": desde, "_to": desde + 49})
            else:
                params = f"{filtro}&_from={desde}&_to={desde + 49}"

            url_consulta = f"{base}{ruta}?{params}"
            try:
                texto, headers = cliente.pedir(url_consulta)
                lote = json.loads(texto)
            except Exception as e:
                logger.error(f"    [!] Fallo en '{nombre_bloque}' (offset {desde}): {e}")
                break

            if not isinstance(lote, list) or not lote:
                break

            convertidos = []
            for p in lote:
                try:
                    items = p.get("items") or [{}]
                    primer_item = items[0]
                    sellers = primer_item.get("sellers") or [{}]
                    oferta = sellers[0].get("commertialOffer") or {}
                    principios = [
                        x.strip() for x in (p.get("Principio activo") or [])
                        if x.strip() and x.strip().upper() not in PRINCIPIOS_BASURA
                    ]

                    if len(principios) == 1 and "," not in principios[0] and "+" not in principios[0]:
                        PRINCIPIOS_CONOCIDOS.add(principios[0].upper())

                    ean = str(primer_item.get("ean") or "").strip()
                    codigo = ean if ean else str(p.get("productId", ""))
                    pres = (p.get("Presentacionunidadmedida") or [""])[0].strip()
                    cant_med = (p.get("Cantidadunidadesmedida") or [""])[0].strip()

                    convertidos.append({
                        "id": codigo,
                        "nombre": p.get("productName", ""),
                        "marca": p.get("brand", ""),
                        "principios": principios,
                        "categoria": nombre_bloque,
                        "presentacion": pres,
                        "cantidad_explicita": cant_med,
                        "precio": float(oferta.get("Price") or 0),
                        "precio_lista": float(oferta.get("ListPrice") or oferta.get("Price") or 0),
                        "disponible": bool(oferta.get("IsAvailable")),
                        "url": p.get("link", ""),
                    })
                except Exception:
                    continue

            yield f"{nombre_bloque} (pág {paginas + 1})", convertidos

            recursos = headers.get("resources") or "0-0/0"
            total = int(recursos.rsplit("/", 1)[-1]) if "/" in recursos else 0
            desde += 50
            paginas += 1
            if desde >= total:
                break


# ==============================================================================
# 2. MOTOR DROGUERÍA LA ECONOMÍA (PLAYWRIGHT SIN LÍMITE DE PÁGINAS)
# ==============================================================================
class LaEconomiaCardParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.productos = []
        self.sku_actual = ""
        self.en_card = False
        self.card = None
        self.capturando_campo = None

    def handle_starttag(self, tag, attrs):
        attr = dict(attrs)
        clases = set((attr.get("class") or "").split())

        if "data-product-sku" in attr:
            self.sku_actual = attr["data-product-sku"].strip()

        if tag == "a" and "containerCard" in clases:
            self.en_card = True
            href = attr.get("href", "").strip()
            sku = self.sku_actual
            if not sku and href:
                m_sku = re.search(r"-([A-Za-z0-9]+)$", href.split("?")[0])
                if m_sku:
                    sku = m_sku.group(1)
            self.card = {
                "id": sku,
                "url": href,
                "nombre_h3": "",
                "nombre_alt": "",
                "precio_base": "",
                "precio_actual": "",
                "precio_viejo": "",
            }
            return

        if not self.en_card:
            return

        if tag == "img" and "prod__figure__img" in clases:
            self.card["nombre_alt"] = (attr.get("alt") or "").strip()
        elif "prod__name" in clases or any(c.startswith("CardName__") for c in clases):
            self.capturando_campo = "nombre_h3"
        elif "base__price" in clases or any(c.startswith("CardBasePrice__") for c in clases):
            self.capturando_campo = "precio_base"
        elif "prod--scratch__price__current" in clases:
            self.capturando_campo = "precio_actual"
        elif "prod--scratch__price__old" in clases:
            self.capturando_campo = "precio_viejo"

    def handle_data(self, data):
        if self.en_card and self.capturando_campo:
            self.card[self.capturando_campo] += data

    def handle_endtag(self, tag):
        if self.en_card:
            if tag in ("h3", "p", "span") and self.capturando_campo:
                self.capturando_campo = None
            elif tag == "a":
                self.en_card = False
                self.productos.append(self.card)
                self.card = None


def parsear_html_laeconomia(html_texto, base_url="https://www.droguerialaeconomia.com", categoria_nombre=""):
    parser = LaEconomiaCardParser()
    parser.feed(html_texto)

    ean_por_sku = {}
    marca_por_sku = {}
    subcat_por_sku = {}

    for m in re.finditer(r'\\"sku\\":\\"([^\\"]+)\\".*?\\"brand\\":\\"([^\\"]*)\\"', html_texto):
        if m.group(2):
            marca_por_sku[m.group(1)] = m.group(2)

    for m in re.finditer(r'\\"sku\\":\\"([^\\"]+)\\".*?\\"subCategory\\":\\"([^\\"]*)\\"', html_texto):
        if m.group(2):
            subcat_por_sku[m.group(1)] = m.group(2)

    listas_ean = dict(re.findall(r'([0-9a-f]+):\[(\\"[0-9]{8,14}\\"(?:,\\"[0-9]{8,14}\\")*)\]', html_texto))
    for m in re.finditer(
        r'\\"ean\\":\\"\$([0-9a-f]+)\\",\\"name\\":\\"[^\\"]+\\",\\"updatedAt\\":\\"[^\\"]+\\",\\"sku\\":\\"([^\\"]+)\\"',
        html_texto,
    ):
        ref_ean, sku = m.group(1), m.group(2)
        if ref_ean in listas_ean:
            ean_por_sku[sku] = listas_ean[ref_ean].split(",")[0].strip('\\"')

    resultados = []
    for c in parser.productos:
        sku = c["id"]
        nombre_h3 = html.unescape(c["nombre_h3"]).strip()
        nombre_alt = html.unescape(c["nombre_alt"]).strip()
        nombre = nombre_alt if (not nombre_h3 or nombre_h3.endswith("...")) and nombre_alt else (nombre_h3 or nombre_alt)

        precio = limpiar_precio_cop(c["precio_actual"]) or limpiar_precio_cop(c["precio_base"])
        precio_lista = limpiar_precio_cop(c["precio_viejo"]) or precio
        url = base_url + c["url"] if c["url"].startswith("/") else c["url"]

        resultados.append({
            "id": ean_por_sku.get(sku) or sku,
            "nombre": nombre,
            "marca": marca_por_sku.get(sku, ""),
            "principios": [],
            "categoria": subcat_por_sku.get(sku) or categoria_nombre,
            "presentacion": "",
            "cantidad_explicita": "",
            "precio": precio,
            "precio_lista": precio_lista,
            "disponible": precio > 0,
            "url": url,
        })

    m_pag = re.search(r'class="ant-pagination-simple-pager"[^>]*>.*?/</span>\s*(\d+)\s*</li>', html_texto, re.DOTALL)
    total_paginas = int(m_pag.group(1)) if m_pag else 1
    return resultados, total_paginas


def iterar_playwright_laeconomia(cliente, config, max_paginas=None):
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        logger.error(f"  [!] Playwright no está instalado ({sys.executable}).")
        return

    base = config["base_url"].rstrip("/")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1920, "height": 1080}, user_agent=USER_AGENT)
        page = context.new_page()

        for nombre_cat, slug in CATEGORIAS_SEMI_LA_ECONOMIA:
            url = f"{base}/ca/{slug.lstrip('/')}"
            try:
                logger.debug(f"Playwright La Economía abriendo: {url}")
                page.goto(url, wait_until="domcontentloaded", timeout=35000)
                try:
                    page.wait_for_selector("a.containerCard", timeout=12000)
                except Exception:
                    page.wait_for_timeout(3000)

                pagina = 1
                while True:
                    if max_paginas is not None and pagina > max_paginas:
                        break

                    html_pag = page.content()
                    lote, total_pags = parsear_html_laeconomia(html_pag, base, nombre_cat)
                    if not lote:
                        break

                    yield f"La Economía '{nombre_cat}' (pág {pagina}/{total_pags})", lote
                    if pagina >= total_pags:
                        break

                    primer_id_antes = lote[0]["id"] if lote else ""
                    selector_next = "li.ant-pagination-next:not(.ant-pagination-disabled) button, li.ant-pagination-next:not(.ant-pagination-disabled)"

                    # Espera paciente de hasta 8 segundos por el botón de siguiente página
                    btn_next = page.locator(selector_next)
                    encontrado = False
                    for _ in range(8):
                        if btn_next.count() > 0 and btn_next.first.is_visible():
                            encontrado = True
                            break
                        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                        page.wait_for_timeout(1000)

                    if not encontrado:
                        break

                    btn_next.first.scroll_into_view_if_needed(timeout=2000)
                    btn_next.first.click(timeout=3000, force=True)

                    # Esperar hasta 10 segundos a que cambie el listado de productos
                    for _ in range(10):
                        page.wait_for_timeout(1000)
                        nuevo_html = page.content()
                        nuevo_lote, _ = parsear_html_laeconomia(nuevo_html, base, nombre_cat)
                        if nuevo_lote and nuevo_lote[0]["id"] != primer_id_antes:
                            break
                    else:
                        break

                    pagina += 1

            except Exception as e:
                logger.error(f"    [!] Error en La Economía '{nombre_cat}': {e}")
                try:
                    page.close()
                except Exception:
                    pass
                page = context.new_page()
                continue

        try:
            browser.close()
        except Exception:
            pass


# ==============================================================================
# 3. MOTOR PLAYWRIGHT PARA FARMATODO (SIN LÍMITES Y CON ESPERA PACIENTE)
# ==============================================================================
def iterar_playwright_farmatodo(cliente, config, max_paginas=None):
    try:
        from playwright.sync_api import sync_playwright
    except Exception as e:
        logger.error(f"  [!] Falló importación de Playwright: {e}")
        return

    base = config["base_url"].rstrip("/")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1920, "height": 1080}, user_agent=USER_AGENT)
        page = context.new_page()

        for nombre_cat, ruta_cat in CATEGORIAS_FARMATODO:
            url_cat = f"{base}/{ruta_cat.lstrip('/')}"
            try:
                logger.debug(f"Playwright Farmatodo abriendo: {url_cat}")
                page.goto(url_cat, wait_until="domcontentloaded", timeout=40000)
                page.wait_for_timeout(4000)

                num_clic = 0
                while True:
                    if max_paginas is not None and num_clic >= max_paginas:
                        break

                    try:
                        # 1. ¿Apareció explícitamente el mensaje de que no hay más resultados?
                        no_more = page.locator("h5.no-more-result")
                        if no_more.count() > 0 and no_more.first.is_visible():
                            logger.debug(f"  Farmatodo '{nombre_cat}': fin explícito (no-more-result)")
                            break

                        # 2. Espera paciente de hasta 8 segundos haciendo scroll para que el botón se reactive
                        selector_btn = "#group-view-load-more:not([disabled]), button:has-text('Cargar más'):not([disabled])"
                        boton = page.locator(selector_btn)
                        listo = False

                        for intento_espera in range(8):
                            if no_more.count() > 0 and no_more.first.is_visible():
                                break
                            if boton.count() > 0 and boton.first.is_visible() and boton.first.is_enabled():
                                listo = True
                                break
                            # Hacer scroll arriba/abajo para despertar el lazy-load de Angular
                            page.evaluate("window.scrollBy(0, -300)")
                            page.wait_for_timeout(300)
                            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                            page.wait_for_timeout(700)

                        if not listo:
                            logger.debug(f"  Farmatodo '{nombre_cat}': botón 'Cargar más' ya no apareció tras esperar.")
                            break

                        antes = page.locator('a[href*="/producto/"]').count()
                        boton.first.scroll_into_view_if_needed(timeout=2000)
                        boton.first.click(timeout=3000, force=True)
                        num_clic += 1
                        logger.debug(f"  Farmatodo '{nombre_cat}': clic #{num_clic} (Llevamos {antes} productos)")

                        # 3. Esperar hasta 10 segundos a que lleguen las tarjetas nuevas del servidor
                        for _ in range(10):
                            page.wait_for_timeout(1000)
                            if page.locator('a[href*="/producto/"]').count() > antes:
                                break
                        else:
                            # Si tras 10s no cargó nada nuevo, verificar una vez más si sigue el botón
                            logger.debug(f"  Farmatodo '{nombre_cat}': sin nuevos productos tras 10s en clic #{num_clic}")
                            break

                    except Exception as ex_clic:
                        logger.debug(f"  Fin de clics en Farmatodo '{nombre_cat}': {ex_clic}")
                        break

                datos_tarjetas = page.evaluate("""
                    () => {
                        const resultados = [];
                        const vistos = new Set();
                        const links = document.querySelectorAll('a[href*="/producto/"]');
                        for (const a of links) {
                            const href = a.getAttribute('href') || '';
                            const m = href.match(/\\/producto\\/(\\d+)(?:-|$)/);
                            if (!m) continue;
                            const codigo = m[1];
                            if (vistos.has(codigo)) continue;
                            vistos.add(codigo);

                            let nombre = '';
                            const elNombre = document.getElementById('product-card-handler-detail-description-' + codigo);
                            if (elNombre) nombre = elNombre.getAttribute('title') || elNombre.innerText || '';

                            let marca = '';
                            const elMarca = document.getElementById('product-card-handler-detail-brand-' + codigo);
                            if (elMarca) marca = elMarca.innerText || '';

                            let precioTexto = '';
                            const elPrecio = document.getElementById('product-all-price-normal-' + codigo);
                            if (elPrecio) precioTexto = elPrecio.innerText || '';

                            const card = a.closest('.card-ftd, .product-card, [class*="card"], [class*="product"]') || a.parentElement;
                            if (card) {
                                if (!nombre) {
                                    const t = card.querySelector('[id^="product-card-handler-detail-description-"], .text-title, h2, h3, p');
                                    if (t) nombre = t.getAttribute('title') || t.innerText || '';
                                }
                                if (!marca) {
                                    const bEl = card.querySelector('[id^="product-card-handler-detail-brand-"], .text-brand, [class*="brand"]');
                                    if (bEl) marca = bEl.innerText || '';
                                }
                                if (!precioTexto) {
                                    const pEl = card.querySelector('[id^="product-all-price-"], .price__text-price, .text-price, [class*="price"]');
                                    if (pEl) precioTexto = pEl.innerText || '';
                                }
                            }

                            resultados.push({ id: codigo, nombre: nombre.trim(), marca: marca.trim(), precio_str: precioTexto.trim(), href: href });
                        }
                        return resultados;
                    }
                """)

                convertidos = []
                for d in datos_tarjetas:
                    precio = limpiar_precio_cop(d.get("precio_str"))
                    nombre = d.get("nombre") or d.get("href", "").split("/")[-1].replace("-", " ").upper()
                    if precio > 0 and nombre:
                        convertidos.append({
                            "id": d["id"],
                            "nombre": nombre,
                            "marca": d.get("marca", ""),
                            "principios": [],
                            "categoria": nombre_cat.upper(),
                            "presentacion": "",
                            "cantidad_explicita": "",
                            "precio": precio,
                            "precio_lista": precio,
                            "disponible": True,
                            "url": urllib.parse.urljoin(base + "/", d["href"]),
                        })

                yield f"Farmatodo '{nombre_cat}'", convertidos

            except Exception as e:
                logger.error(f"    [!] Error en Farmatodo categoría '{nombre_cat}': {e}")
                try:
                    page.close()
                except Exception:
                    pass
                page = context.new_page()
                continue

        try:
            browser.close()
        except Exception:
            pass


# ==============================================================================
# 4. MOTOR PLAYWRIGHT PARA CRUZ VERDE (SIN LÍMITES Y CON ESPERA PACIENTE)
# ==============================================================================
def parsear_html_cruzverde(html_texto, base_url="https://www.cruzverde.com.co", categoria_nombre=""):
    bloques = re.findall(r"<ml-card-product\b.*?</ml-card-product>", html_texto, re.DOTALL | re.IGNORECASE)
    resultados = []

    for bloque in bloques:
        try:
            codigo = ""
            m_img = re.search(r'src="[^"]*?/(\d{4,14})[_-][^"]+?\.(?:jpg|png|webp|jpeg)"', bloque, re.IGNORECASE)
            if m_img:
                codigo = m_img.group(1)

            nombre = ""
            m_alt = re.search(r'<img[^>]+?\balt="([^"]+)"', bloque, re.IGNORECASE)
            if m_alt and m_alt.group(1).strip().lower() not in ("fail", "logo", ""):
                nombre = html.unescape(m_alt.group(1)).strip()

            m_link = re.search(r'<at-link[^>]*>\s*<a([^>]+)>', bloque, re.IGNORECASE)
            if not nombre and m_link:
                m_id = re.search(r'\bid="([^"]+)"', m_link.group(1))
                if m_id:
                    nombre = html.unescape(m_id.group(1)).strip()

            if not codigo and nombre:
                codigo = re.sub(r"[^A-Z0-9]", "", nombre.upper())[:12]

            m_marca = re.search(r'class="[^"]*\bitalic\s+uppercase\b[^"]*"[^>]*>\s*([^<]+?)\s*</div>', bloque, re.IGNORECASE)
            marca = html.unescape(m_marca.group(1)).strip() if m_marca else ""

            m_precio = re.search(r'class="[^"]*\btext-prices\b[^"]*"[^>]*>\s*\$?\s*([\d.,]+)\s*</span>', bloque, re.IGNORECASE)
            precio = limpiar_precio_cop(m_precio.group(1)) if m_precio else 0.0

            m_normal = re.search(r'class="[^"]*\bline-through\b[^"]*"[^>]*>\s*\$?\s*([\d.,]+)', bloque, re.IGNORECASE)
            precio_lista = limpiar_precio_cop(m_normal.group(1)) if m_normal else precio

            if not nombre or precio <= 0:
                continue

            if codigo and codigo.isdigit():
                nombre_url = re.sub(r'[^a-zA-Z0-9]+', '_', nombre.lower()).strip('_')
                url_prod = f"{base_url}/{nombre_url}/COCV_{codigo}.html"
            else:
                url_prod = f"{base_url}/search?query={urllib.parse.quote(nombre)}"

            resultados.append({
                "id": codigo,
                "nombre": nombre,
                "marca": marca,
                "principios": [],
                "categoria": categoria_nombre,
                "presentacion": "",
                "cantidad_explicita": "",
                "precio": precio,
                "precio_lista": precio_lista if precio_lista > 0 else precio,
                "disponible": True,
                "url": url_prod,
            })
        except Exception:
            continue

    return resultados


def iterar_playwright_cruzverde(cliente, config, max_paginas=None):
    try:
        from playwright.sync_api import sync_playwright
    except Exception as e:
        logger.error(f"  [!] Falló importación de Playwright: {e}")
        return

    base = config["base_url"]

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1920, "height": 1080}, user_agent=USER_AGENT)
        page = context.new_page()

        for nombre_cat, ruta_cat in CATEGORIAS_CRUZ_VERDE:
            url_cat = base + ruta_cat
            try:
                logger.debug(f"Playwright Cruz Verde abriendo: {url_cat}")
                page.goto(url_cat, wait_until="domcontentloaded", timeout=40000)
                page.wait_for_timeout(4500)

                page.evaluate("""
                    () => {
                        document.querySelectorAll('or-modal-location, aside#modal, .modal-backdrop').forEach(el => el.remove());
                    }
                """)

                num_clic = 0
                while True:
                    if max_paginas is not None and num_clic >= max_paginas:
                        break

                    try:
                        btn = page.locator("button:has-text('Ver más productos')")
                        listo = False

                        # Espera paciente de hasta 8 segundos haciendo scroll y limpiando modales
                        for _ in range(8):
                            page.evaluate("""
                                () => {
                                    document.querySelectorAll('or-modal-location, aside#modal, .modal-backdrop').forEach(el => el.remove());
                                    window.scrollTo(0, document.body.scrollHeight);
                                }
                            """)
                            if btn.count() > 0 and btn.first.is_visible():
                                listo = True
                                break
                            page.wait_for_timeout(1000)

                        if not listo:
                            break

                        antes = page.locator("ml-card-product").count()
                        btn.first.click(timeout=3000, force=True)
                        num_clic += 1
                        logger.debug(f"  Cruz Verde '{nombre_cat}': clic #{num_clic} (Llevamos {antes} tarjetas)")

                        for _ in range(10):
                            page.wait_for_timeout(1000)
                            if page.locator("ml-card-product").count() > antes:
                                break
                        else:
                            break
                    except Exception:
                        break

                html_renderizado = page.content()
                lote = parsear_html_cruzverde(html_renderizado, base, nombre_cat)
                yield f"Cruz Verde '{nombre_cat}'", lote

            except Exception as e:
                logger.error(f"    [!] Error en Cruz Verde '{nombre_cat}': {e}")
                continue

        try:
            browser.close()
        except Exception:
            pass


# ==============================================================================
# 5. MOTOR PLAYWRIGHT PARA HABIB DROGUERÍAS (SIN LÍMITES Y CON ESPERA PACIENTE)
# ==============================================================================
def obtener_urls_categorias_habib(cliente, base_url):
    url_arbol = f"{base_url}/api/catalog_system/pub/category/tree/3"
    categorias = []
    try:
        texto, _ = cliente.pedir(url_arbol)
        arbol = json.loads(texto)

        def recorrer(nodos):
            for n in nodos:
                hijos = n.get("children") or []
                if hijos:
                    recorrer(hijos)
                else:
                    url_cat = n.get("url", "")
                    nombre = n.get("name", "")
                    if url_cat:
                        parsed = urllib.parse.urlparse(url_cat)
                        ruta = parsed.path if parsed.scheme else url_cat
                        categorias.append((nombre, ruta))

        if isinstance(arbol, list):
            recorrer(arbol)
    except Exception as e:
        logger.warning(f"  [!] No se pudo bajar árbol VTEX de Habib ({e}), usando respaldo.")

    return categorias if categorias else CATEGORIAS_HABIB_RESPALDO


def iterar_playwright_habib(cliente, config, max_paginas=None):
    try:
        from playwright.sync_api import sync_playwright
    except Exception as e:
        logger.error(f"  [!] Falló importación de Playwright: {e}")
        return

    base = config["base_url"].rstrip("/")
    categorias = obtener_urls_categorias_habib(cliente, base)
    logger.info(f"  Categorías a recorrer en Habib Droguerías: {len(categorias)}")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1920, "height": 1080}, user_agent=USER_AGENT)
        page = context.new_page()

        for nombre_cat, ruta_cat in categorias:
            url_cat = f"{base}/{ruta_cat.lstrip('/')}"
            try:
                logger.debug(f"Playwright Habib abriendo: {url_cat}")
                page.goto(url_cat, wait_until="domcontentloaded", timeout=40000)
                page.wait_for_timeout(4000)

                selector_btn = (
                    "button.vtex-button:has-text('Mostrar más'), "
                    "a.vtex-button:has-text('Mostrar más'), "
                    "button.vtex-button:has-text('Ver más'), "
                    "a.vtex-button:has-text('Ver más'), "
                    "[class*='fetchMore'] button.vtex-button, "
                    "[class*='search-fetch-more'] button.vtex-button"
                )

                num_clic = 0
                while True:
                    if max_paginas is not None and num_clic >= max_paginas:
                        break

                    try:
                        btn = page.locator(selector_btn)
                        listo = False

                        # Espera paciente de hasta 8 segundos haciendo scroll para que aparezca el botón
                        for _ in range(8):
                            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                            if btn.count() > 0 and btn.first.is_visible():
                                listo = True
                                break
                            page.wait_for_timeout(1000)

                        if not listo:
                            break

                        antes = page.locator('a[href$="/p"], a[href*="/p?"]').count()
                        btn.first.scroll_into_view_if_needed(timeout=2000)
                        btn.first.click(timeout=3000, force=True)
                        num_clic += 1
                        logger.debug(f"  Habib '{nombre_cat}': clic #{num_clic} (Llevamos {antes} productos)")

                        for _ in range(10):
                            page.wait_for_timeout(1000)
                            if page.locator('a[href$="/p"], a[href*="/p?"]').count() > antes:
                                break
                        else:
                            break

                    except Exception as ex_clic:
                        logger.debug(f"  Fin de clics en Habib '{nombre_cat}': {ex_clic}")
                        break

                datos_tarjetas = page.evaluate("""
                    () => {
                        const resultados = [];
                        const vistos = new Set();
                        const links = document.querySelectorAll('a[href$="/p"], a[href*="/p?"]');

                        for (const a of links) {
                            const href = a.getAttribute('href') || '';
                            const limpioHref = href.split('?')[0];
                            if (!limpioHref || vistos.has(limpioHref)) continue;
                            vistos.add(limpioHref);

                            const card = a.closest('section, article, [class*="product-summary"], [class*="galleryItem"]') || a;

                            let nombre = '';
                            const elNombre = card.querySelector('[class*="productBrand"], [class*="productName"], h2, h3');
                            if (elNombre) nombre = elNombre.innerText || '';

                            let marca = '';
                            const elMarca = card.querySelector('[class*="productBrandName"], [class*="brandName"], [class*="brand"]');
                            if (elMarca && elMarca !== elNombre) marca = elMarca.innerText || '';

                            let precioTexto = '';
                            const elPrecio = card.querySelector('[class*="sellingPriceValue"], [class*="sellingPrice"], [class*="Price"]');
                            if (elPrecio) precioTexto = elPrecio.innerText || '';

                            let precioListaTexto = '';
                            const elLista = card.querySelector('[class*="listPriceValue"], [class*="listPrice"]');
                            if (elLista) precioListaTexto = elLista.innerText || '';

                            let codigo = '';
                            const img = card.querySelector('img[src*="ids/"]');
                            if (img) {
                                const mImg = img.src.match(/\\/ids\\/(\\d+)/);
                                if (mImg) codigo = mImg[1];
                            }
                            if (!codigo) {
                                codigo = limpioHref.replace(/^\\/|\\/p$/g, '');
                            }

                            resultados.push({
                                id: codigo,
                                nombre: nombre.trim(),
                                marca: marca.trim(),
                                precio_str: precioTexto.trim(),
                                precio_lista_str: precioListaTexto.trim(),
                                href: limpioHref
                            });
                        }
                        return resultados;
                    }
                """)

                convertidos = []
                for d in datos_tarjetas:
                    precio = limpiar_precio_cop(d.get("precio_str"))
                    precio_lista = limpiar_precio_cop(d.get("precio_lista_str")) or precio
                    nombre = d.get("nombre") or d.get("href", "").strip("/").replace("/p", "").replace("-", " ").upper()

                    if precio > 0 and nombre:
                        convertidos.append({
                            "id": d["id"],
                            "nombre": nombre,
                            "marca": d.get("marca", ""),
                            "principios": [],
                            "categoria": nombre_cat.upper(),
                            "presentacion": "",
                            "cantidad_explicita": "",
                            "precio": precio,
                            "precio_lista": precio_lista,
                            "disponible": True,
                            "url": urllib.parse.urljoin(base + "/", d["href"]),
                        })

                yield f"Habib '{nombre_cat}'", convertidos

            except Exception as e:
                logger.error(f"    [!] Error en Habib categoría '{nombre_cat}': {e}")
                try:
                    page.close()
                except Exception:
                    pass
                page = context.new_page()
                continue

        try:
            browser.close()
        except Exception:
            pass

# ==============================================================================
# 6. MOTOR PLAYWRIGHT PARA TU DROGUERÍA VIRTUAL (INTERCEPTOR JSON VTEX)
# ==============================================================================
def iterar_playwright_tudrogueria(cliente, config, max_paginas=None):
    try:
        from playwright.sync_api import sync_playwright
    except Exception as e:
        logger.error(f"  [!] Falló importación de Playwright: {e}")
        return

    base = config["base_url"].rstrip("/")
    logger.info(f"  Categorías a recorrer en Tu Droguería Virtual: {len(CATEGORIAS_TUDROGUERIA)}")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1920, "height": 1080}, user_agent=USER_AGENT)
        page = context.new_page()

        for nombre_cat, ruta_cat in CATEGORIAS_TUDROGUERIA:
            url_cat = f"{base}/{ruta_cat.lstrip('/')}"
            productos_categoria = []
            skus_vistos = set()

            def procesar_producto_json(prod):
                try:
                    product_id = str(prod.get("productId") or prod.get("id") or "")
                    nombre = prod.get("productName") or prod.get("name") or ""
                    marca = prod.get("brand") or ""
                    link = prod.get("link") or prod.get("linkText") or ""
                    if link and not link.startswith("http"):
                        if not link.startswith("/"):
                            link = "/" + link
                        if not link.endswith("/p"):
                            link = link + "/p"
                        link = base + link

                    # Extracción exacta desde priceRange (según captura de VTEX IO)
                    price_range = prod.get("priceRange") or {}
                    selling_range = price_range.get("sellingPrice") or {}
                    list_range = price_range.get("listPrice") or {}

                    precio = float(selling_range.get("lowPrice") or selling_range.get("highPrice") or 0.0)
                    precio_lista = float(list_range.get("highPrice") or list_range.get("lowPrice") or precio)

                    items = prod.get("items") or []
                    sku_id = product_id
                    if items:
                        primer_item = items[0]
                        sku_id = str(primer_item.get("itemId") or product_id)
                        sellers = primer_item.get("sellers") or []
                        if sellers and precio <= 0:
                            comm_offer = sellers[0].get("commertialOffer") or {}
                            precio = float(comm_offer.get("Price") or 0.0)
                            precio_lista = float(comm_offer.get("ListPrice") or precio)

                    if not sku_id or sku_id in skus_vistos:
                        return
                    if precio <= 0 or not nombre:
                        return

                    skus_vistos.add(sku_id)
                    productos_categoria.append({
                        "id": sku_id,
                        "nombre": nombre.strip(),
                        "marca": marca.strip(),
                        "principios": [],
                        "categoria": nombre_cat.upper(),
                        "presentacion": "",
                        "cantidad_explicita": "",
                        "precio": precio,
                        "precio_lista": precio_lista,
                        "disponible": True,
                        "url": link,
                    })
                except Exception:
                    pass

            # Listener que captura automáticamente los JSON de productos en tránsito
            def interceptar_red(response):
                try:
                    url = response.url.lower()
                    if any(k in url for k in ["graphql", "search", "products", "query"]):
                        ct = response.headers.get("content-type", "")
                        if "json" in ct:
                            data = response.json()
                            if isinstance(data, dict):
                                # Casos GraphQL VTEX
                                g_data = data.get("data") or {}
                                prods = (
                                    g_data.get("products")
                                    or (g_data.get("productSearch") or {}).get("products")
                                    or []
                                )
                                for pr in prods:
                                    procesar_producto_json(pr)
                            elif isinstance(data, list):
                                for pr in data:
                                    if isinstance(pr, dict):
                                        procesar_producto_json(pr)
                except Exception:
                    pass

            page.on("response", interceptar_red)

            try:
                logger.debug(f"Playwright Tu Droguería Virtual abriendo: {url_cat}")
                page.goto(url_cat, wait_until="domcontentloaded", timeout=40000)
                page.wait_for_timeout(3500)

                # Extraer también del estado inicial renderizado en HTML (__STATE__)
                try:
                    estado_inicial = page.evaluate("""
                        () => {
                            if (window.__STATE__) {
                                const resultados = [];
                                for (const k in window.__STATE__) {
                                    if (window.__STATE__[k].__typename === 'Product' || window.__STATE__[k].productId) {
                                        resultados.push(window.__STATE__[k]);
                                    }
                                }
                                return resultados;
                            }
                            return [];
                        }
                    """)
                    for p_state in estado_inicial:
                        procesar_producto_json(p_state)
                except Exception:
                    pass

                selector_btn = (
                    "button.vtex-button:has(div.vtex-button__label:has-text('Mostrar más')), "
                    "button.vtex-button:has(div.vtex-button__label:has-text('Ver más')), "
                    "a.vtex-button:has(div.vtex-button__label:has-text('Mostrar más')), "
                    "a.vtex-button:has(div.vtex-button__label:has-text('Ver más')), "
                    "[class*='fetchMore'] button.vtex-button, "
                    "[class*='search-fetch-more'] button.vtex-button, "
                    "div.vtex-button__label:has-text('Mostrar más'), "
                    "div.vtex-button__label:has-text('Ver más')"
                )

                num_clic = 0
                intentos_sin_cambio = 0

                while True:
                    if max_paginas is not None and num_clic >= max_paginas:
                        break

                    try:
                        listo = False
                        btn_actual = None

                        for _ in range(15):
                            page.evaluate("window.scrollBy(0, -350)")
                            page.wait_for_timeout(300)
                            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")

                            current_btn = page.locator(selector_btn).first
                            if current_btn.count() > 0 and current_btn.is_visible():
                                btn_actual = current_btn
                                listo = True
                                break
                            page.wait_for_timeout(1000)

                        if not listo or not btn_actual:
                            break

                        cant_antes = len(productos_categoria)

                        try:
                            btn_actual.scroll_into_view_if_needed(timeout=3000)
                            page.wait_for_timeout(300)
                            btn_actual.evaluate("el => el.click()")
                        except Exception:
                            page.evaluate("""
                                () => {
                                    const btns = Array.from(document.querySelectorAll('button, a')).filter(el => {
                                        const text = el.innerText || '';
                                        return text.includes('Mostrar más') || text.includes('Ver más');
                                    });
                                    if (btns.length > 0) btns[0].click();
                                }
                            """)

                        num_clic += 1
                        logger.debug(
                            f"  Tu Droguería '{nombre_cat}': clic #{num_clic} (Capturados {cant_antes} productos en JSON)"
                        )

                        # Esperar hasta 12s a que la red responda con el nuevo JSON
                        recibidos_nuevos = False
                        for _ in range(12):
                            page.wait_for_timeout(1000)
                            if len(productos_categoria) > cant_antes:
                                recibidos_nuevos = True
                                intentos_sin_cambio = 0
                                break

                        if not recibidos_nuevos:
                            intentos_sin_cambio += 1
                            if intentos_sin_cambio >= 3:
                                break
                            continue

                    except Exception as ex_clic:
                        logger.debug(f"  Fin de clics en Tu Droguería '{nombre_cat}': {ex_clic}")
                        break

                yield f"Tu Droguería '{nombre_cat}'", productos_categoria

            except Exception as e:
                logger.error(f"    [!] Error en Tu Droguería categoría '{nombre_cat}': {e}")
                continue
            finally:
                page.remove_listener("response", interceptar_red)

        try:
            browser.close()
        except Exception:
            pass

# ==============================================================================
# DICCIONARIO DE MOTORES
# ==============================================================================
ITERADORES = {
    "vtex": iterar_catalogo_vtex,
    "playwright_habib": iterar_playwright_habib,
    "playwright_tudrogueria": iterar_playwright_tudrogueria,
    "playwright_laeconomia": iterar_playwright_laeconomia,
    "playwright_farmatodo": iterar_playwright_farmatodo,
    "playwright_cruzverde": iterar_playwright_cruzverde,
}


# ==============================================================================
# NORMALIZACIÓN Y CURACIÓN DE PRODUCTOS
# ==============================================================================
def inferir_marca_del_nombre(nombre):
    nombre_limpio = limpiar_acentos(nombre)
    for m in sorted(MARCAS_CONOCIDAS, key=len, reverse=True):
        m_limpia = limpiar_acentos(m.strip())
        if re.search(rf"\b{re.escape(m_limpia)}\b", nombre_limpio):
            return m.strip().upper()
    return "GENERICO"


def inferir_principio_del_nombre(nombre):
    nombre_limpio = limpiar_acentos(nombre)
    encontrados = []

    for pa in sorted(PRINCIPIOS_CONOCIDOS, key=len, reverse=True):
        if re.search(rf"\b{re.escape(pa)}\b", nombre_limpio):
            # Evitar duplicados si un principio es subcadena de otro ya detectado
            if not any(pa in existente for existente in encontrados):
                encontrados.append(pa)

    if encontrados:
        return " / ".join(sorted(encontrados))

    for marca_clave, pa_asociado in MARCAS_A_PRINCIPIO.items():
        if re.search(rf"\b{re.escape(marca_clave)}\b", nombre_limpio):
            return pa_asociado

    return None


def determinar_principio_o_categoria(principios_lista, categoria_cruda, nombre_producto):
    inferido = inferir_principio_del_nombre(nombre_producto)
    if inferido:
        return inferido

    if principios_lista:
        limpios = [
            p.strip().upper() for p in principios_lista
            if p.strip() and p.strip().upper() not in PRINCIPIOS_BASURA
        ]
        if limpios:
            unido = " / ".join(limpios)
            if limpiar_acentos(unido) in PRINCIPIOS_CONOCIDOS:
                return unido

    return clasificar_macrocategoria(categoria_cruda, nombre_producto)


def extraer_unidades_universal(item_crudo):
    presentacion = item_crudo.get("presentacion", "")
    nombre = item_crudo.get("nombre", "")

    for texto in (presentacion, nombre):
        m = RE_UNIDADES.search(texto)
        if m:
            num = m.group(1) or m.group(2) or m.group(3)
            try:
                val = int(num)
                if val > 0:
                    return presentacion or m.group(0).strip().upper(), val
            except ValueError:
                pass

    if item_crudo.get("cantidad_explicita"):
        try:
            val = int(float(item_crudo["cantidad_explicita"]))
            if val > 0:
                return presentacion or f"X {val}", val
        except ValueError:
            pass

    return presentacion or "UNIDAD", 1


def procesar_producto(item, nombre_farmacia, fecha, descartes):
    nombre = re.sub(r"\s+", " ", item.get("nombre", "")).strip()
    if not nombre:
        return None

    precio = float(item.get("precio") or 0.0)
    if not item.get("disponible", True) or precio <= 0:
        descartes["agotado / sin precio"] += 1
        return None

    m_conc = RE_CONCENTRACION.search(nombre)
    if m_conc:
        unidad_conc = m_conc.group(2).upper()
        if unidad_conc == "GR":
            unidad_conc = "G"
        concentracion = f"{m_conc.group(1).replace(',', '.')} {unidad_conc}"
    else:
        concentracion = "N/A"

    marca = (item.get("marca") or "").strip().upper()
    if not marca or marca in PRINCIPIOS_BASURA:
        marca = inferir_marca_del_nombre(nombre)

    principio_activo = determinar_principio_o_categoria(
        item.get("principios") or [],
        item.get("categoria") or "",
        nombre,
    )

    presentacion, unidades = extraer_unidades_universal(item)
    precio_lista = round(float(item.get("precio_lista") or precio))

    codigo_raw = str(item.get("id", "")).strip()
    if codigo_raw.endswith(".0"):
        codigo_raw = codigo_raw[:-2]

    return {
        "fecha": fecha,
        "farmacia": nombre_farmacia,
        "codigo": codigo_raw,
        "principio_activo": principio_activo,
        "concentracion": concentracion,
        "producto": nombre,
        "marca": marca,
        "presentacion": presentacion,
        "unidades": unidades,
        "precio": round(precio),
        "precio_lista": precio_lista,
        "precio_unidad": round(precio / unidades, 2),
        "url": item.get("url", "").split("?")[0].strip(),
    }


def curar_csv_existente(ruta_csv):
    if not ruta_csv.exists():
        return
    filas_limpias = []
    cambios = 0
    with ruta_csv.open("r", encoding="utf-8", errors="replace") as f:
        reader = csv.DictReader(f)
        campos = reader.fieldnames or COLUMNAS
        for fila in reader:
            nombre = fila.get("producto", "")
            pa_actual = (fila.get("principio_activo") or "").strip().upper()
            marca = (fila.get("marca") or "").strip().upper()
            conc = (fila.get("concentracion") or "").strip()
            cod = (fila.get("codigo") or "").strip()

            if cod.endswith(".0"):
                fila["codigo"] = cod[:-2]

            if not conc:
                m_c = RE_CONCENTRACION.search(nombre)
                fila["concentracion"] = f"{m_c.group(1).replace(',', '.')} {m_c.group(2).upper()}" if m_c else "N/A"

            if not marca or marca in PRINCIPIOS_BASURA:
                fila["marca"] = inferir_marca_del_nombre(nombre)
                cambios += 1

            pa_sin_acentos = limpiar_acentos(pa_actual)
            es_principio_real = (
                pa_sin_acentos in PRINCIPIOS_CONOCIDOS
                or any(re.search(rf"\b{re.escape(p)}\b", pa_sin_acentos) for p in PRINCIPIOS_CONOCIDOS)
            ) and "0 NO CODIFICADO" not in pa_sin_acentos

            if es_principio_real:
                nuevo_pa = pa_actual
            else:
                inferido = inferir_principio_del_nombre(nombre)
                nuevo_pa = inferido if inferido else clasificar_macrocategoria(pa_actual, nombre)

            if nuevo_pa != pa_actual:
                fila["principio_activo"] = nuevo_pa
                cambios += 1

            filas_limpias.append(fila)

    with ruta_csv.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=campos)
        writer.writeheader()
        writer.writerows(filas_limpias)
    logger.info(f"  [Curación] {ruta_csv.name}: {len(filas_limpias)} filas revisadas ({cambios} categorías unificadas).")


def main():
    parser = argparse.ArgumentParser(description="Scraper Maestro Multi-Farmacia sin límites con Curación.")
    parser.add_argument(
        "--farmacias",
        nargs="+",
        choices=list(FARMACIAS_CONFIG.keys()),
        default=list(FARMACIAS_CONFIG.keys()),
        help="Farmacias a consultar.",
    )
    parser.add_argument("--max-paginas", type=int, default=None)
    parser.add_argument(
        "--solo-curar",
        action="store_true",
        help="Repara y unifica inmediatamente base.csv y precios.csv sin volver a descargar de internet.",
    )
    args = parser.parse_args()

    if args.solo_curar:
        curar_csv_existente(DATA_DIR / "base.csv")
        curar_csv_existente(DATA_DIR / "precios.csv")
        return

    fecha = datetime.date.today().isoformat()
    filas_totales = []
    cliente = ClienteHTTP(pausa_s=PAUSA_S)

    with SALIDA.open("w", newline="", encoding="utf-8") as f_csv:
        writer = csv.DictWriter(f_csv, fieldnames=COLUMNAS)
        writer.writeheader()

        for clave_farmacia in args.farmacias:
            config = FARMACIAS_CONFIG[clave_farmacia]
            nombre_farmacia = config["nombre"]
            iterador = ITERADORES.get(config["tipo"])
            if not iterador:
                continue

            logger.info(f"\n=== Barriendo catálogo de {nombre_farmacia} ({config['base_url']}) ===")
            vistos = set()
            descartes = {"agotado / sin precio": 0}
            filas_farmacia = 0

            try:
                for descripcion_lote, lote_crudo in iterador(cliente, config, max_paginas=args.max_paginas):
                    nuevos_lote = 0
                    for item in lote_crudo:
                        try:
                            uid = item.get("id") or item.get("url")
                            if not uid or uid in vistos:
                                continue
                            vistos.add(uid)
                            fila = procesar_producto(item, nombre_farmacia, fecha, descartes)
                            if fila:
                                writer.writerow(fila)
                                filas_totales.append(fila)
                                nuevos_lote += 1
                                filas_farmacia += 1
                        except Exception:
                            continue
                    f_csv.flush()
                    logger.info(
                        f"  [{descripcion_lote}] {len(lote_crudo)} vistos "
                        f"-> +{nuevos_lote} guardados (Acumulado {nombre_farmacia}: {filas_farmacia})"
                    )
            except Exception as e:
                logger.error(f"  [!] Error general en {nombre_farmacia}: {e}", exc_info=True)

    curar_csv_existente(DATA_DIR / "base.csv")

    ruta_unir = BASE_DIR / "unir_precios.py"
    if ruta_unir.exists():
        logger.info("\nEjecutando unir_precios.py para actualizar base.csv y precios.csv...")
        try:
            subprocess.run([sys.executable, str(ruta_unir), "--actualizar-base"], check=True)
            curar_csv_existente(DATA_DIR / "precios.csv")
        except Exception as e:
            logger.error(f"[!] Error al ejecutar unir_precios.py: {e}")


if __name__ == "__main__":
    main()