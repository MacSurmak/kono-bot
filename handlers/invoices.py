import os
import uuid
import time
import asyncio
import xml.etree.ElementTree as ET
from typing import Dict, Any, List, Optional
from aiogram import Router, types, F
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from rapidfuzz import process, fuzz
from loguru import logger

from lexicon import t
from models import RawInvoiceDocument
from parsers import parse_document
from services.crypto import decrypt_secret
from services.iiko_client import client, IikoApiError
from services.invoice_service import build_iiko_xml
from services.item_matcher import (
    find_catalog_candidates,
    MIN_ACCEPTABLE_SCORE,
    FUZZY_SUPPLIER_SEARCH_LIMIT,
)
from storage import (
    get_consensus_mapping,
    record_mapping_vote,
    get_preferred_supplier,
    save_preferred_supplier,
    get_user_stores,
    get_bot_user,
    save_invoice_session,
    get_invoice_session,
    delete_invoice_session,
)
from keyboards.invoices_kb import (
    get_invoice_store_choice_kb,
    get_fuzzy_supplier_kb,
    get_supplier_disambiguation_kb,
    get_upload_confirmation_kb,
    get_item_resolution_kb,
    get_packaging_coeff_kb,
    get_items_review_kb,
    get_upload_retry_kb,
    get_setup_creds_kb,
)


class InvoiceState(StatesGroup):
    waiting_manual_sku = State()
    waiting_custom_coeff = State()


router = Router(name="invoices_router")

TMP_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "data",
    "in",
    "telegram_tmp",
)
os.makedirs(TMP_DIR, exist_ok=True)

# Per-document mutex locks to eliminate race conditions on simultaneous button taps
from config import (
    PAGE_SIZE_INVOICE_STORES,
    PAGE_SIZE_REVIEW_ITEMS,
    CACHE_TTL_CATALOG_SECONDS,
    CACHE_TTL_SUPPLIERS_SECONDS,
)

_DOC_LOCKS: Dict[str, asyncio.Lock] = {}
_CATALOG_CACHE: Dict[str, Any] = {"timestamp": 0.0, "data": []}
_SUPPLIERS_CACHE: Dict[str, Any] = {"timestamp": 0.0, "data": {}}
_CACHE_LOCK = asyncio.Lock()


def get_doc_lock(doc_id: str) -> asyncio.Lock:
    if doc_id not in _DOC_LOCKS:
        _DOC_LOCKS[doc_id] = asyncio.Lock()
    return _DOC_LOCKS[doc_id]


async def get_cached_catalog(login: str, password: str) -> list:
    async with _CACHE_LOCK:
        now = time.monotonic()
        if not _CATALOG_CACHE["data"] or (
            now - _CATALOG_CACHE["timestamp"] > CACHE_TTL_CATALOG_SECONDS
        ):
            catalog = await asyncio.to_thread(
                client.get_active_stock_products_for_user, login, password
            )
            _CATALOG_CACHE["data"] = catalog
            _CATALOG_CACHE["timestamp"] = now
        return _CATALOG_CACHE["data"]


async def get_cached_suppliers(login: str, password: str) -> dict:
    async with _CACHE_LOCK:
        now = time.monotonic()
        if not _SUPPLIERS_CACHE["data"] or (
            now - _SUPPLIERS_CACHE["timestamp"] > CACHE_TTL_SUPPLIERS_SECONDS
        ):
            suppliers = await asyncio.to_thread(
                client.get_suppliers_grouped_for_user, login, password
            )
            _SUPPLIERS_CACHE["data"] = suppliers
            _SUPPLIERS_CACHE["timestamp"] = now
        return _SUPPLIERS_CACHE["data"]


async def cleanup_session_data(doc_id: str) -> None:
    """Removes persistent session record and associated local disk artifact."""
    session = await get_invoice_session(doc_id)
    if session and "file_path" in session:
        file_path = session["file_path"]
        if os.path.exists(file_path):
            try:
                os.remove(file_path)
            except OSError:
                pass
    await delete_invoice_session(doc_id)
    _DOC_LOCKS.pop(doc_id, None)


@router.message(F.document)
async def handle_document_upload(message: types.Message):
    """Entrypoint for incoming invoices. Validates connected stores first before any parsing."""
    doc = message.document
    if not doc.file_name or not doc.file_name.strip():
        raise ValueError("Uploaded Telegram document is missing a valid filename.")
    filename = doc.file_name.strip()
    ext = os.path.splitext(filename)[1].lower()

    if ext not in (".xml", ".pdf"):
        await message.answer(t("invoice_invalid_format"))
        return

    # Fail-Fast: verify operator has connected stores
    operator = await get_bot_user(message.from_user.id)
    if (
        not operator
        or not operator.get("iiko_login")
        or not operator.get("iiko_password_encrypted")
    ):
        await message.answer(
            t("invoice_no_creds_error"),
            reply_markup=get_setup_creds_kb("setup"),
            parse_mode="HTML",
        )
        return

    user_stores = await get_user_stores(message.from_user.id)
    if not user_stores:
        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text=t("btn_connect_stores"), callback_data="cab:my_stores"
                    )
                ]
            ]
        )
        await message.answer(
            t("invoice_no_stores_error"), reply_markup=kb, parse_mode="HTML"
        )
        return

    doc_id = str(uuid.uuid4())[:8]
    temp_path = os.path.join(TMP_DIR, f"{doc_id}_{filename}")
    await message.bot.download(doc.file_id, destination=temp_path)

    # Initial session without store assigned yet
    session_data = {
        "doc_id": doc_id,
        "user_id": message.from_user.id,
        "filename": filename,
        "ext": ext,
        "file_path": temp_path,
        "store_id": None,
        "store_name": None,
        "parsed_doc": None,
        "total_sum": 0.0,
        "supplier_id": None,
        "supplier_name": None,
        "matched_items": [],
        "unresolved_items": [],
    }
    await save_invoice_session(doc_id, message.from_user.id, session_data)

    login = operator["iiko_login"]
    password = decrypt_secret(operator["iiko_password_encrypted"])

    # Single store connected -> Auto-select and proceed directly
    if len(user_stores) == 1:
        chosen_store = user_stores[0]
        status_msg = await message.answer(
            t("invoice_store_autoselected", store=chosen_store["name"])
            + t("invoice_parsing_wait", filename=filename),
            parse_mode="HTML",
        )
        await execute_parse_and_alignment(
            status_msg,
            doc_id,
            chosen_store["store_id"],
            chosen_store["name"],
            login,
            password,
        )
    else:
        # Multiple stores connected -> Operator chooses target store with paginated view
        await message.answer(
            t("invoice_select_store_first", filename=filename),
            reply_markup=get_invoice_store_choice_kb(
                doc_id, user_stores, page=1, page_size=PAGE_SIZE_INVOICE_STORES
            ),
            parse_mode="HTML",
        )


@router.callback_query(F.data.startswith("inv:store_page:"))
async def process_store_page_choice(callback: types.CallbackQuery):
    """Paginates store list for incoming invoice."""
    parts = callback.data.split(":")
    doc_id, page = parts[2], int(parts[3])

    session = await get_invoice_session(doc_id)
    if not session:
        await callback.message.edit_text(t("invoice_session_expired"))
        return

    user_stores = await get_user_stores(callback.from_user.id)
    await callback.message.edit_reply_markup(
        reply_markup=get_invoice_store_choice_kb(
            doc_id, user_stores, page=page, page_size=PAGE_SIZE_INVOICE_STORES
        )
    )


@router.callback_query(F.data.startswith("inv:init_store:"))
async def process_initial_store_choice(callback: types.CallbackQuery):
    """Records chosen target store first and initiates document parsing."""
    parts = callback.data.split(":")
    doc_id, store_id = parts[2], parts[3]

    session = await get_invoice_session(doc_id)
    if not session:
        await callback.message.edit_text(t("invoice_session_expired"))
        return

    operator = await get_bot_user(callback.from_user.id)
    if (
        not operator
        or not operator.get("iiko_login")
        or not operator.get("iiko_password_encrypted")
    ):
        await callback.message.edit_text(t("invoice_no_creds_error"))
        return

    login = operator["iiko_login"]
    password = decrypt_secret(operator["iiko_password_encrypted"])

    user_stores = await get_user_stores(callback.from_user.id)
    chosen = next((s for s in user_stores if s["store_id"] == store_id), None)
    if not chosen:
        raise ValueError(
            f"Selected store ID '{store_id}' is not connected to operator's account."
        )
    store_name = chosen["name"]

    await callback.message.edit_text(
        t("invoice_store_selected", store=store_name)
        + t("invoice_parsing_wait", filename=session.get("filename", "документ")),
        parse_mode="HTML",
    )
    await execute_parse_and_alignment(
        callback.message, doc_id, store_id, store_name, login, password
    )


async def execute_parse_and_alignment(
    message: types.Message,
    doc_id: str,
    store_id: str,
    store_name: str,
    login: str,
    password: str,
):
    """Executes document parsing and advances directly to item alignment using operator credentials."""
    session = await get_invoice_session(doc_id)
    temp_path = session["file_path"]

    try:
        parsed_doc = await asyncio.to_thread(parse_document, temp_path)
        if not parsed_doc or not parsed_doc.items:
            raise ValueError(t("invoice_empty_items_error"))

        total_sum = sum(it.sum for it in parsed_doc.items)
        session["store_id"] = store_id
        session["store_name"] = store_name
        session["total_sum"] = total_sum
        session["parsed_doc"] = {
            "doc_number": parsed_doc.doc_number,
            "doc_date": parsed_doc.doc_date,
            "supplier_inn": parsed_doc.supplier_inn,
            "supplier_name": parsed_doc.supplier_name,
            "consignee_address": parsed_doc.consignee_address,
            "source_file": temp_path,
            "items": [
                {
                    "line_num": it.line_num,
                    "raw_name": it.raw_name,
                    "article": it.article,
                    "quantity": it.quantity,
                    "price": it.price,
                    "sum": it.sum,
                    "vat_rate": it.vat_rate,
                }
                for it in parsed_doc.items
            ],
        }
        await save_invoice_session(doc_id, session["user_id"], session)

        # Resolve Supplier via INN preference or directory
        supplier_inn = (parsed_doc.supplier_inn or "").strip()
        pref = await get_preferred_supplier(supplier_inn) if supplier_inn else None

        if pref:
            session["supplier_id"], session["supplier_name"] = pref[0], pref[1]
            await save_invoice_session(doc_id, session["user_id"], session)
        else:
            suppliers_grouped = await get_cached_suppliers(login, password)
            candidates = suppliers_grouped.get(supplier_inn, []) if supplier_inn else []

            if not candidates:
                all_suppliers = [
                    s for supp_list in suppliers_grouped.values() for s in supp_list
                ]
                supp_names = [s["name"] for s in all_suppliers]
                raw_supp_name = parsed_doc.supplier_name
                top_matches = process.extract(
                    raw_supp_name,
                    supp_names,
                    limit=FUZZY_SUPPLIER_SEARCH_LIMIT,
                    scorer=fuzz.token_sort_ratio,
                )

                fuzzy_candidates = []
                for name, score, _ in top_matches:
                    if score >= MIN_ACCEPTABLE_SCORE:
                        match_supp = next(
                            (s for s in all_suppliers if s["name"] == name), None
                        )
                        if match_supp and match_supp not in fuzzy_candidates:
                            fuzzy_candidates.append({**match_supp, "score": score})

                if fuzzy_candidates:
                    await message.edit_text(
                        t(
                            "invoice_supplier_not_found_fuzzy",
                            inn=supplier_inn or t("invoice_inn_not_specified"),
                            raw_name=raw_supp_name,
                        ),
                        reply_markup=get_fuzzy_supplier_kb(doc_id, fuzzy_candidates),
                    )
                    return
                else:
                    await message.edit_text(
                        t(
                            "invoice_supplier_none_matched",
                            raw_name=raw_supp_name,
                            inn=supplier_inn or t("invoice_inn_not_specified"),
                        )
                    )
                    await cleanup_session_data(doc_id)
                    return

            if len(candidates) == 1:
                session["supplier_id"] = candidates[0]["id"]
                session["supplier_name"] = candidates[0]["name"]
                await save_invoice_session(doc_id, session["user_id"], session)
            else:
                await message.edit_text(
                    t("invoice_supplier_conflict", inn=supplier_inn),
                    reply_markup=get_supplier_disambiguation_kb(doc_id, candidates),
                )
                return

        await proceed_with_item_alignment(message, doc_id, login, password)

    except Exception as e:
        logger.exception(f"Document parsing error for {temp_path}: {e}")
        await cleanup_session_data(doc_id)
        await message.edit_text(t("invoice_parsing_error", error=str(e)))


@router.callback_query(F.data.startswith("inv:supp:"))
async def process_supplier_disambiguation(callback: types.CallbackQuery):
    """Saves chosen supplier branch globally and advances to item alignment."""
    parts = callback.data.split(":")
    doc_id, supp_id = parts[2], parts[3]

    session = await get_invoice_session(doc_id)
    if not session:
        await callback.message.edit_text(t("invoice_session_expired"))
        return

    operator = await get_bot_user(callback.from_user.id)
    login = operator["iiko_login"]
    password = decrypt_secret(operator["iiko_password_encrypted"])

    suppliers_grouped = await get_cached_suppliers(login, password)
    all_suppliers = [s for supp_list in suppliers_grouped.values() for s in supp_list]
    chosen = next((c for c in all_suppliers if c["id"] == supp_id), None)

    if chosen:
        supplier_inn = (session["parsed_doc"].get("supplier_inn") or "").strip()
        if supplier_inn:
            await save_preferred_supplier(supplier_inn, chosen["id"], chosen["name"])
            logger.info(
                f"Associated supplier preference: INN={supplier_inn} -> '{chosen['name']}' ({chosen['id']})"
            )
        session["supplier_id"] = chosen["id"]
        session["supplier_name"] = chosen["name"]
        await save_invoice_session(doc_id, callback.from_user.id, session)

    await proceed_with_item_alignment(callback.message, doc_id, login, password)


async def proceed_with_item_alignment(
    message: types.Message, doc_id: str, login: str, password: str
):
    """Executes item matching against knowledge base and active stock catalog."""
    session = await get_invoice_session(doc_id)
    if not session:
        return

    catalog = await get_cached_catalog(login, password)
    supplier_id = session["supplier_id"]
    parsed_items = session["parsed_doc"].get("items", [])

    matched_items = []
    unresolved_items = []

    for idx, item in enumerate(parsed_items, 1):
        consensus = await get_consensus_mapping(
            supplier_id, item["raw_name"], item.get("article", "")
        )
        if consensus and not consensus["has_conflict"]:
            coeff = consensus.get("package_coefficient", 1.0) or 1.0
            matched_items.append(
                {
                    "num": idx,
                    "product_id": consensus["product_id"],
                    "iiko_name": consensus["iiko_name"],
                    "raw_name": item["raw_name"],
                    "amount": item["quantity"],
                    "coefficient": coeff,
                    "price": item["price"],
                    "sum": item["sum"],
                    "vat": item["vat_rate"],
                }
            )
        else:
            candidates = find_catalog_candidates(
                raw_name=item["raw_name"],
                article=item.get("article", ""),
                catalog=catalog,
                limit=3,
            )
            unresolved_items.append(
                {"item_idx": idx, "item": item, "candidates": candidates}
            )

    session["matched_items"] = matched_items
    session["unresolved_items"] = unresolved_items
    await save_invoice_session(doc_id, session["user_id"], session)

    if not unresolved_items:
        await message.edit_text(
            t(
                "invoice_all_matched_card",
                doc_number=session["parsed_doc"].get("doc_number") or "Б/Н",
                doc_date=session["parsed_doc"].get("doc_date", ""),
                supplier_name=session["supplier_name"],
                store_name=session["store_name"],
                total_sum=session["total_sum"],
                items_count=len(matched_items),
            ),
            reply_markup=get_upload_confirmation_kb(doc_id),
        )
    else:
        await prompt_next_unresolved_item(message, doc_id)


async def prompt_next_unresolved_item(
    message: types.Message, doc_id: str, is_new: bool = False
):
    """Presents the next unaligned item to the operator."""
    session = await get_invoice_session(doc_id)
    if not session or not session.get("unresolved_items"):
        return

    current = session["unresolved_items"][0]
    item = current["item"]
    total = len(session["parsed_doc"].get("items", []))

    article_val = item.get("article", "")
    article_info = t("invoice_article_info", article=article_val) if article_val else ""
    card_text = t(
        "invoice_unmatched_item_card",
        current=current["item_idx"],
        total=total,
        raw_name=item["raw_name"],
        article_info=article_info,
        sum=item["sum"],
        qty=item["quantity"],
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

    session = await get_invoice_session(doc_id)
    if not session or not session.get("unresolved_items"):
        await callback.message.edit_text(t("invoice_session_expired"))
        return

    target_entry = next(
        (it for it in session["unresolved_items"] if it["item_idx"] == item_idx), None
    )
    if not target_entry:
        await callback.message.edit_text(t("invoice_session_expired"))
        return

    current_item = target_entry["item"]
    await state.set_state(InvoiceState.waiting_manual_sku)

    cancel_kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=t("btn_cancel"), callback_data=f"inv:cancel:{doc_id}"
                )
            ]
        ]
    )
    msg = await callback.message.edit_text(
        t("invoice_enter_sku_prompt", raw_name=current_item["raw_name"]),
        reply_markup=cancel_kb,
    )
    await state.update_data(
        doc_id=doc_id, item_idx=item_idx, prompt_msg_id=msg.message_id
    )


@router.message(InvoiceState.waiting_manual_sku)
async def handle_manual_sku_input(message: types.Message, state: FSMContext):
    """Validates entered SKU against live catalog, cleans prompt, and transitions to packaging multiplier selection."""
    sku = message.text.strip()
    data = await state.get_data()
    doc_id = data.get("doc_id")
    item_idx = data.get("item_idx")
    prompt_id = data.get("prompt_msg_id")

    if prompt_id:
        try:
            await message.bot.delete_message(
                chat_id=message.chat.id, message_id=prompt_id
            )
        except Exception:
            pass

    session = await get_invoice_session(doc_id)
    if not session or not session.get("unresolved_items"):
        await state.clear()
        await message.answer(t("invoice_session_expired"))
        return

    target_entry = next(
        (it for it in session["unresolved_items"] if it["item_idx"] == item_idx), None
    )
    if not target_entry:
        await state.clear()
        await message.answer(t("invoice_session_expired"))
        return

    operator = await get_bot_user(message.from_user.id)
    if (
        not operator
        or not operator.get("iiko_login")
        or not operator.get("iiko_password_encrypted")
    ):
        await message.answer(t("invoice_no_creds_error"))
        return

    login = operator["iiko_login"]
    password = decrypt_secret(operator["iiko_password_encrypted"])

    catalog = await get_cached_catalog(login, password)
    clean_sku = sku.lower()
    prod = next(
        (
            p
            for p in catalog
            if p.get("article", "").strip().lower() == clean_sku
            or p.get("id", "").strip().lower() == clean_sku
        ),
        None,
    )

    if not prod:
        await message.answer(t("invoice_sku_not_found", sku=sku))
        return

    await state.clear()
    current_item = target_entry["item"]

    await message.answer(
        t(
            "invoice_packaging_prompt",
            prod_name=prod["name"],
            sku=prod.get("article", sku),
            qty=current_item["quantity"],
        ),
        reply_markup=get_packaging_coeff_kb(doc_id, item_idx, prod["id"]),
    )


@router.callback_query(F.data.startswith("inv:match:"))
async def process_manual_match(callback: types.CallbackQuery):
    """Transitions selected candidate to packaging multiplier selection."""
    parts = callback.data.split(":")
    doc_id, item_idx, prod_id = parts[2], int(parts[3]), parts[4]

    session = await get_invoice_session(doc_id)
    if not session or not session.get("unresolved_items"):
        await callback.message.edit_text(t("invoice_session_expired"))
        return

    target_entry = next(
        (it for it in session["unresolved_items"] if it["item_idx"] == item_idx), None
    )
    if not target_entry:
        await callback.message.edit_text(t("invoice_session_expired"))
        return

    operator = await get_bot_user(callback.from_user.id)
    login = operator["iiko_login"]
    password = decrypt_secret(operator["iiko_password_encrypted"])

    catalog = await get_cached_catalog(login, password)
    prod = next((p for p in catalog if p["id"] == prod_id), None)
    if not prod:
        await callback.answer(t("invoice_sku_not_found", sku=prod_id), show_alert=True)
        return

    current_item = target_entry["item"]

    await callback.message.edit_text(
        t(
            "invoice_packaging_prompt",
            prod_name=prod["name"],
            sku=prod.get("article", "Б/А"),
            qty=current_item["quantity"],
        ),
        reply_markup=get_packaging_coeff_kb(doc_id, item_idx, prod["id"]),
    )


@router.callback_query(F.data.startswith("inv:coeff:"))
async def process_coeff_selection(callback: types.CallbackQuery, state: FSMContext):
    """Handles packaging multiplier choice or prompts for custom number."""
    parts = callback.data.split(":")
    doc_id, item_idx, prod_id, coeff_val = parts[2], int(parts[3]), parts[4], parts[5]

    if coeff_val == "custom":
        await state.set_state(InvoiceState.waiting_custom_coeff)

        cancel_kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text=t("btn_cancel"), callback_data=f"inv:cancel:{doc_id}"
                    )
                ]
            ]
        )
        msg = await callback.message.edit_text(
            t("invoice_custom_coeff_prompt"), reply_markup=cancel_kb
        )
        await state.update_data(
            doc_id=doc_id,
            item_idx=item_idx,
            prod_id=prod_id,
            prompt_msg_id=msg.message_id,
        )
        return

    coeff = float(coeff_val)
    if coeff <= 0:
        raise ValueError(f"Packaging multiplier must be positive, got: {coeff_val}")

    await apply_confirmed_item_match(
        callback, doc_id, item_idx, prod_id, coeff, is_new=False
    )


@router.message(InvoiceState.waiting_custom_coeff)
async def handle_custom_coeff_input(message: types.Message, state: FSMContext):
    """Validates custom numeric multiplier, cleans prompt, and applies item alignment at bottom."""
    raw_val = message.text.strip().replace(",", ".")
    try:
        coeff = float(raw_val)
        if coeff <= 0:
            raise ValueError
    except ValueError:
        await message.answer(t("invoice_custom_coeff_invalid"))
        return

    # ==========================================================================
    # ARCHITECTURAL INVARIANT: SPECIFIC EXCEPTION CATCHING ON UI MUTATIONS
    #
    # RULE: When purging ephemeral prompt messages, strictly catch `TelegramBadRequest`
    # (for messages already purged by user). Log any unexpected exceptions.
    #
    # FORBIDDEN:
    # - Bare `except Exception: pass` which swallows network and permission faults.
    # ==========================================================================
    data = await state.get_data()
    prompt_id = data.get("prompt_msg_id")
    if prompt_id:
        try:
            await message.bot.delete_message(
                chat_id=message.chat.id, message_id=prompt_id
            )
        except TelegramBadRequest:
            pass
        except Exception as err:
            logger.warning(f"Failed to delete prompt message {prompt_id}: {err}")

    await state.clear()

    await state.clear()
    await apply_confirmed_item_match(
        message, data["doc_id"], data["item_idx"], data["prod_id"], coeff, is_new=True
    )


async def apply_confirmed_item_match(
    target_event: types.Message | types.CallbackQuery,
    doc_id: str,
    item_idx: int,
    prod_id: str,
    coeff: float,
    is_new: bool = False,
):
    """Applies verified alignment, saves persistent consensus vote, and advances workflow."""
    target_msg = (
        target_event
        if isinstance(target_event, types.Message)
        else target_event.message
    )

    doc_lock = get_doc_lock(doc_id)
    async with doc_lock:
        session = await get_invoice_session(doc_id)
        if not session or not session.get("unresolved_items"):
            if is_new:
                await target_msg.answer(t("invoice_session_expired"))
            else:
                await target_msg.edit_text(t("invoice_session_expired"))
            return

        target_idx_entry = next(
            (
                idx
                for idx, it in enumerate(session["unresolved_items"])
                if it["item_idx"] == item_idx
            ),
            None,
        )
        if target_idx_entry is None:
            if is_new:
                await target_msg.answer(t("invoice_session_expired"))
            else:
                await target_msg.edit_text(t("invoice_session_expired"))
            return

        operator = await get_bot_user(session["user_id"])
        login = operator["iiko_login"]
        password = decrypt_secret(operator["iiko_password_encrypted"])

        catalog = await get_cached_catalog(login, password)
        prod = next((p for p in catalog if p["id"] == prod_id), None)
        if not prod:
            return

        resolved_entry = session["unresolved_items"].pop(target_idx_entry)
        item = resolved_entry["item"]

        # Track vote with operator authorship and separate iiko SKU from vendor SKU
        await record_mapping_vote(
            supplier_id=session["supplier_id"],
            raw_name=item["raw_name"],
            product_id=prod["id"],
            iiko_name=prod["name"],
            article=prod.get("article", ""),
            vendor_article=item.get("article", ""),
            weight=3,
            package_coefficient=coeff,
            user_id=session["user_id"],
            source="invoice",
        )
        session["matched_items"].append(
            {
                "num": item_idx,
                "product_id": prod["id"],
                "iiko_name": prod["name"],
                "raw_name": item["raw_name"],
                "amount": item["quantity"],
                "coefficient": coeff,
                "price": item["price"],
                "sum": item["sum"],
                "vat": item["vat_rate"],
            }
        )
        await save_invoice_session(doc_id, session["user_id"], session)
        logger.info(
            f"Item alignment confirmed: '{item['raw_name']}' -> '{prod['name']}' (coeff={coeff})"
        )

        pack_info = (
            t("invoice_pack_coeff_fmt", coeff=f"{coeff:g}") if coeff != 1.0 else ""
        )
        success_text = t(
            "invoice_sku_matched_success",
            prod_name=prod["name"],
            sku=prod.get("article", ""),
            pack_info=pack_info,
        )

        if is_new:
            await target_msg.answer(success_text)
        else:
            await target_msg.edit_text(success_text)

        if session["unresolved_items"]:
            await prompt_next_unresolved_item(target_msg, doc_id, is_new=True)
        else:
            await target_msg.answer(
                t(
                    "invoice_all_matched_card",
                    doc_number=session["parsed_doc"].get("doc_number") or "Б/Н",
                    doc_date=session["parsed_doc"].get("doc_date", ""),
                    supplier_name=session["supplier_name"],
                    store_name=session["store_name"],
                    total_sum=session["total_sum"],
                    items_count=len(session["matched_items"]),
                ),
                reply_markup=get_upload_confirmation_kb(doc_id),
            )


@router.callback_query(F.data.startswith("inv:skip:"))
async def process_skip_item(callback: types.CallbackQuery):
    """Skips unmatched item without creating an alignment record."""
    parts = callback.data.split(":")
    doc_id = parts[2]
    item_idx = int(parts[3]) if len(parts) > 3 else None

    doc_lock = get_doc_lock(doc_id)
    async with doc_lock:
        session = await get_invoice_session(doc_id)
        if not session or not session.get("unresolved_items"):
            await callback.message.edit_text(t("invoice_session_expired"))
            return

        if item_idx is not None:
            session["unresolved_items"] = [
                it for it in session["unresolved_items"] if it["item_idx"] != item_idx
            ]
        else:
            session["unresolved_items"].pop(0)

        await save_invoice_session(doc_id, session["user_id"], session)

        if session["unresolved_items"]:
            await prompt_next_unresolved_item(callback.message, doc_id)
        else:
            await callback.message.edit_text(
                t(
                    "invoice_all_matched_card",
                    doc_number=session["parsed_doc"].get("doc_number") or "Б/Н",
                    doc_date=session["parsed_doc"].get("doc_date", ""),
                    supplier_name=session["supplier_name"],
                    store_name=session["store_name"],
                    total_sum=session["total_sum"],
                    items_count=len(session["matched_items"]),
                ),
                reply_markup=get_upload_confirmation_kb(doc_id),
            )


@router.callback_query(F.data.startswith("inv:review:"))
async def process_review_items_click(callback: types.CallbackQuery):
    """Presents line-by-line inspection view before final submission to iiko."""
    parts = callback.data.split(":")
    doc_id = parts[2]
    page = int(parts[3]) if len(parts) > 3 else 1

    session = await get_invoice_session(doc_id)
    if not session or not session.get("matched_items"):
        await callback.message.edit_text(t("invoice_session_expired"))
        return

    doc_num = session["parsed_doc"].get("doc_number") or "Б/Н"
    await callback.message.edit_text(
        t("invoice_review_title", doc_number=doc_num),
        reply_markup=get_items_review_kb(
            doc_id,
            session["matched_items"],
            page=page,
            page_size=PAGE_SIZE_REVIEW_ITEMS,
        ),
        parse_mode="HTML",
    )


@router.callback_query(F.data.startswith("inv:review_page:"))
async def process_review_page_change(callback: types.CallbackQuery):
    """Switches page in item review keyboard."""
    parts = callback.data.split(":")
    doc_id, page = parts[2], int(parts[3])

    session = await get_invoice_session(doc_id)
    if not session or not session.get("matched_items"):
        await callback.message.edit_text(t("invoice_session_expired"))
        return

    await callback.message.edit_reply_markup(
        reply_markup=get_items_review_kb(
            doc_id,
            session["matched_items"],
            page=page,
            page_size=PAGE_SIZE_REVIEW_ITEMS,
        )
    )


@router.callback_query(F.data.startswith("inv:review_done:"))
async def process_review_done_click(callback: types.CallbackQuery):
    """Returns operator from review list to final confirmation card."""
    doc_id = callback.data.split(":")[2]
    session = await get_invoice_session(doc_id)
    if not session:
        await callback.message.edit_text(t("invoice_session_expired"))
        return

    await callback.message.edit_text(
        t(
            "invoice_all_matched_card",
            doc_number=session["parsed_doc"].get("doc_number") or "Б/Н",
            doc_date=session["parsed_doc"].get("doc_date", ""),
            supplier_name=session["supplier_name"],
            store_name=session["store_name"],
            total_sum=session["total_sum"],
            items_count=len(session["matched_items"]),
        ),
        reply_markup=get_upload_confirmation_kb(doc_id),
    )


@router.callback_query(F.data.startswith("inv:edit:"))
async def process_edit_matched_item(callback: types.CallbackQuery):
    """Removes chosen item from matched list and restarts alignment for revision."""
    parts = callback.data.split(":")
    doc_id, item_num = parts[2], int(parts[3])

    doc_lock = get_doc_lock(doc_id)
    async with doc_lock:
        session = await get_invoice_session(doc_id)
        if not session or not session.get("matched_items"):
            await callback.message.edit_text(t("invoice_session_expired"))
            return

        target_idx = next(
            (
                idx
                for idx, it in enumerate(session["matched_items"])
                if it["num"] == item_num
            ),
            None,
        )
        if target_idx is None:
            await callback.answer(t("invoice_session_expired"), show_alert=True)
            return

        reverted_matched = session["matched_items"].pop(target_idx)
        raw_items = session["parsed_doc"].get("items", [])
        original_raw_item = next(
            (it for it in raw_items if it["line_num"] == item_num), None
        )

        if not original_raw_item:
            raise KeyError(
                f"Original raw item for line #{item_num} not found in parsed document."
            )

        operator = await get_bot_user(session["user_id"])
        login = operator["iiko_login"]
        password = decrypt_secret(operator["iiko_password_encrypted"])

        catalog = await get_cached_catalog(login, password)
        candidates = find_catalog_candidates(
            raw_name=original_raw_item["raw_name"],
            article=original_raw_item.get("article", ""),
            catalog=catalog,
            limit=3,
        )

        session["unresolved_items"].insert(
            0,
            {"item_idx": item_num, "item": original_raw_item, "candidates": candidates},
        )
        await save_invoice_session(doc_id, session["user_id"], session)

    await prompt_next_unresolved_item(callback.message, doc_id, is_new=False)


@router.callback_query(F.data.startswith("inv:upload:"))
async def process_draft_upload(callback: types.CallbackQuery):
    """Builds escaped XML and uploads draft invoice using operator's personal iiko credentials."""
    doc_id = callback.data.split(":")[2]
    session = await get_invoice_session(doc_id)
    if not session:
        await callback.message.edit_text(t("invoice_session_expired"))
        return

    # Verify operator has configured iiko credentials
    operator = await get_bot_user(callback.from_user.id)
    if (
        not operator
        or not operator.get("iiko_login")
        or not operator.get("iiko_password_encrypted")
    ):
        await callback.message.edit_text(
            t("invoice_no_creds_error"),
            reply_markup=get_setup_creds_kb(doc_id),
            parse_mode="HTML",
        )
        return

    login = operator["iiko_login"]
    try:
        password = decrypt_secret(operator["iiko_password_encrypted"])
    except Exception as e:
        logger.error(f"Decryption failure for user {callback.from_user.id}: {e}")
        await callback.message.edit_text(
            t(
                "cab_creds_failed",
                error="Сбой расшифровки пароля. Настройте пароль заново.",
            ),
            reply_markup=get_setup_creds_kb(doc_id),
            parse_mode="HTML",
        )
        return

    try:
        raw_doc = RawInvoiceDocument(
            doc_number=session["parsed_doc"].get("doc_number", ""),
            doc_date=session["parsed_doc"].get("doc_date", ""),
            supplier_inn=session["parsed_doc"].get("supplier_inn", ""),
            supplier_name=session["parsed_doc"].get("supplier_name", ""),
            consignee_address=session["parsed_doc"].get("consignee_address", ""),
            items=[],
        )

        xml_payload = build_iiko_xml(
            doc=raw_doc,
            store_id=session["store_id"],
            supplier_id=session["supplier_id"],
            matched_items=session["matched_items"],
        )

        # Upload strictly under authenticated operator identity
        resp = await asyncio.to_thread(
            client.upload_invoice_as_user,
            session["store_id"],
            xml_payload,
            login,
            password,
        )

        if resp.status_code == 200 and "valid>true" in resp.text:
            root = ET.fromstring(resp.content)
            raw_doc_num = root.findtext("documentNumber")
            if not raw_doc_num or not raw_doc_num.strip():
                raise IikoApiError(
                    f"iiko draft creation succeeded but returned empty documentNumber: {resp.text[:300]}"
                )
            iiko_doc_num = raw_doc_num.strip()
            logger.info(
                f"Draft invoice created in iiko by {login}: #{iiko_doc_num} (incoming: #{raw_doc.doc_number}) for store '{session['store_name']}'"
            )
            await cleanup_session_data(doc_id)
            await callback.message.edit_text(
                t(
                    "invoice_draft_success",
                    store_name=session["store_name"],
                    iiko_doc_num=iiko_doc_num,
                    inc_doc_num=raw_doc.doc_number or "Б/Н",
                )
            )
        else:
            logger.error(
                f"iiko upload rejected for user {login}: {resp.status_code} - {resp.text[:300]}"
            )
            await callback.message.edit_text(
                t("invoice_upload_failed", error=resp.text[:300]),
                reply_markup=get_upload_retry_kb(doc_id),
            )

    except Exception as e:
        logger.exception(f"Unexpected error while uploading invoice to iiko: {e}")
        await callback.message.edit_text(
            t("invoice_upload_failed", error=str(e)),
            reply_markup=get_upload_retry_kb(doc_id),
        )


@router.callback_query(F.data.startswith("inv:cancel:"))
async def process_invoice_cancel(callback: types.CallbackQuery):
    """Cancels invoice processing and deletes local temporary artifacts."""
    doc_id = callback.data.split(":")[2]
    await cleanup_session_data(doc_id)
    await callback.message.edit_text(t("invoice_cancelled"))
