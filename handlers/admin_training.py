import os
import uuid
import json
import shutil
import asyncio
from typing import Dict, Any
from aiogram import Router, types, F
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from loguru import logger

from lexicon import t
from config import get_admin_ids
from services.crypto import decrypt_secret
from services.training_service import (
    MAX_BATCH_FILES,
    safe_extract_zip,
    simulate_batch_training,
    apply_batch_training,
)
from storage import is_admin_user, get_bot_user
from keyboards.admin_kb import (
    get_training_accumulator_kb,
    get_training_confirmation_kb,
    get_admin_main_kb,
)

router = Router(name="admin_training_router")

SCRATCH_BASE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "data",
    "in",
    "training_scratch",
)
os.makedirs(SCRATCH_BASE, exist_ok=True)

# Staged batch telemetry and debounce workers
_TRAINING_CACHE: Dict[str, Dict[str, Any]] = {}
_DEBOUNCE_TASKS: Dict[str, asyncio.Task] = {}
_PROCESSED_ZIPS: Dict[str, set] = {}


class AdminTrainingState(StatesGroup):
    accumulating_files = State()


def _cleanup_scratch(batch_id: str):
    """Guaranteed physical cleanup of batch staging scratchpad and tasks."""
    task = _DEBOUNCE_TASKS.pop(batch_id, None)
    if task and not task.done():
        task.cancel()
    _PROCESSED_ZIPS.pop(batch_id, None)

    target_dir = os.path.join(SCRATCH_BASE, batch_id)
    if os.path.exists(target_dir):
        try:
            shutil.rmtree(target_dir, ignore_errors=True)
        except OSError as e:
            logger.warning(f"Could not purge scratch directory {target_dir}: {e}")
    _TRAINING_CACHE.pop(batch_id, None)


async def _debounced_accumulator_update(
    batch_id: str,
    chat_id: int,
    scratch_dir: str,
    bot,
    state: FSMContext,
):
    """Waits for upload burst to settle, purges outdated prompt, and sends summary card at bottom."""
    try:
        await asyncio.sleep(1.5)

        # Physical filesystem inspection as Single Source of Truth
        xml_count = 0
        pdf_count = 0
        for root, _, files in os.walk(scratch_dir):
            for f in files:
                low = f.lower()
                if low.endswith(".xml"):
                    xml_count += 1
                elif low.endswith(".pdf"):
                    pdf_count += 1
        total_files = xml_count + pdf_count
        zip_count = len(_PROCESSED_ZIPS.get(batch_id, set()))

        data = await state.get_data()
        old_msg_id = data.get("status_msg_id")
        if old_msg_id:
            try:
                await bot.delete_message(chat_id=chat_id, message_id=old_msg_id)
            except TelegramBadRequest:
                pass
            except Exception as err:
                logger.warning(
                    f"Failed to delete outdated status message {old_msg_id}: {err}"
                )

        card_text = t(
            "admin_train_accumulator_title",
            batch_id=batch_id,
            zip_count=zip_count,
            xml_count=xml_count,
            pdf_count=pdf_count,
            total_files=total_files,
            max_files=MAX_BATCH_FILES,
        )
        new_msg = await bot.send_message(
            chat_id=chat_id,
            text=card_text,
            reply_markup=get_training_accumulator_kb(batch_id, total_files=total_files),
            parse_mode="HTML",
        )
        await state.update_data(
            status_msg_id=new_msg.message_id, total_files=total_files
        )
    except asyncio.CancelledError:
        pass
    except Exception as e:
        logger.error(f"Error in debounced accumulator update: {e}")


@router.callback_query(F.data == "admin:training_menu")
async def process_start_training_session(
    callback: types.CallbackQuery, state: FSMContext
):
    """Validates admin iiko credentials upfront and activates training batch accumulator session."""
    if not await is_admin_user(callback.from_user.id):
        await callback.answer(t("admin_access_denied"), show_alert=True)
        return

    admin = await get_bot_user(callback.from_user.id)
    if (
        not admin
        or not admin.get("iiko_login")
        or not admin.get("iiko_password_encrypted")
    ):
        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text=t("btn_setup_iiko_creds"), callback_data="cab:set_creds"
                    )
                ],
                [
                    InlineKeyboardButton(
                        text=t("admin_btn_back"), callback_data="admin:open"
                    ),
                    InlineKeyboardButton(
                        text=t("menu_btn_back"), callback_data="menu:back_main"
                    ),
                ],
            ]
        )
        await callback.message.edit_text(
            t("invoice_no_creds_error"), reply_markup=kb, parse_mode="HTML"
        )
        return

    batch_id = str(uuid.uuid4())[:10]
    batch_dir = os.path.join(SCRATCH_BASE, batch_id)
    os.makedirs(batch_dir, exist_ok=True)
    _PROCESSED_ZIPS[batch_id] = set()

    await state.set_state(AdminTrainingState.accumulating_files)
    await state.update_data(
        batch_id=batch_id,
        scratch_dir=batch_dir,
        status_msg_id=callback.message.message_id,
        chat_id=callback.message.chat.id,
    )

    await callback.message.edit_text(
        t(
            "admin_train_accumulator_title",
            batch_id=batch_id,
            zip_count=0,
            xml_count=0,
            pdf_count=0,
            total_files=0,
            max_files=MAX_BATCH_FILES,
        ),
        reply_markup=get_training_accumulator_kb(batch_id, total_files=0),
        parse_mode="HTML",
    )


@router.message(AdminTrainingState.accumulating_files, F.document)
async def process_accumulate_document(message: types.Message, state: FSMContext):
    """Silently stages and unpacks batch documents without chat spam or UI locking."""
    if not await is_admin_user(message.from_user.id):
        return

    data = await state.get_data()
    batch_id = data.get("batch_id")
    scratch_dir = data.get("scratch_dir")
    if not batch_id or not scratch_dir:
        return

    doc = message.document
    if not doc.file_name or not doc.file_name.strip():
        raise ValueError("Uploaded training document is missing a valid filename.")
    filename = doc.file_name.strip().lower()
    ext = os.path.splitext(filename)[1]

    if ext not in (".zip", ".xml", ".pdf"):
        return

    temp_file = os.path.join(scratch_dir, f"raw_{doc.file_id[:8]}_{filename}")
    await message.bot.download(doc.file_id, destination=temp_file)

    if ext == ".zip":
        try:
            safe_extract_zip(temp_file, scratch_dir)
            _PROCESSED_ZIPS.setdefault(batch_id, set()).add(filename)
        except Exception as e:
            logger.error(f"Error extracting zip {filename}: {e}")
        finally:
            if os.path.exists(temp_file):
                try:
                    os.remove(temp_file)
                except OSError as e:
                    logger.warning(f"Failed to remove temp file '{temp_file}': {e}")

    # Debounce interface update to settle multiple concurrent document uploads
    existing_task = _DEBOUNCE_TASKS.get(batch_id)
    if existing_task and not existing_task.done():
        existing_task.cancel()

    _DEBOUNCE_TASKS[batch_id] = asyncio.create_task(
        _debounced_accumulator_update(
            batch_id=batch_id,
            chat_id=message.chat.id,
            scratch_dir=scratch_dir,
            bot=message.bot,
            state=state,
        )
    )


@router.callback_query(F.data.startswith("admin:train_run:"))
async def process_execute_training_simulation(
    callback: types.CallbackQuery, state: FSMContext
):
    """Executes dry-run matching simulation against iikoChain under admin credentials."""
    if not await is_admin_user(callback.from_user.id):
        await callback.answer(t("admin_access_denied"), show_alert=True)
        return

    admin = await get_bot_user(callback.from_user.id)
    if (
        not admin
        or not admin.get("iiko_login")
        or not admin.get("iiko_password_encrypted")
    ):
        await callback.answer(
            t("admin_train_no_creds_alert"),
            show_alert=True,
        )
        return

    admin_login = admin["iiko_login"]
    admin_password = decrypt_secret(admin["iiko_password_encrypted"])

    batch_id = callback.data.split(":")[2]
    data = await state.get_data()
    scratch_dir = data.get("scratch_dir") or os.path.join(SCRATCH_BASE, batch_id)

    await state.clear()

    await callback.message.edit_text(
        t("admin_train_running_wait", date_from="...", date_to="..."),
        parse_mode="HTML",
    )

    try:
        # Execute pure asynchronous simulation natively
        report = await simulate_batch_training(scratch_dir, admin_login, admin_password)
        _TRAINING_CACHE[batch_id] = {
            "report": report,
            "scratch_dir": scratch_dir,
            "admin_id": callback.from_user.id,
        }

        conflict_details = ""
        if report["conflicts_count"] > 0:
            conflict_details = t("admin_train_conflict_header")
            for ex in report["conflict_examples"]:
                conflict_details += t(
                    "admin_train_conflict_item",
                    raw_name=ex["raw_name"][:25],
                    current_name=ex["current_name"][:25],
                    current_votes=ex["current_votes"],
                    new_name=ex["new_name"][:25],
                    new_votes=ex["new_votes"],
                )

        matched_count = report["matched_strict"] + report["matched_unique_sums"]
        await callback.message.edit_text(
            t(
                "admin_train_report_card",
                total_files=report["total_files"],
                matched_count=matched_count,
                strict_count=report["matched_strict"],
                unique_sums_count=report["matched_unique_sums"],
                unmatched_count=report["unmatched_invoices"],
                new_count=report["new_items_count"],
                confirmed_count=report["confirmed_count"],
                coeff_count=report["coeff_updates_count"],
                conflicts_count=report["conflicts_count"],
                conflict_details=conflict_details,
            ),
            reply_markup=get_training_confirmation_kb(
                batch_id, report["new_items_count"]
            ),
            parse_mode="HTML",
        )

    except Exception as e:
        logger.exception(f"Batch training simulation failed for {batch_id}: {e}")
        _cleanup_scratch(batch_id)

        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text=t("admin_btn_back"), callback_data="admin:open"
                    ),
                    InlineKeyboardButton(
                        text=t("menu_btn_back"), callback_data="menu:back_main"
                    ),
                ]
            ]
        )
        await callback.message.edit_text(
            t("admin_train_simulation_error", error=str(e)),
            reply_markup=kb,
            parse_mode="HTML",
        )


@router.callback_query(F.data.startswith("admin:train_commit:"))
async def process_commit_training_results(callback: types.CallbackQuery):
    """Atomically commits candidate mappings into PostgreSQL knowledge base."""
    if not await is_admin_user(callback.from_user.id):
        await callback.answer(t("admin_access_denied"), show_alert=True)
        return

    batch_id = callback.data.split(":")[2]
    cached = _TRAINING_CACHE.get(batch_id)

    if not cached or "report" not in cached:
        await callback.message.edit_text(t("invoice_session_expired"))
        _cleanup_scratch(batch_id)
        return

    candidates = cached["report"].get("candidates_list", [])

    try:
        committed = await apply_batch_training(
            candidates, admin_id=callback.from_user.id
        )
        _cleanup_scratch(batch_id)

        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text=t("admin_btn_back"), callback_data="admin:open"
                    )
                ]
            ]
        )
        await callback.message.edit_text(
            t("admin_train_success", committed_count=committed),
            reply_markup=kb,
            parse_mode="HTML",
        )
    except Exception as e:
        logger.exception(f"Failed to commit training batch {batch_id}: {e}")
        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text=t("admin_btn_back"), callback_data="admin:open"
                    ),
                    InlineKeyboardButton(
                        text=t("menu_btn_back"), callback_data="menu:back_main"
                    ),
                ]
            ]
        )
        await callback.message.edit_text(
            t("admin_train_commit_error", error=str(e)),
            reply_markup=kb,
            parse_mode="HTML",
        )
        _cleanup_scratch(batch_id)


@router.callback_query(F.data.startswith("admin:train_report:"))
async def process_download_training_report(callback: types.CallbackQuery):
    """Sends detailed telemetry simulation report as downloadable JSON file."""
    if not await is_admin_user(callback.from_user.id):
        return

    batch_id = callback.data.split(":")[2]
    cached = _TRAINING_CACHE.get(batch_id)

    if not cached or "report" not in cached:
        await callback.answer(t("invoice_session_expired"), show_alert=True)
        return

    report_bytes = json.dumps(cached["report"], ensure_ascii=False, indent=2).encode(
        "utf-8"
    )
    doc_file = types.BufferedInputFile(
        report_bytes, filename=f"training_report_{batch_id}.json"
    )

    await callback.message.answer_document(
        document=doc_file,
        caption=t("admin_train_report_caption", batch_id=batch_id),
    )


@router.callback_query(F.data.startswith("admin:train_cancel:"))
async def process_cancel_training(callback: types.CallbackQuery, state: FSMContext):
    """Aborts training batch session and wipes all temporary files without touching database."""
    if not await is_admin_user(callback.from_user.id):
        return

    batch_id = callback.data.split(":")[2]
    await state.clear()
    _cleanup_scratch(batch_id)

    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=t("admin_btn_back"), callback_data="admin:open"
                ),
                InlineKeyboardButton(
                    text=t("menu_btn_back"), callback_data="menu:back_main"
                ),
            ]
        ]
    )
    await callback.message.edit_text(
        t("admin_train_cancelled"), reply_markup=kb, parse_mode="HTML"
    )
