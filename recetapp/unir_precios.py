#!/usr/bin/env python3
"""Une data/base.csv y data/scrapeado-hoy.csv en data/precios.csv.

Soporta la columna `codigo` (SKU / EAN) y múltiples farmacias:
- Si base.csv es antiguo y no tiene la columna `codigo`, la rellena automáticamente con "".
- Deduplica por `(farmacia, codigo)` (o `(farmacia, url)` si no hay código).

Uso:
    python3 unir_precios.py
    python3 unir_precios.py --actualizar-base
"""

import argparse
import collections
import csv
import sys
from pathlib import Path

DATA = Path(__file__).resolve().parent / "data"
BASE = DATA / "base.csv"
HOY = DATA / "scrapeado-hoy.csv"
SALIDA = DATA / "precios.csv"

COLUMNAS = [
    "fecha", "farmacia", "codigo", "principio_activo", "concentracion", "producto",
    "marca", "presentacion", "unidades", "precio", "precio_lista", "precio_unidad", "url",
]
COLUMNAS_ANTIGUAS = [c for c in COLUMNAS if c != "codigo"]


def normalizar_url(url):
    return (url or "").split("?")[0].rstrip("/").strip().lower()


def clave_unica(fila):
    farmacia = (fila.get("farmacia") or "").strip().lower()
    codigo = (fila.get("codigo") or "").strip().lower()
    if codigo:
        return (farmacia, f"id:{codigo}")
    return (farmacia, f"url:{normalizar_url(fila.get('url'))}")


def leer(ruta, obligatorio=False):
    if not ruta.exists():
        if obligatorio:
            sys.exit(f"Error: No existe {ruta}")
        return []
    with ruta.open(newline="", encoding="utf-8") as f:
        lector = csv.DictReader(f)
        if lector.fieldnames == COLUMNAS:
            return list(lector)
        elif lector.fieldnames == COLUMNAS_ANTIGUAS:
            filas = []
            for r in lector:
                r["codigo"] = ""
                filas.append(r)
            return filas
        else:
            sys.exit(f"{ruta.name}: columnas inesperadas {lector.fieldnames}")


def escribir(ruta, filas):
    ruta.parent.mkdir(parents=True, exist_ok=True)
    with ruta.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNAS)
        w.writeheader()
        w.writerows(filas)


def orden(fila):
    try:
        precio_unidad = float(fila["precio_unidad"])
    except (ValueError, TypeError):
        precio_unidad = float("inf")
    return (
        fila["principio_activo"],
        fila["concentracion"],
        precio_unidad,
        fila["farmacia"],
    )


def main():
    parser = argparse.ArgumentParser(description="Une base.csv y scrapeado-hoy.csv.")
    parser.add_argument(
        "--actualizar-base",
        action="store_true",
        help="Actualiza también data/base.csv con la unión consolidada.",
    )
    args = parser.parse_args()

    base = leer(BASE, obligatorio=False)
    hoy = leer(HOY, obligatorio=False)

    if not base and not hoy:
        sys.exit("Ni base.csv ni scrapeado-hoy.csv contienen datos.")

    mapa_hoy = {}
    urls_hoy_por_farmacia = {}
    for fila in hoy:
        clave = clave_unica(fila)
        mapa_hoy[clave] = fila
        par_url = (fila["farmacia"].strip().lower(), normalizar_url(fila["url"]))
        urls_hoy_por_farmacia[par_url] = clave

    reemplazadas = 0
    filas_conservadas = []

    for fila in base:
        clave = clave_unica(fila)
        par_url = (fila["farmacia"].strip().lower(), normalizar_url(fila["url"]))
        if clave in mapa_hoy or par_url in urls_hoy_por_farmacia:
            reemplazadas += 1
        else:
            filas_conservadas.append(fila)

    filas_finales = filas_conservadas + list(mapa_hoy.values())
    filas_finales.sort(key=orden)

    escribir(SALIDA, filas_finales)
    if args.actualizar_base:
        escribir(BASE, filas_finales)

    print(f"{BASE.name}: {len(base)} · {HOY.name}: {len(mapa_hoy)} · actualizadas hoy: {reemplazadas}")
    conteo = collections.Counter(f["farmacia"] for f in filas_finales)
    print("Por cadena: " + ", ".join(f"{k}: {v}" for k, v in sorted(conteo.items())))
    print(f"{len(filas_finales)} filas → {SALIDA}")


if __name__ == "__main__":
    main()
