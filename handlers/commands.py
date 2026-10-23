from aiogram import Router, types
from aiogram.filters import CommandStart, Command
from storage import validate_and_consume_invite, get_bot_user

router = Router(name="commands_router")


@router.message(CommandStart())
async def handle_start(message: types.Message):
    """Handles /start command with optional invite token deep-link."""
    args = message.text.split(maxsplit=1)
    user = message.from_user

    # Handle deep-linking invite token: /start inv_<token>
    if len(args) > 1 and args[1].startswith("inv_"):
        token = args[1].replace("inv_", "").strip()
        success = validate_and_consume_invite(
            token=token,
            telegram_id=user.id,
            username=user.username,
            full_name=user.full_name,
        )
        if success:
            await message.answer(
                f"🎉 <b>Добро пожаловать, {user.first_name}!</b>\n\n"
                "Приглашение успешно активировано.\n"
                "Теперь вы можете отправлять сюда накладные поставщиков:\n"
                "• <b>XML-файлы</b> из Диадока (УПД / счета-фактуры)\n"
                "• <b>PDF-документы</b> (сканы, накладные, спецификации)\n\n"
                "Бот автоматически распознает номенклатуру и сформирует черновик в iiko.",
                parse_mode="HTML",
            )
            return
        else:
            await message.answer(
                "❌ <b>Ссылка-приглашение недействительна или уже была использована.</b>",
                parse_mode="HTML",
            )
            return

    db_user = get_bot_user(user.id)
    if db_user and db_user["is_active"]:
        await message.answer(
            f"👋 <b>С возвращением, {user.first_name}!</b>\n\n"
            "Отправьте мне файл накладной (<b>.xml</b> или <b>.pdf</b>), чтобы начать обработку.",
            parse_mode="HTML",
        )
    else:
        await message.answer(
            "⛔ <b>Доступ ограничен.</b> Для работы с ботом требуется персональное приглашение.",
            parse_mode="HTML",
        )


@router.message(Command("help"))
async def handle_help(message: types.Message):
    """Displays user assistance manual."""
    help_text = (
        "📖 <b>Инструкция по работе с KONO Supply Bot:</b>\n\n"
        "1. Отправьте боту документ (файл накладной <b>.xml</b> или <b>.pdf</b>).\n"
        "2. Бот мгновенно разберет файл и предложит выбрать склад доставки (<b>Аэропорт</b> или <b>Октябрьская</b>).\n"
        "3. Если все позиции известны, бот предложит создать черновик в iiko.\n"
        "4. Если в накладной появились новые товары, бот предложит сопоставить их кнопками.\n\n"
        "<i>Накладные всегда создаются в iiko со статусом черновика (NOT_PROCESSED).</i>"
    )
    await message.answer(help_text, parse_mode="HTML")
