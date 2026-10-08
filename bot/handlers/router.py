"""
ثبت گردانندگان.

ترتیب اینجا سرنوشت‌ساز است و ساده‌ترین جای اشتباه در کل ربات.
سه قاعده‌ای که رعایت شده:

۱) دکمه‌های منو پیش از گردانندهٔ وضعیت می‌آیند. اگر وارونه بود،
   کاربری که در میانهٔ پیشکش نوا «کیسهٔ سکه» را می‌زند، آن نوشتار
   به عنوان نام مداح گرفته می‌شد.

۲) پیام‌های گروه از پیام‌های گفتگوی خصوصی جدا شده‌اند. بی این
   جدایی، پاسخ گرداننده در گروه، به چشم «پیشکش نوا» می‌آمد.

۳) هر وضعیت، تنها یک مقصد دارد و همه از یک درگاه می‌گذرند. پراکندن
   گردانندگان بر پایهٔ گونهٔ پیام، دیر یا زود به دو گردانندهٔ هم‌پوش
   می‌انجامد که هیچ‌کس نمی‌فهمد کدام‌شان پاسخ داده.
"""

from __future__ import annotations

import logging

from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    InlineQueryHandler,
    MessageHandler,
    filters,
)

from bot import states
from bot import commands as command_lists
from bot.handlers import (
    admin,
    archive,
    browse,
    channels as channel_admin,
    curation,
    feedback,
    inline_query,
    intake,
    menu,
    restore,
    search,
    start,
    submission,
    websearch,
)
from bot.keyboards import inline
from config import config
from core import texts
from services import instagram

logger = logging.getLogger(__name__)

# پالایهٔ کانال‌های منبع. در `register()` ساخته می‌شود و از آن پس
# `watch_source`/`unwatch_source` در جا بازش می‌کنند و می‌بندند.
_source_filter = None


# ── دامنه‌بندی فرمان‌ها ────────────────────────────────────────
#
# نامِ هر گروه به شناسهٔ راستینش می‌رسد. `ornate_target` خودش به
# گروه مداحی فرو می‌ریزد، پس اگر ORNATE_GROUP_ID تنظیم نشده باشد
# فرمان‌های گروه بایگانی همچنان در همان گروه مداحی کار می‌کنند.
def _kind_chats() -> dict[str, int]:
    """شناسه‌های تازه — پس از پیش‌پرواز، شکلِ `resolved` هم هست."""
    from core import net

    return {
        "archive": net.resolved(config.ornate_target) or config.ornate_target,
        "madahi": net.resolved(config.madahi_group_id) or config.madahi_group_id,
        "feedback": net.resolved(config.feedback_group_id) or config.feedback_group_id,
        "users": net.resolved(config.users_group_id) or config.users_group_id,
    }

# فرمانی که دامنه‌اش خالی است (شناسه‌ای تنظیم نشده) هیچ‌جا
# نباید کار کند — نه اینکه بی‌قید همه‌جا.
_NEVER = filters.COMMAND & ~filters.COMMAND


def _scope_filter(name: str):
    """
    پالایهٔ گفتگو برای یک فرمان، از روی `bot/commands.allowed_chats`.

    `None` یعنی فرمان در همه‌جا رواست (`/id`، `/cancel`)؛ وگرنه
    اجتماعِ پالایه‌ها. فرمانی که اصلاً در فهرست‌ها نیست — مانند
    دستورهای ناشناخته — اینجا ثبت نمی‌شود و به handler پایانی
    می‌رسد که پاسخِ رد می‌دهد.
    """
    kinds = command_lists.allowed_chats(name)
    if kinds is None:
        return None

    from core import net

    kind_chats = _kind_chats()
    clauses = []
    ids: list[int] = []
    for kind in kinds:
        if kind == "private":
            clauses.append(filters.ChatType.PRIVATE)
            continue
        chat_id = kind_chats.get(kind)
        # شناسهٔ .env و گونهٔ کارآمدش هر دو: پیش‌پرواز پس از ثبت
        # می‌دود، و تا آنگاه تنها گونهٔ خام شناخته شده است.
        for candidate in ([chat_id] + net.variants(chat_id) if chat_id else []):
            if candidate and candidate not in ids:
                ids.append(candidate)
    if ids:
        clauses.append(filters.Chat(chat_id=ids))
    if not clauses:
        return _NEVER
    clause = clauses[0]
    for extra in clauses[1:]:
        clause = clause | extra
    return clause


def watch_source(chat_id: int) -> bool:
    """کانالی را به شنودِ زنده می‌افزاید. بی بازراه‌اندازی."""
    if _source_filter is None:
        logger.warning("پالایهٔ کانال منبع هنوز ساخته نشده است.")
        return False
    _source_filter.add_chat_ids(chat_id)
    logger.info("کانال %s به شنود افزوده شد.", chat_id)
    return True


def unwatch_source(chat_id: int) -> bool:
    """کانالی را از شنود برمی‌دارد."""
    if _source_filter is None:
        return False
    try:
        _source_filter.remove_chat_ids(chat_id)
    except Exception:  # noqa: BLE001
        logger.debug("برداشتن کانال %s از شنود نشد.", chat_id)
        return False
    logger.info("کانال %s از شنود برداشته شد.", chat_id)
    return True


def _exact(key: str):
    """پالایه‌ای که تنها با نوشتار دقیق یک دکمه هم‌خوان است."""
    return filters.Regex(f"^{texts.btn(key)}$")


async def _on_private_text_or_media(update, context) -> None:
    """
    پیام‌های گفتگوی خصوصی را بر پایهٔ وضعیت کاربر مسیریابی می‌کند.

    این یک درگاه یگانه است، نه چند گردانندهٔ پراکنده؛ چنین شکلی
    بازبینی «کاربر در چه وضعی است» را در یک جا نگه می‌دارد.
    """
    state = states.get_state(context.user_data)
    message = update.effective_message

    # وضعیتِ گروهی که به گفتگوی خصوصی نشت کرده — user_data برای هر
    # کاربر یکی است، نه برای هر گفتگو. اینجا معنایی ندارد.
    #
    # استثنا: اگر وضعیت برای **همین** گفتگو ساخته شده باشد (مانند
    # `/upload` که بارگذاریِ دسته‌ایِ همراهِ مورد اعتماد است) پاک
    # نمی‌شود. پیش‌تر همه پاک می‌شدند و همین بود که پس از `/trust`،
    # کاربر `/upload` می‌زد ولی فرستادنِ انبوه هرگز راه نمی‌افتاد.
    if state in states.GROUP_ONLY_STATES:
        owner = states.get_data(context.user_data).get("chat_id")
        if (
            owner is None
            or message is None
            or int(owner) != int(message.chat_id)
        ):
            states.clear_state(context.user_data)
            state = None

    # اگر کاربر به جای نوشتن نام مداح، پارهٔ تازه‌ای بفرستد، پیداست
    # که بازجویی تازه‌ای می‌خواهد. خاموش ماندن اینجا — که پیش از
    # این می‌شد — کاربر را به گمان خرابی می‌انداخت.
    if state in (states.AWAITING_SEARCH_HINT, states.AWAITING_HINT_AFTER_FAIL):
        if _looks_like_query(update):
            states.clear_state(context.user_data)
            await search.on_input(update, context)
            return

    if state in states.INTAKE_STATES:
        # پذیرشِ در جریان، خودش می‌سنجد که این پیام از همان گفتگوست؛
        # اگر نبود، هیچ نمی‌کند و کار به شاخهٔ پایین می‌رسد.
        if await _route_intake(update, context, state):
            return

    if state == states.AWAITING_SEARCH_INPUT:
        await search.on_input(update, context)
    elif state == states.AWAITING_SEARCH_HINT:
        await search.on_hint(update, context)
    elif state == states.AWAITING_HINT_AFTER_FAIL:
        await search.on_hint_after_fail(update, context)
    elif state == states.AWAITING_BULK_AUDIO:
        # بارگذاری دسته‌ایِ همراهِ مورد اعتماد (`/upload`).
        #
        # ولی اگر مدت‌هاست بی‌کار مانده، پیداست که `/done` فراموش
        # شده؛ آنگاه این آوا برای **جست‌وجو** آمده نه بارگذاری.
        # بلعیدنش یعنی ثبتِ بی‌داوری در گنجینه.
        if curation.bulk_is_stale(context.user_data):
            states.clear_state(context.user_data)
            await search.on_input(update, context)
        else:
            await curation.on_bulk_audio(update, context)
    elif state == states.AWAITING_SUBMISSION_FILE:
        await submission.on_audio(update, context)
    elif state == states.AWAITING_SUBMISSION_MADAH:
        await submission.on_madah(update, context)
    elif state == states.AWAITING_SUBMISSION_STYLE:
        await submission.on_style(update, context)
    elif state == states.AWAITING_SUBMISSION_TITLE:
        await submission.on_title(update, context)
    elif state == states.AWAITING_EDIT_VALUE:
        await submission.on_edit_value(update, context)
    elif state == states.AWAITING_FEEDBACK:
        await feedback.on_content(update, context)
    elif state == states.AWAITING_CHANNEL_INPUT:
        await channel_admin.on_input(update, context)
    elif _is_forwarded_audio(update) and _is_admin(update):
        # نوای بازفرستادهٔ گرداننده: افزودن است یا بازجویی؟ خودِ
        # پیام نمی‌گوید، پس پرسیده می‌شود. پیش‌تر خودکار افزوده
        # می‌شد و همان، جریان پیشکش را از میان برمی‌داشت.
        await archive.ask_forwarded(update, context)
    elif _looks_like_query(update) or _looks_like_name(update):
        # کاربر بی‌مقدمه چیزی فرستاده. پیش‌تر همین‌جا خودکار
        # جست‌وجو می‌شد، با این استدلال که خواستش روشن است. ولی
        # روشن نبود: همان فایل می‌توانست پیشکش باشد، یا اشتباهی
        # فرستاده شده باشد — و جست‌وجو سکه می‌خواهد. اکنون آغازِ
        # جست‌وجو یک تصمیمِ صریح است، با دکمهٔ میان‌بر زیر پیام.
        await search.nudge(update, context)
    else:
        await menu.show_menu(update, context)


async def _route_intake(update, context, state: str) -> bool:
    """
    پیامی در میانهٔ دفتر پذیرش.

    بازگشتی می‌گوید آیا این پیام خورده شد. اگر پذیرش در گفتگوی
    دیگری در جریان باشد، اینجا چیزی خورده نمی‌شود و پیام راه
    همیشگی خود را می‌رود.
    """
    message = update.effective_message
    data = states.get_data(context.user_data)
    if message is None or int(data.get("chat_id", 0)) != message.chat_id:
        return False

    if state == states.AWAITING_INTAKE_MADAH:
        await intake.on_madah(update, context)
    elif state == states.AWAITING_INTAKE_STYLE:
        await intake.on_style(update, context)
    elif state == states.AWAITING_INTAKE_TITLE:
        await intake.on_title(update, context)
    elif state == states.AWAITING_INTAKE_EDIT:
        await intake.on_value(update, context)
    else:
        # کارت بر پرده است و ربات چشم‌به‌راه نواختن است، نه نوشتار.
        # خاموش گذشتن اینجا درست است: گرداننده در گروه سخن می‌گوید،
        # و هر سخنش نباید نام نوا شمرده شود.
        return False
    return True


def _is_forwarded_audio(update) -> bool:
    message = update.effective_message
    if message is None or message.audio is None:
        return False
    return bool(
        getattr(message, "forward_origin", None)
        or getattr(message, "forward_date", None)
    )


def _is_admin(update) -> bool:
    user = update.effective_user
    return user is not None and config.is_admin(user.id)


def _looks_like_name(update) -> bool:
    """نوشتاری که می‌تواند نام مداح یا نوا باشد."""
    message = update.effective_message
    if message is None or not message.text:
        return False
    text = message.text.strip()
    if text.startswith("/"):
        return False
    # نوشتار بسیار دراز، پیام است نه نام
    return 2 <= len(text) <= 60


def _looks_like_query(update) -> bool:
    """
    آیا کاربر بی‌مقدمه چیزی فرستاده که روشن است می‌خواهد بجوید.

    آوا، نماهنگ و نشانی اینستاگرام همه گویای خواست اویند؛ واداشتنش
    به زدن دکمه پیش از آن، آزردن بی‌سبب است.
    """
    message = update.effective_message
    if message is None:
        return False
    if any(
        getattr(message, attr, None)
        for attr in ("audio", "voice", "video", "video_note")
    ):
        return True
    return instagram.find_url(message.text or message.caption) is not None


async def _on_group_message(update, context) -> None:
    """
    پیام‌های گروه: پاسخ گرداننده، محتوای همگانی‌رسانی، افزودن انبوه،
    یا پر کردن یک بازجویی ناکام.
    """
    state = states.get_state(context.user_data)

    if state in states.INTAKE_STATES:
        if await _route_intake(update, context, state):
            return

    if state == states.AWAITING_ADMIN_REPLY:
        await feedback.on_admin_reply(update, context)
        return
    elif state == states.AWAITING_BROADCAST:
        await admin.on_broadcast_content(update, context)
        return
    elif state == states.AWAITING_BULK_AUDIO:
        await curation.on_bulk_audio(update, context)
        return
    elif state == states.AWAITING_DELETE_QUERY:
        await curation.on_delete_query(update, context)
        return
    elif state == states.AWAITING_TRACK_EDIT:
        await curation.on_track_value(update, context)
        return
    elif state == states.AWAITING_EDIT_VALUE:
        await submission.on_edit_value(update, context)
        return
    elif state == states.AWAITING_FILL_AUDIO:
        await curation.on_fill_audio(update, context)
        return
    elif state == states.AWAITING_CHANNEL_INPUT:
        await channel_admin.on_input(update, context)
        return
    elif state == states.AWAITING_RESTORE_FILE:
        # `/restore` زده شده؛ این سندِ `.db`ای است که خواسته شد.
        await restore.on_document(update, context)
        return


def register(app: Application) -> None:
    private = filters.ChatType.PRIVATE
    # گروه بایگانی هم افزوده می‌شود: ویرایشِ زیر فایل همان‌جا
    # پاسخ می‌گیرد، و بی این، آن پاسخ اصلاً به ربات نمی‌رسید.
    _group_ids = [config.madahi_group_id, config.feedback_group_id]
    if config.ornate_group_id and config.ornate_group_id not in _group_ids:
        _group_ids.append(config.ornate_group_id)
    # گونه‌های هم‌ارز شناسه هم: پیش‌پرواز پس از ثبت می‌دود و شکل
    # کارآمد (`resolved`) را می‌یابد؛ تا آنگاه گونهٔ خام بس است و
    # پس از آن، هر دو باید به ربات برسند.
    from core import net as _net

    _group_ids = [
        _candidate
        for _chat_id in list(_group_ids)
        if _chat_id
        for _candidate in _net.variants(_chat_id)
    ] or _group_ids
    groups = filters.Chat(chat_id=_group_ids)

    # ── فرمان‌ها ────────────────────────────────────────────
    #
    # دامنهٔ هر فرمان از `bot/commands.allowed_chats` می‌آید: فرمانِ
    # گروه در گروه خودش، فرمانِ خصوصی در خصوصی. فرمانِ ناشناخته یا
    # فرمانِ گروه که در خصوصی زده شود، به handler پایانی می‌رسد و
    # پاسخِ رد می‌گیرد — پیش‌تر همه جا بی‌قید کار می‌کردند.
    def cmd(name: str, handler, **kwargs) -> None:
        app.add_handler(
            CommandHandler(name, handler, filters=_scope_filter(name), **kwargs)
        )

    cmd("start", start.start)
    cmd("help", menu.show_help)
    cmd("menu", menu.show_menu)
    # /cancel در گروه هم بایسته است: پذیرشِ نیمه‌کاره باید راه
    # بیرون آمدن داشته باشد، وگرنه گرداننده در گام «نام مداح»
    # می‌ماند و هر سخنش در گروه، نام نوا می‌شود.
    cmd("cancel", _cancel)

    cmd("stats", admin.stats)
    cmd("engine", admin.engine)
    cmd("failures", admin.failures)
    cmd("wanted", admin.wanted)
    cmd("clean", admin.clean)
    cmd("alias", admin.alias)
    # `/madahs` هم برای گرداننده کار می‌کند و هم برای کاربر؛
    # خودِ گرداننده در `browse` سنجیده می‌شود، نه اینجا.
    cmd("madahs", browse.show_madahs)
    cmd("reindex", admin.reindex)
    # صوت‌هایی که نمایه نشدند — در گنجینه‌اند ولی موتور
    # نمی‌بیندشان.
    cmd("broken", admin.broken)
    cmd("textall", admin.begin_broadcast)
    cmd("reload_texts", admin.reload_texts)
    cmd("backup", admin.backup_now)
    cmd("train", admin.train_classifier)
    cmd("features", admin.features_status)
    cmd("crawl", admin.crawl_status)

    # ── گردآوری گنجینه ─────────────────────────────────────
    cmd("bulk", curation.begin_bulk)
    cmd("bulk_end", curation.end_bulk)
    cmd("upload", curation.begin_upload)
    cmd("done", curation.end_upload)
    cmd("trust", curation.trust)
    cmd("untrust", curation.untrust)
    cmd("trusted", curation.trusted_list)
    cmd("delete", curation.begin_delete)

    # ── تنها از دست مالک ────────────────────────────────────
    cmd("addadmin", curation.add_admin)
    cmd("deladmin", curation.remove_admin)
    cmd("admins", curation.list_admins)
    cmd("health", admin.health)

    # ── کانال‌ها، در زمان اجرا ──────────────────────────────
    cmd("addchannel", channel_admin.add_required)
    cmd("channels", channel_admin.list_required)
    cmd("delchannel", channel_admin.remove_required)
    cmd("addsource", channel_admin.add_source)
    cmd("sources", channel_admin.list_sources)
    cmd("delsource", channel_admin.remove_source)

    # /id در هر گفتگویی کار می‌کند — گروهی که تازه ربات را به آن
    # افزوده‌اید هم. شناسه‌ای که می‌دهد، همان است که .env می‌خواهد.
    cmd("id", admin.chat_id)
    cmd("sites", admin.sites_status)

    # ── بازیابی پایگاه داده ─────────────────────────────────
    #
    # فرمان در گروه مداحی؛ فایلِ `.db` پس از آن می‌آید (وضعیت
    # AWAITING_RESTORE_FILE). مسیرِ خصوصیِ مالک همچنان پابرجاست:
    # همان‌جا فایل را بفرستد، بی‌نیاز از فرمان.
    cmd("restore", restore.begin)
    # پیش از intake: وگرنه فایلِ `.db` مالک در خصوصی نخست به
    # `_on_private_text_or_media` می‌رسید و به چشم «پیشکش نوا»
    # گرفته می‌شد. ترتیبِ ثبت در PTB همان ترتیبِ رسیدگی است.
    _owner_ids = [int(v) for v in list(config.admin_ids[:1]) if v]
    if _owner_ids:
        app.add_handler(
            MessageHandler(
                private
                & filters.User(user_id=_owner_ids)
                & filters.Document.FileExtension("db"),
                restore.on_document,
            )
        )
    app.add_handler(CallbackQueryHandler(restore.on_choice, pattern="^rst:"))

    # ── دکمه‌های درون‌خطی ───────────────────────────────────
    app.add_handler(
        CallbackQueryHandler(start.on_instagram_tap, pattern=f"^{inline.GATE_INSTAGRAM}$")
    )
    app.add_handler(
        CallbackQueryHandler(start.on_check_membership, pattern=f"^{inline.GATE_CHECK}$")
    )
    app.add_handler(
        CallbackQueryHandler(
            submission.on_review,
            pattern=f"^({inline.SUB_APPROVE}|{inline.SUB_REJECT}|{inline.SUB_TRUST}):",
        )
    )
    # ── بازبینی و ویرایش پیشکش ──────────────────────────────
    app.add_handler(
        CallbackQueryHandler(submission.on_user_send, pattern=f"^{inline.SUB_SEND}:")
    )
    app.add_handler(
        CallbackQueryHandler(submission.on_user_drop, pattern=f"^{inline.SUB_DROP}:")
    )
    app.add_handler(
        CallbackQueryHandler(submission.on_edit_open, pattern=f"^{inline.SUB_EDIT}:")
    )
    app.add_handler(
        CallbackQueryHandler(submission.on_edit_field, pattern=f"^{inline.SUB_FIELD}:")
    )
    app.add_handler(
        CallbackQueryHandler(submission.on_edit_back, pattern=f"^{inline.SUB_BACK}:")
    )
    app.add_handler(
        CallbackQueryHandler(feedback.on_reply_tap, pattern=f"^{inline.FB_REPLY}:")
    )
    app.add_handler(
        CallbackQueryHandler(feedback.on_release_tap, pattern=f"^{inline.FB_RELEASE}:")
    )
    app.add_handler(
        CallbackQueryHandler(
            admin.on_broadcast_cancel, pattern=f"^{inline.BROADCAST_CANCEL}:"
        )
    )
    app.add_handler(
        CallbackQueryHandler(
            search.on_feedback,
            pattern=f"^({inline.SEARCH_CORRECT}|{inline.SEARCH_WRONG}):",
        )
    )
    app.add_handler(
        CallbackQueryHandler(
            search.on_send_full, pattern=f"^{inline.SEARCH_SEND_FULL}(:|$)"
        )
    )
    app.add_handler(
        CallbackQueryHandler(
            search.on_notify, pattern=f"^{inline.SEARCH_NOTIFY}(:|$)"
        )
    )
    app.add_handler(
        CallbackQueryHandler(
            browse.on_madah_pick, pattern=f"^{inline.MADAH_PICK}:"
        )
    )
    app.add_handler(
        CallbackQueryHandler(
            browse.on_madah_track, pattern=f"^{inline.MADAH_TRACK}:"
        )
    )
    # ترتیب مهم است: الگوی برگه‌ها پیش از الگوی گزینش نیاید،
    # وگرنه «mdh:trpg» را «mdh:tr» می‌بلعد.
    app.add_handler(
        CallbackQueryHandler(
            browse.on_madah_track_page, pattern=f"^{inline.MADAH_TRACK_PAGE}:"
        )
    )
    app.add_handler(
        CallbackQueryHandler(
            browse.on_madah_page, pattern=f"^{inline.MADAH_PAGE}:"
        )
    )
    app.add_handler(
        CallbackQueryHandler(
            browse.on_madah_back, pattern=f"^{inline.MADAH_BACK}:"
        )
    )
    # شمارهٔ برگه دکمه‌ای است که کاری نمی‌کند؛ بی این، چرخِ روی
    # دکمه تا مهلتِ تلگرام می‌چرخد.
    app.add_handler(
        CallbackQueryHandler(
            admin.on_broken_retry, pattern=f"^{inline.BROKEN_RETRY}:"
        )
    )
    app.add_handler(CallbackQueryHandler(browse.on_noop, pattern="^noop$"))
    app.add_handler(
        CallbackQueryHandler(
            archive.on_harvest_ok, pattern=f"^{inline.HARVEST_OK}:"
        )
    )
    app.add_handler(
        CallbackQueryHandler(
            archive.on_harvest_no, pattern=f"^{inline.HARVEST_NO}:"
        )
    )
    # «بی‌خیال» گاه شمارهٔ جست‌وجو را با خود دارد و گاه نه (کیبوردهای
    # کهنه‌ای که پیش از این تغییر فرستاده شده‌اند). هر دو پذیرفته
    # می‌شوند تا دکمه‌های روی پرده یک‌شبه از کار نیفتند.
    app.add_handler(
        CallbackQueryHandler(
            search.on_cancel, pattern=f"^{inline.SEARCH_CANCEL}(:|$)"
        )
    )
    app.add_handler(
        CallbackQueryHandler(search.on_begin_tap, pattern=f"^{inline.SEARCH_BEGIN}$")
    )
    app.add_handler(
        CallbackQueryHandler(browse.on_pick, pattern=f"^{inline.POPULAR_PICK}:")
    )
    app.add_handler(
        CallbackQueryHandler(
            browse.on_popular_page, pattern=f"^{inline.POPULAR_PAGE}:"
        )
    )
    app.add_handler(
        CallbackQueryHandler(search.on_hint_skip, pattern=f"^{inline.HINT_SKIP}$")
    )
    app.add_handler(
        CallbackQueryHandler(search.on_similar_play, pattern=f"^{inline.SIM_PLAY}:")
    )
    # پلهٔ دوم: یافته‌های تارنماها. داوری کاربر بر پیش‌نمایش
    # سی‌ثانیه‌ای، و فهرست نوشتاری که تنها راه فروافتادن است.
    app.add_handler(
        CallbackQueryHandler(websearch.on_preview_yes, pattern=f"^{inline.SITE_OK}:")
    )
    app.add_handler(
        CallbackQueryHandler(websearch.on_preview_no, pattern=f"^{inline.SITE_NO}:")
    )
    app.add_handler(
        CallbackQueryHandler(websearch.on_pick, pattern=f"^{inline.SITE_PICK}:")
    )
    app.add_handler(
        CallbackQueryHandler(websearch.on_cancel, pattern=f"^{inline.SITE_CANCEL}$")
    )
    app.add_handler(
        CallbackQueryHandler(curation.on_fill_tap, pattern=f"^{inline.FAIL_FILL}:")
    )
    app.add_handler(
        CallbackQueryHandler(curation.on_bulk_end_tap, pattern=f"^{inline.BULK_END}$")
    )

    # ── دفتر پذیرش ─────────────────────────────────────────
    app.add_handler(CallbackQueryHandler(intake.on_confirm, pattern=f"^{inline.IN_OK}:"))
    app.add_handler(CallbackQueryHandler(intake.on_drop, pattern=f"^{inline.IN_NO}:"))
    # غربالِ پیش از پرسش‌ها: «این را از پیش داریم، درست است؟»
    app.add_handler(CallbackQueryHandler(intake.on_screen_dup, pattern=f"^{inline.IN_DUP}:"))
    app.add_handler(CallbackQueryHandler(intake.on_screen_new, pattern=f"^{inline.IN_NEW}:"))
    app.add_handler(CallbackQueryHandler(intake.on_edit, pattern=f"^{inline.IN_EDIT}:"))
    app.add_handler(CallbackQueryHandler(intake.on_field, pattern=f"^{inline.IN_FIELD}:"))
    app.add_handler(CallbackQueryHandler(intake.on_back, pattern=f"^{inline.IN_BACK}:"))
    app.add_handler(
        CallbackQueryHandler(intake.on_style_tap, pattern=f"^{inline.IN_STYLE}:")
    )
    app.add_handler(
        CallbackQueryHandler(intake.on_skip_title, pattern=f"^{inline.IN_SKIP}:")
    )
    app.add_handler(
        CallbackQueryHandler(archive.on_forward_add, pattern=f"^{inline.ARC_ADD}$")
    )
    app.add_handler(
        CallbackQueryHandler(archive.on_forward_seek, pattern=f"^{inline.ARC_SEEK}$")
    )
    app.add_handler(
        CallbackQueryHandler(curation.on_delete_pick, pattern=f"^{inline.DEL_PICK}:")
    )
    app.add_handler(
        CallbackQueryHandler(curation.on_delete_confirm, pattern=f"^{inline.DEL_YES}:")
    )
    app.add_handler(
        CallbackQueryHandler(curation.on_delete_cancel, pattern=f"^{inline.DEL_CANCEL}$")
    )

    # ── ویرایش و حذف، از زیر خودِ فایل در گروه بایگانی ──────
    app.add_handler(
        CallbackQueryHandler(curation.on_ornate_edit, pattern=f"^{inline.ORN_EDIT}:")
    )
    app.add_handler(
        CallbackQueryHandler(curation.on_ornate_field, pattern=f"^{inline.ORN_FIELD}:")
    )
    app.add_handler(
        CallbackQueryHandler(curation.on_ornate_back, pattern=f"^{inline.ORN_BACK}:")
    )
    app.add_handler(
        CallbackQueryHandler(curation.on_ornate_delete, pattern=f"^{inline.ORN_DEL}:")
    )
    app.add_handler(
        CallbackQueryHandler(
            curation.on_ornate_delete_yes, pattern=f"^{inline.ORN_YES}:"
        )
    )

    # ── دکمه‌های منو — پیش از گردانندهٔ وضعیت ───────────────
    app.add_handler(MessageHandler(private & _exact("menu_help"), menu.show_help))
    app.add_handler(MessageHandler(private & _exact("menu_tokens"), _tokens))
    app.add_handler(MessageHandler(private & _exact("menu_submit"), submission.begin))
    app.add_handler(MessageHandler(private & _exact("menu_feedback"), feedback.begin))
    app.add_handler(MessageHandler(private & _exact("menu_search"), search.begin))
    app.add_handler(
        MessageHandler(private & _exact("menu_popular"), browse.show_popular)
    )
    app.add_handler(
        MessageHandler(private & _exact("menu_madahs"), browse.show_madahs)
    )
    app.add_handler(MessageHandler(private & _exact("cancel"), menu.cancel))

    # ── حالت درون‌خطی ───────────────────────────────────────
    # نیرومندترین اهرم گسترش: کاربر در هر گفتگویی نام مداحی را
    # می‌نویسد و نتیجه را همان‌جا می‌فرستد؛ هر بازفرست، همراه تازه
    # می‌آورد — و چون هم‌نشینی شرط است، هم‌نشین تازه.
    app.add_handler(InlineQueryHandler(inline_query.on_inline_query))

    # ── کانال‌های منبع: هر نوای تازه خودکار نمایه شود ───────
    #
    # پالایه **در جا تغییرپذیر** است و در ماژول نگه داشته می‌شود.
    # پیش‌تر یک بار از config ساخته می‌شد و کانالی که در زمان اجرا
    # افزوده می‌شد هیچ پیامی نمی‌گرفت — نه خصوصی بود، نه گروه، نه
    # کانال مخزن، پس به‌آرامی از ته زنجیرهٔ گردانندگان می‌افتاد.
    #
    # شرطِ `if config.archive_channel_id` هم برداشته شد: با .env
    # تهی، گرداننده اصلاً ثبت نمی‌شد و فهرست پایگاه داده هرگز
    # شنیده نمی‌شد.
    global _source_filter
    _source_filter = filters.Chat(chat_id=[])
    if config.archive_channel_id:
        _source_filter.add_chat_ids(config.archive_channel_id)
    try:
        from core.db import channels as channel_store

        for chat_id in channel_store.ids(channel_store.SOURCE):
            _source_filter.add_chat_ids(chat_id)
    except Exception:  # noqa: BLE001
        logger.exception("خواندن کانال‌های منبع هنگام راه‌اندازی نشد.")

    # سند و آوا هم شنیده می‌شوند، نه تنها «صوت».
    #
    # بسیاری از کانال‌های مداحی فایل را به‌شکل **سند** می‌گذارند؛
    # تلگرام آنگاه `message.audio` نمی‌سازد و پیش‌تر همان پست‌ها
    # یکسره از کنار گوش ربات می‌گذشتند. `archive._audio_of` خودش
    # سندِ ناصوتی را پس می‌زند.
    app.add_handler(
        MessageHandler(
            _source_filter & (filters.AUDIO | filters.VOICE | filters.Document.ALL),
            archive.on_channel_post,
        )
    )

    # ── پیام‌های گروه ───────────────────────────────────────
    app.add_handler(
        MessageHandler(groups & ~filters.COMMAND & ~filters.StatusUpdate.ALL, _on_group_message)
    )

    # ── هر چیز دیگر در گفتگوی خصوصی ─────────────────────────
    app.add_handler(
        MessageHandler(
            private & ~filters.COMMAND & ~filters.StatusUpdate.ALL,
            _on_private_text_or_media,
        )
    )

    logger.info("گردانندگان ثبت شدند.")


async def _cancel(update, context) -> None:
    """
    `/cancel` — هر جا و در هر وضعی.

    پذیرش نخست سنجیده می‌شود چون پیامِ پایانش گویاتر است: می‌گوید
    چند نوا نیمه‌کاره ماند.
    """
    if await intake.cancel(update, context):
        return
    message = update.effective_message
    if message is not None and message.chat.type != "private":
        states.clear_state(context.user_data)
        await message.reply_html(texts.msg("cancelled"))
        return
    await menu.cancel(update, context)


async def _tokens(update, context) -> None:
    from bot.handlers import tokens

    await tokens.show_balance(update, context)
