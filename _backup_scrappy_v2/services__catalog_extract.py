"""
Descarga masiva de catálogos de farmacias VTEX (VTEX Intelligent Search API).

Porta al proyecto web la lógica del extractor de catálogos (scrapys) para las
farmacias VTEX: Farmanorte, Tu Droguería Virtual, La Rebaja Virtual y Farmacias
Pasteur. A diferencia del comparador por EAN (que usa el catálogo público), aquí
se pagina el endpoint de búsqueda inteligente de VTEX y se extraen campos ricos:
precio, precio de lista, registro sanitario (INVIMA), PUM, código de barras y stock.

Flujo por cada enlace de búsqueda pegado por el usuario:
  1. parsear_url(url)  -> (facet_path, query, nombre)
  2. paginar {base}/_v/api/intelligent-search/product_search/{facet_path}
  3. extraer cada producto/ítem -> fila normalizada
  4. consolidar todo en un DataFrame y exportar a Excel (una hoja por búsqueda).
"""
from __future__ import annotations

import re
import time
import unicodedata
from datetime import date
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse, parse_qs, unquote

import pandas as pd
import requests

from config import RETAILERS

PAGE_SIZE = 50      # productos por página (máximo que permite VTEX)
MAX_PAGINAS = 100
PAUSA = 0.5         # segundos entre páginas (para no saturar)
TIMEOUT = 60

HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "es-CO,es;q=0.9,en;q=0.8",
}

COLUMNAS = [
    "fecha", "tienda", "busqueda", "sku", "codigo_barras", "ref_tienda", "producto",
    "marca", "presentacion", "registro_sanitario", "pum", "categoria", "precio",
    "precio_lista", "stock", "disponible", "url",
]

# Tiendas soportadas por el extractor (todas VTEX con Intelligent Search).
# clave -> (nombre visible, dominios para detectar la tienda desde el enlace)
EXTRACT_STORES: dict[str, tuple[str, list[str]]] = {
    "farmanorte": ("Farmanorte", ["farmanorte.com.co"]),
    "tudrogueriavirtual": ("Tu Droguería Virtual", ["tudrogueriavirtual.com"]),
    "larebajavirtual": ("La Rebaja Virtual", ["larebajavirtual.com"]),
    "farmaciaspasteur": ("Farmacias Pasteur", ["farmaciaspasteur.com.co"]),
}


def detectar_tienda(url: str) -> Optional[str]:
    """Devuelve la clave de tienda reconocida desde un enlace, o None."""
    host = (urlparse(url.strip()).hostname or "").lower()
    for key, (_nombre, dominios) in EXTRACT_STORES.items():
        for dom in dominios:
            if host == dom or host.endswith("." + dom):
                return key
    return None


def tiendas_soportadas() -> list[str]:
    """Lista de nombres visibles de tiendas soportadas (para mensajes)."""
    return [nombre for _k, (nombre, _d) in EXTRACT_STORES.items()]


def _norm(txt) -> str:
    txt = unicodedata.normalize("NFKD", str(txt or ""))
    txt = "".join(c for c in txt if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", txt).lower().strip()


def _nombre_seguro(txt: str) -> str:
    txt = unicodedata.normalize("NFKD", str(txt))
    txt = "".join(c for c in txt if not unicodedata.combining(c))
    txt = re.sub(r'[\\/:*?"<>|]+', "", txt).strip()
    return re.sub(r"\s+", "_", txt) or "busqueda"


# ── URL -> parámetros de búsqueda ───────────────────────────────────────────
CLAVES_QUERY = ("_q", "q", "query", "ft", "keyword", "term", "search", "s")
SEGMENTOS_GENERICOS = {"buscar", "search", "busqueda", "busca", "s", "productos", "catalogo"}


def parsear_url(url: str):
    """Devuelve (facet_path, query, nombre, final) a partir de un enlace VTEX."""
    u = urlparse(url.strip())
    qs = parse_qs(u.query)
    segmentos = [unquote(s).strip() for s in u.path.split("/") if s]
    mapa = qs.get("map", [""])[0].split(",") if qs.get("map") else []

    query = ""
    for k in CLAVES_QUERY:
        if qs.get(k) and qs[k][0].strip():
            query = qs[k][0].strip()
            break

    facets, cat_n = [], 0
    for i, seg in enumerate(segmentos):
        clave = mapa[i] if i < len(mapa) else ""
        if clave == "ft":
            query = query or seg
            continue
        if not clave and seg.lower() in SEGMENTOS_GENERICOS:
            continue
        if clave in ("", "c"):
            cat_n += 1
            clave = f"category-{cat_n}"
        elif clave == "b":
            clave = "brand"
        facets.append(f"{clave}/{seg}")

    final = segmentos[-1] if segmentos else ""
    nombre = (query or final or "busqueda").replace("+", " ").strip()
    return "/".join(facets), query, nombre, final


# ── Lectura de productos (VTEX Intelligent Search) ─────────────────────────
def _prop(p, *nombres):
    """Lee una propiedad del producto (clave directa o dentro de 'properties')."""
    objetivo = {_norm(n) for n in nombres}
    for k, v in p.items():
        if _norm(k) in objetivo and isinstance(v, list) and v and not isinstance(v[0], dict):
            return str(v[0])
    for pr in p.get("properties") or []:
        if _norm(pr.get("name", "")) in objetivo:
            vals = pr.get("values") or []
            if vals:
                return str(vals[0])
    return ""


def _codigo_barras(p, item):
    """Elige el código de barras real entre productReference, ean y la URL."""
    candidatos = [p.get("productReference"), item.get("ean")]
    candidatos += [r.get("Value") for r in (item.get("referenceId") or [])]
    m = re.search(r"-(\d{8,14})(?:/p)?/?$", p.get("link") or "")
    if m:
        candidatos.append(m.group(1))
    limpios = [re.sub(r"\D", "", str(c)) for c in candidatos if c]
    for c in limpios:
        if 12 <= len(c) <= 14:
            return c
    for c in limpios:
        if len(c) >= 8:
            return c
    return ""


def _fila(p, item, tienda, busqueda, base_url):
    sellers = item.get("sellers") or []
    seller = next((s for s in sellers if s.get("sellerDefault")), sellers[0] if sellers else {})
    offer = seller.get("commertialOffer") or {}
    cats = [c.strip("/") for c in (p.get("categories") or [])]
    link = p.get("link") or ""
    return {
        "fecha": date.today(),
        "tienda": tienda,
        "busqueda": busqueda,
        "sku": item.get("itemId"),
        "codigo_barras": _codigo_barras(p, item),
        "ref_tienda": p.get("productReference") or "",
        "producto": p.get("productName"),
        "marca": p.get("brand"),
        "presentacion": _prop(p, "Presentación", "Presentacion"),
        "registro_sanitario": _prop(p, "ID Invima", "Registro Sanitario", "Invima"),
        "pum": _prop(p, "pum"),
        "categoria": " | ".join(cats),
        "precio": offer.get("Price"),
        "precio_lista": offer.get("ListPrice"),
        "stock": offer.get("AvailableQuantity"),
        "disponible": offer.get("IsAvailable"),
        "url": link if link.startswith("http") else base_url.rstrip("/") + link,
    }


def _crear_sesion(base_url):
    s = requests.Session()
    s.headers.update(HEADERS)
    s.headers["Referer"] = base_url.rstrip("/") + "/"
    try:
        s.get(base_url.rstrip("/") + "/", timeout=30, stream=True).close()
    except requests.RequestException:
        pass
    return s


def _pedir(session, base_url, facet_path, query, page, intentos=4):
    url = base_url.rstrip("/") + "/_v/api/intelligent-search/product_search/" + facet_path
    params = {"query": query, "page": page, "count": PAGE_SIZE, "locale": "es-CO"}
    for i in range(intentos):
        try:
            r = session.get(url, params=params, timeout=TIMEOUT)
            if r.status_code == 200:
                return r.json()
            if r.status_code in (400, 404):
                return {"products": [], "recordsFiltered": 0}
        except (requests.RequestException, ValueError):
            pass
        time.sleep(2 * (i + 1))
    raise RuntimeError("la tienda no respondió")


def descargar_tienda(tienda_key: str, url: str, *, progreso=None, cancelar=None):
    """Baja TODOS los productos de una búsqueda/marca/categoría de una tienda VTEX.

    Devuelve (DataFrame, nombre_usado).
    """
    nombre_visible = EXTRACT_STORES[tienda_key][0]
    base_url = RETAILERS[tienda_key]["base_url"]
    facet_path, query, nombre_auto, final = parsear_url(url)
    nombre = nombre_auto

    def avisar(txt):
        if progreso:
            progreso(txt)

    session = _crear_sesion(base_url)
    filas, vistos, total = [], 0, None

    for page in range(1, MAX_PAGINAS + 1):
        if cancelar is not None and cancelar.is_set():
            raise InterruptedError("Cancelado")
        data = _pedir(session, base_url, facet_path, query, page)
        productos = data.get("products") or []

        # Enlace de marca/categoría sin filtro válido: reintentar como texto.
        if page == 1 and not productos and facet_path and not query and final:
            facet_path, query = "", final.replace("+", " ")
            data = _pedir(session, base_url, facet_path, query, page)
            productos = data.get("products") or []

        rf = data.get("recordsFiltered")
        if rf not in (None, ""):
            try:
                total = int(rf)
            except (TypeError, ValueError):
                total = None
        if not productos:
            break
        vistos += len(productos)
        avisar(f"{vistos} de {total}")
        for p in productos:
            for item in p.get("items") or []:
                filas.append(_fila(p, item, nombre_visible, nombre, base_url))
        if total is not None and vistos >= total:
            break
        time.sleep(PAUSA)

    df = pd.DataFrame(filas, columns=COLUMNAS)
    if not df.empty:
        df = df.drop_duplicates(subset=["sku"]).reset_index(drop=True)
    return df, nombre


# ── Excel: un archivo consolidado, una hoja por búsqueda ───────────────────
def _nombre_hoja(nombre, usados):
    hoja = re.sub(r"[\[\]:*?/\\]", "", str(nombre)).strip()[:31] or "Hoja"
    base_n, n = hoja, 2
    while hoja.lower() in usados:
        sufijo = f"_{n}"
        hoja = base_n[: 31 - len(sufijo)] + sufijo
        n += 1
    usados.add(hoja.lower())
    return hoja


def _formato(ws):
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = ws.dimensions
    for col in ws.columns:
        ancho = max(len(str(c.value)) if c.value is not None else 0 for c in col[:200])
        ws.column_dimensions[col[0].column_letter].width = min(max(ancho + 2, 10), 60)


def generar_excel(resultados, out_dir=None) -> Path:
    """resultados = lista de (tienda, nombre, DataFrame, url). Devuelve la ruta del Excel."""
    out_dir = Path(out_dir) if out_dir else Path(__file__).resolve().parent.parent / "reports"
    out_dir.mkdir(parents=True, exist_ok=True)

    resumen = pd.DataFrame(
        [{"tienda": t, "busqueda": n, "filas": len(df), "link": u} for t, n, df, u in resultados]
    )

    archivo = out_dir / f"catalogos_{date.today().isoformat()}.xlsx"
    for k in range(1, 50):
        candidato = archivo if k == 1 else out_dir / f"catalogos_{date.today().isoformat()}_{k}.xlsx"
        try:
            with pd.ExcelWriter(candidato, engine="openpyxl") as w:
                resumen.to_excel(w, sheet_name="Resumen", index=False)
                _formato(w.sheets["Resumen"])
                usados = {"resumen"}
                for t, n, df, _u in resultados:
                    hoja = _nombre_hoja(f"{t} - {n}" if n else t, usados)
                    df.to_excel(w, sheet_name=hoja, index=False)
                    _formato(w.sheets[hoja])
            return candidato
        except PermissionError:
            continue
    raise PermissionError(f"No se pudo guardar el Excel en {out_dir}")
