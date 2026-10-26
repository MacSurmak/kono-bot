import os
import uuid
import asyncio
from typing import Dict, Any, List
from aiogram import Router, types, F
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from rapidfuzz import process, fuzz
from loguru import logger

from lexicon import t
from parsers import parse_document
from config import ALLOWED_STORES
from iiko_client import client
from invoice_service import build_iiko_xml
from item_matcher import find_catalog_candidates
from storage import (
    get_consensus_mapping,
    record_mapping_vote,
    get_preferred_supplier,
    save_preferred_supplier,
)


class InvoiceState(StatesGroup):
    waiting_manual_sku = State()


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
        logger.info(f"Incoming document from user {message.from_user.id} ({message.from_user.full_name}): '{filename}'")
        await message.bot.download(doc.file_id, destination=temp_path)
        parsed_doc = await asyncio.to_thread(parse_document, temp_path)

        if not parsed_doc or not parsed_doc.items:
            raise ValueError("Документ не содержит товарных позиций или поврежден.")

        total_sum = sum(it.sum for it in parsed_doc.items)
        logger.info(f"Document parsed successfully: Doc #{parsed_doc.doc_number}, supplier='{parsed_doc.supplier_name}', items={len(parsed_doc.items)}, total={total_sum:.2f} RUB")

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

        if ext == ".pdf":
            # Generate preview of extracted lines for visual verification
            preview_lines = []
            for it in parsed_doc.items[:15]:
                name = it.raw_name[:32]
                preview_lines.append(f"{it.line_num}. {name} — {it.quantity:.2f} × {it.price:.2f} ₽ = {it.sum:.2f} ₽")
            if len(parsed_doc.items) > 15:
                preview_lines.append(f"<i>...и еще {len(parsed_doc.items) - 15} позиций</i>")

            from keyboards.invoices_kb import get_pdf_confirmation_kb
            await status_msg.edit_text(
                t(
                    "pdf_verification_card",
                    doc_number=parsed_doc.doc_number or "Б/Н",
                    doc_date=parsed_doc.doc_date,
                    supplier_name=parsed_doc.supplier_name or "Не определен",
                    supplier_inn=parsed_doc.supplier_inn or "Не определен",
                    total_sum=total_sum,
                    items_count=len(parsed_doc.items),
                    items_preview="\n".join(preview_lines),
                ),
                reply_markup=get_pdf_confirmation_kb(doc_id)
            )
        else:
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


@router.callback_query(F.data.startswith("inv:pdf_ok:"))
async def process_pdf_confirmation(callback: types.CallbackQuery):
    """Handles operator approval of raw OCR extraction and advances to store selection."""
    doc_id = callback.data.split(":")[2]
    session = sessions.get(doc_id)
    if not session:
        await callback.message.edit_text(t("invoice_session_expired"))
        return

    parsed_doc = session["parsed_doc"]
    from keyboards.invoices_kb import get_store_selection_kb
    await callback.message.edit_text(
        t(
            "invoice_card",
            doc_number=parsed_doc.doc_number or "Б/Н",
            doc_date=parsed_doc.doc_date,
            supplier_name=parsed_doc.supplier_name,
            supplier_inn=parsed_doc.supplier_inn,
            total_sum=session["total_sum"],
            items_count=len(parsed_doc.items),
        ),
        reply_markup=get_store_selection_kb(doc_id)
    )


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
    logger.info(f"Store selected for Doc #{parsed_doc.doc_number}: '{session['store_name']}' ({store_id})")

    # 1. Resolve Supplier
    pref = get_preferred_supplier(parsed_doc.supplier_inn)
    if pref:
        session["supplier_id"], session["supplier_name"] = pref[0], pref[1]
    else:
        suppliers_grouped = client.get_suppliers_grouped()
        candidates = suppliers_grouped.get(parsed_doc.supplier_inn, [])

        if not candidates:
            # Fallback: fuzzy search supplier by name across entire iiko registry
            all_suppliers = [s for supp_list in suppliers_grouped.values() for s in supp_list]
            supp_names = [s["name"] for s in all_suppliers]
            top_matches = process.extract(
                parsed_doc.supplier_name, supp_names, limit=4, scorer=fuzz.token_sort_ratio
            )

            fuzzy_candidates = []
            for name, score, _ in top_matches:
                if score >= 45:
                    match_supp = next((s for s in all_suppliers if s["name"] == name), None)
                    if match_supp and match_supp not in fuzzy_candidates:
                        fuzzy_candidates.append({**match_supp, "score": score})

            if fuzzy_candidates:
                from keyboards.invoices_kb import get_fuzzy_supplier_kb
                await callback.message.edit_text(
                    t(
                        "invoice_supplier_not_found_fuzzy",
                        inn=parsed_doc.supplier_inn or "Не указан",
                        raw_name=parsed_doc.supplier_name,
                    ),
                    reply_markup=get_fuzzy_supplier_kb(doc_id, fuzzy_candidates)
                )
                return
            else:
                await callback.message.edit_text(
                    t(
                        "invoice_supplier_none_matched",
                        raw_name=parsed_doc.supplier_name,
                        inn=parsed_doc.supplier_inn or "Не указан"
                    )
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
    """Saves chosen supplier branch globally and advances to item alignment."""
    parts = callback.data.split(":")
    doc_id, supp_id = parts[2], parts[3]

    session = sessions.get(doc_id)
    if not session:
        await callback.message.edit_text(t("invoice_session_expired"))
        return

    suppliers_grouped = client.get_suppliers_grouped()
    all_suppliers = [s for supp_list in suppliers_grouped.values() for s in supp_list]
    chosen = next((c for c in all_suppliers if c["id"] == supp_id), None)

    if chosen:
        inn_to_save = session["parsed_doc"].supplier_inn or "CUSTOM"
        save_preferred_supplier(inn_to_save, chosen["id"], chosen["name"])
        session["supplier_id"] = chosen["id"]
        session["supplier_name"] = chosen["name"]
        logger.info(f"Associated supplier preference: INN={inn_to_save} -> '{chosen['name']}' ({chosen['id']})")

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
            coeff = consensus.get("package_coefficient", 1.0) or 1.0
            matched_items.append({
                "num": idx,
                "product_id": consensus["product_id"],
                "iiko_name": consensus["iiko_name"],
                "raw_name": item.raw_name,
                "amount": item.quantity,
                "coefficient": coeff,
                "price": item.price,
                "sum": item.sum,
                "vat": item.vat_rate,
            })
        else:
            # Generate smart domain-aware candidates using item_matcher
            candidates = find_catalog_candidates(
                raw_name=item.raw_name,
                article=item.article,
                catalog=catalog,
                limit=3
            )
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


async def prompt_next_unresolved_item(message: types.Message, doc_id: str, is_new: bool = False):
    """Presents the next unaligned item to the operator, either editing or sending a fresh message."""
    session = sessions.get(doc_id)
    if not session or not session["unresolved_items"]:
        return

    current = session["unresolved_items"][0]
    item = current["item"]
    total = len(session["parsed_doc"].items)
    from keyboards.invoices_kb import get_item_resolution_kb

    article_info = f"\nАртикул поставщика: <code>{item.article}</code>" if item.article else ""
    card_text = t(
        "invoice_unmatched_item_card",
        current=current["item_idx"],
        total=total,
        raw_name=item.raw_name,
        article_info=article_info,
        sum=item.sum,
        qty=item.quantity,
    )
    markup = get_item_resolution_kb(doc_id, current["item_idx"], current["candidates"])

    if is_new:
        await message.answer(card_text, reply_markup=markup)
    else:
        await message.edit_text(card_text, reply_markup=markup)


@router.callback_query(F.data.startswith("inv:manual:"))
async def process_manual_sku_click(callback: types.CallbackQuery, state: FSMContext):
    """Initiates FSM prompt waiting for manual iiko SKU input from operator."""
    parts = callback.data.split(":")
    doc_id, item_idx = parts[2], int(parts[3])

    session = sessions.get(doc_id)
    if not session or not session["unresolved_items"]:
        await callback.message.edit_text(t("invoice_session_expired"))
        return

    current_item = session["unresolved_items"][0]["item"]
    await state.set_state(InvoiceState.waiting_manual_sku)
    await state.update_data(doc_id=doc_id, item_idx=item_idx)

    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    cancel_kb = InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text=t("btn_cancel"), callback_data=f"inv:cancel:{doc_id}")]]
    )
    await callback.message.edit_text(
        t("invoice_enter_sku_prompt", raw_name=current_item.raw_name),
        reply_markup=cancel_kb
    )


@router.message(InvoiceState.waiting_manual_sku)
async def handle_manual_sku_input(message: types.Message, state: FSMContext):
    """Validates entered SKU (with optional packaging multiplier) against live iiko stock catalog."""
    raw_input = message.text.strip()
    data = await state.get_data()
    doc_id = data.get("doc_id")
    item_idx = data.get("item_idx")

    session = sessions.get(doc_id)
    if not session or not session.get("unresolved_items"):
        await state.clear()
        await message.answer(t("invoice_session_expired"))
        return

    # Parse optional packaging multiplier, e.g. "6406*100" or "6406 x100"
    sku = raw_input
    coeff = 1.0
    import re
    if "*" in raw_input:
        parts = raw_input.split("*", 1)
        sku = parts[0].strip()
        try:
            coeff = float(parts[1].strip().replace(",", "."))
        except ValueError:
            coeff = 1.0
    elif " x" in raw_input.lower():
        parts = re.split(r"\s+[xх]\s*", raw_input, flags=re.IGNORECASE)
        if len(parts) == 2:
            sku = parts[0].strip()
            try:
                coeff = float(parts[1].strip().replace(",", "."))
            except ValueError:
                coeff = 1.0

    catalog = await asyncio.to_thread(client.get_active_stock_products)
    clean_sku = sku.lower()
    prod = next(
        (p for p in catalog if p.get("article", "").strip().lower() == clean_sku or p.get("id", "").strip().lower() == clean_sku),
        None
    )

    if not prod:
        await message.answer(t("invoice_sku_not_found", sku=sku))
        return

    resolved_entry = session["unresolved_items"].pop(0)
    item = resolved_entry["item"]

    record_mapping_vote(
        supplier_id=session["supplier_id"],
        raw_name=item.raw_name,
        product_id=prod["id"],
        iiko_name=prod["name"],
        article=sku,
        weight=3,
        package_coefficient=coeff
    )
    session["matched_items"].append({
        "num": item_idx,
        "product_id": prod["id"],
        "iiko_name": prod["name"],
        "raw_name": item.raw_name,
        "amount": item.quantity,
        "coefficient": coeff,
        "price": item.price,
        "sum": item.sum,
        "vat": item.vat_rate,
    })
    logger.info(f"Manual SKU match confirmed: '{item.raw_name}' -> '{prod['name']}' (article={sku}, coeff={coeff})")

    pack_info = f", фасовка x{coeff:g}" if coeff > 1.0 else ""
    await state.clear()
    await message.answer(t("invoice_sku_matched_success", prod_name=prod["name"], sku=sku, pack_info=pack_info))

    if session["unresolved_items"]:
        await prompt_next_unresolved_item(message, doc_id, is_new=True)
    else:
        from keyboards.invoices_kb import get_upload_confirmation_kb
        await message.answer(
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
    from loguru import logger

    if prod:
        record_mapping_vote(
            supplier_id=session["supplier_id"],
            raw_name=item.raw_name,
            product_id=prod["id"],
            iiko_name=prod["name"],
            article=item.article or prod["article"],
            weight=2
        )
        logger.info(f"Recorded manual mapping vote: '{item.raw_name}' -> '{prod['name']}' (supplier_id={session['supplier_id']})")
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
            logger.info(f"Draft invoice created in iiko: #{iiko_doc_num} (incoming: #{session['parsed_doc'].doc_number}) for store '{session['store_name']}'")
            await callback.message.edit_text(
                t(
                    "invoice_draft_success",
                    store_name=session["store_name"],
                    iiko_doc_num=iiko_doc_num,
                    inc_doc_num=session["parsed_doc"].doc_number or "Б/Н",
                )
            )
        else:
            logger.error(f"iiko upload rejected: {resp.status_code} - {resp.text[:300]}")
            await callback.message.edit_text(t("invoice_upload_failed", error=resp.text[:300]))

    except Exception as e:
        logger.exception(f"Unexpected error while uploading invoice to iiko: {e}")
        await callback.message.edit_text(t("invoice_upload_failed", error=str(e)))
    finally:
        cleanup_session(doc_id)


@router.callback_query(F.data.startswith("inv:cancel:"))
async def process_invoice_cancel(callback: types.CallbackQuery):
    """Cancels invoice processing and deletes local temporary artifacts."""
    doc_id = callback.data.split(":")[2]
    cleanup_session(doc_id)
    await callback.message.edit_text(t("invoice_cancelled"))
