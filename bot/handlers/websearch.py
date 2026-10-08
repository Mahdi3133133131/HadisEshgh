"""
پلهٔ دوم جست‌وجو: تارنماها.

    آرشیو ──نیافتیم──▶ تارنماها ──پیش‌نمایش──▶ کاربر تأیید کرد ──▶ آرشیو

وقتی نه اثر انگشت چیزی گفت و نه جست‌وجوی نامِ آرشیو، سراغ چهار
تارنمای مداحی می‌رویم.

## چرا پیش‌نمایش، و نه فهرست نام

پیش‌تر فهرستی از نام‌ها با دکمه می‌آمد و کاربر باید از روی نام
حدس می‌زد کدام همان است. ولی نامِ برگرفته از نشانیِ صفحه اغلب
گنگ است، و مداحی‌ها نام‌های به‌هم‌شبیه دارند. پس اکنون از هر
گمانه **سی ثانیه از خودِ صدا** فرستاده می‌شود: شنیدن، یقین
می‌آورد؛ خواندنِ نام، نمی‌آورد.

سه گمانه، نه بیشتر. و همان سی ثانیه هم با گرفتنِ **سرِ** فایل
ساخته می‌شود، نه فرو گرفتنِ کلِ آن — نسخهٔ کامل تنها پس از تأیید
کاربر می‌آید.

## سکه کِی سوزانده می‌شود

گشتن رایگان است و پیش‌نمایش هم. تنها **تأیید** سکه می‌ستاند —
یعنی همان لحظه‌ای که کاربر چیزی را که می‌خواست به دست می‌آورد.
رد کردنِ هر سه، سکه‌ای نمی‌برد.

پس از تأیید، نوا با نشانِ سرچشمه برچسب می‌خورد، به تلگرام سپرده
می‌شود و در آرشیو می‌نشیند، با اثر انگشت. یعنی **دفعهٔ بعد هیچ‌کس
به تارنما نمی‌رود**؛ همان نوا از آرشیو خودمان و در یک لحظه یافته
می‌شود.
"""

from __future__ import annotations

import asyncio
import logging
import time

from telegram import Update
from telegram.error import TelegramError
from telegram.ext import ContextTypes

from bot.keyboards import inline
from config import config
from core import net, texts
from core.audio.decode import DecodeError, extract_preview
from core.db import database
from core.db.database import InsufficientTokens
from core.normalize import fix_display, to_persian_digits
from services import sites

logger = logging.getLogger(__name__)

HITS_KEY = "site_hits"

# سه گمانه. بیشتر از این، کاربر را در انبوهی از صوت گم می‌کند —
# همان چیزی که خواسته بودند نباشد.
MAX_SHOWN = 3

PREVIEW_SECONDS = 30.0


def _fa(value: object) -> str:
    return to_persian_digits(str(value))


# ═════════════════════════════════════════════════════════════
#  پیشنهاد
# ═════════════════════════════════════════════════════════════

async def offer(
    message,
    context: ContextTypes.DEFAULT_TYPE,
    term: str,
    search_id: int | None = None,
) -> bool:
    """
    تارنماها را می‌جوید و از هر گمانه سی ثانیه پیش می‌گذارد.

    بازگشتی می‌گوید آیا پیش‌نمایشی فرستاده شد — تا فراخوان بداند
    پیام پایانیِ «متأسفم» را همین حالا بفرستد یا پس از داوری کاربر.
    """
    term = (term or "").strip()
    if len(term) < 3:
        return False

    try:
        hits = await sites.search(term, limit=MAX_SHOWN)
    except Exception:  # noqa: BLE001
        logger.exception("جست‌وجوی تارنماها شکست خورد.")
        return False

    if not hits:
        logger.info("تارنماها برای «%s» چیزی نداشتند.", term)
        return False

    # نامِ یافته‌هایی که از نشانی درنیامد، از خودِ برگه گرفته
    # می‌شود. پیش‌تر این‌ها خاموش دور ریخته می‌شدند و musicdel —
    # که نشانی‌اش عدد است — هرگز دیده نمی‌شد.
    hits = await _fill_titles(hits)
    hits = [hit for hit in hits if hit.title][:MAX_SHOWN]
    if not hits:
        return False

    user_id = message.chat_id
    previews = await asyncio.gather(
        *(_make_preview(user_id, index, hit) for index, hit in enumerate(hits))
    )

    items: list[dict] = []
    for hit, preview in zip(hits, previews):
        items.append(
            {
                "site": hit.site,
                "title": hit.title,
                "page_url": hit.page_url,
                "file_url": hit.file_url,
                # آنچه کاربر جسته، بهترین گمانه برای نام مداح است.
                # اگر غلط باشد، در گروه بایگانی زیر همان فایل دکمهٔ
                # «ویرایش» هست. جایگزینِ این، تهی ماندنِ نام مداح
                # بود — و آن، نامِ برند را روی فایل می‌نشاند.
                "madah": term,
                "preview": str(preview) if preview else None,
                "message_id": None,
                "settled": False,
            }
        )

    sent_any = False
    for index, (hit, item) in enumerate(zip(hits, items)):
        if not item["preview"]:
            continue
        message_id = await _send_preview(context, user_id, index, hit, item["preview"])
        if message_id is not None:
            item["message_id"] = message_id
            sent_any = True

    if not sent_any:
        logger.info("هیچ پیش‌نمایشی برای «%s» ساخته نشد.", term)
        return False

    context.user_data[HITS_KEY] = {
        "term": term,
        "search_id": search_id,
        "at": time.time(),
        "items": items,
    }
    logger.info(
        "تارنماها برای «%s»: %s پیش‌نمایش فرستاده شد.",
        term, sum(1 for i in items if i["message_id"]),
    )
    return True


async def _fill_titles(hits: list[sites.Hit]) -> list[sites.Hit]:
    """نام یافته‌های بی‌نام را از خودِ برگه می‌گیرد."""
    missing = [hit for hit in hits if not hit.title]
    if not missing:
        return hits
    try:
        await asyncio.gather(
            *(sites.resolve(hit) for hit in missing), return_exceptions=True
        )
    except Exception:  # noqa: BLE001
        logger.debug("گرفتن نامِ یافته‌های بی‌نام نشد.")
    return hits


async def _make_preview(user_id: int, index: int, hit: sites.Hit):
    """
    سی ثانیه از سرِ یک یافته می‌سازد؛ None اگر نشد.

    ناکامی‌اش کارِ بقیه را نمی‌شکند: دو گمانهٔ دیگر همچنان
    فرستاده می‌شوند.
    """
    try:
        resolved = await sites.resolve(hit)
        if not resolved.file_url:
            logger.debug("نشانی فایل در %s یافت نشد.", hit.page_url)
            return None

        partial = config.tmp_dir / f"part_{user_id}_{index}.mp3"
        preview = config.tmp_dir / f"prev_{user_id}_{index}.mp3"

        got = await sites.download(
            resolved.file_url, partial, max_bytes=sites.PREVIEW_BYTES
        )
        if got is None:
            return None

        loop = asyncio.get_running_loop()
        try:
            return await loop.run_in_executor(
                None, lambda: extract_preview(partial, preview, PREVIEW_SECONDS)
            )
        finally:
            partial.unlink(missing_ok=True)
    except DecodeError as exc:
        logger.debug("پیش‌نمایش %s ساخته نشد: %s", hit.page_url, exc)
        return None
    except Exception:  # noqa: BLE001
        logger.exception("ساختن پیش‌نمایش %s شکست خورد.", hit.page_url)
        return None


async def _send_preview(
    context: ContextTypes.DEFAULT_TYPE, chat_id: int, index: int, hit, path
) -> int | None:
    """یک پیش‌نمایش را با دو دکمهٔ داوری می‌فرستد."""
    caption = texts.msg(
        "site_preview",
        number=_fa(index + 1),
        title=fix_display(hit.title),
        site=hit.label,
        url=hit.page_url,
        seconds=_fa(int(PREVIEW_SECONDS)),
    )
    try:
        with open(path, "rb") as handle:
            sent = await net.retry(
                lambda: context.bot.send_audio(
                    chat_id=chat_id,
                    audio=handle,
                    caption=caption,
                    parse_mode="HTML",
                    title=hit.title[:64] or hit.label,
                    performer=hit.label,
                    reply_markup=inline.site_preview(index),
                    read_timeout=config.read_timeout,
                    write_timeout=config.write_timeout,
                    connect_timeout=config.connect_timeout,
                ),
                label="فرستادن پیش‌نمایش",
            )
        return sent.message_id
    except (OSError, TelegramError) as exc:
        logger.warning("فرستادن پیش‌نمایش شکست خورد: %s", exc)
        return None


# ═════════════════════════════════════════════════════════════
#  داوری کاربر بر پیش‌نمایش‌ها
# ═════════════════════════════════════════════════════════════

def _picked(context: ContextTypes.DEFAULT_TYPE, query) -> tuple[dict, dict, int] | None:
    """بستهٔ یافته‌ها و آیتمِ نواخته‌شده."""
    try:
        index = int(query.data.rpartition(":")[2])
    except (AttributeError, ValueError):
        return None
    bundle = context.user_data.get(HITS_KEY) or {}
    items = bundle.get("items") or []
    if not 0 <= index < len(items):
        return None
    return bundle, items[index], index


async def on_preview_no(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """«این نیست» — همین پیش‌نمایش بسته می‌شود، بی هیچ هزینه‌ای."""
    query = update.callback_query
    if query is None:
        return
    if query.message is None:
        await _ack(query)
        return

    found = _picked(context, query)
    if found is None:
        await _ack(query, texts.msg("site_gone"), alert=True)
        return

    bundle, item, _ = found
    item["settled"] = True
    await _ack(query)
    await _close(query, texts.msg("site_preview_dropped"))

    # اگر هر سه رد شدند، اکنون — و تنها اکنون — پایانِ کار است.
    if all(entry["settled"] or not entry["message_id"] for entry in bundle["items"]):
        _cleanup(bundle)
        context.user_data.pop(HITS_KEY, None)
        from bot.handlers.search import send_sorry

        await send_sorry(context, query.message.chat_id, bundle.get("search_id"))


async def on_preview_yes(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """«خودشه» — نسخهٔ کامل می‌آید و سکه سوزانده می‌شود."""
    query = update.callback_query
    user = update.effective_user
    if query is None:
        return
    if user is None or query.message is None:
        await _ack(query)
        return

    found = _picked(context, query)
    if found is None:
        await _ack(query, texts.msg("site_gone"), alert=True)
        return

    bundle, item, _ = found
    chat_id = query.message.chat_id

    # سکه پیش از کار سنجیده می‌شود، نه پس از آن: فرو گرفتنِ یک
    # فایل چندمگابایتی و سپس گفتن «سکه نداری» هم وقت را هدر
    # می‌دهد و هم آزردن است.
    if database.get_tokens(user.id) <= 0:
        await _ack(query, texts.msg("site_need_token"), alert=True)
        return

    item["settled"] = True
    await _ack(query, texts.msg("site_fetching"))
    await _close(query, texts.msg("site_preview_chosen"))

    status = None
    try:
        status = await net.say(context.bot, chat_id, texts.msg("site_fetching_long"))
    except TelegramError:
        pass

    track_id = await _bring(context, chat_id, user.id, item, bundle.get("search_id"))

    if status is not None:
        try:
            await status.delete()
        except TelegramError:
            pass

    if track_id is None:
        await net.say(context.bot, chat_id, texts.msg("site_failed"))
        return

    _charge(user.id, bundle.get("search_id"))

    # کارِ این جست‌وجو تمام شد؛ پیش‌نمایش‌های دیگر بی‌معنا شده‌اند.
    await _drop_others(context, chat_id, bundle, keep=item)
    _cleanup(bundle)
    context.user_data.pop(HITS_KEY, None)


async def on_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """«بی‌خیال» زیر فهرست نوشتاری یافته‌ها."""
    query = update.callback_query
    if query is None:
        return
    bundle = context.user_data.pop(HITS_KEY, None)
    if bundle:
        _cleanup(bundle)
    await _ack(query)
    try:
        await query.edit_message_reply_markup(reply_markup=None)
    except TelegramError:
        pass


def _charge(user_id: int, search_id: int | None) -> None:
    """
    سکهٔ این یافتن را برمی‌دارد.

    ناکامی‌اش نوا را پس نمی‌گیرد: فایل از پیش رفته و گرفتنش
    ناممکن است. تنها گزارش می‌شود.
    """
    from core.db import searches

    try:
        balance = database.adjust_tokens(
            user_id,
            -config.token_cost_per_search,
            reason="search",
            ref_type="search",
            ref_id=search_id,
            note="یافته‌شده در سایت‌ها",
        )
        if search_id:
            searches.mark_charged(int(search_id))
        logger.info("سکهٔ کاربر %s پس از یافتنِ سایتی شد %s.", user_id, balance)
    except InsufficientTokens:
        logger.warning("کاربر %s سکه نداشت ولی نوای سایتی رفت.", user_id)
    except Exception:  # noqa: BLE001
        logger.exception("برداشتن سکهٔ کاربر %s نشد.", user_id)


async def _drop_others(
    context: ContextTypes.DEFAULT_TYPE, chat_id: int, bundle: dict, keep: dict
) -> None:
    """پیش‌نمایش‌های دیگر را برمی‌دارد."""
    for entry in bundle.get("items") or []:
        if entry is keep or not entry.get("message_id"):
            continue
        try:
            await context.bot.delete_message(chat_id, entry["message_id"])
        except TelegramError:
            # نشد، مهم نیست — دکمه‌هایش دیگر به جایی وصل نیستند و
            # نواختنشان «این فهرست قدیمی شده» می‌گیرد.
            pass


def _cleanup(bundle: dict) -> None:
    """فایل‌های پیش‌نمایش را از دیسک برمی‌دارد."""
    from pathlib import Path

    for entry in bundle.get("items") or []:
        preview = entry.get("preview")
        if preview:
            Path(preview).unlink(missing_ok=True)


async def _close(query, note: str) -> None:
    """
    دکمه‌ها را برمی‌دارد و نشانِ داوری را به زیرنویس می‌افزاید.

    اگر ویرایشِ زیرنویس نشد — که با یک نویسهٔ HTML در نام هم
    می‌شود — دست‌کم دکمه‌ها برداشته می‌شوند. وگرنه دکمه سر جایش
    می‌ماند و به چشم «کار نکرد» می‌آید.
    """
    try:
        caption = getattr(query.message, "caption", None) or ""
        await query.edit_message_caption(
            caption=f"{caption}\n\n{note}".strip(),
            parse_mode="HTML",
            reply_markup=None,
        )
        return
    except TelegramError as exc:
        logger.debug("نشان‌گذاری زیرنویس پیش‌نمایش نشد: %s", exc)

    try:
        await query.edit_message_reply_markup(reply_markup=None)
    except TelegramError as exc:
        logger.warning("برداشتن دکمه‌های پیش‌نمایش نشد: %s", exc)


# ═════════════════════════════════════════════════════════════
#  فهرست نوشتاری — راهِ فروافتادن
# ═════════════════════════════════════════════════════════════

async def on_pick(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    کاربر یکی از یافته‌های فهرست نوشتاری را برگزید.

    این راه دیگر خودبه‌خود پیش نمی‌آید (جایش را پیش‌نمایش گرفت)،
    ولی دکمه‌هایی که پیش از این تغییر فرستاده شده‌اند باید کار
    کنند؛ پیامِ کهنه در تلگرام از میان نمی‌رود.
    """
    query = update.callback_query
    user = update.effective_user
    if query is None:
        return
    if user is None or query.message is None:
        await _ack(query)
        return

    found = _picked(context, query)
    if found is None:
        await _ack(query, texts.msg("site_gone"), alert=True)
        return

    bundle, item, _ = found
    if database.get_tokens(user.id) <= 0:
        await _ack(query, texts.msg("site_need_token"), alert=True)
        return

    await _ack(query, texts.msg("site_fetching"))
    try:
        await query.edit_message_reply_markup(reply_markup=None)
    except TelegramError:
        pass

    chat_id = query.message.chat_id
    status = None
    try:
        status = await net.say(context.bot, chat_id, texts.msg("site_fetching_long"))
    except TelegramError:
        pass

    track_id = await _bring(context, chat_id, user.id, item, bundle.get("search_id"))

    if status is not None:
        try:
            await status.delete()
        except TelegramError:
            pass

    if track_id is None:
        await net.say(context.bot, chat_id, texts.msg("site_failed"))
        return
    _charge(user.id, bundle.get("search_id"))


# ═════════════════════════════════════════════════════════════
#  آوردنِ نسخهٔ کامل
# ═════════════════════════════════════════════════════════════

async def _bring(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    user_id: int,
    item: dict,
    search_id: int | None,
) -> int | None:
    """
    فرو گرفتن، برچسب، سپردن به تلگرام، نشاندن در آرشیو، فرستادن.

    ترتیبش سرنوشت‌ساز است: برچسب **پیش از** بارگذاری می‌خورد،
    وگرنه فایلی که در تلگرام می‌نشیند بی‌نشانِ سرچشمه می‌ماند و
    دیگر نمی‌شود درستش کرد مگر با بارگذاری دوباره.
    """
    from services import indexer, tagger
    from worker.queue import get_queue

    hit = sites.Hit(
        site=item["site"],
        title=item.get("title") or "",
        page_url=item["page_url"],
        file_url=item.get("file_url"),
    )

    hit = await sites.resolve(hit)
    if not hit.file_url:
        logger.info("نشانی فایل در %s یافت نشد.", hit.page_url)
        return None

    # نام مداح از آنچه کاربر جسته بود گمانه زده می‌شود.
    #
    # ## چرا گمانه، و چرا اصلاً
    #
    # پیش‌تر نوای سایتی بی مداح در آرشیو می‌نشست، و آنگاه هر جا
    # فرستاده می‌شد نامِ برند به جای نام مداح روی فایل می‌نشست —
    # همان که کاربر دید و گفت باید نام مداح باشد. کاربر معمولاً
    # نام مداح را جسته است، پس همان بهترین گمانه است. اگر غلط
    # باشد، در گروه بایگانی زیر همان فایل دکمهٔ «ویرایش» هست.
    madah = (item.get("madah") or "").strip() or None

    path = config.tmp_dir / f"site_{user_id}_{abs(hash(hit.page_url)) % 10**8}.mp3"
    if await sites.download(hit.file_url, path) is None:
        return None

    try:
        # ── برچسب، با نشانِ سرچشمه ──────────────────────────
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(
            None,
            lambda: tagger.tag_with_cover(
                path,
                madah=madah,
                title=hit.title,
                source_label=hit.label,
                source_url=hit.page_url,
            ),
        )

        caption = texts.msg(
            "site_delivered",
            title=fix_display(hit.title),
            site=hit.label,
            url=hit.page_url,
        )
        # «درست است / این نیست» زیر نسخهٔ کامل هم بایسته است: این
        # صوت سکه می‌ستاند و اگر آنی نباشد که کاربر می‌خواست، باید
        # راهی برای بازگرداندنش باشد.
        keyboard = (
            inline.search_result(int(search_id)) if search_id else None
        )
        with path.open("rb") as handle:
            sent = await net.retry(
                lambda: context.bot.send_audio(
                    chat_id=chat_id,
                    audio=handle,
                    caption=caption,
                    parse_mode="HTML",
                    protect_content=True,
                    reply_markup=keyboard,
                    title=hit.title[:64] or hit.label,
                    performer=madah or hit.label,
                    read_timeout=config.read_timeout,
                    write_timeout=config.write_timeout,
                    connect_timeout=config.connect_timeout,
                ),
                label="فرستادن نوای تارنما",
            )
        if sent.audio is None:
            return None

        # ── نشاندن در آرشیو ────────────────────────────────
        duplicate = database.find_duplicate_track(
            file_unique_id=sent.audio.file_unique_id
        )
        if duplicate is not None:
            database.bump_sent_count(int(duplicate["id"]))
            # شکافی که هنگام کار دیده شد: نوای تکراری، بازجویی را
            # نشان نمی‌زد، پس مسیرِ بازکردنِ قفل شناسهٔ نوا را
            # نداشت.
            if search_id:
                _mark_search(search_id, int(duplicate["id"]))
            return int(duplicate["id"])

        track_id = database.add_track(
            file_id=sent.audio.file_id,
            file_unique_id=sent.audio.file_unique_id,
            source="site",
            madah=madah,
            title=hit.title,
            duration=sent.audio.duration,
            file_size=sent.audio.file_size,
            source_url=hit.page_url,
            added_by=user_id,
        )
        database.bump_sent_count(track_id)

        # اثر انگشت، تا دفعهٔ بعد از آرشیو خودمان یافته شود و
        # هیچ‌کس به تارنما نرود.
        context.application.create_task(
            get_queue().run_async(indexer.index_track(context.bot, track_id))
        )
        logger.info(
            "نوای %s از %s به آرشیو افزوده شد (%s).",
            track_id, hit.label, hit.page_url,
        )
        if search_id:
            _mark_search(search_id, track_id)
        return track_id

    except TelegramError as exc:
        logger.warning("فرستادن نوای تارنما شکست خورد: %s", exc)
        return None
    finally:
        path.unlink(missing_ok=True)


def _mark_search(search_id: int, track_id: int) -> None:
    """
    بازجویی را «پرشده» می‌نشاند.

    نه «یافته» — چون موتور نیافت، تارنما یافت. آمارِ موتور نباید
    دروغ بگوید.
    """
    from core.db import searches

    try:
        searches.mark_fulfilled(search_id, track_id, 0)
    except Exception:  # noqa: BLE001
        logger.debug("نشاندن سرانجام بازجویی %s نشد.", search_id)


async def _ack(query, text: str | None = None, alert: bool = False) -> None:
    try:
        await query.answer(text, show_alert=alert)
    except TelegramError as exc:
        logger.debug("پاسخ نواخت نرسید: %s", exc)
