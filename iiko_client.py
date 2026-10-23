import os
import hashlib
import requests
import xml.etree.ElementTree as ET
from config import cfg, ALLOWED_STORES

iiko_cfg = cfg["iiko"]
BASE_URL = iiko_cfg["base_url"].rstrip("/")
LOGIN = iiko_cfg["login"]
PASSWORD = iiko_cfg["password"]


class IikoClient:
    def __init__(self):
        self.session = requests.Session()
        self.base_url = BASE_URL
        self._auth()

    def _auth(self):
        pass_hash = hashlib.sha1(PASSWORD.encode("utf-8")).hexdigest()
        resp = self.session.get(
            f"{self.base_url}/api/auth", params={"login": LOGIN, "pass": pass_hash}
        )
        if resp.status_code != 200:
            resp = self.session.get(
                f"{self.base_url}/api/auth", params={"login": LOGIN, "pass": PASSWORD}
            )
        if resp.status_code != 200:
            raise ConnectionError(
                f"iiko authorization failed: {resp.status_code} - {resp.text}"
            )
        self.session.params = {"key": resp.text.strip()}

    def _request_with_reauth(self, method: str, endpoint: str, **kwargs):
        """Executes HTTP request and transparently refreshes session on token expiration."""
        url = f"{self.base_url}/{endpoint.lstrip('/')}"
        resp = self.session.request(method, url, **kwargs)
        if resp.status_code == 401 or (resp.status_code == 400 and "auth" in resp.text.lower()):
            self._auth()
            resp = self.session.request(method, url, **kwargs)
        return resp

    def get(self, endpoint: str, **kwargs):
        return self._request_with_reauth("GET", endpoint, **kwargs)

    def post(self, endpoint: str, **kwargs):
        return self._request_with_reauth("POST", endpoint, **kwargs)

    def get_suppliers_grouped(self) -> dict:
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
        return suppliers

    def get_active_stock_products(self) -> list:
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
        return clean_products

    def upload_invoice(self, target_store_id: str, xml_payload: str):
        # Safety guardrail preventing uploads to unapproved stores
        if target_store_id not in ALLOWED_STORES:
            raise PermissionError(
                f"CRITICAL: Attempted upload to unauthorized store {target_store_id}! "
                f"Allowed stores: {ALLOWED_STORES}"
            )

        headers = {"Content-Type": "application/xml; charset=utf-8"}
        return self.post(
            "/api/documents/import/incomingInvoice",
            data=xml_payload.encode("utf-8"),
            headers=headers,
        )


client = IikoClient()
