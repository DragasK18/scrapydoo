"""
Descarga masiva de catalogos de farmacias (Scrappy Doo). Tres motores en lote:
VTEX Intelligent Search (Farmanorte, TuDrogueriaVirtual, LaRebaja, Pasteur,
La Economia), Algolia (Farmatodo) y OCAPI/SFCC (Cruz Verde). Gestiona trabajos
en segundo plano con progreso por enlace.
"""
from __future__ import annotations

import json
import re
import threading
import time
import unicodedata
import uuid
from datetime import date
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse, parse_qs, unquote

import pandas as pd
import requests

from config import RETAILERS

PAGE_SIZE = 50
PAUSA = 0.4
MAX_PAGINAS = 100
TIMEOUT = 60

HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "es-CO,es;q=0.9,en;q=0.8",
}

ALGOLIA_APP_ID = "VCOJEYD2PO"
ALGOLIA_API_KEY = "eb9544fe7bfe7ec4c1aa5e5bf7740feb"
ALGOLIA_INDEX = "products"

CRUZVERDE_API_BASE = "https://api.cruzverde.com.co"

COLUMNAS = [
    "fecha", "tienda", "busqueda", "sku", "codigo_barras", "ref_tienda", "producto",
    "marca", "presentacion", "registro_sanitario", "pum", "categoria", "precio",
    "precio_lista", "stock", "disponible", "url",
]

EXTRACT_STORES = {
    "farmanorte": {"nombre": "Farmanorte", "dominios": ["farmanorte.com.co"], "engine": "vtex"},
    "tudrogueriavirtual": {"nombre": "Tu Droguería Virtual", "dominios": ["tudrogueriavirtual.com"], "engine": "vtex"},
    "larebajavirtual": {"nombre": "La Rebaja Virtual", "dominios": ["larebajavirtual.com"], "engine": "vtex"},
    "farmaciaspasteur": {"nombre": "Farmacias Pasteur", "dominios": ["farmaciaspasteur.com.co"], "engine": "vtex"},
    "farmatodo": {"nombre": "Farmatodo", "dominios": ["farmatodo.com.co"], "engine": "algolia"},
    "cruzverde": {"nombre": "Cruz Verde", "dominios": ["cruzverde.com.co"], "engine": "ocapi"},
    "droguerialaeconomia": {"nombre": "Droguería La Economía", "dominios": ["droguerialaeconomia.com"], "engine": "vtex"},
}


def detectar_tienda(url):
    host = (urlparse(url.strip()).hostname or "").lower()
    for key, meta in EXTRACT_STORES.items():
        for dom in meta["dominios"]:
            if host == dom or host.endswith("." + dom):
                return key
    return None


def tiendas_soportadas():
    return [m["nombre"] for m in EXTRACT_STORES.values()]


def _int(value):
    if value in (None, ""):
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _norm(txt):
    txt = unicodedata.normalize("NFKD", str(txt or ""))
    txt = "".join(c for c in txt if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", txt).lower().strip()


def _nombre_seguro(txt):
    txt = unicodedata.normalize("NFKD", str(txt))
    txt = "".join(c for c in txt if not unicodedata.combining(c))
    txt = re.sub(r'[\\/:*?"<>|]+', "", txt).strip()
    return re.sub(r"\s+", "_", txt) or "busqueda"


def _parse_query_param(url, nombres):
    qs = parse_qs(urlparse(url.strip()).query)
    for k in nombres:
        if qs.get(k) and qs[k][0].strip():
            return qs[k][0].strip()
    return ""


CLAVES_QUERY = ("_q", "q", "query", "ft", "keyword", "term", "search", "s")
SEGMENTOS_GENERICOS = {"buscar", "search", "busqueda", "busca", "s", "productos", "catalogo"}


def _parsear_url_vtex(url):
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
            clave = "category-" + str(cat_n)
        elif clave == "b":
            clave = "brand"
        facets.append(clave + "/" + seg)
    final = segmentos[-1] if segmentos else ""
    nombre = (query or final or "busqueda").replace("+", " ").strip()
    return "/".join(facets), query, nombre, final


def _prop(p, *nombres):
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


def _fila_vtex(p, item, tienda, busqueda, base_url):
    sellers = item.get("sellers") or []
    seller = next((s for s in sellers if s.get("sellerDefault")), sellers[0] if sellers else {})
    offer = seller.get("commertialOffer") or {}
    cats = [c.strip("/") for c in (p.get("categories") or [])]
    link = p.get("link") or ""
    return {
        "fecha": date.today(), "tienda": tienda, "busqueda": busqueda,
        "sku": item.get("itemId"),
        "codigo_barras": _codigo_barras(p, item),
        "ref_tienda": p.get("productReference") or "",
        "producto": p.get("productName"),
        "marca": p.get("brand") or "",
        "presentacion": _prop(p, "Presentación", "Presentacion"),
        "registro_sanitario": _prop(p, "ID Invima", "Registro Sanitario", "Invima"),
        "pum": _prop(p, "pum"),
        "categoria": " | ".join(cats),
        "precio": _int(offer.get("Price")),
        "precio_lista": _int(offer.get("ListPrice")),
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


def _descargar_vtex(tienda_key, url, progreso=None):
    nombre_visible = EXTRACT_STORES[tienda_key]["nombre"]
    base_url = RETAILERS[tienda_key]["base_url"]
    facet_path, query, nombre, final = _parsear_url_vtex(url)

    def avisar(filas, total, txt):
        if progreso:
            progreso(filas, total, txt)

    session = _crear_sesion(base_url)
    filas, vistos, total = [], 0, None
    for page in range(1, MAX_PAGINAS + 1):
        api = base_url.rstrip("/") + "/_v/api/intelligent-search/product_search/" + facet_path
        params = {"query": query, "page": page, "count": PAGE_SIZE, "locale": "es-CO"}
        data = None
        for i in range(4):
            try:
                r = session.get(api, params=params, timeout=TIMEOUT)
                if r.status_code == 200:
                    data = r.json(); break
                if r.status_code in (400, 404):
                    data = {"products": [], "recordsFiltered": 0}; break
            except (requests.RequestException, ValueError):
                pass
            time.sleep(2 * (i + 1))
        if data is None:
            raise RuntimeError("la tienda no respondió")
        productos = data.get("products") or []
        if page == 1 and not productos and facet_path and not query and final:
            facet_path, query = "", final.replace("+", " ")
            continue
        rf = data.get("recordsFiltered")
        if rf not in (None, ""):
            try: total = int(rf)
            except (TypeError, ValueError): total = None
        if not productos:
            break
        vistos += len(productos)
        avisar(vistos, total, str(vistos) + " de " + str(total))
        for p in productos:
            for item in p.get("items") or []:
                filas.append(_fila_vtex(p, item, nombre_visible, nombre, base_url))
        if total is not None and vistos >= total:
            break
        time.sleep(PAUSA)
    df = pd.DataFrame(filas, columns=COLUMNAS)
    if not df.empty:
        df = df.drop_duplicates(subset=["sku"]).reset_index(drop=True)
    return df, nombre


def _fila_farmatodo(hit, tienda, busqueda):
    full = _int(hit.get("fullPrice"))
    offer = _int(hit.get("offerPrice"))
    precio = offer if (offer is not None and full is not None and offer < full) else full
    stock = _int(hit.get("totalStock")) if hit.get("totalStock") not in (None, "") else _int(hit.get("stock"))
    presentacion = hit.get("presentación") or ""
    pum = ""
    measure = hit.get("measurePum")
    label = hit.get("labelPum") or ""
    if measure and full:
        try: pum = (label + " " + str(round(full / float(measure)))).strip()
        except (TypeError, ValueError, ZeroDivisionError): pum = ""
    slug = hit.get("url") or str(hit.get("id") or "")
    url = slug if slug.startswith("http") else ("https://www.farmatodo.com.co/producto/" + slug if slug else "")
    return {
        "fecha": date.today(), "tienda": tienda, "busqueda": busqueda,
        "sku": str(hit.get("id") or ""),
        "codigo_barras": str(hit.get("barcode") or ""),
        "ref_tienda": str(hit.get("objectID") or ""),
        "producto": hit.get("description"),
        "marca": hit.get("marca") or "",
        "presentacion": presentacion,
        "registro_sanitario": hit.get("brand") or "",
        "pum": pum,
        "categoria": hit.get("Categoría") or "",
        "precio": precio, "precio_lista": full,
        "stock": stock, "disponible": bool(stock),
        "url": url,
    }


def _descargar_farmatodo(url, progreso=None):
    termino = _parse_query_param(url, ("product", "q", "query", "search", "s", "buscar"))
    nombre = termino or "busqueda"
    def avisar(filas, total, txt):
        if progreso: progreso(filas, total, txt)
    filas, total_hits = [], None
    api = "https://" + ALGOLIA_APP_ID + "-dsn.algolia.net/1/indexes/" + ALGOLIA_INDEX + "/query"
    headers = {
        "X-Algolia-Application-Id": ALGOLIA_APP_ID,
        "X-Algolia-API-Key": ALGOLIA_API_KEY,
        "Content-Type": "application/json",
        "User-Agent": HEADERS["User-Agent"],
    }
    for page in range(0, MAX_PAGINAS):
        params = "query=" + requests.utils.quote(termino) + "&hitsPerPage=100&page=" + str(page)
        r = requests.post(api, headers=headers, data=json.dumps({"params": params}), timeout=TIMEOUT)
        if r.status_code != 200:
            raise RuntimeError("Algolia respondió HTTP " + str(r.status_code))
        data = r.json()
        total_hits = data.get("nbHits")
        hits = data.get("hits") or []
        if not hits:
            break
        for h in hits:
            filas.append(_fila_farmatodo(h, "Farmatodo", nombre))
        avisar(len(filas), total_hits, str(len(filas)) + " de " + str(total_hits))
        if total_hits is not None and len(filas) >= total_hits:
            break
        if page + 1 >= int(data.get("nbPages") or 0):
            break
        time.sleep(0.3)
    df = pd.DataFrame(filas, columns=COLUMNAS)
    if not df.empty:
        df = df.drop_duplicates(subset=["sku"]).reset_index(drop=True)
    return df, nombre


def _fila_cruzverde(hit, tienda, busqueda):
    prices = hit.get("prices") or {}
    def read(key):
        return _int(prices.get(key))
    lista = read("price-list-col")
    sale = read("price-sale-col")
    club = read("price-club-col")
    candidatos = [p for p in (sale, club) if p is not None]
    precio = min(candidatos) if candidatos and (lista is None or min(candidatos) < lista) else lista
    pid = hit.get("productId")
    slug = hit.get("pageURL") or (pid or "").lower()
    url = "https://www.cruzverde.com.co/" + slug + "/" + pid + ".html" if pid else ""
    stock = hit.get("stock")
    return {
        "fecha": date.today(), "tienda": tienda, "busqueda": busqueda,
        "sku": str(pid or ""), "codigo_barras": "", "ref_tienda": str(pid or ""),
        "producto": hit.get("productName"), "marca": hit.get("brand") or "",
        "presentacion": "", "registro_sanitario": "", "pum": hit.get("pum") or "",
        "categoria": "", "precio": precio, "precio_lista": lista,
        "stock": stock, "disponible": bool(stock), "url": url,
    }


def _sesion_cruzverde():
    s = requests.Session()
    s.headers.update({"User-Agent": HEADERS["User-Agent"], "Accept": "application/json", "Content-Type": "application/json"})
    s.post(CRUZVERDE_API_BASE + "/customer-service/login", json={}, timeout=TIMEOUT)
    return s


def _categoria_cruzverde(session, ruta):
    """Resuelve una ruta de categoría (ej. /ofertas/) a {id, name}."""
    api = CRUZVERDE_API_BASE + "/product-service/categories/path-category-dict"
    try:
        r = session.get(api, params={"path": ruta}, timeout=TIMEOUT)
        if r.status_code == 200:
            data = r.json()
            if isinstance(data, dict) and data.get("id"):
                return data
    except requests.RequestException:
        pass
    return None


def _descargar_cruzverde(url, progreso=None):
    termino = _parse_query_param(url, ("q", "query", "search", "s"))
    session = _sesion_cruzverde()
    refine = ""
    nombre = termino or ""
    if not termino:
        # Enlace de categoría/ofertas (ej. /ofertas/): resolver ruta -> categoría.
        ruta = urlparse(url.strip()).path or ""
        if ruta and ruta != "/":
            ruta_norm = "/" + ruta.strip("/") + "/"
            cat = _categoria_cruzverde(session, ruta_norm)
            if cat and cat.get("id"):
                refine = cat["id"]
                nombre = cat.get("name") or ruta_norm
    if not termino and not refine:
        raise RuntimeError("Cruz Verde: pega un enlace de búsqueda (.../search?q=...) o de categoría (.../ofertas/).")

    def avisar(filas, total, txt):
        if progreso: progreso(filas, total, txt)

    filas, total, offset = [], None, 0
    for _ in range(MAX_PAGINAS):
        api = CRUZVERDE_API_BASE + "/product-service/products/search"
        refine_part = "&refine[]=cgid=" + refine if refine else ""
        query_url = (api + "?limit=" + str(PAGE_SIZE) + "&offset=" + str(offset)
                     + "&sort=&q=" + requests.utils.quote(termino) + refine_part)
        r = session.get(query_url, timeout=TIMEOUT)
        if r.status_code == 401:
            session = _sesion_cruzverde()
            r = session.get(query_url, timeout=TIMEOUT)
        if r.status_code != 200:
            raise RuntimeError("Cruz Verde respondió HTTP " + str(r.status_code))
        data = r.json()
        total = data.get("total")
        hits = data.get("hits") or []
        if not hits:
            break
        for h in hits:
            filas.append(_fila_cruzverde(h, "Cruz Verde", nombre))
        avisar(len(filas), total, str(len(filas)) + " de " + str(total))
        offset += PAGE_SIZE
        if total is not None and offset >= total:
            break
        time.sleep(0.3)
    df = pd.DataFrame(filas, columns=COLUMNAS)
    if not df.empty:
        df = df.drop_duplicates(subset=["sku"]).reset_index(drop=True)
    return df, nombre


def descargar_tienda(tienda_key, url, progreso=None):
    engine = EXTRACT_STORES[tienda_key]["engine"]
    if engine == "vtex":
        return _descargar_vtex(tienda_key, url, progreso=progreso)
    if engine == "algolia":
        return _descargar_farmatodo(url, progreso=progreso)
    if engine == "ocapi":
        return _descargar_cruzverde(url, progreso=progreso)
    raise RuntimeError("Motor no implementado para " + tienda_key)


def _nombre_hoja(nombre, usados):
    hoja = re.sub(r'[^A-Za-z0-9 _-]', "", str(nombre)).strip()[:31] or "Hoja"
    base_n, n = hoja, 2
    while hoja.lower() in usados:
        sufijo = "_" + str(n)
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


def generar_excel(resultados, out_dir=None):
    out_dir = Path(out_dir) if out_dir else Path(__file__).resolve().parent.parent / "reports"
    out_dir.mkdir(parents=True, exist_ok=True)
    resumen = pd.DataFrame([{"tienda": t, "busqueda": n, "filas": len(df), "link": u} for t, n, df, u in resultados])
    archivo = out_dir / ("catalogos_" + date.today().isoformat() + ".xlsx")
    for k in range(1, 50):
        candidato = archivo if k == 1 else out_dir / ("catalogos_" + date.today().isoformat() + "_" + str(k) + ".xlsx")
        try:
            with pd.ExcelWriter(candidato, engine="openpyxl") as w:
                resumen.to_excel(w, sheet_name="Resumen", index=False)
                _formato(w.sheets["Resumen"])
                usados = {"resumen"}
                for t, n, df, _u in resultados:
                    hoja = _nombre_hoja((t + " - " + n) if n else t, usados)
                    df.to_excel(w, sheet_name=hoja, index=False)
                    _formato(w.sheets[hoja])
            return candidato
        except PermissionError:
            continue
    raise PermissionError("No se pudo guardar el Excel en " + str(out_dir))


_JOBS = {}
_JOBS_LOCK = threading.Lock()


def start_job(links):
    job_id = uuid.uuid4().hex[:12]
    job = {"id": job_id, "status": "running", "links": [], "result_path": None, "error": None, "started_at": time.time()}
    with _JOBS_LOCK:
        _JOBS[job_id] = job
    threading.Thread(target=_run_job, args=(job_id, links), daemon=True).start()
    return job_id


def get_job(job_id):
    return _JOBS.get(job_id)


def _run_job(job_id, links):
    job = _JOBS[job_id]
    resultados = []
    for url in links:
        ls = {"url": url, "tienda": "Desconocida", "estado": "pending", "filas": 0, "total": None, "mensaje": ""}
        job["links"].append(ls)
        tienda = detectar_tienda(url)
        if tienda is None:
            ls["estado"] = "error"
            ls["mensaje"] = "Tienda no soportada para descarga de catálogos."
            continue
        ls["tienda"] = EXTRACT_STORES[tienda]["nombre"]
        ls["estado"] = "running"
        def cb(filas, total, texto, _ls=ls):
            _ls["filas"] = filas
            _ls["total"] = total
            _ls["mensaje"] = texto
        try:
            df, nombre = descargar_tienda(tienda, url, progreso=cb)
            ls["filas"] = len(df)
            if df.empty:
                ls["estado"] = "vacio"; ls["mensaje"] = "Sin resultados"
            else:
                ls["estado"] = "done"; ls["mensaje"] = "Listo: " + str(len(df)) + " filas"
                resultados.append((EXTRACT_STORES[tienda]["nombre"], nombre, df, url))
        except Exception as exc:
            ls["estado"] = "error"; ls["mensaje"] = str(exc)
    if resultados:
        try:
            job["result_path"] = str(generar_excel(resultados))
        except Exception as exc:
            job["error"] = "Error generando Excel: " + str(exc)
    else:
        job["error"] = "No se descargó ningún catálogo."
    job["status"] = "done"
