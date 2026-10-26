from typing import Dict
from aiogram import Bot
from aiogram.types import BotCommand


LEXICON: Dict[str, str] = {
    # System and Auth
    "auth_access_denied_msg": (
        "⛔ <b>Доступ ограничен.</b>\n\n"
        "Этот бот работает только по персональным приглашениям.\n"
        "Запросите ссылку-приглашение у администратора сети."
    ),
    "auth_access_denied_alert": "⛔ Доступ ограничен. Вы не авторизованы.",
    "throttling_warning": "⚠️ Пожалуйста, не нажимайте кнопки так часто. Подождите секунду.",

    # Start & Help
    "start_welcome_invite": (
        "🎉 <b>Добро пожаловать, {name}!</b>\n\n"
        "Приглашение успешно активировано.\n"
        "Теперь вы можете отправлять сюда накладные поставщиков:\n"
        "• <b>XML-файлы</b> из Диадока (УПД / счета-фактуры)\n"
        "• <b>PDF-документы</b> (сканы, накладные, спецификации)\n\n"
        "Бот автоматически распознает номенклатуру и предложит ресторан для оприходования."
    ),
    "start_invite_invalid": "❌ <b>Ссылка-приглашение недействительна или уже была использована.</b>",
    "start_registered": (
        "👋 <b>С возвращением, {name}!</b>\n\n"
        "Отправьте мне файл накладной (<b>.xml</b> или <b>.pdf</b>), чтобы начать обработку."
    ),
    "start_unauthorized": "⛔ <b>Доступ ограничен.</b> Для работы с ботом требуется персональное приглашение.",
    "help_text": (
        "📖 <b>Инструкция по работе с KONO Supply Bot:</b>\n\n"
        "1. Отправьте боту документ (файл накладной <b>.xml</b> или <b>.pdf</b>).\n"
        "2. Бот мгновенно разберет файл и предложит выбрать ресторан доставки (<b>Аэропорт</b> или <b>Октябрьская</b>).\n"
        "3. Если все позиции известны, бот выведет сводку и кнопку создания черновика.\n"
        "4. Если в накладной появились новые товары, бот предложит сопоставить их кнопками из каталога iiko.\n\n"
        "<i>Все накладные всегда создаются в iiko со статусом черновика (NOT_PROCESSED).</i>"
    ),

    # Admin Panel
    "admin_panel_title": (
        "🛠 <b>Панель управления доступом KONO Supply:</b>\n\n"
        "Здесь вы можете генерировать приглашения для сотрудников и просматривать список пользователей."
    ),
    "admin_btn_invite": "🎟 Создать ссылку-приглашение",
    "admin_btn_users": "👥 Список пользователей",
    "admin_invite_created": (
        "🎟 <b>Создана новая ссылка-приглашение:</b>\n\n"
        "<code>{invite_url}</code>\n\n"
        "<i>Ссылка одноразовая. Отправьте её сотруднику для авторизации в боте.</i>"
    ),
    "admin_users_title": "👥 <b>Авторизованные пользователи:</b>\n",
    "admin_users_empty": "Список пользователей пуст.",
    "admin_access_denied": "Отказано в доступе.",

    # Invoice Processing UI
    "invoice_parsing_wait": "⏳ <b>Распознаю документ:</b> <code>{filename}</code>...\n<i>Пожалуйста, подождите.</i>",
    "invoice_parsing_error": "❌ <b>Ошибка при разборе документа:</b>\n<code>{error}</code>",
    "invoice_invalid_format": "⚠️ <b>Неподдерживаемый формат файла.</b>\nПринимаются только файлы <b>.xml</b> (Диадок) и <b>.pdf</b>.",
    "pdf_verification_card": (
        "🔍 <b>Результат распознавания PDF (Gemini Vision):</b>\n\n"
        "📄 Документ: № <code>{doc_number}</code> от {doc_date}\n"
        "🏢 Поставщик: <b>{supplier_name}</b> (ИНН: <code>{supplier_inn}</code>)\n"
        "💰 Итоговая сумма: <b>{total_sum:,.2f} ₽</b> ({items_count} поз.)\n\n"
        "📋 <b>Извлеченные строки:</b>\n"
        "{items_preview}\n\n"
        "<i>Всё распознано правильно?</i>"
    ),
    "invoice_card": (
        "📄 <b>Накладная:</b> № <code>{doc_number}</code> от {doc_date}\n"
        "🏢 <b>Поставщик:</b> {supplier_name} (ИНН: <code>{supplier_inn}</code>)\n"
        "💰 <b>Сумма документа:</b> {total_sum:,.2f} ₽\n"
        "📦 <b>Позиций:</b> {items_count} шт.\n\n"
        "📍 <b>Выберите ресторан для оприходования:</b>"
    ),
    "invoice_supplier_conflict": (
        "🏢 <b>Найдено несколько подразделений поставщика (ИНН: {inn}):</b>\n"
        "Выберите нужное юридическое лицо:"
    ),
    "invoice_supplier_not_found_fuzzy": (
        "🔍 <b>Поставщик с ИНН <code>{inn}</code> не найден в iiko.</b>\n"
        "Распознанное имя: <b>«{raw_name}»</b>\n\n"
        "<i>Возможна опечатка в базе iiko или нечеткий скан.</i>\n"
        "Выберите подходящего контрагента из вашей базы iiko:"
    ),
    "invoice_supplier_none_matched": (
        "❌ <b>Поставщик «{raw_name}» (ИНН: {inn}) не найден в iiko.</b>\n"
        "Убедитесь, что контрагент заведен в iikoOffice."
    ),
    "invoice_all_matched_card": (
        "✅ <b>Все позиции успешно сопоставлены!</b>\n\n"
        "📄 Документ: № <code>{doc_number}</code> от {doc_date}\n"
        "🏢 Поставщик: {supplier_name}\n"
        "📍 Ресторан: <b>{store_name}</b>\n"
        "💰 Итоговая сумма: <b>{total_sum:,.2f} ₽</b> ({items_count} поз.)\n\n"
        "Создать черновик в iiko?"
    ),
    "invoice_unmatched_item_card": (
        "🔍 <b>Сопоставление номенклатуры ({current}/{total}):</b>\n\n"
        "Наименование поставщика:\n"
        "👉 <b>«{raw_name}»</b>"
        "{article_info}\n\n"
        "Сумма строки: {sum:,.2f} ₽ (кол-во: {qty})\n\n"
        "Выберите соответствие из каталога iiko:"
    ),
    "invoice_enter_sku_prompt": (
        "🔢 <b>Ручной ввод артикула iiko:</b>\n\n"
        "Товар поставщика:\n"
        "👉 <b>«{raw_name}»</b>\n\n"
        "Отправьте в чат <b>артикул товара</b> из iiko (например, <code>6406</code> или с фасовкой: <code>6406*100</code>):"
    ),
    "invoice_sku_not_found": "❌ <b>Товар с артикулом «{sku}» не найден в каталоге iiko.</b>\nПроверьте артикул в iikoOffice и попробуйте еще раз:",
    "invoice_sku_matched_success": "✅ Позиция привязана к <b>«{prod_name}»</b> (артикул: {sku}{pack_info}).",
    "invoice_draft_success": (
        "🚀 <b>Черновик накладной успешно создан в iiko!</b>\n\n"
        "• Ресторан: <b>{store_name}</b>\n"
        "• Номер документа iiko: <code>{iiko_doc_num}</code>\n"
        "• Входящий номер: <code>{inc_doc_num}</code>\n"
        "• Статус: <code>NOT_PROCESSED</code> (черновик)\n\n"
        "<i>Документ ожидает финальной проверки и проведения в iikoOffice.</i>"
    ),
    "invoice_upload_failed": "❌ <b>Ошибка при загрузке накладной в iiko:</b>\n<code>{error}</code>",
    "invoice_cancelled": "❌ <b>Обработка накладной отменена.</b> Временные файлы удалены.",
    "invoice_session_expired": "⚠️ Сессия обработки документа устарела. Отправьте файл заново.",

    # Buttons
    "btn_airport": "🏢 АЭРОПОРТ",
    "btn_october": "🏢 ОКТЯБРЬСКАЯ",
    "btn_cancel": "❌ Отмена",
    "btn_create_draft": "🚀 Загрузить черновик в iiko",
    "btn_skip_item": "⏭ Пропустить позицию",
    "btn_manual_sku": "🔢 Ввести артикул вручную",
    "btn_confirm_pdf": "✅ Всё верно, продолжить",
}

LEXICON_COMMANDS: Dict[str, str] = {
    "/start": "Главное меню / Старт",
    "/help": "Инструкция по накладным",
    "/admin": "Панель управления доступом",
}


def t(key: str, **kwargs) -> str:
    """Retrieves localized text with fail-fast validation against missing keys."""
    if key not in LEXICON:
        raise KeyError(f"Lexicon key '{key}' not found in registry")
    template = LEXICON[key]
    return template.format(**kwargs) if kwargs else template


async def set_bot_commands(bot: Bot) -> None:
    """Configures persistent menu commands in Telegram interface."""
    commands = [
        BotCommand(command=cmd.lstrip("/"), description=desc)
        for cmd, desc in LEXICON_COMMANDS.items()
    ]
    await bot.set_my_commands(commands)
