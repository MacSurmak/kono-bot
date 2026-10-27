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
    "admin_btn_stores": "🏬 Управление ресторанами",
    "admin_btn_mappings": "🗑 Удаление сопоставлений",
    "admin_stores_title": "🏬 <b>Управление ресторанами сети:</b>\n\nСписок подключенных складов iiko:\n",
    "admin_stores_empty": "Нет подключенных ресторанов.",
    "admin_btn_add_store": "➕ Подключить точку",
    "admin_btn_manual_store": "✏️ Ввести GUID вручную",
    "admin_store_manual_prompt": (
        "✏️ <b>Ручное добавление склада iiko:</b>\n\n"
        "Отправьте GUID и название точки через пробел:\n"
        "<code>4841e49a-61b4-4f34-b51c-7cfb3ccad7ac ТАГАНКА</code>\n\n"
        "<i>Для отмены нажмите кнопку ниже.</i>"
    ),
    "admin_store_invalid_format": "❌ Неверный формат. Отправьте GUID (36 символов) и название через пробел:",
    "admin_store_added_success": "✅ Ресторан <b>«{name}»</b> успешно подключен!",
    "admin_store_deleted_success": "🗑 Склад отключен.",
    "admin_iiko_stores_available": "🏬 <b>Склады, найденные в iiko:</b>\nВыберите точку для подключения:",
    "admin_iiko_no_new_stores": "В iiko не найдено новых неподключенных складов. Вы можете ввести GUID вручную.",
    "admin_search_mapping_prompt": (
        "🔍 <b>Удаление ошибочных сопоставлений из базы знаний:</b>\n\n"
        "Отправьте в чат название товара или артикул для поиска:\n"
        "<i>(например, «перчатки» или «палочки»)</i>"
    ),
    "admin_search_mapping_empty": "❌ По запросу «{query}» сопоставлений не найдено.",
    "admin_search_mapping_results": "🔍 <b>Найдено сопоставлений ({count}):</b>\nНажмите «Удалить» под ошибочной связкой:",
    "admin_mapping_deleted_success": "✅ Сопоставление удалено из базы знаний!",
    "admin_btn_back": "⬅️ Назад в админку",
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
        "Отправьте в чат <b>артикул или код товара</b> из iiko (например, <code>6406</code> или <code>31698</code>):"
    ),
    "invoice_packaging_prompt": (
        "📦 <b>Укажите фасовку для товара:</b>\n"
        "«{prod_name}» (арт. <code>{sku}</code>)\n\n"
        "В накладной поставщика: <b>{qty:g}</b> ед.\n"
        "👉 <i>Сколько штук iiko содержится в 1 единице поставщика?</i>"
    ),
    "invoice_custom_coeff_prompt": (
        "✏️ <b>Введите числовой коэффициент фасовки:</b>\n\n"
        "Сколько базовых штук iiko в одной упаковке? (Например: <code>12</code>, <code>24</code> или <code>150</code>):"
    ),
    "invoice_custom_coeff_invalid": "❌ Введите корректное положительное число (например, 24 или 100):",
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
    "invoice_upload_failed": "❌ <b>Ошибка при загрузке накладной в iiko:</b>\n<code>{error}</code>\n\n<i>Сессия сохранена. Вы можете повторить попытку после проверки связи.</i>",
    "invoice_cancelled": "❌ <b>Обработка накладной отменена.</b> Временные файлы удалены.",
    "invoice_session_expired": "⚠️ Сессия обработки документа устарела. Отправьте файл заново.",
    # Buttons
    "btn_airport": "🏢 АЭРОПОРТ",
    "btn_october": "🏢 ОКТЯБРЬСКАЯ",
    "btn_cancel": "❌ Отмена",
    "btn_create_draft": "🚀 Загрузить черновик в iiko",
    "btn_retry_upload": "🔄 Повторить загрузку в iiko",
    "btn_skip_item": "⏭ Пропустить позицию",
    "btn_manual_sku": "🔢 Ввести артикул вручную",
    "btn_confirm_pdf": "✅ Всё верно, продолжить",
    "btn_custom_coeff": "✏️ Другое число",
    "btn_coeff_metric_gram": "x0.001 (г → кг / мл → л)",
    "btn_coeff_half": "x0.5",
}

    # Main Navigation Menu
    "menu_main_title": (
        "📱 <b>Главное меню KONO Supply:</b>\n\n"
        "Выберите необходимое действие с помощью кнопок ниже:"
    ),
    "menu_btn_upload": "📄 Загрузить накладную (XML / PDF)",
    "menu_btn_cabinet": "⚙️ Личный кабинет / Настройки iiko",
    "menu_btn_help": "ℹ️ Инструкция и статус",
    "menu_btn_admin": "👑 Панель администратора сети",
}

LEXICON_COMMANDS: Dict[str, str] = {
    "/menu": "Главное меню управления",
    "/help": "Инструкция по накладным",
    "/admin": "Панель администратора сети",
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
