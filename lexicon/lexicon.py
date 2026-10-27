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
        "2. Бот мгновенно разберет файл и предложит выбрать подключенный ресторан сети для оприходования.\n"
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
    "admin_users_title": "👥 <b>Список сотрудников:</b>\n\nВыберите пользователя для управления ролью и доступом:",
    "admin_users_empty": "Список пользователей пуст.",
    "admin_access_denied": "Отказано в доступе.",
    "admin_btn_back_users": "⬅️ Назад к списку сотрудников",
    "admin_user_card_title": (
        "👤 <b>Карточка сотрудника:</b>\n\n"
        "• Имя: <b>{full_name}</b> ({username})\n"
        "• Telegram ID: <code>{telegram_id}</code>\n"
        "• Роль: <b>{role_str}</b>\n"
        "• Доступ: <b>{status_str}</b>\n"
        "• Логин iiko: <code>{iiko_login}</code>\n"
        "• Склад по умолчанию: <b>{default_store}</b>"
    ),
    "admin_btn_promote": "👑 Сделать администратором",
    "admin_btn_demote": "👤 Разжаловать в операторы",
    "admin_btn_block": "🚫 Заблокировать доступ",
    "admin_btn_unblock": "🟢 Разблокировать доступ",
    "admin_role_updated": "✅ Роль сотрудника успешно обновлена!",
    "admin_status_updated": "✅ Статус доступа обновлен!",
    "admin_cannot_modify_primary": "⛔ Запрещено разжаловать или блокировать первичного администратора сети.",
    "admin_btn_mappings": "🗑 Удаление сопоставлений",
    "admin_search_mapping_prompt": (
        "🔍 <b>Удаление ошибочных сопоставлений из базы знаний:</b>\n\n"
        "Отправьте в чат название товара или артикул для поиска:\n"
        "<i>(например, «перчатки» или «палочки»)</i>"
    ),
    "admin_search_mapping_empty": "❌ По запросу «{query}» сопоставлений не найдено.",
    "admin_search_mapping_results": "🔍 <b>Найдено сопоставлений ({count}):</b>\nНажмите «Удалить» под ошибочной связкой:",
    "admin_mapping_deleted_success": "✅ Сопоставление удалено из базы знаний!",
    "admin_btn_back": "⬅️ Назад в админку",
    "admin_btn_training": "🎓 Пакетное обучение базы (ZIP/XML/PDF)",
    "admin_btn_start_training_analysis": "📊 Начать сопоставление и анализ",
    "admin_btn_commit_training": "✅ Применить обучение (+{count} связок)",
    "admin_btn_download_report": "📄 Скачать отчет симуляции (.json)",
    "admin_train_accumulator_title": (
        "🎓 <b>Режим пакетного обучения базы знаний:</b>\n\n"
        "Отправляйте в чат любые файлы накладных (пакетами или архивами):\n"
        "• <b>.zip</b> — архивы с накладными Диадока (распаковываются автоматически)\n"
        "• <b>.xml</b> — электронные УПД / счета-фактуры\n"
        "• <b>.pdf</b> — растровые накладные и сканы\n\n"
        "📦 <b>Текущая очередь сессии (№ <code>{batch_id}</code>):</b>\n"
        "• Архивов .zip: <b>{zip_count}</b> шт.\n"
        "• Файлов .xml: <b>{xml_count}</b> шт.\n"
        "• Файлов .pdf: <b>{pdf_count}</b> шт.\n"
        "• Всего документов: <b>{total_files}</b> / 2000\n\n"
        "<i>Отправьте еще файлы или запустите анализ:</i>"
    ),
    "admin_train_running_wait": (
        "⏳ <b>Запущен алгоритмический анализ пакета...</b>\n\n"
        "1. Распаковка и верификация XML/PDF...\n"
        "2. Экспорт проведенных накладных из iikoChain ({date_from} — {date_to})...\n"
        "3. Сверка инвариантов сумм и расчет фасовок...\n\n"
        "<i>Это может занять 1-2 минуты. Пожалуйста, подождите.</i>"
    ),
    "admin_train_report_card": (
        "📊 <b>ПРЕДВАРИТЕЛЬНАЯ СВОДКА ОБУЧЕНИЯ (СИМУЛЯЦИЯ):</b>\n\n"
        "📁 Документов в пакете: <b>{total_files}</b>\n"
        "✅ Сопоставлено в iiko: <b>{matched_count}</b> накладных\n"
        "• По строгому порядку: {strict_count}\n"
        "• По уникальным суммам: {unique_sums_count}\n"
        "⚠️ Не найдено в iiko: {unmatched_count}\n\n"
        "🧠 <b>Изменения для базы знаний сети:</b>\n"
        "• 🟢 <b>Абсолютно новых связок:</b> +{new_count}\n"
        "• 🔵 Подтверждений существующих: +{confirmed_count}\n"
        "• 🟡 Обновлений фасовки: {coeff_count}\n"
        "• 🔴 <b>Конфликтов с базой:</b> {conflicts_count}\n"
        "{conflict_details}\n"
        "<i>Применить изменения в базе знаний KONO?</i>"
    ),
    "admin_train_success": (
        "✅ <b>Пакетное обучение успешно завершено!</b>\n\n"
        "В базу знаний сети KONO транзакционно внесено / подтверждено: <b>{committed_count}</b> связок.\n"
        "Временные файлы сессии удалены."
    ),
    "admin_train_cancelled": "❌ <b>Сессия обучения отменена.</b> Временные файлы удалены без изменения базы.",
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
    "invoice_review_title": (
        "📋 <b>Ревизия сопоставленных позиций (№ {doc_number}):</b>\n\n"
        "Нажмите на строку, если требуется изменить товар iiko или коэффициент фасовки:"
    ),
    "invoice_no_creds_error": (
        "⚠️ <b>Учетная запись iikoOffice не привязана!</b>\n\n"
        "Для оприходования накладных необходимо указать ваш логин и пароль iiko в личном кабинете, "
        "чтобы зафиксировать автора документа в ERP."
    ),
    # Buttons
    "btn_cancel": "❌ Отмена",
    "btn_create_draft": "🚀 Загрузить черновик в iiko",
    "btn_review_items": "📋 Проверить позиции и фасовку",
    "btn_back_to_upload": "⬅️ Назад к подтверждению",
    "btn_retry_upload": "🔄 Повторить загрузку в iiko",
    "btn_setup_iiko_creds": "🔐 Привязать iiko в профиле",
    "btn_skip_item": "⏭ Пропустить позицию",
    "btn_manual_sku": "🔢 Ввести артикул вручную",
    "btn_confirm_pdf": "✅ Всё верно, продолжить",
    "btn_custom_coeff": "✏️ Другое число",
    "btn_coeff_metric_gram": "x0.001 (г → кг / мл → л)",
    "btn_coeff_half": "x0.5",
    "cab_btn_my_mappings": "📋 Мои привязки товаров",
    "cab_my_mappings_title": (
        "📋 <b>Ваши сопоставления номенклатуры:</b>\n\n"
        "Если вы ошиблись при сопоставлении, нажмите на позицию, чтобы отозвать свой выбор:\n"
        "<i>(Общий словарь сети не пострадает)</i>"
    ),
    "cab_my_mappings_empty": "У вас пока нет созданных привязок номенклатуры.",
    "cab_mapping_revoked_success": "✅ Привязка успешно отозвана!",
    "cab_mapping_revoke_failed": "❌ Не удалось отозвать привязку.",
    # Main Navigation Menu
    "menu_main_title": (
        "📱 <b>Главное меню KONO Supply:</b>\n\n"
        "Выберите необходимое действие с помощью кнопок ниже:"
    ),
    "menu_btn_upload": "📄 Загрузить накладную (XML / PDF)",
    "menu_btn_cabinet": "⚙️ Личный кабинет / Настройки iiko",
    "menu_btn_help": "ℹ️ Инструкция и статус",
    "menu_btn_admin": "👑 Панель администратора сети",
    "menu_btn_back": "⬅️ В главное меню",
    "menu_upload_info_text": (
        "📄 <b>Загрузка накладных поставщиков:</b>\n\n"
        "Просто отправьте файл накладной в этот диалог:\n"
        "• <b>.xml</b> — электронные накладные из Диадока (УПД, счета-фактуры)\n"
        "• <b>.pdf</b> — сканы, накладные, спецификации\n\n"
        "Бот автоматически распознает номенклатуру и предложит ресторан для оприходования черновика."
    ),
    # User Cabinet
    "cab_profile_card": (
        "⚙️ <b>Личный кабинет сотрудника:</b>\n\n"
        "👤 <b>Пользователь:</b> {full_name} ({username})\n"
        "🎖 <b>Роль:</b> {role}\n"
        "🔑 <b>Учетная запись iiko:</b> {creds_status}\n"
        "🏢 <b>Ресторан по умолчанию:</b> <b>{default_store}</b>\n\n"
        "<i>Все накладные создаются в iikoOffice от имени вашей учетной записи.</i>"
    ),
    "cab_btn_set_creds": "🔐 Привязать логин и пароль iiko",
    "cab_btn_change_creds": "✏️ Изменить пароль",
    "cab_btn_test_conn": "🔄 Проверить связь с iiko",
    "cab_btn_clear_creds": "🗑 Сбросить учетную запись",
    "cab_btn_my_stores": "🏬 Мои рестораны (подключить точки)",
    "cab_my_stores_title": (
        "🏬 <b>Ваши подключенные рестораны:</b>\n\n"
        "Нажимайте на точки, чтобы подключить или отключить их:\n"
        "<i>(Вы сможете принимать накладные только на подключенные рестораны)</i>"
    ),
    "invoice_no_stores_error": (
        "⚠️ <b>У вас не подключено ни одного ресторана!</b>\n\n"
        "Перед отправкой накладных перейдите в профиль и отметьте точки, с которыми вы работаете."
    ),
    "invoice_select_store_first": (
        "📍 <b>Выберите ресторан для оприходования накладной:</b>\n"
        "Файл: <code>{filename}</code>"
    ),
    "btn_connect_stores": "🏬 Подключить рестораны",
    "cab_prompt_login": (
        "🔐 <b>Привязка учетной записи iikoOffice:</b>\n\n"
        "Введите ваш <b>логин</b> в системе iiko (например, <code>ivanov</code>):"
    ),
    "cab_prompt_password": (
        "🔑 <b>Введите ваш пароль от iikoOffice:</b>\n\n"
        "<i>Сообщение с паролем будет немедленно удалено из чата для безопасности.</i>"
    ),
    "cab_invalid_login": "❌ Слишком короткий логин. Введите корректный логин iiko:",
    "cab_validating_wait": "⏳ <i>Проверяю авторизацию на сервере iiko...</i>",
    "cab_creds_success": (
        "✅ <b>Учетная запись iiko успешно привязана!</b>\n\n"
        "Логин: <code>{login}</code>\n"
        "Пароль зашифрован ключом AES-128 Fernet.\n"
        "Теперь вы можете загружать накладные в iikoOffice от своего имени."
    ),
    "cab_creds_failed": (
        "❌ <b>Ошибка авторизации в iiko:</b>\n"
        "<code>{error}</code>\n\n"
        "Убедитесь, что логин и пароль совпадают с вашими учетными данными в iikoOffice."
    ),
    "cab_creds_empty": "❌ Логин и пароль не могут быть пустыми.",
    "cab_btn_to_cabinet": "⚙️ В личный кабинет",
    "cab_btn_retry": "🔄 Попробовать снова",
    "cab_no_creds_alert": "У вас еще не настроены логин и пароль iiko.",
    "cab_test_ok_alert": "✅ Связь с сервером iiko успешна! Учетная запись активна.",
    "cab_test_fail_alert": "❌ Сбой связи с iiko:\n{error}",
    "cab_creds_cleared": "Учетные данные iiko сброшены.",
    "cab_choose_store_title": (
        "🏢 <b>Выбор ресторана по умолчанию:</b>\n\n"
        "Выберите точку, на которую чаще всего принимаете поставки:\n"
        "<i>(Она будет автоматически подставляться первой кнопкой при разборе накладных)</i>"
    ),
    "cab_store_saved": "✅ Ресторан по умолчанию сохранен!",
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
