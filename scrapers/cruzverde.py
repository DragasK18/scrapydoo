"""
Scraper para Cruz Verde Colombia (Salesforce Commerce Cloud / OCAPI).

Cruz Verde no expone su OCAPI (Salesforce Commerce Cloud) directamente; lo hace
a través de un backend propio (api.cruzverde.com.co) que exige una sesión
anónima de invitado. Flujo:

  1. POST {api_base}/customer-service/login          -> 201 + cookie connect.sid
  2. GET  {api_base}/product-service/products/search -> JSON OCAPI
            ?q={query}&limit={n}&offset=0&sort=

La respuesta trae hits[] con:
  - productId  (SKU, ej. COCV_560131)
  - productName
  - prices     (price-list-col = precio de lista, price-sale-col = oferta,
                price-club-col = precio Club)
  - image.link y pageURL (slug para armar la URL pública del producto).

El buscador indexa el EAN (validado), así que la búsqueda por EAN y por
descripción funcionan contra el mismo endpoint.
"""
from __future__ import annotations

from typing import Optional

import requests

from config import Config
from services.matching import MatchCandidate
from services.search_queries import merge_query_search
from services.rounding import round_cop

from .base import BaseScraper, RetailerResult

_API_BASE = "https://api.cruzverde.com.co"
_PRODUCT_URL_BASE = "https://www.cruzverde.com.co"


class CruzVerdeScraper(BaseScraper):
    """Cruz Verde (backend OCAPI con sesión de invitado)."""

    api_base: str = _API_BASE

    def _session(self) -> requests.Session:
        """Crea una sesión requests con la cookie anónima (connect.sid)."""
        session = requests.Session()
        session.headers.update(
            {
                "User-Agent": Config.USER_AGENT,
                "Accept": "application/json",
                "Content-Type": "application/json",
            }
        )
        session.post(
            f"{self.api_base}/customer-service/login",
            json={},
            timeout=Config.SCRAPER_TIMEOUT,
        )
        return session

    def _search(self, query: str, limit: int = 24) -> list[dict]:
        url = f"{self.api_base}/product-service/products/search"
        params = {"q": query, "limit": limit, "offset": 0, "sort": ""}
        session = self._session()
        resp = session.get(url, params=params, timeout=Config.SCRAPER_TIMEOUT)
        if resp.status_code == 401:
            # La cookie de invitado expiró: se recrea y se reintenta una vez.
            session = self._session()
            resp = session.get(url, params=params, timeout=Config.SCRAPER_TIMEOUT)
        if resp.status_code == 404:
            return []
        resp.raise_for_status()
        return resp.json().get("hits") or []

    @staticmethod
    def _read_price(prices: dict, key: str) -> Optional[int]:
        value = prices.get(key)
        if value in (None, ""):
            return None
        try:
            return round_cop(int(float(value)))
        except (TypeError, ValueError):
            return None

    def _hit_to_result(self, hit: dict, *, found: bool = True) -> Optional[RetailerResult]:
        prices = hit.get("prices") or {}
        list_price = self._read_price(prices, "price-list-col")
        sale_price = self._read_price(prices, "price-sale-col")
        club_price = self._read_price(prices, "price-club-col")

        if list_price is None:
            # Respaldo: cualquier otro price book presente.
            for value in prices.values():
                try:
                    list_price = round_cop(int(float(value)))
                    break
                except (TypeError, ValueError):
                    continue
        if list_price is None:
            return None

        # Promoción: la menor de la oferta (price-sale-col) o el precio Club
        # (price-club-col) cuando está por debajo del precio de lista.
        promo = None
        promo_desc = None
        candidates = [p for p in (sale_price, club_price) if p is not None]
        if candidates and min(candidates) < list_price:
            promo = round_cop(min(candidates))
            if sale_price is not None and (club_price is None or sale_price <= club_price):
                promo_desc = "Precio de oferta"
            else:
                promo_desc = "Precio Club Cruz Verde"

        product_id = hit.get("productId")
        slug = hit.get("pageURL") or (product_id or "").lower()
        product_url = None
        if product_id:
            product_url = f"{_PRODUCT_URL_BASE}/{slug}/{product_id}.html"

        image_url = None
        image = hit.get("image") or {}
        if image:
            image_url = image.get("link") or image.get("disBaseLink")

        return RetailerResult(
            retailer=self.key,
            retailer_name=self.name,
            found=found,
            price=list_price,
            promo_price=promo,
            promo_desc=promo_desc,
            product_name=hit.get("productName"),
            image_url=image_url,
            url=product_url,
            match_mode="ean",
        )

    def _fetch_by_ean(self, ean: str, city: Optional[str] = None) -> Optional[RetailerResult]:
        hits = self._search(ean, limit=5)
        if not hits:
            return RetailerResult(retailer=self.key, retailer_name=self.name, found=False, city=city)
        result = self._hit_to_result(hits[0])
        if result:
            result.city = city
        return result

    def _fetch_candidates(
        self, description: str, city: Optional[str] = None
    ) -> list[tuple[MatchCandidate, RetailerResult]]:
        merged = merge_query_search(
            description,
            lambda q: self._search(q, limit=24),
            dedupe_key=lambda h: str(h.get("productId") or h.get("productName") or ""),
        )
        out: list[tuple[MatchCandidate, RetailerResult]] = []
        for rank, hit in enumerate(merged):
            result = self._hit_to_result(hit, found=False)
            if result and result.product_name:
                result.city = city
                out.append(
                    (
                        MatchCandidate(name=result.product_name, payload={"catalog_rank": rank}),
                        result,
                    )
                )
        return out
