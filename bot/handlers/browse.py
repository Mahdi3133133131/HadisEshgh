"""
گشت‌وگذار در آرشیو — «محبوب‌ترین‌ها».

## چرا این بخش هست

تا امروز ربات تنها یک در داشت: کاربر باید **از پیش می‌دانست**
دنبال چه می‌گردد. کسی که تازه آمده و تنها می‌خواهد چیزی بشنود،
هیچ راهی نداشت — نه فهرستی، نه پیشنهادی، هیچ.

شمارندهٔ فرستادن (`tracks.sent_count`) از پیش هر بار که نوایی به
دست کسی می‌رسد بالا می‌رود. پس فهرستِ «آنچه بیشتر خواسته شده»
بی هیچ کار تازه‌ای در دست است — تنها باید نشانش داد.

## سکه

گرفتنِ نوا از این فهرست، همان گرفتنِ نواست و یک سکه می‌ستاند —
مانند هر راه دیگر. دیدنِ **فهرست** رایگان است؛ تنها فایل بها
دارد.

دکمهٔ داوری («این همونه / این آن نیست») اینجا **نیست**، و نبودنش
عمدی است: آن دکمه‌ها برای پاسخِ گمانیِ ربات‌اند. اینجا کاربر
نامِ نوا را دیده و خودش برگزیده — از او پرسیدن که «درست بود؟»
پرسشی است بی‌پاسخ.
"""

from __future__ import annotations

import logging

from telegram import Update
from telegram.error import TelegramError
from telegram.ext import ContextTypes

from bot.guards import answer_quietly, require_verified
from bot.keyboards import inline, reply
from config import config
from core import net, texts
from core.db import database, searches
from core.db.database import InsufficientTokens
from core.normalize import format_duration, to_persian_digits

logger = logging.getLogger(__name__)

# بیش از این، فهرست به جای راهنمایی، سردرگمی می‌سازد.
HOW_MANY = 8

# شکستِ خط، به‌جای گریزِ درون‌رشته‌ای — خواناتر در
# رشته‌های چندتکه‌ای که با + به هم می‌چسبند.
BREAK = chr(10)


def _fa(value: object) -> str:
    return to_persian_digits(str(value))


def _popular_rows(page: int):
    """(ردیف‌های دکمه، متنِ فهرست، برگه، شمار برگه‌ها)"""
    total = database.count_popular()
    pages = _pages(total, HOW_MANY)
    page = max(0, min(page, pages - 1))
    rows = database.popular_tracks(HOW_MANY, offset=page * HOW_MANY)

    lines = [texts.messages.raw("popular_header"), ""]
    buttons: list[tuple[int, str]] = []
    for index, row in enumerate(rows, start=page * HOW_MANY + 1):
        madah = row["madah"] or "نامعلوم"
        title = row["title"] or "بی‌نام"
        count = int(row["sent_count"] or 0)
        lines.append(
            f"<b>{_fa(index)}.</b> {texts.escape(title)}"
            + BREAK
            + f"     <i>{texts.escape(madah)} · {format_duration(row['duration'])}"
            f" · {_fa(count)} بار</i>"
        )
        buttons.append((int(row["id"]), f"{_fa(index)}. {title[:38]}"))
    return buttons, BREAK.join(lines), page, pages


@require_verified
async def show_popular(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """فهرست پرخواسته‌ترین نواهای آرشیو."""
    message = update.effective_message
    if message is None:
        return

    buttons, body, page, pages = _popular_rows(0)
    if not buttons:
        await message.reply_html(
            texts.msg("popular_empty"), reply_markup=reply.main_menu()
        )
        return

    await message.reply_html(
        body, reply_markup=inline.popular_list(buttons, page, pages)
    )


async def on_popular_page(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """ورق زدنِ فهرست محبوب‌ترین‌ها."""
    query = update.callback_query
    if query is None or not query.data:
        return
    try:
        page = int(query.data.rpartition(":")[2])
    except ValueError:
        await answer_quietly(query)
        return

    await answer_quietly(query)
    buttons, body, page, pages = _popular_rows(page)
    try:
        await query.edit_message_text(
            body, parse_mode="HTML",
            reply_markup=inline.popular_list(buttons, page, pages),
        )
    except TelegramError as exc:
        logger.debug("ورق زدنِ محبوب‌ترین‌ها نشد: %s", exc)


async def on_pick(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """کاربر یکی از فهرست را برگزید."""
    query = update.callback_query
    user = update.effective_user
    if query is None:
        return
    if user is None or not query.data or query.message is None:
        await answer_quietly(query)
        return

    try:
        track_id = int(query.data.rpartition(":")[2])
    except ValueError:
        await answer_quietly(query)
        return

    track = database.get_track(track_id)
    if track is None or not track["file_id"]:
        await answer_quietly(query, texts.msg("popular_gone"), alert=True)
        return

    # کیسه پیش از فرستادن سنجیده می‌شود، نه پس از آن.
    if database.get_tokens(user.id) <= 0:
        await answer_quietly(query, texts.msg("site_need_token"), alert=True)
        return

    await answer_quietly(query)

    # ردیفی در دفتر، تا برداشتِ سکه جایی برای اشاره داشته باشد
    # (`ref_id` در دفترِ سکه) و آمار هم درست بماند.
    search_id = searches.create(
        user_id=user.id, input_kind="text", query_text=f"محبوب‌ترین‌ها #{track_id}"
    )

    from services.tagger import audio_labels

    count = database.bump_sent_count(track_id)
    caption = texts.msg(
        "popular_item",
        madah=track["madah"] or "نامعلوم",
        style=track["style"] or "—",
        duration=format_duration(track["duration"]),
        count=_fa(count),
    )
    try:
        await net.retry(
            lambda: context.bot.send_audio(
                chat_id=query.message.chat_id,
                audio=track["file_id"],
                caption=caption,
                parse_mode="HTML",
                protect_content=True,
                # ── چرا اکنون دکمه دارد و پیش‌تر نداشت ──────────
                #
                # پیش‌تر نداشت، و دلیلش درست بود: کاربر خودش از
                # فهرست برگزیده بود و پرسیدنِ «درست بود؟» از او
                # بی‌معنا می‌نمود.
                #
                # ولی کارِ این دکمه‌ها عوض شده: اکنون **قفلِ فایل**
                # را برمی‌دارند. بی آن‌ها، نوایی که کاربر خودش
                # برگزیده تا ابد قفل می‌ماند — و آن بدتر از یک
                # پرسشِ زائد است.
                reply_markup=inline.search_result(search_id),
                **audio_labels(track),
            ),
            label="فرستادن نوای محبوب",
        )
    except TelegramError as exc:
        logger.warning("فرستادن نوای محبوب %s شکست خورد: %s", track_id, exc)
        return

    _charge(user.id, search_id, track_id)


def _charge(user_id: int, search_id: int, track_id: int) -> None:
    """سکهٔ نوایی که از فهرست برداشته شد."""
    try:
        balance = database.adjust_tokens(
            user_id,
            -config.token_cost_per_search,
            reason="search",
            ref_type="search",
            ref_id=search_id,
            note="از فهرست محبوب‌ترین‌ها",
        )
        searches.mark_charged(search_id)
        searches.finish(search_id, "fulfilled", matched_track_id=track_id)
        logger.info("سکهٔ کاربر %s پس از برداشتن از فهرست شد %s.", user_id, balance)
    except InsufficientTokens:
        logger.warning("کاربر %s سکه نداشت ولی نوای محبوب رفت.", user_id)
    except Exception:  # noqa: BLE001
        logger.exception("برداشتن سکهٔ فهرست محبوب نشد.")

# ═════════════════════════════════════════════════════════════
#  گشت‌وگذار در مداحان
# ═════════════════════════════════════════════════════════════

# شمارِ هر برگه همان است که شبکهٔ صفحه‌کلید جا می‌دهد. دو جا
# نوشتنش یعنی روزی یکی عوض شود و دیگری نه.
PER_PAGE = inline.PER_PAGE


def _pages(total: int, per_page: int = 0) -> int:
    per_page = per_page or PER_PAGE
    return max(1, -(-total // per_page))


async def _allowed(update, context) -> bool:
    """
    گرداننده بی‌قید می‌گذرد؛ کاربر باید تأییدشده باشد.

    دو رویه، یک درگاه: همان دستور برای گرداننده ابزارِ مدیریت است
    و برای کاربر پنجرهٔ گشت‌وگذار.
    """
    user = update.effective_user
    if user is None:
        return False
    if config.is_admin(user.id):
        return True

    from core.db.database import get_user

    record = get_user(user.id)
    if record is None or not int(record["is_verified"] or 0):
        message = update.effective_message
        if message is not None:
            await message.reply_html(texts.msg("must_verify_first"))
        return False
    if int(record["is_banned"] or 0):
        return False
    return True


def _madah_rows(page: int):
    """(ردیف‌های دکمه، متنِ فهرست، شمار برگه‌ها)"""
    total = database.count_madahs()
    pages = _pages(total)
    page = max(0, min(page, pages - 1))
    rows = database.madahs_with_counts(offset=page * PER_PAGE, limit=PER_PAGE)

    lines = [texts.msg("madahs_header", total=_fa(total)).rstrip(), ""]
    buttons: list[tuple[int, int]] = []
    for index, row in enumerate(rows, start=page * PER_PAGE + 1):
        name = row["madah"] or "نامعلوم"
        count = int(row["tracks"])
        lines.append(f"<b>{_fa(index)}.</b> {texts.escape(name)} — {_fa(count)} نوا")
        # لنگر از همان پرس‌وجو می‌آید. پیش‌تر برای **هر ردیف** یک
        # پرس‌وجوی جدا زده می‌شد؛ با سی‌ودو ردیف در هر برگه،
        # سی‌ودو پرس‌وجوی اضافه.
        if row.get("anchor"):
            buttons.append((index, int(row["anchor"])))
    return buttons, "\n".join(lines), page, pages


async def on_noop(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    دکمهٔ شمارهٔ برگه — تنها نشانه است، کاری نمی‌کند.

    بی این، تلگرام چرخِ روی دکمه را تا سرآمدنِ مهلت می‌چرخاند و
    کاربر می‌پندارد چیزی خراب است.
    """
    if update.callback_query is not None:
        await answer_quietly(update.callback_query)


async def show_madahs(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """فهرست مداحان گنجینه."""
    message = update.effective_message
    if message is None or not await _allowed(update, context):
        return

    buttons, body, page, pages = _madah_rows(0)
    if not buttons:
        await message.reply_html(texts.msg("madahs_empty"))
        return
    await message.reply_html(body, reply_markup=inline.madah_list(buttons, page, pages))


async def on_madah_page(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """ورق زدنِ فهرست مداحان."""
    query = update.callback_query
    if query is None or not query.data:
        return
    if not await _allowed(update, context):
        await answer_quietly(query)
        return
    try:
        page = int(query.data.rpartition(":")[2])
    except ValueError:
        await answer_quietly(query)
        return

    await answer_quietly(query)
    buttons, body, page, pages = _madah_rows(page)
    try:
        await query.edit_message_text(
            body, parse_mode="HTML",
            reply_markup=inline.madah_list(buttons, page, pages),
        )
    except TelegramError as exc:
        logger.debug("ورق زدنِ مداحان نشد: %s", exc)


def _track_rows(madah_norm: str, anchor_id: int, page: int):
    total = database.count_tracks_of_madah(madah_norm)
    pages = _pages(total)
    page = max(0, min(page, pages - 1))
    rows = database.tracks_of_madah(madah_norm, offset=page * PER_PAGE, limit=PER_PAGE)

    name = rows[0]["madah"] if rows else "—"
    lines = [
        texts.msg("madah_tracks_header", madah=texts.escape(name or "—"),
                  total=_fa(total)).rstrip(),
        "",
    ]
    buttons: list[tuple[int, int]] = []
    for index, row in enumerate(rows, start=page * PER_PAGE + 1):
        title = row["title"] or "بی‌نام"
        lines.append(
            f"<b>{_fa(index)}.</b> {texts.escape(title)}"
            f" <i>({format_duration(row['duration'])})</i>"
        )
        buttons.append((index, int(row["id"])))
    return buttons, "\n".join(lines), page, pages


async def _show_tracks(query, anchor_id: int, page: int) -> None:
    track = database.get_track(anchor_id)
    if track is None:
        await answer_quietly(query, texts.msg("popular_gone"), alert=True)
        return
    buttons, body, page, pages = _track_rows(track["madah_norm"], anchor_id, page)
    try:
        await query.edit_message_text(
            body, parse_mode="HTML",
            reply_markup=inline.madah_tracks(buttons, anchor_id, page, pages),
        )
    except TelegramError as exc:
        logger.debug("نمایشِ نواهای مداح نشد: %s", exc)


async def on_madah_pick(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """مداحی برگزیده شد — نواهایش را نشان بده."""
    query = update.callback_query
    if query is None or not query.data:
        return
    if not await _allowed(update, context):
        await answer_quietly(query)
        return
    try:
        anchor = int(query.data.rpartition(":")[2])
    except ValueError:
        await answer_quietly(query)
        return
    await answer_quietly(query)
    await _show_tracks(query, anchor, 0)


async def on_madah_track_page(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """ورق زدنِ نواهای یک مداح."""
    query = update.callback_query
    if query is None or not query.data:
        return
    if not await _allowed(update, context):
        await answer_quietly(query)
        return
    parts = query.data.split(":")
    try:
        page, anchor = int(parts[-2]), int(parts[-1])
    except (IndexError, ValueError):
        await answer_quietly(query)
        return
    await answer_quietly(query)
    await _show_tracks(query, anchor, page)


async def on_madah_back(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """بازگشت به فهرست مداحان."""
    query = update.callback_query
    if query is None:
        return
    if not await _allowed(update, context):
        await answer_quietly(query)
        return
    await answer_quietly(query)
    buttons, body, page, pages = _madah_rows(0)
    try:
        await query.edit_message_text(
            body, parse_mode="HTML",
            reply_markup=inline.madah_list(buttons, page, pages),
        )
    except TelegramError as exc:
        logger.debug("بازگشت به فهرست مداحان نشد: %s", exc)


async def on_madah_track(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    نوایی برگزیده شد — فرستاده می‌شود.

    ## دو رویه

    **گرداننده** صفحه‌کلیدِ ویرایش/حذف می‌گیرد و سکه‌ای نمی‌دهد؛
    این ابزارِ مدیریتِ گنجینه است. آن صفحه‌کلید و جریانِ پشتش از
    پیش هست و آزموده — `ornate_actions` و گردانندگانش — و قیدی
    بر گفتگو ندارد، پس همین‌جا هم کار می‌کند.

    **کاربر** همان راهی می‌رود که «محبوب‌ترین‌ها» می‌رود: یک سکه،
    و دکمهٔ «این نیست» که بازش می‌گرداند.
    """
    query = update.callback_query
    user = update.effective_user
    if query is None or user is None or not query.data or query.message is None:
        return
    if not await _allowed(update, context):
        await answer_quietly(query)
        return
    try:
        track_id = int(query.data.rpartition(":")[2])
    except ValueError:
        await answer_quietly(query)
        return

    track = database.get_track(track_id)
    if track is None or not track["file_id"]:
        await answer_quietly(query, texts.msg("popular_gone"), alert=True)
        return

    from services.tagger import audio_labels

    # ── راهِ گرداننده: رایگان، با ویرایش و حذف ──────────────
    if config.is_admin(user.id):
        await answer_quietly(query)
        try:
            await context.bot.send_audio(
                chat_id=query.message.chat_id,
                audio=track["file_id"],
                caption=texts.msg(
                    "madah_track_admin",
                    madah=track["madah"] or "—",
                    title=track["title"] or "—",
                    style=track["style"] or "—",
                    duration=format_duration(track["duration"]),
                    track_id=_fa(track_id),
                ),
                parse_mode="HTML",
                reply_markup=inline.ornate_actions(track_id),
                **audio_labels(track),
            )
        except TelegramError as exc:
            logger.warning("فرستادنِ نوا از فهرست مداحان نشد: %s", exc)
        return

    # ── راهِ کاربر: همان یک سکه ─────────────────────────────
    if database.get_tokens(user.id) <= 0:
        await answer_quietly(query, texts.msg("site_need_token"), alert=True)
        return

    await answer_quietly(query)
    search_id = searches.create(
        user_id=user.id, input_kind="text",
        query_text=f"مداحان #{track_id}",
    )
    count = database.bump_sent_count(track_id)
    try:
        await net.retry(
            lambda: context.bot.send_audio(
                chat_id=query.message.chat_id,
                audio=track["file_id"],
                caption=texts.msg(
                    "popular_item",
                    madah=track["madah"] or "نامعلوم",
                    style=track["style"] or "—",
                    duration=format_duration(track["duration"]),
                    count=_fa(count),
                ),
                parse_mode="HTML",
                protect_content=True,
                reply_markup=inline.search_result(search_id),
                **audio_labels(track),
            ),
            label="فرستادن نوا از فهرست مداحان",
        )
    except TelegramError as exc:
        logger.warning("فرستادنِ نوای مداح نشد: %s", exc)
        return

    _charge(user.id, search_id, track_id)
