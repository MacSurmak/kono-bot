import os
import hashlib
import requests
import xml.etree.ElementTree as ET
from config import cfg

iiko_cfg = cfg["iiko"]
BASE_URL = iiko_cfg["base_url"].rstrip("/")
LOGIN = iiko_cfg["login"]
PASSWORD = iiko_cfg["password"]


import json
from loguru import logger

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")


class IikoClient:
    def __init__(self):
        self.base_url = BASE_URL
        self.session = requests.Session()
        self._init_redis()

    def _init_redis(self):
        try:
            import redis

            self.redis_client = redis.Redis.from_url(REDIS_URL, decode_responses=True)
        except Exception as e:
            logger.warning(
                f"Redis cache connection unavailable: {e}. Falling back to live API calls."
            )
            self.redis_client = None

    def authenticate_credentials(self, login: str, password: str) -> str:
        """Authenticates against iikoChain /api/auth and returns active session key."""
        pass_hash = hashlib.sha1(password.encode("utf-8")).hexdigest()
        with requests.Session() as s:
            resp = s.get(
                f"{self.base_url}/api/auth",
                params={"login": login, "pass": pass_hash},
                timeout=12,
            )
            if resp.status_code != 200:
                resp = s.get(
                    f"{self.base_url}/api/auth",
                    params={"login": login, "pass": password},
                    timeout=12,
                )
            if resp.status_code != 200:
                raise ConnectionError(
                    f"Ошибка авторизации в iiko ({resp.status_code}): {resp.text.strip()}"
                )
            token = resp.text.strip()
            if not token:
                raise ConnectionError("iiko вернул пустой ключ сессии.")
            return token

    def test_user_credentials(self, login: str, password: str) -> bool:
        """Validates credentials. Raises ConnectionError if invalid."""
        token = self.authenticate_credentials(login, password)
        # Immediately logout session token
        try:
            requests.get(
                f"{self.base_url}/api/logout", params={"key": token}, timeout=5
            )
        except Exception:
            pass
        return True

    def upload_invoice_as_user(
        self, target_store_id: str, xml_payload: str, login: str, password: str
    ) -> requests.Response:
        """Uploads invoice payload using specific user credentials, attributing authorship."""
        token = self.authenticate_credentials(login, password)
        headers = {"Content-Type": "application/xml; charset=utf-8"}
        with requests.Session() as s:
            try:
                resp = s.post(
                    f"{self.base_url}/api/documents/import/incomingInvoice",
                    params={"key": token},
                    data=xml_payload.encode("utf-8"),
                    headers=headers,
                    timeout=30,
                )
                return resp
            finally:
                try:
                    s.get(
                        f"{self.base_url}/api/logout", params={"key": token}, timeout=5
                    )
                except Exception:
                    pass

    def get(self, endpoint: str, **kwargs):
        """Executes GET request using temporary anonymous or session key."""
        url = f"{self.base_url}/{endpoint.lstrip('/')}"
        return self.session.get(url, **kwargs)

    def post(self, endpoint: str, **kwargs):
        """Executes POST request."""
        url = f"{self.base_url}/{endpoint.lstrip('/')}"
        return self.session.post(url, **kwargs)

    def get_suppliers_grouped(self) -> dict:
        """Retrieves supplier registry with 10-minute Redis cache."""
        cache_key = "cache:iiko:suppliers"
        if self.redis_client:
            try:
                cached = self.redis_client.get(cache_key)
                if cached:
                    return json.loads(cached)
            except Exception as e:
                logger.warning(f"Failed to read suppliers from Redis cache: {e}")

        resp = self.get("/api/suppliers")
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
            except Exception as e:
                logger.warning(f"Failed to write suppliers to Redis cache: {e}")

        return suppliers

    def get_active_stock_products(self) -> list:
        """Retrieves active stock product catalog with 10-minute Redis cache."""
        cache_key = "cache:iiko:catalog"
        if self.redis_client:
            try:
                cached = self.redis_client.get(cache_key)
                if cached:
                    return json.loads(cached)
            except Exception as e:
                logger.warning(f"Failed to read catalog from Redis cache: {e}")

        resp = self.get("/api/products")
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
            except Exception as e:
                logger.warning(f"Failed to write catalog to Redis cache: {e}")

        return clean_products

    def get_iiko_departments(self) -> list:
        """Retrieves all physical warehouse stores from /api/corporation/stores with Redis cache."""
        cache_key = "cache:iiko:departments"
        if self.redis_client:
            try:
                cached = self.redis_client.get(cache_key)
                if cached:
                    return json.loads(cached)
            except Exception:
                pass

        resp = self.get("/api/corporation/stores")
        if resp.status_code != 200:
            return []
        root = ET.fromstring(resp.content)
        stores = []
        for dep in root.findall(".//corporateItemDto"):
            s_id = dep.findtext("id")
            name = (dep.findtext("name") or "").strip()
            code = (dep.findtext("code") or "").strip()
            if s_id and name:
                stores.append(
                    {
                        "id": s_id,
                        "name": name,
                        "code": code,
                    }
                )
        sorted_stores = sorted(stores, key=lambda s: s["name"])
        if self.redis_client and sorted_stores:
            try:
                self.redis_client.setex(
                    cache_key, 600, json.dumps(sorted_stores, ensure_ascii=False)
                )
            except Exception:
                pass
        return sorted_stores

    def upload_invoice(self, target_store_id: str, xml_payload: str):
        # Safety guardrail dynamically validating against managed stores in database
        from storage import get_allowed_stores

        allowed = get_allowed_stores()
        if target_store_id not in allowed:
            raise PermissionError(
                f"CRITICAL: Attempted upload to unauthorized store {target_store_id}! "
                f"Allowed stores: {allowed}"
            )

        headers = {"Content-Type": "application/xml; charset=utf-8"}
        return self.post(
            "/api/documents/import/incomingInvoice",
            data=xml_payload.encode("utf-8"),
            headers=headers,
        )


client = IikoClient()
