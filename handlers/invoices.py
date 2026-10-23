import os
import uuid
from typing import Dict, Any, List
from aiogram import Router, types, F
from rapidfuzz import process, fuzz

from lexicon import t
from parsers import parse_document
from config import ALLOWED_STORES
from iiko_client import client
from invoice_service import build_iiko_xml
from storage import (
    get_consensus_mapping,
    record_mapping_vote,
    get_preferred_supplier,
    save_preferred_supplier,
)

router = Router(name="invoices_router")

# In-memory document processing sessions
TMP_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "in", "telegram_tmp")
os.makedirs(TMP_DIR, exist_ok=True)

sessions: Dict[str, Dict[str, Any]] = {}


def cleanup_session(doc_id: str) -> None:
    """Removes temporary session state and local file artifact."""
    session = sessions.pop(doc_id, None)
    if session and "file_path" in session:
        file_path = session["file_path"]
        if os.path.exists(file_path):
            try:
                os.remove(file_path)
            except OSError:
                pass


@router.message(F.document)
async def handle_document_upload(message: types.Message):
    """Entrypoint for incoming XML and PDF supplier invoices."""
    doc = message.document
    filename = doc.file_name or "unknown_file"
    ext = os.path.splitext(filename)[1].lower()

    if ext not in (".xml", ".pdf"):
        await message.answer(t("invoice_invalid_format"))
        return

    status_msg = await message.answer(t("invoice_parsing_wait", filename=filename))

    doc_id = str(uuid.uuid4())[:8]
    temp_path = os.path.join(TMP_DIR, f"{doc_id}_{filename}")

    try:
        await message.bot.download(doc.file_id, destination=temp_path)
        parsed_doc = parse_document(temp_path)

        if not parsed_doc or not parsed_doc.items:
            raise ValueError("Документ не содержит товарных позиций или поврежден.")

        total_sum = sum(it.sum for it in parsed_doc.items)

        sessions[doc_id] = {
            "parsed_doc": parsed_doc,
            "file_path": temp_path,
            "total_sum": total_sum,
            "store_id": None,
            "store_name": None,
            "supplier_id": None,
            "supplier_name": None,
            "matched_items": [],
            "unresolved_items": [],
        }

        from keyboards.invoices_kb import get_store_selection_kb
        await status_msg.edit_text(
            t(
                "invoice_card",
                doc_number=parsed_doc.doc_number or "Б/Н",
                doc_date=parsed_doc.doc_date,
                supplier_name=parsed_doc.supplier_name,
                supplier_inn=parsed_doc.supplier_inn,
                total_sum=total_sum,
                items_count=len(parsed_doc.items),
            ),
            reply_markup=get_store_selection_kb(doc_id)
        )

    except Exception as e:
        if os.path.exists(temp_path):
            os.remove(temp_path)
        sessions.pop(doc_id, None)
        await status_msg.edit_text(t("invoice_parsing_error", error=str(e)))


@router.callback_query(F.data.startswith("inv:store:"))
async def process_store_selection(callback: types.CallbackQuery):
    """Handles store destination choice and initiates item alignment."""
    parts = callback.data.split(":")
    doc_id, store_id = parts[2], parts[3]

    session = sessions.get(doc_id)
    if not session:
        await callback.message.edit_text(t("invoice_session_expired"))
        return

    session["store_id"] = store_id
    session["store_name"] = ALLOWED_STORES[store_id]
    parsed_doc = session["parsed_doc"]

    # 1. Resolve Supplier
    pref = get_preferred_supplier(parsed_doc.supplier_inn)
    if pref:
        session["supplier_id"], session["supplier_name"] = pref[0], pref[1]
    else:
        suppliers = client.get_suppliers_grouped()
        candidates = suppliers.get(parsed_doc.supplier_inn, [])
        if not candidates:
            await callback.message.edit_text(
                t("invoice_parsing_error", error=f"Поставщик с ИНН {parsed_doc.supplier_inn} не найден в iiko!")
            )
            cleanup_session(doc_id)
            return

        if len(candidates) == 1:
            session["supplier_id"] = candidates[0]["id"]
            session["supplier_name"] = candidates[0]["name"]
        else:
            from keyboards.invoices_kb import get_supplier_disambiguation_kb
            await callback.message.edit_text(
                t("invoice_supplier_conflict", inn=parsed_doc.supplier_inn),
                reply_markup=get_supplier_disambiguation_kb(doc_id, candidates)
            )
            return

    await proceed_with_item_alignment(callback.message, doc_id)


@router.callback_query(F.data.startswith("inv:supp:"))
async def process_supplier_disambiguation(callback: types.CallbackQuery):
    """Saves chosen supplier branch and advances to item alignment."""
    parts = callback.data.split(":")
    doc_id, supp_id = parts[2], parts[3]

    session = sessions.get(doc_id)
    if not session:
        await callback.message.edit_text(t("invoice_session_expired"))
        return

    suppliers = client.get_suppliers_grouped()
    candidates = suppliers.get(session["parsed_doc"].supplier_inn, [])
    chosen = next((c for c in candidates if c["id"] == supp_id), None)
    if chosen:
        save_preferred_supplier(session["parsed_doc"].supplier_inn, chosen["id"], chosen["name"])
        session["supplier_id"] = chosen["id"]
        session["supplier_name"] = chosen["name"]

    await proceed_with_item_alignment(callback.message, doc_id)


async def proceed_with_item_alignment(message: types.Message, doc_id: str):
    """Executes item matching against knowledge base and active stock catalog."""
    session = sessions.get(doc_id)
    if not session:
        return

    catalog = client.get_active_stock_products()
    supplier_id = session["supplier_id"]
    parsed_doc = session["parsed_doc"]

    matched_items = []
    unresolved_items = []

    for idx, item in enumerate(parsed_doc.items, 1):
        consensus = get_consensus_mapping(supplier_id, item.raw_name)
        if consensus and not consensus["has_conflict"]:
            matched_items.append({
                "num": idx,
                "product_id": consensus["product_id"],
                "iiko_name": consensus["iiko_name"],
                "raw_name": item.raw_name,
                "amount": item.quantity,
                "price": item.price,
                "sum": item.sum,
                "vat": item.vat_rate,
            })
        else:
            # Generate top 3 catalog suggestions
            choices = [p["name"] for p in catalog]
            top_matches = process.extract(item.raw_name, choices, limit=3, scorer=fuzz.token_sort_ratio)
            name_to_prod = {p["name"]: p for p in catalog}

            candidates = []
            for name, score, _ in top_matches:
                p = name_to_prod[name]
                candidates.append({"id": p["id"], "name": p["name"], "score": score})

            unresolved_items.append({
                "item_idx": idx,
                "item": item,
                "candidates": candidates
            })

    session["matched_items"] = matched_items
    session["unresolved_items"] = unresolved_items

    if not unresolved_items:
        from keyboards.invoices_kb import get_upload_confirmation_kb
        await message.edit_text(
            t(
                "invoice_all_matched_card",
                doc_number=parsed_doc.doc_number or "Б/Н",
                doc_date=parsed_doc.doc_date,
                supplier_name=session["supplier_name"],
                store_name=session["store_name"],
                total_sum=session["total_sum"],
                items_count=len(matched_items),
            ),
            reply_markup=get_upload_confirmation_kb(doc_id)
        )
    else:
        await prompt_next_unresolved_item(message, doc_id)


async def prompt_next_unresolved_item(message: types.Message, doc_id: str):
    """Presents the next unaligned item to the operator."""
    session = sessions.get(doc_id)
    if not session or not session["unresolved_items"]:
        return

    current = session["unresolved_items"][0]
    item = current["item"]
    total = len(session["parsed_doc"].items)
    from keyboards.invoices_kb import get_item_resolution_kb

    article_info = f"\nАртикул поставщика: <code>{item.article}</code>" if item.article else ""
    await message.edit_text(
        t(
            "invoice_unmatched_item_card",
            current=current["item_idx"],
            total=total,
            raw_name=item.raw_name,
            article_info=article_info,
            sum=item.sum,
            qty=item.quantity,
        ),
        reply_markup=get_item_resolution_kb(doc_id, current["item_idx"], current["candidates"])
    )


@router.callback_query(F.data.startswith("inv:match:"))
async def process_manual_match(callback: types.CallbackQuery):
    """Records operator alignment vote into knowledge base."""
    parts = callback.data.split(":")
    doc_id, item_idx, prod_id = parts[2], int(parts[3]), parts[4]

    session = sessions.get(doc_id)
    if not session or not session["unresolved_items"]:
        await callback.message.edit_text(t("invoice_session_expired"))
        return

    resolved_entry = session["unresolved_items"].pop(0)
    item = resolved_entry["item"]

    catalog = client.get_active_stock_products()
    prod = next((p for p in catalog if p["id"] == prod_id), None)
    if prod:
        record_mapping_vote(
            supplier_id=session["supplier_id"],
            raw_name=item.raw_name,
            product_id=prod["id"],
            iiko_name=prod["name"],
            article=item.article or prod["article"],
            weight=2
        )
        session["matched_items"].append({
            "num": item_idx,
            "product_id": prod["id"],
            "iiko_name": prod["name"],
            "raw_name": item.raw_name,
            "amount": item.quantity,
            "price": item.price,
            "sum": item.sum,
            "vat": item.vat_rate,
        })

    if session["unresolved_items"]:
        await prompt_next_unresolved_item(callback.message, doc_id)
    else:
        from keyboards.invoices_kb import get_upload_confirmation_kb
        await callback.message.edit_text(
            t(
                "invoice_all_matched_card",
                doc_number=session["parsed_doc"].doc_number or "Б/Н",
                doc_date=session["parsed_doc"].doc_date,
                supplier_name=session["supplier_name"],
                store_name=session["store_name"],
                total_sum=session["total_sum"],
                items_count=len(session["matched_items"]),
            ),
            reply_markup=get_upload_confirmation_kb(doc_id)
        )


@router.callback_query(F.data.startswith("inv:skip:"))
async def process_skip_item(callback: types.CallbackQuery):
    """Skips unmatched item without creating an alignment record."""
    parts = callback.data.split(":")
    doc_id = parts[2]

    session = sessions.get(doc_id)
    if not session or not session["unresolved_items"]:
        await callback.message.edit_text(t("invoice_session_expired"))
        return

    session["unresolved_items"].pop(0)
    if session["unresolved_items"]:
        await prompt_next_unresolved_item(callback.message, doc_id)
    else:
        from keyboards.invoices_kb import get_upload_confirmation_kb
        await callback.message.edit_text(
            t(
                "invoice_all_matched_card",
                doc_number=session["parsed_doc"].doc_number or "Б/Н",
                doc_date=session["parsed_doc"].doc_date,
                supplier_name=session["supplier_name"],
                store_name=session["store_name"],
                total_sum=session["total_sum"],
                items_count=len(session["matched_items"]),
            ),
            reply_markup=get_upload_confirmation_kb(doc_id)
        )


@router.callback_query(F.data.startswith("inv:upload:"))
async def process_draft_upload(callback: types.CallbackQuery):
    """Builds escaped XML and uploads draft invoice to iiko."""
    doc_id = callback.data.split(":")[2]
    session = sessions.get(doc_id)
    if not session:
        await callback.message.edit_text(t("invoice_session_expired"))
        return

    try:
        xml_payload = build_iiko_xml(
            doc=session["parsed_doc"],
            store_id=session["store_id"],
            supplier_id=session["supplier_id"],
            matched_items=session["matched_items"],
        )

        resp = client.upload_invoice(session["store_id"], xml_payload)
        import xml.etree.ElementTree as ET

        if resp.status_code == 200 and "valid>true" in resp.text:
            iiko_doc_num = ET.fromstring(resp.content).findtext("documentNumber") or "Создан"
            await callback.message.edit_text(
                t(
                    "invoice_draft_success",
                    store_name=session["store_name"],
                    iiko_doc_num=iiko_doc_num,
                    inc_doc_num=session["parsed_doc"].doc_number or "Б/Н",
                )
            )
        else:
            await callback.message.edit_text(t("invoice_upload_failed", error=resp.text[:300]))

    except Exception as e:
        await callback.message.edit_text(t("invoice_upload_failed", error=str(e)))
    finally:
        cleanup_session(doc_id)


@router.callback_query(F.data.startswith("inv:cancel:"))
async def process_invoice_cancel(callback: types.CallbackQuery):
    """Cancels invoice processing and deletes local temporary artifacts."""
    doc_id = callback.data.split(":")[2]
    cleanup_session(doc_id)
    await callback.message.edit_text(t("invoice_cancelled"))
