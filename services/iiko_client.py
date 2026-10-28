import os
import json
import hashlib
import requests
import xml.etree.ElementTree as ET
from typing import Optional, Dict, Any, List
from loguru import logger
from config import cfg

BASE_URL = cfg["iiko"]["base_url"].rstrip("/")
REDIS_URL = os.getenv("REDIS_URL")
if not REDIS_URL or not REDIS_URL.strip():
    raise RuntimeError("CRITICAL CONFIGURATION ERROR: 'REDIS_URL' environment variable is not set.")
TOKEN_CACHE_TTL = 900  # 15 minutes


class IikoApiError(Exception):
    """Raised when an iiko API request fails or returns an error."""


class IikoClient:
    """HTTP client interacting with iikoChain API strictly under individual user credentials."""

    def __init__(self):
        self.base_url = BASE_URL
        self.session = requests.Session()
        self._init_redis()

    def _init_redis(self):
        import redis

        self.redis_client = redis.Redis.from_url(REDIS_URL, decode_responses=True)
        # Fail-Fast: verify Redis connection immediately
        self.redis_client.ping()

    def _authenticate_direct(self, login: str, password: str) -> str:
        """Performs raw /api/auth authentication against iiko server."""
        pass_hash = hashlib.sha1(password.encode("utf-8")).hexdigest()
        resp = self.session.get(
            f"{self.base_url}/api/auth",
            params={"login": login, "pass": pass_hash},
            timeout=15,
        )
        if resp.status_code != 200:
            resp = self.session.get(
                f"{self.base_url}/api/auth",
                params={"login": login, "pass": password},
                timeout=15,
            )
        if resp.status_code != 200:
            raise IikoApiError(
                f"Ошибка авторизации в iiko ({resp.status_code}): {resp.text.strip()}"
            )
        token = resp.text.strip()
        if not token:
            raise IikoApiError("iikoChain вернул пустой ключ сессии.")
        return token

    def get_user_token(self, login: str, password: str) -> str:
        """Retrieves user session token with Redis caching."""
        cache_key = f"cache:iiko:token:{login}"
        if self.redis_client:
            try:
                cached_token = self.redis_client.get(cache_key)
                if cached_token:
                    return cached_token
            except Exception as e:
                logger.warning(f"Failed to read token from Redis: {e}")

        token = self._authenticate_direct(login, password)
        if self.redis_client and token:
            try:
                self.redis_client.setex(cache_key, TOKEN_CACHE_TTL, token)
            except Exception as e:
                logger.warning(f"Failed to cache token in Redis: {e}")
        return token

    def invalidate_user_token(self, login: str) -> None:
        """Purges cached token from Redis."""
        cache_key = f"cache:iiko:token:{login}"
        if self.redis_client:
            try:
                self.redis_client.delete(cache_key)
            except Exception:
                pass

    def _request_with_user_auth(
        self,
        login: str,
        password: str,
        method: str,
        endpoint: str,
        **kwargs,
    ) -> requests.Response:
        """Executes HTTP request with user token and transparent 1-time re-auth on 401."""
        token = self.get_user_token(login, password)
        params = kwargs.pop("params", {}) or {}
        params["key"] = token
        timeout = kwargs.pop("timeout", 30)

        url = f"{self.base_url}/{endpoint.lstrip('/')}"
        resp = self.session.request(
            method, url, params=params, timeout=timeout, **kwargs
        )

        # Transparent Re-Auth on 401: invalidate cached token and retry once
        if resp.status_code == 401:
            logger.warning(
                f"Cached token for '{login}' rejected with 401. Re-authenticating..."
            )
            self.invalidate_user_token(login)
            fresh_token = self.get_user_token(login, password)
            params["key"] = fresh_token
            resp = self.session.request(
                method, url, params=params, timeout=timeout, **kwargs
            )

        if resp.status_code != 200:
            raise IikoApiError(
                f"Ошибка API iiko ({resp.status_code}) при вызове {endpoint}: {resp.text[:300].strip()}"
            )
        return resp

    def test_user_credentials(self, login: str, password: str) -> bool:
        """Validates credentials by requesting fresh token and testing stores endpoint."""
        token = self._authenticate_direct(login, password)
        try:
            resp = self.session.get(
                f"{self.base_url}/api/corporation/stores",
                params={"key": token},
                timeout=15,
            )
            if resp.status_code != 200:
                raise IikoApiError(f"HTTP {resp.status_code}: {resp.text[:200]}")
            return True
        finally:
            try:
                self.session.get(
                    f"{self.base_url}/api/logout", params={"key": token}, timeout=5
                )
            except Exception:
                pass

    def upload_invoice_as_user(
        self, target_store_id: str, xml_payload: str, login: str, password: str
    ) -> requests.Response:
        """Uploads invoice XML payload under authenticated operator identity."""
        headers = {"Content-Type": "application/xml; charset=utf-8"}
        return self._request_with_user_auth(
            login=login,
            password=password,
            method="POST",
            endpoint="/api/documents/import/incomingInvoice",
            data=xml_payload.encode("utf-8"),
            headers=headers,
            timeout=35,
        )

    def get_suppliers_grouped_for_user(self, login: str, password: str) -> dict:
        """Retrieves supplier registry using user credentials with 10-minute cache."""
        cache_key = "cache:iiko:suppliers"
        if self.redis_client:
            try:
                cached = self.redis_client.get(cache_key)
                if cached:
                    return json.loads(cached)
            except Exception:
                pass

        resp = self._request_with_user_auth(login, password, "GET", "/api/suppliers")
        root = ET.fromstring(resp.content)
        suppliers = {}
        for emp in root.findall(".//employee"):
            inn = (emp.findtext("taxpayerIdNumber") or "").strip()
            is_supplier = emp.findtext("supplier", "false") == "true"
            is_deleted = emp.findtext("deleted", "false") == "true"
            if inn and is_supplier and not is_deleted:
                suppliers.setdefault(inn, []).append(
                    {
                        "id": emp.findtext("id"),
                        "name": (emp.findtext("name") or "").strip(),
                        "code": (emp.findtext("code") or "").strip(),
                        "dept_codes": (emp.findtext("departmentCodes") or "").strip(),
                    }
                )

        if self.redis_client and suppliers:
            try:
                self.redis_client.setex(
                    cache_key, 600, json.dumps(suppliers, ensure_ascii=False)
                )
            except Exception:
                pass
        return suppliers

    def get_active_stock_products_for_user(self, login: str, password: str) -> list:
        """Retrieves active product catalog using user credentials with 10-minute cache."""
        cache_key = "cache:iiko:catalog"
        if self.redis_client:
            try:
                cached = self.redis_client.get(cache_key)
                if cached:
                    return json.loads(cached)
            except Exception:
                pass

        resp = self._request_with_user_auth(login, password, "GET", "/api/products")
        root = ET.fromstring(resp.content)
        all_elements = root.findall(".//productDto")
        id_to_name = {
            p.findtext("id"): p.findtext("name", "").strip() for p in all_elements
        }

        clean_products = []
        for p in all_elements:
            p_type = p.findtext("productType", "")
            if p_type not in ("GOODS", "PREPARED", "MODIFIER"):
                continue

            name = p.findtext("name", "").strip()
            cat = p.findtext("productCategory", "").strip()
            parent_id = p.findtext("parentId")
            folder_name = id_to_name.get(parent_id, "Корень")

            if (
                "архив" in folder_name.lower()
                or name.lower().startswith("архив.")
                or "архив" in cat.lower()
            ):
                continue
            if any(
                k in folder_name.lower()
                for k in ["агрегаторы яе", "яе мск", "яе калининград"]
            ):
                continue

            clean_products.append(
                {
                    "id": p.findtext("id"),
                    "name": name,
                    "article": p.findtext("num", "") or p.findtext("code", ""),
                    "category": cat,
                    "folder": folder_name,
                }
            )

        if self.redis_client and clean_products:
            try:
                self.redis_client.setex(
                    cache_key, 600, json.dumps(clean_products, ensure_ascii=False)
                )
            except Exception:
                pass
        return clean_products

    def get_iiko_departments_for_user(self, login: str, password: str) -> list:
        """Retrieves warehouse stores using user credentials."""
        resp = self._request_with_user_auth(
            login, password, "GET", "/api/corporation/stores", timeout=20
        )
        root = ET.fromstring(resp.content)
        stores = []
        for dep in root.findall(".//corporateItemDto"):
            s_id = dep.findtext("id")
            name = (dep.findtext("name") or "").strip()
            code = (dep.findtext("code") or "").strip()
            if s_id and name:
                stores.append({"id": s_id, "name": name, "code": code})
        return sorted(stores, key=lambda st: st["name"])

    def export_incoming_invoices_for_user(
        self, login: str, password: str, date_from: str, date_to: str
    ) -> ET.Element:
        """Exports processed incoming invoices from iiko for deterministic training."""
        resp = self._request_with_user_auth(
            login,
            password,
            "GET",
            "/api/documents/export/incomingInvoice",
            params={"from": date_from, "to": date_to},
            timeout=45,
        )
        return ET.fromstring(resp.content)


client = IikoClient()
