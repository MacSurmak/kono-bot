import os
import json
import asyncio
import zipfile
import shutil
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from collections import Counter
from typing import List, Dict, Any, Tuple
from loguru import logger

from models import RawInvoiceDocument
from parsers import parse_document
from services.iiko_client import client
from storage import get_db_pool, record_mapping_vote

# Expanded limits for bulk network ingestion
MAX_BATCH_FILES = 2000
MAX_BATCH_BYTES = 1024 * 1024 * 1024  # 1 GB
DATE_BUFFER_DAYS = 5


class BatchTrainingError(Exception):
    """Raised when batch archive extraction or matching invariants fail."""


def compute_packaging_coefficient(d_qty: float, i_amount: float) -> float:
    """Computes deterministic packaging multiplier only when invoice quantity is discrete and unit weight is exact."""
    if d_qty <= 0 or i_amount <= 0:
        return 1.0
    # If supplier quantity is already fractional (e.g. 1.020 kg), item is billed by continuous weight -> coeff is 1.0
    if abs(d_qty - round(d_qty)) > 0.001:
        return 1.0

    ratio = i_amount / d_qty
    # Integer pack count (1, 2, 5, 6, 8, 10, 12, 20, 24, 25, 50, 75, 100, 200, 250, 500, 1000)
    if abs(ratio - round(ratio)) < 0.001 and round(ratio) >= 1:
        return float(round(ratio))

    # Exact metric pack weight/volume in grams/milliliters (up to 3 decimal places, e.g. 0.04, 0.125, 0.454, 1.8, 2.05)
    if 0.001 <= ratio <= 10.0 and abs(ratio * 1000 - round(ratio * 1000)) < 0.01:
        return round(round(ratio * 1000) / 1000.0, 3)

    return 1.0


def safe_extract_zip(zip_path: str, extract_dir: str) -> Tuple[int, int]:
    """Safely extracts zip archive preventing path traversal attacks and OS junk files."""
    xml_count = 0
    pdf_count = 0
    total_uncompressed_size = 0

    with zipfile.ZipFile(zip_path, "r") as zf:
        for member in zf.infolist():
            # Defense against Zip-Slip path traversal
            filename = os.path.basename(member.filename)
            if (
                not filename
                or filename.startswith(".")
                or member.filename.startswith("__MACOSX")
            ):
                continue

            lower_name = filename.lower()
            if not (lower_name.endswith(".xml") or lower_name.endswith(".pdf")):
                continue

            total_uncompressed_size += member.file_size
            if total_uncompressed_size > MAX_BATCH_BYTES:
                raise BatchTrainingError(
                    f"Превышен лимит размера распакованных данных (макс. {MAX_BATCH_BYTES // (1024*1024)} МБ)."
                )

            target_path = os.path.join(extract_dir, filename)
            # Handle duplicate filenames inside subfolders safely
            if os.path.exists(target_path):
                base, ext = os.path.splitext(filename)
                target_path = os.path.join(
                    extract_dir, f"{base}_{abs(hash(member.filename)) % 10000}{ext}"
                )

            with zf.open(member) as source, open(target_path, "wb") as target:
                shutil.copyfileobj(source, target)

            if lower_name.endswith(".xml"):
                xml_count += 1
            else:
                pdf_count += 1

    return xml_count, pdf_count


def _parse_all_scratch_documents(
    files: List[str],
) -> Tuple[List[RawInvoiceDocument], List[datetime.date], List[str]]:
    """CPU-bound parsing of all scratch documents."""
    parsed_docs: List[RawInvoiceDocument] = []
    valid_dates: List[datetime.date] = []
    parse_errors: List[str] = []

    for file_path in files:
        try:
            doc = parse_document(file_path)
            if doc and doc.items:
                parsed_docs.append(doc)
                try:
                    d_obj = datetime.strptime(doc.doc_date, "%Y-%m-%d").date()
                    valid_dates.append(d_obj)
                except ValueError:
                    pass
            else:
                parse_errors.append(
                    f"{os.path.basename(file_path)}: документ не содержит товарных строк"
                )
        except Exception as e:
            parse_errors.append(f"{os.path.basename(file_path)}: {str(e)}")

    return parsed_docs, valid_dates, parse_errors


async def simulate_batch_training(
    scratch_dir: str, login: str, password: str
) -> Dict[str, Any]:
    """Executes deterministic dry-run training simulation using admin's iiko credentials."""
    files = [
        os.path.join(scratch_dir, f)
        for f in os.listdir(scratch_dir)
        if f.lower().endswith((".xml", ".pdf"))
    ]

    if not files:
        raise BatchTrainingError(
            "В пакете не обнаружено поддерживаемых документов (.xml или .pdf)."
        )

    if len(files) > MAX_BATCH_FILES:
        raise BatchTrainingError(
            f"Превышен максимальный лимит документов на одну сессию: {len(files)} из {MAX_BATCH_FILES}."
        )

    parsed_docs, valid_dates, parse_errors = await asyncio.to_thread(
        _parse_all_scratch_documents, files
    )

    if not parsed_docs:
        raise BatchTrainingError(
            f"Не удалось успешно разобрать ни одного документа. Ошибки: {'; '.join(parse_errors[:3])}"
        )

    # Determine date boundaries with 5-day buffer
    if not valid_dates:
        raise BatchTrainingError(
            "Не удалось извлечь ни одной валидной даты из документов пакета. Обучение невозможно."
        )

    min_doc_date = min(valid_dates)
    max_doc_date = max(valid_dates)
    date_from = (min_doc_date - timedelta(days=DATE_BUFFER_DAYS)).strftime("%Y-%m-%d")
    date_to = (max_doc_date + timedelta(days=DATE_BUFFER_DAYS)).strftime("%Y-%m-%d")

    # Fetch active catalog and historical invoices from iiko under admin credentials
    active_products = await asyncio.to_thread(
        client.get_active_stock_products_for_user, login, password
    )
    active_pool = {p["id"]: p for p in active_products}
    suppliers_grouped = await asyncio.to_thread(
        client.get_suppliers_grouped_for_user, login, password
    )

    inv_root = await asyncio.to_thread(
        client.export_incoming_invoices_for_user, login, password, date_from, date_to
    )
    iiko_docs = inv_root.findall(".//document")

    # ==========================================================================
    # ARCHITECTURAL INVARIANT: PARSING FAIL-FAST & ZERO FAKE ZEROS
    #
    # RULE: When parsing documents from external ERP or XML, required numerical
    # fields (sum, amount) must be present.
    #
    # FORBIDDEN:
    # - Using `findtext("sum", 0)` or `findtext("amount", 0)` to substitute
    #   missing structural elements with fake zeros.
    # ==========================================================================

    # Index iiko documents by (supplier_id, documentNumber) and unique sums
    iiko_by_supp_and_num = {}
    iiko_by_supp_and_sum = {}
    for d in iiko_docs:
        s_id = (d.findtext("supplier") or "").strip()
        inc_num = (d.findtext("incomingDocumentNumber") or "").strip()
        items = d.findall(".//items/item")
        item_sums = []
        for it in items:
            raw_sum = it.findtext("sum")
            if raw_sum is None or not raw_sum.strip():
                raise BatchTrainingError(
                    f"iiko invoice #{inc_num} contains item missing required 'sum' element."
                )
            item_sums.append(float(raw_sum))
        doc_sum = round(sum(item_sums), 2)
        if s_id and inc_num:
            iiko_by_supp_and_num[(s_id, inc_num)] = d
        if s_id and doc_sum > 0:
            iiko_by_supp_and_sum.setdefault((s_id, doc_sum), []).append(d)

    candidate_votes: List[Dict[str, Any]] = []
    strict_matches_count = 0
    unique_sums_matches_count = 0
    unmatched_invoices_count = 0

    for doc in parsed_docs:
        target_num = doc.doc_number
        target_sum = round(sum(it.sum for it in doc.items), 2)
        valid_supps = suppliers_grouped.get(doc.supplier_inn, [])
        valid_supplier_ids = {s["id"] for s in valid_supps}

        if not valid_supplier_ids:
            unmatched_invoices_count += 1
            continue

        matched_iiko_doc = None
        for s_id in valid_supplier_ids:
            if (s_id, target_num) in iiko_by_supp_and_num:
                matched_iiko_doc = iiko_by_supp_and_num[(s_id, target_num)]
                break

        if matched_iiko_doc is None:
            for s_id in valid_supplier_ids:
                candidates = iiko_by_supp_and_sum.get((s_id, target_sum), [])
                if len(candidates) == 1:
                    matched_iiko_doc = candidates[0]
                    break

        if matched_iiko_doc is None:
            unmatched_invoices_count += 1
            continue

        supplier_id = matched_iiko_doc.findtext("supplier")
        iiko_num = (matched_iiko_doc.findtext("documentNumber") or target_num).strip()
        raw_iiko_items = matched_iiko_doc.findall(".//items/item")

        all_iiko_items = []
        has_inactive = False
        for it in raw_iiko_items:
            p_id = (it.findtext("product") or "").strip()
            raw_amount = it.findtext("amount")
            if raw_amount is None or not raw_amount.strip():
                raise BatchTrainingError(
                    f"iiko invoice #{iiko_num} item missing required 'amount' element."
                )

            raw_sum = it.findtext("sum")
            if raw_sum is None or not raw_sum.strip():
                raise BatchTrainingError(
                    f"iiko invoice #{iiko_num} item missing required 'sum' element."
                )

            in_pool = p_id in active_pool
            if not in_pool:
                has_inactive = True

            all_iiko_items.append(
                {
                    "product_id": p_id,
                    "in_active_pool": in_pool,
                    "name": active_pool[p_id]["name"] if in_pool else "",
                    "article": active_pool[p_id]["article"] if in_pool else "",
                    "amount": float(raw_amount),
                    "sum": round(float(raw_sum), 2),
                }
            )

        # Invariant 1: Strict sequential order (requires 100% active items and equal line count)
        is_sequential = False
        temp_seq = []
        if not has_inactive and len(doc.items) == len(all_iiko_items):
            is_sequential = True
            for d_item, i_item in zip(doc.items, all_iiko_items):
                if abs(round(d_item.sum, 2) - i_item["sum"]) >= 0.50:
                    is_sequential = False
                    break

                coeff = compute_packaging_coefficient(
                    d_item.quantity, i_item["amount"]
                )

                temp_seq.append(
                    {
                        "supplier_id": supplier_id,
                        "raw_name": d_item.raw_name,
                        "product_id": i_item["product_id"],
                        "iiko_name": i_item["name"],
                        "article": i_item["article"],
                        "vendor_article": d_item.article,
                        "package_coefficient": coeff,
                        "weight": 1,
                    }
                )

        if is_sequential and temp_seq:
            strict_matches_count += 1
            candidate_votes.extend(temp_seq)
            continue

        # Invariant 2: Unique sum bijections across all document lines
        d_sums = Counter(round(it.sum, 2) for it in doc.items)
        i_sums = Counter(it["sum"] for it in all_iiko_items)
        unique_sums = {
            s for s, count in d_sums.items() if count == 1 and i_sums.get(s) == 1
        }

        if unique_sums:
            doc_by_sum = {round(it.sum, 2): it for it in doc.items}
            iiko_by_sum_row = {it["sum"]: it for it in all_iiko_items}
            stage2_pairs = []

            for s in unique_sums:
                d_it = doc_by_sum[s]
                i_it = iiko_by_sum_row[s]
                if not i_it["in_active_pool"]:
                    continue

                coeff = compute_packaging_coefficient(
                    d_it.quantity, i_it["amount"]
                )

                stage2_pairs.append(
                    {
                        "supplier_id": supplier_id,
                        "raw_name": d_it.raw_name,
                        "product_id": i_it["product_id"],
                        "iiko_name": i_it["name"],
                        "article": i_it["article"],
                        "vendor_article": d_it.article,
                        "package_coefficient": coeff,
                        "weight": 1,
                    }
                )

            if stage2_pairs:
                unique_sums_matches_count += 1
                candidate_votes.extend(stage2_pairs)
            else:
                unmatched_invoices_count += 1
        else:
            unmatched_invoices_count += 1

    # Cross-check candidates against current PostgreSQL database
    pool = get_db_pool()
    current_mappings = await pool.fetch(
        "SELECT supplier_id, raw_name, product_id, iiko_name, package_coefficient, usage_count FROM supplier_mappings;"
    )
    current_map = {
        (r["supplier_id"], r["raw_name"].strip().lower()): r for r in current_mappings
    }

    new_items_count = 0
    confirmed_count = 0
    coeff_updates_count = 0
    conflicts = []

    unique_candidates = {}
    for c in candidate_votes:
        key = (c["supplier_id"], c["raw_name"].strip().lower())
        if key not in unique_candidates:
            unique_candidates[key] = c
        else:
            unique_candidates[key]["weight"] += 1

    for key, c in unique_candidates.items():
        if key not in current_map:
            new_items_count += 1
        else:
            curr = current_map[key]
            if curr["product_id"] == c["product_id"]:
                confirmed_count += 1
                if (
                    abs(float(curr["package_coefficient"]) - c["package_coefficient"])
                    > 0.001
                ):
                    coeff_updates_count += 1
            else:
                conflicts.append(
                    {
                        "raw_name": c["raw_name"],
                        "current_name": curr["iiko_name"],
                        "current_votes": curr["usage_count"],
                        "new_name": c["iiko_name"],
                        "new_votes": c["weight"],
                    }
                )

    return {
        "total_files": len(files),
        "parsed_docs_count": len(parsed_docs),
        "parse_errors": parse_errors[:5],
        "date_from": date_from,
        "date_to": date_to,
        "matched_strict": strict_matches_count,
        "matched_unique_sums": unique_sums_matches_count,
        "unmatched_invoices": unmatched_invoices_count,
        "total_candidate_items": len(candidate_votes),
        "unique_items_count": len(unique_candidates),
        "new_items_count": new_items_count,
        "confirmed_count": confirmed_count,
        "coeff_updates_count": coeff_updates_count,
        "conflicts_count": len(conflicts),
        "conflict_examples": conflicts[:3],
        "candidates_list": list(unique_candidates.values()),
    }


async def apply_batch_training(candidates: List[Dict[str, Any]], admin_id: int) -> int:
    """Atomically commits verified batch candidates into PostgreSQL."""
    pool = get_db_pool()
    committed_count = 0

    async with pool.acquire() as conn:
        async with conn.transaction():
            for c in candidates:
                await record_mapping_vote(
                    supplier_id=c["supplier_id"],
                    raw_name=c["raw_name"],
                    product_id=c["product_id"],
                    iiko_name=c["iiko_name"],
                    article=c.get("article", ""),
                    vendor_article=c.get("vendor_article", ""),
                    weight=c.get("weight", 1),
                    package_coefficient=c.get("package_coefficient", 1.0),
                    user_id=admin_id,
                    source="batch_training",
                )
                committed_count += 1

    logger.info(
        f"Admin {admin_id} committed {committed_count} mappings from batch training."
    )
    return committed_count
