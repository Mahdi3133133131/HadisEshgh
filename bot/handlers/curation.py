"""
کارهای گردانندگان در گروه مداحی — افزودن انبوه و پر کردن ناکامی‌ها.

دو جریان جدا که هر دو در همان گروه می‌گذرند و هر دو از یک نیاز
برخاسته‌اند: گنجینه باید پر شود، و پر شدنش نباید کار سختی باشد.

## ۱ — افزودن انبوه (`/bulk`)

گرداننده یک‌بار فرمان می‌دهد و از آن پس هر نوایی که در گروه بگذارد
گرفته می‌شود. **به هیچ فایلی جداگانه پاسخ داده نمی‌شود**؛ تنها یک
پیام شمارشگر ویرایش می‌شود. اگر به هر فایل پاسخ می‌دادیم، افزودن
پنجاه نوا یعنی پنجاه پیام ربات در گروه — و کسی دیگر آن گروه را
نمی‌خواند.

## ۲ — برداشتن نوا (`/delete`)

تنها در همین گروه و تنها به دست گردانندگان. جست‌وجو با نام، برگزیدن
از فهرست، و یک پرسش واپسین — چون برداشتن برگشت‌ناپذیر است و نامِ
نواها به هم می‌مانند.

## ۳ — پر کردن بازجویی ناکام

هر بازجویی ناکام با خودِ کلیپِ کاربر به این گروه می‌آید، با دکمه‌ای
که می‌گوید «نسخهٔ کامل را می‌فرستم». گرداننده می‌نوازد، نوا را
می‌فرستد، مداح و سبک و نام را می‌گوید، و ربات هم آن را به گنجینه
می‌افزاید و هم برای همان جویندهٔ نخست می‌فرستد.

**قفل اتمی و مهلت‌دار** دارد، به همان دو دلیلی که قفل پاسخ‌گویی
داشت: اگر دو گرداننده هم‌زمان بنوازند نباید هر دو بگیرند (وگرنه
کاربر یک نوا را دوبار می‌گیرد)، و اگر یکی دکمه را زد و رفت نباید
آن بازجویی برای همیشه قفل بماند.
"""

from __future__ import annotations

import logging
import time

from telegram import Update
from telegram.error import TelegramError
from telegram.ext import ContextTypes

from bot.guards import admin_only
from bot.keyboards import inline
from bot.states import (
    AWAITING_BULK_AUDIO,
    AWAITING_DELETE_QUERY,
    AWAITING_FILL_AUDIO,
    AWAITING_TRACK_EDIT,
    clear_state,
    get_data,
    set_state,
)
from config import config
from core import texts
from core.db import database, searches
from core.normalize import clean_tag, fix_characters, to_persian_digits

logger = logging.getLogger(__name__)

# پیام شمارشگر دست‌کم این اندازه فاصله میان دو ویرایش داشته باشد.
# تلگرام ویرایش پیاپی را می‌بندد و افزودن انبوه، پیاپی‌ترین کاری
# است که این ربات می‌کند.
_EDIT_EVERY_SECONDS = 3.0

# نوشتاری که گرداننده برای گذشتن از نام می‌فرستد
_SKIP_WORDS = {"-", "—", "ندارد", "نمی‌دانم", "نمیدانم"}


def _fa(value: object) -> str:
    return to_persian_digits(str(value))


# ═════════════════════════════════════════════════════════════
#  افزودن انبوه
# ═════════════════════════════════════════════════════════════

def _from_tags(audio) -> dict:
    """
    نام مداح و اسم مداحی، از برچسب خودِ فایل.

    `Document` این خانه‌ها را ندارد، پس getattr با پیش‌فرض.
    مقدارِ پوچ (Unknown، نامِ پرونده، …) None می‌شود تا کارت
    «—» نشان دهد نه زباله.
    """
    return {
        "madah": clean_tag(getattr(audio, "performer", None), 120),
        "title": clean_tag(getattr(audio, "title", None), 200),
    }


@admin_only
async def begin_bulk(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    `/bulk` یا `/bulk نام مداح` — آغاز افزودن انبوه.

    نام مداحِ اختیاری برای همهٔ نواهای این دسته به کار می‌رود؛ چون
    معمولاً یک دسته، آلبوم یا مجلس یک مداح است و نوشتنش برای هر
    فایل، همان کاری است که این فرمان می‌خواست از آن بگریزد.
    """
    message = update.effective_message
    if message is None:
        return

    # در هر دو گروهِ کاری، ولی نه در گفتگوی خصوصی.
    #
    # ## چرا هر دو گروه
    #
    # پیش‌تر تنها گروه بایگانی روا بود، تا پرسش‌های پیاپیِ پذیرش با
    # داوری پیشکش‌ها قاطی نشود. ولی این یعنی تنها **یک نفر در یک
    # زمان** می‌توانست ثبت کند. با دو گروه، دو گرداننده هم‌زمان
    # کار می‌کنند و کارِ دسته‌های بزرگ دو برابر پیش می‌رود.
    #
    # تداخلی هم پیش نمی‌آید: وضعیتِ پذیرش در `user_data` است —
    # برای هر گرداننده جدا — و `_mine()` گفتگو را هم می‌سنجد، پس
    # پیامِ یکی به جریانِ دیگری نمی‌رود.
    #
    # گفتگوی خصوصی همچنان بسته است: آنجا وضعیتِ انبوه با جریان
    # جست‌وجو درمی‌آمیزد و آوایی که گرداننده برای **یافتن**
    # می‌فرستد، به چشم «فایل دسته» می‌آید.
    workrooms = {config.ornate_target, config.madahi_group_id}
    workrooms.discard(0)
    workrooms.discard(None)
    if message.chat_id not in workrooms:
        await message.reply_html(texts.msg("bulk_group_only"))
        return

    madah = " ".join(context.args).strip() if context.args else ""
    madah = fix_characters(madah)[:120] if madah else None

    set_state(
        context.user_data,
        AWAITING_BULK_AUDIO,
        madah=madah,
        added=0,
        duplicate=0,
        items=[],
        status_msg_id=None,
        last_edit=0.0,
        chat_id=message.chat_id,
    )
    _keep_bulk(context, message.chat_id, get_data(context.user_data))

    madah_line = (
        texts.msg("bulk_madah_line", madah=madah) if madah else ""
    )
    sent = await message.reply_html(
        texts.msg("bulk_started", madah_line=madah_line),
        reply_markup=inline.bulk_finish(),
    )
    get_data(context.user_data)["status_msg_id"] = sent.message_id
    _mark_transient(message.chat_id, sent.message_id)
    # خودِ فرمانِ `/bulk` هم گذراست.
    _mark_transient(message.chat_id, message.message_id)
    logger.info("افزودن انبوه آغاز شد (مداح دسته: %s).", madah or "—")


def _mark_transient(chat_id, message_id, kind: str = "bulk") -> None:
    """
    پیامی گذرا را برای پاک‌سازیِ بعدی نشان می‌کند.

    اینجا **پیامِ خودِ گرداننده** هم نشان می‌شود، نه فقط پیام‌های
    ربات: خواستهٔ روشن این بود که پس از پایانِ کار، صوت‌هایی که
    گردانندگان فرستاده‌اند هم برداشته شوند و تنها نسخهٔ آراسته
    بماند. ربات در گروه گرداننده است و می‌تواند پیامِ دیگران را
    بردارد — تا ۴۸ ساعت، که مرزِ خودِ تلگرام است.
    """
    if not chat_id or not message_id:
        return
    try:
        from core.db import bot_messages

        bot_messages.remember(int(chat_id), int(message_id), kind)
    except Exception:  # noqa: BLE001
        logger.debug("نشان‌کردنِ پیامِ گذرا نشد.", exc_info=True)


async def on_bulk_audio(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    نوایی که گرداننده در حالت انبوه فرستاده است.

    **اینجا چیزی در گنجینه نمی‌نشیند.** فایل‌ها تنها گردآوری
    می‌شوند؛ پس از «پایان افزودن»، دفتر پذیرش یکی‌یکی شناسنامهٔ
    هرکدام را می‌پرسد و تا تأیید نگیرد نمی‌نشاندشان.

    چرا این ترتیب: پیش‌تر شناسنامه از برچسب ID3 برداشته می‌شد، و
    آن برچسب معمولاً یا تهی است یا چیزی مانند `voice_0032`. همان
    نام، هم روی نسخهٔ آراسته می‌نشست و هم کلید یافتن نوا می‌شد.
    """
    message = update.effective_message
    if message is None or message.audio is None:
        return

    data = get_data(context.user_data)
    audio = message.audio

    duplicate = database.find_duplicate_track(file_unique_id=audio.file_unique_id)
    if duplicate is not None:
        data["duplicate"] = int(data.get("duplicate", 0)) + 1
    else:
        items = data.setdefault("items", [])
        # همان فایل، دوبار در یک دسته: تلگرام گاه پیام را دوباره
        # می‌رساند و شمارشگر بی این سنجش دروغ می‌گفت.
        if not any(i["file_unique_id"] == audio.file_unique_id for i in items):
            items.append(
                {
                    "file_id": audio.file_id,
                    "file_unique_id": audio.file_unique_id,
                    "file_name": audio.title or audio.file_name,
                    # شناسنامه از خودِ برچسب فایل. تلگرام آن را با
                    # پیام می‌آورد، پس نه فرو گرفتنی لازم است و نه
                    # پرسشی از گرداننده.
                    **_from_tags(audio),
                    "duration": audio.duration,
                    "file_size": audio.file_size,
                    "source_chat_id": message.chat_id,
                    "source_msg_id": message.message_id,
                }
            )
            data["added"] = int(data.get("added", 0)) + 1

    # صوتی که گرداننده فرستاد، خودش گذراست: نسخهٔ آراسته پس از
    # پذیرش جایش را می‌گیرد و ماندنِ هر دو، گروه را دوبرابر شلوغ
    # می‌کند.
    _mark_transient(message.chat_id, message.message_id, "bulk_audio")

    data["last_file"] = time.time()
    _keep_bulk(context, message.chat_id, data)
    await _refresh_bulk_status(context, message.chat_id, data)


def _keep_bulk(context, chat_id: int, data: dict) -> None:
    """
    گردآوریِ نیمه‌کاره را در پایگاه می‌نشاند.

    ## چرا این هست

    `user_data` در حافظه است و بس — هیچ `persistence` روی
    برنامه سوار نیست. پس هر بار که ربات از نو بالا می‌آمد،
    فایل‌هایی که گرداننده فرستاده بود و هنوز `/bulk_end` نزده
    بود، یکسره گم می‌شدند. همان «یادش می‌ره مداحی‌ها رو».

    اکنون پس از **هر فایل** نوشته می‌شود؛ راه‌اندازیِ دوباره
    دست‌بالا یک فایل را می‌بَرد، نه همهٔ دسته را.
    """
    try:
        from core.db import intake_sessions

        intake_sessions.ensure_table()
        payload = dict(data)
        payload["chat_id"] = int(chat_id)
        payload["_state"] = AWAITING_BULK_AUDIO
        intake_sessions.save(int(chat_id), payload)
        intake_sessions.touch(int(chat_id))
    except Exception:  # noqa: BLE001
        logger.debug("نگه‌داشتنِ گردآوریِ انبوه نشد.", exc_info=True)


# چند ثانیه بی‌کاری، حالتِ بارگذاری را کهنه می‌کند.
#
# ## چرا این نگهبان لازم شد
#
# `/upload` حالتی است که تا `/done` روشن می‌مانَد، و تا روشن
# است **هر** آوایی که در گفتگوی خصوصی برسد به‌جای جست‌وجو به
# صفِ بارگذاری می‌رود. کسی که `/done` را فراموش کند، فردا
# کلیپی برای **یافتن** می‌فرستد و آن کلیپ خاموش در صف
# می‌نشیند و سپس بی داوری در گنجینه ثبت می‌شود.
#
# پانزده دقیقه بی‌کاری یعنی کار تمام شده. آنگاه حالت بسته
# می‌شود و آوا همان جست‌وجوی همیشگی را می‌گیرد.
UPLOAD_IDLE_LIMIT = 900


def bulk_is_stale(user_data) -> bool:
    """آیا حالتِ بارگذاری آن‌قدر بی‌کار مانده که باید بسته شود."""
    from bot import states

    if states.get_state(user_data) != AWAITING_BULK_AUDIO:
        return False
    data = get_data(user_data)
    last = float(data.get("last_file") or 0.0)
    if not last:
        return False
    return (time.time() - last) > UPLOAD_IDLE_LIMIT


def _recover_bulk(chat_id: int) -> dict | None:
    """گردآوریِ گم‌شده را از پایگاه بازمی‌گرداند."""
    try:
        from core.db import intake_sessions

        intake_sessions.ensure_table()
        saved = intake_sessions.load(int(chat_id))
    except Exception:  # noqa: BLE001
        logger.debug("بازگرداندنِ گردآوریِ انبوه نشد.", exc_info=True)
        return None
    if not saved or saved.get("_state") != AWAITING_BULK_AUDIO:
        return None
    if not saved.get("items"):
        return None
    logger.info(
        "گردآوریِ گفتگوی %s از پایگاه بازگردانده شد (%s نوا).",
        chat_id, len(saved["items"]),
    )
    return saved


async def _refresh_bulk_status(context, chat_id: int, data: dict) -> None:
    """
    شمارشگر را تازه می‌کند، ولی نه بیش از یک بار در چند ثانیه.

    بی این مهار، افزودن پنجاه نوای پشت سر هم یعنی پنجاه ویرایش در
    چند ثانیه، و تلگرام همان را می‌بندد.
    """
    now = time.monotonic()
    if now - float(data.get("last_edit", 0.0)) < _EDIT_EVERY_SECONDS:
        return
    data["last_edit"] = now

    message_id = data.get("status_msg_id")
    if not message_id:
        return

    try:
        await context.bot.edit_message_text(
            chat_id=chat_id,
            message_id=message_id,
            text=texts.msg(
                "bulk_progress",
                added=_fa(data.get("added", 0)),
                duplicate=_fa(data.get("duplicate", 0)),
            ),
            parse_mode="HTML",
            reply_markup=inline.bulk_finish(),
        )
    except TelegramError:
        # ویرایش نشدن شمارشگر، افزودن را نمی‌شکند
        pass


async def begin_upload(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    `/upload` — بارگذاری دسته‌ای برای همراهِ مورد اعتماد.

    ## چرا فرمانی جدا، و نه همان `/bulk`

    در گفتگوی خصوصی، آوا **پرسشِ جست‌وجو** است. اگر بی‌خبر حالتِ
    دسته روشن می‌شد، آوایی که کسی برای *یافتن* می‌فرستد به چشم
    «فایلِ دسته» می‌آمد. پس روشن‌کردنش باید صریح باشد، و
    `/done` هم صریح خاموشش کند.
    """
    message = update.effective_message
    user = update.effective_user
    if message is None or user is None:
        return
    if message.chat.type != "private":
        await message.reply_html(texts.msg("upload_private_only"))
        return
    if not (config.is_admin(user.id) or database.is_trusted(user.id)):
        await message.reply_html(texts.msg("upload_trusted_only"))
        return

    madah = " ".join(context.args).strip() if context.args else ""
    madah = fix_characters(madah)[:120] if madah else None

    set_state(
        context.user_data,
        AWAITING_BULK_AUDIO,
        madah=madah,
        added=0,
        duplicate=0,
        items=[],
        status_msg_id=None,
        last_edit=0.0,
        chat_id=message.chat_id,
        trusted_batch=True,
    )
    _keep_bulk(context, message.chat_id, get_data(context.user_data))
    await message.reply_html(texts.msg("upload_started"))


async def end_upload(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    `/done` — پایانِ بارگذاری دسته‌ای همراه.

    جدا از `/bulk_end` است چون آن `@admin_only` است و این باید
    برای همراهِ مورد اعتماد هم کار کند.
    """
    message = update.effective_message
    if message is None:
        return
    if message.chat.type != "private":
        return
    await _finish_bulk(context, message.chat_id, context.user_data, message)


@admin_only
async def end_bulk(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """`/bulk_end` — پایان دادن به افزودن انبوه."""
    message = update.effective_message
    if message is None:
        return
    await _finish_bulk(context, message.chat_id, context.user_data, message)


async def on_bulk_end_tap(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """دکمهٔ «پایان افزودن»."""
    query = update.callback_query
    admin = update.effective_user
    if query is None:
        return
    if admin is None or query.message is None:
        await _ack(query)
        return
    if not config.is_admin(admin.id):
        await query.answer(texts.msg("admin_only"), show_alert=True)
        return

    await query.answer()
    try:
        await query.edit_message_reply_markup(reply_markup=None)
    except TelegramError:
        pass
    await _finish_bulk(context, query.message.chat_id, context.user_data, query.message)


async def _finish_bulk(context, chat_id: int, user_data, message) -> None:
    from bot import states
    from bot.handlers import intake

    if states.get_state(user_data) != AWAITING_BULK_AUDIO:
        # شاید ربات میانِ گردآوری از نو بالا آمده و حافظه‌اش رفته؛
        # پیش از گفتنِ «چیزی در جریان نیست»، پایگاه را می‌پرسیم.
        saved = _recover_bulk(chat_id)
        if saved is None:
            await message.reply_html(texts.msg("bulk_not_running"))
            return
        data = saved
    else:
        data = dict(get_data(user_data))
    clear_state(user_data)

    items = list(data.get("items", []))
    duplicate = int(data.get("duplicate", 0))

    if not items and not duplicate:
        await message.reply_html(texts.msg("bulk_none"))
        return

    await message.reply_html(
        texts.msg("bulk_finished", added=_fa(len(items)), duplicate=_fa(duplicate))
    )
    logger.info(
        "گردآوری انبوه پایان یافت: %s نوا برای پذیرش، %s تکراری.",
        len(items), duplicate,
    )

    if not items:
        return

    if data.get("trusted_batch"):
        # همراهِ مورد اعتماد: بی پرسش می‌نشیند، هر نوا یک سکه.
        from bot.handlers import submission

        user = message.from_user
        if user is None:
            return
        batch_madah = data.get("madah")
        if batch_madah:
            for item in items:
                item.setdefault("madah", None)
                if not item.get("madah"):
                    item["madah"] = batch_madah
        await submission.accept_batch(context, chat_id, user, items)
        return

    await intake.start(context, chat_id, items, batch_madah=data.get("madah"))


# ═════════════════════════════════════════════════════════════
#  پر کردن بازجویی ناکام
# ═════════════════════════════════════════════════════════════

async def on_fill_tap(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """گرداننده می‌گوید نسخهٔ کامل را دارد."""
    query = update.callback_query
    admin = update.effective_user
    if query is None:
        return
    if admin is None or not query.data or query.message is None:
        await _ack(query)
        return

    if not config.is_admin(admin.id):
        await query.answer(texts.msg("admin_only"), show_alert=True)
        return

    try:
        search_id = int(query.data.rpartition(":")[2])
    except ValueError:
        await query.answer()
        return

    record = searches.get(search_id)
    if record is None:
        await query.answer("این بازجویی دیگر در دفتر نیست.", show_alert=True)
        return

    if record["status"] == "fulfilled":
        await query.answer(texts.msg("fill_already_done"), show_alert=True)
        return

    acquired, _ = searches.try_acquire_fill(
        search_id, admin.id, config.admin_reply_lock_timeout
    )
    if not acquired:
        await query.answer(texts.msg("fill_locked"), show_alert=True)
        return

    set_state(context.user_data, AWAITING_FILL_AUDIO, search_id=search_id)
    await query.answer("بر عهدهٔ شماست. 📤")
    await context.bot.send_message(
        chat_id=query.message.chat_id,
        text=texts.msg(
            "fill_ask_audio",
            admin=admin.full_name,
            minutes=_fa(config.admin_reply_lock_timeout // 60),
        ),
        parse_mode="HTML",
        reply_to_message_id=query.message.message_id,
    )
    logger.info("گرداننده %s پرکردن بازجویی %s را بر عهده گرفت.", admin.id, search_id)


async def on_fill_audio(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    نوایی که گرداننده برای پر کردن ناکامی فرستاد.

    از اینجا به بعد کار با دفتر پذیرش است: همان پرسش‌ها، همان
    کارت شناسنامه، و همان دکمهٔ ویرایش. تنها فرقش این است که
    شمارهٔ بازجویی همراه نوا می‌رود، تا پس از تأیید، نوا برای
    جویندهٔ نخست هم فرستاده شود.
    """
    from bot.handlers import intake

    message = update.effective_message
    admin = update.effective_user
    if message is None or admin is None:
        return

    audio = message.audio or message.document
    if audio is None:
        await message.reply_html(texts.msg("submit_only_audio"))
        return

    data = get_data(context.user_data)

    # قفل شاید در این میان سر آمده و به گردانندهٔ دیگری رسیده باشد.
    # بی این سنجش، دو نفر همان نوا را برای کاربر می‌فرستادند.
    search_id = data.get("search_id")
    if search_id and searches.current_fill_holder(int(search_id)) not in (admin.id, None):
        clear_state(context.user_data)
        await message.reply_html(texts.msg("fill_locked"))
        return

    await intake.start(
        context,
        message.chat_id,
        [
            {
                "file_id": audio.file_id,
                "file_unique_id": audio.file_unique_id,
                # نامِ درونِ فایل پیش از نام پرونده — همان ترتیبی
                # که دو مسیر دیگرِ پذیرش دارند. اینجا از قلم افتاده
                # بود و گرداننده به جای «شور محرم» چیزی مانند
                # voice_0032 می‌دید.
                "file_name": getattr(audio, "title", None)
                or getattr(audio, "file_name", None),
                **_from_tags(audio),
                "duration": getattr(audio, "duration", None),
                "file_size": getattr(audio, "file_size", None),
                "source_chat_id": message.chat_id,
                "source_msg_id": message.message_id,
                "search_id": int(search_id) if search_id else None,
            }
        ],
    )


# ═════════════════════════════════════════════════════════════
#  اعتماد، از راه فرمان
# ═════════════════════════════════════════════════════════════

@admin_only
async def trust(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """`/trust <شناسه>` — پیشکش این همراه دیگر داوری نمی‌خواهد."""
    await _set_trust(update, context, True)


@admin_only
async def untrust(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """`/untrust <شناسه>` — اعتماد را پس می‌گیرد."""
    await _set_trust(update, context, False)


async def _set_trust(update: Update, context, trusted: bool) -> None:
    message = update.effective_message
    admin = update.effective_user
    if message is None or admin is None:
        return

    if not context.args:
        await message.reply_html(
            "🌿 شناسهٔ عددی همراه را بنویسید:\n"
            "<code>/trust 123456789</code>\n\n"
            "<i>یا آسان‌تر: زیر پیشکش او در همین گروه، دکمهٔ «🤝 اعتماد» را بنوازید.</i>"
        )
        return

    try:
        user_id = int(context.args[0])
    except ValueError:
        await message.reply_html("🌿 شناسه باید عدد باشد.")
        return

    user_row = database.get_user(user_id)
    if user_row is None:
        await message.reply_html("🌿 چنین همراهی در دفتر نیست؛ نخست باید /start بزند.")
        return

    name = user_row["first_name"] or str(user_id)
    database.set_trusted(user_id, trusted, by_admin=admin.id if trusted else None)

    key = "trusted_granted" if trusted else "trusted_revoked"
    await message.reply_html(texts.msg(key, name=name))

    if trusted:
        try:
            await context.bot.send_message(
                chat_id=user_id,
                text=texts.msg("trusted_user_notice"),
                parse_mode="HTML",
            )
        except TelegramError:
            pass

    logger.info(
        "اعتماد به کاربر %s %s (به دست %s).",
        user_id, "داده شد" if trusted else "پس گرفته شد", admin.id,
    )


@admin_only
async def trusted_list(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """`/trusted` — فهرست همراهان مورد اعتماد."""
    message = update.effective_message
    if message is None:
        return

    rows = database.list_trusted()
    if not rows:
        await message.reply_html(
            "🌿 هنوز به کسی اعتماد نشده است.\n\n"
            "<i>برای اعتماد، زیر پیشکش هر همراه دکمهٔ «🤝 اعتماد» را بنوازید"
            " یا <code>/trust شناسه</code> بفرستید.</i>"
        )
        return

    lines = ["🤝 <b>همراهان مورد اعتماد</b>", ""]
    for row in rows:
        name = row["first_name"] or row["username"] or str(row["user_id"])
        since = (row["trusted_at"] or "")[:10]
        lines.append(f"• {name} — <code>{row['user_id']}</code> — {since}")
    lines += [
        "",
        "<i>پیشکش این همراهان بی داوری به گنجینه می‌رود؛ ولی سنجش"
        " تکراری همچنان بر آن‌ها هم روا می‌شود.</i>",
    ]
    await message.reply_html("\n".join(lines))


# ═════════════════════════════════════════════════════════════
#  برداشتن نوا از گنجینه
# ═════════════════════════════════════════════════════════════

# بیشترین نوایی که در فهرست برگزیدن نشان داده می‌شود. بیش از این،
# پیام دراز می‌شود و برگزیدن سخت‌تر — نه آسان‌تر.
_MAX_CANDIDATES = 8


@admin_only
async def begin_delete(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    `/delete` — آغاز برداشتن نوا.

    تنها در گروه مداحی. در گفتگوی خصوصی، وضعیتِ برداشتن با جریان
    بازجویی درمی‌آمیزد: نامی که گرداننده برای جستن می‌نویسد به چشم
    «نوایی که می‌خواهم بردارم» می‌آمد — و یک نواخت، نوایی را از
    گنجینه می‌برد.
    """
    message = update.effective_message
    if message is None:
        return

    if message.chat_id != config.ornate_target:
        await message.reply_html(texts.msg("delete_group_only"))
        return

    # اگر نام را همراه فرمان نوشته باشد، یک گام کمتر
    term = " ".join(context.args).strip() if context.args else ""
    if term:
        await _show_candidates(message, context, term)
        return

    set_state(context.user_data, AWAITING_DELETE_QUERY)
    await message.reply_html(texts.msg("delete_ask_name"))


async def on_delete_query(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """نامی که گرداننده برای یافتن نوا نوشت."""
    message = update.effective_message
    if message is None or not message.text:
        return
    clear_state(context.user_data)
    await _show_candidates(message, context, message.text.strip())


async def _show_candidates(message, context, term: str) -> None:
    rows = database.search_tracks_by_text(term, limit=_MAX_CANDIDATES)
    if not rows:
        await message.reply_html(texts.msg("delete_none", term=term))
        return

    await message.reply_html(
        texts.msg("delete_pick", term=term, count=_fa(len(rows))),
        reply_markup=inline.delete_candidates(rows),
    )


async def on_delete_pick(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """گرداننده نوایی را برگزید؛ پرسش واپسین."""
    query = update.callback_query
    admin = update.effective_user
    if query is None:
        return
    if admin is None or not query.data:
        await _ack(query)
        return
    if not config.is_admin(admin.id):
        await query.answer(texts.msg("admin_only"), show_alert=True)
        return

    try:
        track_id = int(query.data.rpartition(":")[2])
    except ValueError:
        await query.answer()
        return

    track = database.get_track(track_id)
    if track is None:
        await query.answer(texts.msg("delete_gone"), show_alert=True)
        return

    from core.db import fingerprints as fp_store
    from core.normalize import format_duration

    await query.answer()
    try:
        await query.edit_message_text(
            texts.msg(
                "delete_confirm",
                track_id=str(track_id),
                madah=track["madah"] or "نامعلوم",
                style=track["style"] or "—",
                title=track["title"] or "بی‌نام",
                duration=format_duration(track["duration"]),
                hashes=_fa(f"{fp_store.count_for_track(track_id):,}"),
            ),
            parse_mode="HTML",
            reply_markup=inline.delete_confirm(track_id),
        )
    except TelegramError as exc:
        logger.debug("نمایش پرسش برداشتن نشد: %s", exc)


async def on_delete_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """برداشتن، پس از تأیید."""
    query = update.callback_query
    admin = update.effective_user
    if query is None:
        return
    if admin is None or not query.data:
        await _ack(query)
        return
    if not config.is_admin(admin.id):
        await query.answer(texts.msg("admin_only"), show_alert=True)
        return

    try:
        track_id = int(query.data.rpartition(":")[2])
    except ValueError:
        await query.answer()
        return

    track = database.get_track(track_id)
    if track is None:
        await query.answer(texts.msg("delete_gone"), show_alert=True)
        return

    label = texts.escape(f"{track['madah'] or 'نامعلوم'} — {track['title'] or 'بی‌نام'}")
    removed = database.remove_track(track_id)

    await query.answer("برداشته شد." if removed else "پیش‌تر برداشته شده بود.")
    try:
        await query.edit_message_text(
            texts.msg("delete_done", label=label, admin=admin.full_name),
            parse_mode="HTML",
        )
    except TelegramError:
        pass

    logger.info(
        "نوای %s (%s) به دست گرداننده %s برداشته شد.", track_id, label, admin.id
    )


async def on_delete_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query is None:
        return
    clear_state(context.user_data)
    await query.answer()
    try:
        await query.edit_message_text(texts.msg("cancelled"), parse_mode="HTML")
    except TelegramError:
        pass


# ═════════════════════════════════════════════════════════════
#  گردانندگان — تنها به دست مالک
# ═════════════════════════════════════════════════════════════

def _owner_only(func):
    """
    تنها مالک می‌گذرد — نخستین شناسهٔ ADMIN_IDS در .env.

    اگر هر گرداننده‌ای می‌توانست گرداننده بیفزاید، اختیارِ مالک
    بی‌معنا می‌شد: یکی می‌افزود و همان تازه‌وارد، مالک را برمی‌داشت.
    """
    import functools

    @functools.wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        user = update.effective_user
        message = update.effective_message
        if user is None or not config.is_owner(user.id):
            if message is not None and config.is_admin(user.id if user else 0):
                # گردانندهٔ ساده دست‌کم بداند چرا نشد
                await message.reply_html(texts.msg("owner_only"))
            return None
        return await func(update, context)

    return wrapper


@_owner_only
async def add_admin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """`/addadmin <شناسه>` — گرداننده‌ای تازه."""
    await _set_admin(update, context, True)


@_owner_only
async def remove_admin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """`/deladmin <شناسه>` — پس گرفتن گردانندگی."""
    await _set_admin(update, context, False)


async def _set_admin(update: Update, context, grant: bool) -> None:
    message = update.effective_message
    owner = update.effective_user
    if message is None or owner is None:
        return

    if not context.args:
        await message.reply_html(texts.msg("admin_needs_id"))
        return

    try:
        user_id = int(context.args[0])
    except ValueError:
        await message.reply_html(texts.msg("admin_id_not_number"))
        return

    if config.is_owner(user_id):
        await message.reply_html(texts.msg("admin_is_owner"))
        return

    row = database.get_user(user_id)
    if row is None:
        await message.reply_html(texts.msg("admin_unknown_user"))
        return

    # شناسه‌های .env در پایگاه داده نیستند و برداشتنشان از آنجا
    # کاری نمی‌کند؛ باید روشن گفته شود، وگرنه مالک می‌پندارد انجام شد.
    if not grant and user_id in config.admin_ids:
        await message.reply_html(texts.msg("admin_in_env"))
        return

    database.set_db_admin(user_id, grant, by_owner=owner.id)
    name = row["first_name"] or str(user_id)
    await message.reply_html(
        texts.msg("admin_granted" if grant else "admin_revoked", name=name)
    )

    if grant:
        try:
            await context.bot.send_message(
                chat_id=user_id,
                text=texts.msg("admin_user_notice"),
                parse_mode="HTML",
            )
        except TelegramError:
            pass

    logger.info(
        "گردانندگی کاربر %s %s (به دست مالک %s).",
        user_id, "داده شد" if grant else "پس گرفته شد", owner.id,
    )


@admin_only
async def list_admins(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """`/admins` — چه کسانی گرداننده‌اند و از کجا."""
    message = update.effective_message
    if message is None:
        return

    lines = ["👥 <b>گردانندگان</b>", ""]
    for index, admin_id in enumerate(config.admin_ids):
        row = database.get_user(admin_id)
        name = (row["first_name"] if row else None) or "—"
        mark = " 👑 <i>مالک</i>" if index == 0 else ""
        lines.append(f"• <code>{admin_id}</code> — {name}{mark}")

    added = database.list_db_admins()
    if added:
        lines += ["", "<b>افزوده به دست مالک:</b>"]
        for row in added:
            name = row["first_name"] or row["username"] or "—"
            since = (row["admin_at"] or "")[:10]
            lines.append(f"• <code>{row['user_id']}</code> — {name}  <i>{since}</i>")

    lines += ["", "<i>افزودن و برداشتن، تنها از دست مالک برمی‌آید.</i>"]
    await message.reply_html("\n".join(lines))


# ═════════════════════════════════════════════════════════════
#  ویرایش و حذف، از زیر خودِ فایل در گروه بایگانی
#
#  ## چرا اینجا و نه در فرمانی جدا
#
#  ماه‌ها بعد، کسی بایگانی را ورق می‌زند و می‌بیند نام مداحِ یکی
#  غلط است. راه پیشین این بود که شمارهٔ نوا را از سرنویس بردارد،
#  /delete را به یاد بیاورد، و از نو بیفزاید. اکنون همان‌جا و با
#  یک نواخت.
#
#  ## و چرا ویرایش، فایل را هم از نو برچسب می‌زند
#
#  اگر تنها ردیف پایگاه داده درست می‌شد، فایلی که در تلگرام نشسته
#  همچنان نام غلط را با خود می‌برد — و همان فایل است که به دست
#  مردم می‌رسد، نه ردیف پایگاه داده.
# ═════════════════════════════════════════════════════════════

_TRACK_FIELDS = {
    "madah": "نام مداح",
    "style": "سبک مداحی",
    "title": "اسم مداحی",
}

_TRACK_LIMITS = {"madah": 120, "style": 40, "title": 200}


def _track_id_of(data: str) -> int | None:
    try:
        return int(data.split(":")[2])
    except (IndexError, ValueError):
        return None


async def _ack(query, text=None, alert=False) -> None:
    try:
        await query.answer(text, show_alert=alert)
    except TelegramError as exc:
        logger.debug("پاسخ نواخت نرسید: %s", exc)


async def _note_on_caption(query, note: str) -> None:
    """یادداشتی زیر سرنویس فایل می‌گذارد و دکمه‌ها را برمی‌دارد."""
    try:
        caption = getattr(query.message, "caption", None) or ""
        await query.edit_message_caption(
            caption=f"{caption}\n\n{note}".strip(),
            parse_mode="HTML",
            reply_markup=None,
        )
    except TelegramError as exc:
        logger.debug("نوشتن یادداشت بر سرنویس نشد: %s", exc)


async def _guard(update, context):
    """نوازنده باید گرداننده باشد و نوا باید هنوز باشد."""
    query = update.callback_query
    admin = update.effective_user
    if query is None:
        return None, None
    if admin is None or not query.data:
        await _ack(query)
        return None, None

    if not config.is_admin(admin.id):
        await _ack(query, texts.msg("admin_only"), alert=True)
        return None, None

    track_id = _track_id_of(query.data)
    if track_id is None:
        await _ack(query)
        return None, None

    track = database.get_track(track_id)
    if track is None:
        await _ack(query, texts.msg("delete_gone"), alert=True)
        return None, None
    return query, track


async def on_ornate_edit(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """«ویرایش» — سه بخش را پیش می‌گذارد."""
    query, track = await _guard(update, context)
    if query is None:
        return
    await _ack(query)
    try:
        await query.edit_message_reply_markup(
            reply_markup=inline.ornate_fields(int(track["id"]))
        )
    except TelegramError as exc:
        logger.debug("نمایش بخش‌های ویرایش نشد: %s", exc)


async def on_ornate_back(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """بازگشت به دو دکمهٔ نخست."""
    query, track = await _guard(update, context)
    if query is None:
        return
    clear_state(context.user_data)
    await _ack(query)
    try:
        await query.edit_message_reply_markup(
            reply_markup=inline.ornate_actions(int(track["id"]))
        )
    except TelegramError as exc:
        logger.debug("بازگشت به دکمه‌های نخست نشد: %s", exc)


async def on_ornate_field(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """بخشی برگزیده شد؛ اکنون مقدار تازه خواسته می‌شود."""
    query, track = await _guard(update, context)
    if query is None:
        return
    if query.message is None:
        await _ack(query)
        return

    field = query.data.split(":")[3] if len(query.data.split(":")) > 3 else ""
    if field not in _TRACK_FIELDS:
        await _ack(query)
        return

    set_state(
        context.user_data,
        AWAITING_TRACK_EDIT,
        track_id=int(track["id"]),
        field=field,
        chat_id=query.message.chat_id,
    )
    await _ack(query)
    await message_or_reply(
        context,
        query.message.chat_id,
        texts.msg(
            "track_edit_ask",
            field=_TRACK_FIELDS[field],
            current=track[field] or "—",
            track_id=str(track["id"]),
        ),
        reply_to=query.message.message_id,
    )


async def message_or_reply(context, chat_id: int, text: str, reply_to=None) -> None:
    from core import net

    try:
        await net.retry(
            lambda: context.bot.send_message(
                chat_id=chat_id,
                text=text,
                parse_mode="HTML",
                reply_to_message_id=reply_to,
            ),
            label="پرسش ویرایش نوا",
        )
    except TelegramError as exc:
        logger.warning("پرسش ویرایش فرستاده نشد: %s", exc)


async def on_track_value(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    مقدار تازه رسید: در گنجینه می‌نشیند و فایل از نو برچسب می‌خورد.
    """
    message = update.effective_message
    if message is None or not message.text:
        return

    data = get_data(context.user_data)
    track_id = data.get("track_id")
    field = data.get("field")
    if not track_id or field not in _TRACK_FIELDS:
        clear_state(context.user_data)
        return
    # پیامی از گفتگوی دیگر، ویرایش این نوا نیست.
    if data.get("chat_id") and message.chat_id != data["chat_id"]:
        return

    value = fix_characters(message.text.strip())[: _TRACK_LIMITS[field]]
    clear_state(context.user_data)
    if not value:
        await message.reply_html(texts.msg("track_edit_empty"))
        return

    from core.normalize import normalize

    if field == "madah":
        database.execute(
            "UPDATE tracks SET madah = ?, madah_norm = ?, updated_at = datetime('now')"
            " WHERE id = ?",
            (value, normalize(value), track_id),
        )
    elif field == "title":
        database.execute(
            "UPDATE tracks SET title = ?, title_norm = ?, lyrics_snippet = ?,"
            " updated_at = datetime('now') WHERE id = ?",
            (value, normalize(value), value, track_id),
        )
    else:
        database.execute(
            "UPDATE tracks SET style = ?, updated_at = datetime('now') WHERE id = ?",
            (value, track_id),
        )

    await message.reply_html(
        texts.msg("track_edit_done", field=_TRACK_FIELDS[field], value=value)
    )

    # فایل هم باید درست شود، نه فقط ردیف پایگاه داده. این کار
    # فایل را از نو برچسب می‌زند و نسخهٔ تازه را در گروه بایگانی
    # می‌نشاند؛ در پس‌زمینه، تا گرداننده چشم‌به‌راه نماند.
    context.application.create_task(_retag(context, int(track_id)))
    logger.info("شناسنامهٔ نوای %s ویرایش شد: %s ← %s", track_id, field, value)


async def _retag(context, track_id: int) -> None:
    from services import indexer

    try:
        await indexer.tag_and_republish(context.bot, track_id)
    except Exception:  # noqa: BLE001
        logger.exception("برچسب‌زدن دوبارهٔ نوای %s شکست خورد.", track_id)


async def on_ornate_delete(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """«حذف» — نخست پرسش واپسین."""
    query, track = await _guard(update, context)
    if query is None:
        return
    await _ack(query)
    try:
        await query.edit_message_reply_markup(
            reply_markup=inline.ornate_confirm_delete(int(track["id"]))
        )
    except TelegramError as exc:
        logger.debug("نمایش پرسش واپسین نشد: %s", exc)


async def on_ornate_delete_yes(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """برداشتن، پس از تأیید."""
    query, track = await _guard(update, context)
    admin = update.effective_user
    if query is None:
        return
    if admin is None:
        await _ack(query)
        return

    track_id = int(track["id"])
    label = texts.escape(f"{track['madah'] or 'نامعلوم'} — {track['title'] or 'بی‌نام'}")
    removed = database.remove_track(track_id)

    await _ack(query, "حذف شد." if removed else "قبلاً حذف شده بود.")
    await _note_on_caption(
        query, texts.msg("ornate_removed", admin=admin.full_name)
    )
    logger.info("نوای %s (%s) از زیر فایل، به دست %s حذف شد.", track_id, label, admin.id)
