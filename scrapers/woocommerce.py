"""
Scraper para farmacias sobre WooCommerce (WooCommerce Store API).

WooCommerce Blocks expone una API JSON pública (sin autenticación) para el
catálogo de la tienda:

    /wp-json/wc/store/v1/products?search={query}&per_page={n}

Devuelve nombre, SKU, precios (regular/sale), imagen y enlace de cada producto.
No requiere Playwright ni claves. Aplica a Droguerías Farmavida.

Los precios vienen en pesos colombianos enteros (currency_minor_unit=0 en COP),
por lo que se interpretan directamente como COP.
"""
from __future__ import annotations

from typing import Optional

import requests

from config import Config
from services.matching import MatchCandidate
from services.search_queries import merge_query_search
from services.rounding import round_cop

from .base import BaseScraper, RetailerResult


class WooCommerceScraper(BaseScraper):
    """Scraper genérico para tiendas WooCommerce (WooCommerce Store API v1)."""

    # Ruta de la API (sobrescribible si la tienda la monta en otro prefijo).
    store_api_path: str = "/wp-json/wc/store/v1/products"

    def _api_url(self) -> str:
        return self.base_url.rstrip("/") + self.store_api_path

    def _query(self, search: str, per_page: int = 24) -> list[dict]:
        resp = requests.get(
            self._api_url(),
            params={"search": search, "per_page": per_page},
            headers={"User-Agent": Config.USER_AGENT, "Accept": "application/json"},
            timeout=Config.SCRAPER_TIMEOUT,
        )
        if resp.status_code == 404:
            return []
        resp.raise_for_status()
        data = resp.json()
        return data if isinstance(data, list) else []

    @staticmethod
    def _price_int(value) -> Optional[int]:
        if value in (None, ""):
            return None
        try:
            return round_cop(int(float(str(value))))
        except (TypeError, ValueError):
            return None

    def _product_to_result(self, product: dict, *, found: bool = True) -> Optional[RetailerResult]:
        prices = product.get("prices") or {}
        regular = self._price_int(prices.get("regular_price")) or self._price_int(prices.get("price"))
        sale = self._price_int(prices.get("sale_price"))
        if regular is None:
            return None

        promo = None
        promo_desc = None
        if sale is not None and sale < regular:
            promo = round_cop(sale)
            promo_desc = "Precio de oferta"

        images = product.get("images") or []
        image_url = images[0].get("src") if images else None

        return RetailerResult(
            retailer=self.key,
            retailer_name=self.name,
            found=found,
            price=regular,
            promo_price=promo,
            promo_desc=promo_desc,
            product_name=product.get("name"),
            url=product.get("permalink"),
            image_url=image_url,
            match_mode="ean",
        )

    def _fetch_by_ean(self, ean: str, city: Optional[str] = None) -> Optional[RetailerResult]:
        # La búsqueda de WooCommerce matchea título, contenido y SKU. Si el EAN
        # está guardado como SKU o aparece en el título, se encuentra aquí; en
        # caso contrario BaseScraper.search homologa por descripción.
        results = self._query(ean, per_page=5)
        if not results:
            return RetailerResult(retailer=self.key, retailer_name=self.name, found=False, city=city)
        result = self._product_to_result(results[0])
        if result:
            result.city = city
        return result

    def _fetch_candidates(
        self, description: str, city: Optional[str] = None
    ) -> list[tuple[MatchCandidate, RetailerResult]]:
        merged = merge_query_search(
            description,
            lambda q: self._query(q, per_page=24),
            dedupe_key=lambda p: str(p.get("id") or p.get("name") or ""),
        )
        out: list[tuple[MatchCandidate, RetailerResult]] = []
        for rank, product in enumerate(merged):
            result = self._product_to_result(product, found=False)
            if result and result.product_name:
                result.city = city
                out.append(
                    (
                        MatchCandidate(name=result.product_name, payload={"catalog_rank": rank}),
                        result,
                    )
                )
        return out
