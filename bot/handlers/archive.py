"""
نمایه‌سازی خودکار کانال مخزن.

هر نوایی که در کانال گذاشته شود، خودکار گرفته، اثر انگشتش ساخته و
به گنجینه افزوده می‌شود. سند این کار را دستی و با فرمان می‌خواست؛
خودکار بودنش هم کار گردانندگان را می‌کاهد و هم جلوی فراموشی را
می‌گیرد.

## کاستی که باید دانست

ربات تلگرام هیچ راهی برای خواندن پست‌های **گذشتهٔ** کانال ندارد؛
تلگرام چنین امکانی به ربات نمی‌دهد. پس این نمایه‌سازی تنها از
لحظه‌ای که ربات گردانندهٔ کانال می‌شود به بعد کار می‌کند.

برای بایگانی پیشین دو راه هست: گرداننده پست‌ها را دستی برای ربات
بازفرستد (که همین‌جا پشتیبانی می‌شود)، یا اسکریپتی جدا با اکانت
کاربری نوشته شود.
"""

from __future__ import annotations

import logging

from telegram import Update
from telegram.ext import ContextTypes

from telegram.error import TelegramError

from bot.guards import answer_quietly
from bot.keyboards import inline
from config import config
from core import texts
from core.db import database
from core.normalize import clean_tag, fix_characters
from services import indexer

logger = logging.getLogger(__name__)


# کانال‌ها فایل صوتی را همیشه به‌شکل «صوت» نمی‌گذارند؛ بسیاری
# آن را به‌شکل **سند** می‌فرستند و آنگاه تلگرام `message.audio`
# نمی‌سازد. پیش‌تر همان‌ها یکسره نادیده گرفته می‌شدند.
_AUDIO_MIME = (
    "audio/", "application/ogg", "video/ogg",
)
_AUDIO_SUFFIX = (
    ".mp3", ".m4a", ".aac", ".ogg", ".oga", ".opus",
    ".wav", ".flac", ".wma", ".amr",
)


def _audio_of(message):
    """
    بخشِ صوتیِ یک پست کانال — یا None اگر صوتی در کار نیست.

    سند تنها وقتی صوت شمرده می‌شود که گونه‌اش یا پسوندش بگوید.
    سندِ ناشناخته رد می‌شود: کانال‌ها عکس و pdf و zip هم می‌گذارند
    و آزمودنِ همه، هم پهنای باند است و هم زبالهٔ گنجینه.
    """
    if message is None:
        return None
    if message.audio is not None:
        return message.audio
    if message.voice is not None:
        return message.voice

    document = message.document
    if document is None:
        return None
    mime = (document.mime_type or "").lower()
    name = (document.file_name or "").lower()
    if mime.startswith(_AUDIO_MIME) or name.endswith(_AUDIO_SUFFIX):
        return document
    return None


async def on_channel_post(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """پست تازهٔ یکی از کانال‌های منبع."""
    message = update.channel_post or update.effective_message
    audio = _audio_of(message)
    if audio is None:
        return

    await _ingest(context, audio, message, source="channel")


async def ask_forwarded(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    گرداننده نوایی برای ربات بازفرستاده است؛ می‌پرسیم چه می‌خواهد.

    ## چرا پرسش، و نه افزودنِ خودکار

    پیش‌تر هر نوای بازفرستادهٔ گرداننده یک‌راست و بی هیچ پرسشی به
    گنجینه می‌رفت. آن یک تصمیمِ نانوشته، دو زیان داشت:

      • جریان پیشکش را از میان برمی‌داشت. گرداننده‌ای که «پیشکش
        نوا» را زده و سپس نوایی **بازفرستاده** بود، هرگز پرسش‌های
        مداح و سبک و نام را نمی‌دید و هرگز به دکمهٔ تأیید و ویرایش
        نمی‌رسید — نوا بی‌صدا و بی‌شناسنامه می‌نشست.
      • بازجویی را ناشدنی می‌کرد. گرداننده‌ای که می‌خواست نوایی را
        **بجوید**، اگر بازفرستاده بودش، به جای پاسخ یک «افزوده شد»
        می‌گرفت.

    خواستِ او از خودِ پیام پیدا نیست، پس پرسیده می‌شود. برای همراهِ
    ساده اصلاً پرسشی نیست: نوای بازفرستادهٔ او، بازجویی است.
    """
    message = update.effective_message
    user = update.effective_user
    if message is None or user is None or message.audio is None:
        return

    context.user_data["forwarded_audio"] = {
        "file_id": message.audio.file_id,
        "file_unique_id": message.audio.file_unique_id,
        "file_name": message.audio.title or message.audio.file_name,
        "madah": clean_tag(getattr(message.audio, "performer", None), 120),
        "title": clean_tag(getattr(message.audio, "title", None), 200),
        "duration": message.audio.duration,
        "file_size": message.audio.file_size,
        "source_chat_id": message.chat_id,
        "source_msg_id": message.message_id,
    }
    await message.reply_html(
        texts.msg("forward_choice"), reply_markup=inline.forwarded_choice()
    )


async def on_forward_add(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """«به گنجینه بیفزا» — همان دفتر پذیرش، با یک نوا."""
    from bot.handlers import intake

    query = update.callback_query
    user = update.effective_user
    if query is None or user is None or query.message is None:
        await answer_quietly(query)
        return
    if not config.is_admin(user.id):
        await query.answer(texts.msg("admin_only"), show_alert=True)
        return

    item = context.user_data.pop("forwarded_audio", None)
    await query.answer()
    try:
        await query.edit_message_reply_markup(reply_markup=None)
    except TelegramError:
        pass

    if item is None:
        await query.message.reply_html(texts.msg("forward_gone"))
        return

    await intake.start(context, query.message.chat_id, [item])


async def on_forward_seek(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """«این را بجو» — همان بازجویی همیشگی."""
    from bot.handlers import search

    query = update.callback_query
    if query is None or query.message is None:
        await answer_quietly(query)
        return

    item = context.user_data.pop("forwarded_audio", None)
    await query.answer()
    try:
        await query.edit_message_reply_markup(reply_markup=None)
    except TelegramError:
        pass

    if item is None:
        await query.message.reply_html(texts.msg("forward_gone"))
        return

    await search.begin_for_file(update, context, item["file_id"], item.get("duration"))


async def _ingest(context, audio, message, source: str) -> int | None:
    """
    نوا را در گنجینه می‌نشاند و نمایه می‌کند.

    بازگشتی: شناسهٔ نوا، یا None اگر تکراری بود.
    """
    duplicate = database.find_duplicate_track(file_unique_id=audio.file_unique_id)
    if duplicate is not None:
        logger.debug("نوای تکراری در کانال نادیده گرفته شد (همانند %s).", duplicate["id"])
        return None

    # ── شناسنامه: برچسبِ فایل، سپس کپشن ─────────────────
    #
    # آنچه روی فایل هست دست نمی‌خورد. ولی کانال‌ها نام مداح را
    # معمولاً در برچسب نمی‌نویسند، در **کپشن** می‌نویسند — بالای
    # فایل یا زیرش. تا امروز خوانده نمی‌شد و نوا بی نام مداح
    # در آرشیو می‌نشست.
    from services import captions

    madah, title = captions.read(audio, message.caption)

    track_id = database.add_track(
        file_id=audio.file_id,
        file_unique_id=audio.file_unique_id,
        source=source,
        title=title,
        madah=madah,
        # سند درازا ندارد؛ نمایه‌ساز آن را از خودِ موج درمی‌آورد
        # و با COALESCE می‌نشاند.
        duration=getattr(audio, "duration", None),
        file_size=audio.file_size,
        source_chat_id=message.chat_id,
        source_msg_id=message.message_id,
    )

    logger.info("نوای %s از %s به گنجینه افزوده شد؛ نمایه‌سازی در پیش است.", track_id, source)

    # نمایه‌سازی در پس‌زمینه، تا گرفتن پست تازه معطل نماند.
    context.application.create_task(_index_later(context, track_id))
    return track_id


async def on_harvest_ok(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    گرداننده نوایی را که ربات خودش یافته بود پذیرفت.

    از اینجا به بعد هیچ فرقی با نوای دستی ندارد: همان
    `add_track` و همان نمایه‌سازیِ پس‌زمینه.
    """
    query = update.callback_query
    if query is None or not query.data:
        return

    from services import harvest

    try:
        queue_id = int(query.data.rpartition(":")[2])
    except ValueError:
        await answer_quietly(query)
        return

    record = harvest.get(queue_id)
    if record is None or record["status"] != "pending":
        await answer_quietly(query, texts.msg("harvest_gone"), alert=True)
        return

    await answer_quietly(query)

    track_id = database.add_track(
        file_id=record["file_id"],
        file_unique_id=record["file_unique_id"],
        source="site",
        title=record["title"],
        madah=record["madah"],
        duration=record["duration"],
        source_url=record["page_url"],
    )
    harvest.mark(queue_id, "approved", track_id=track_id)
    logger.info("نوای یافته %s پذیرفته شد؛ نوای %s ساخته شد.", queue_id, track_id)

    await _strip_harvest(query, texts.msg("harvest_added", track_id=str(track_id)))
    context.application.create_task(_index_later(context, track_id))


async def on_harvest_no(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    گرداننده نپذیرفت.

    نشانی در `crawled_urls` نشان می‌خورد تا گردشِ بعدی همان را
    دوباره پیشنهاد نکند — وگرنه هر شب همان آشغال بازمی‌گشت.
    """
    query = update.callback_query
    if query is None or not query.data:
        return

    from services import crawler, harvest

    try:
        queue_id = int(query.data.rpartition(":")[2])
    except ValueError:
        await answer_quietly(query)
        return

    record = harvest.get(queue_id)
    if record is None or record["status"] != "pending":
        await answer_quietly(query, texts.msg("harvest_gone"), alert=True)
        return

    await answer_quietly(query)
    harvest.mark(queue_id, "rejected")
    crawler._remember(
        record["page_url"], record["site"], "rejected", note="گرداننده نپذیرفت"
    )
    logger.info("نوای یافته %s رد شد.", queue_id)
    await _strip_harvest(query, texts.msg("harvest_rejected"))


async def _strip_harvest(query, note: str) -> None:
    """دکمه‌ها را برمی‌دارد و سرانجام را زیر همان کارت می‌نویسد."""
    try:
        await query.edit_message_caption(
            caption=(query.message.caption or "") + "\n\n" + note,
            parse_mode="HTML",
            reply_markup=None,
        )
    except TelegramError as exc:
        logger.debug("بستنِ کارتِ داوری نشد: %s", exc)


async def _index_later(context, track_id: int) -> None:
    from worker.queue import get_queue

    try:
        await get_queue().run_async(indexer.index_track(context.bot, track_id))
    except Exception as exc:  # noqa: BLE001
        logger.warning("نمایه‌سازی خودکار نوای %s شکست خورد: %s", track_id, exc)


async def reindex_pending(context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    کار زمان‌بندی‌شده: نواهایی که نمایه‌سازی‌شان شکست خورده بود را
    دوباره می‌آزماید.

    بی این، یک قطعی گذرای شبکه، نوایی را برای همیشه نایافتنی
    می‌گذاشت — بی‌آنکه کسی بفهمد.
    """
    try:
        ok, failed = await indexer.index_pending(context.bot, limit=10)
        if ok or failed:
            logger.info("نمایه‌سازی دوره‌ای: %s کامیاب، %s ناکام.", ok, failed)
    except Exception:  # noqa: BLE001
        logger.exception("نمایه‌سازی دوره‌ای شکست خورد.")


async def republish_pending(context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    کار زمان‌بندی‌شده: نواهایی که نسخهٔ آراسته‌شان در گروه بایگانی
    ننشسته را دوباره می‌آزماید.

    بی این، یک شبِ در دسترس نبودنِ آن گروه یعنی چند نوا که برای
    همیشه از بایگانی بیرون می‌مانند — بی آنکه کسی بفهمد.
    """
    try:
        ok, failed = await indexer.republish_pending(context.bot, limit=5)
        if ok or failed:
            logger.info("نسخهٔ آراسته: %s نشست، %s ناکام.", ok, failed)
    except Exception:  # noqa: BLE001
        logger.exception("کار دوره‌ای نسخهٔ آراسته شکست خورد.")
