"""
جست‌وجوی متنی و حالت درون‌خطی.

## چرا این بخش، با آنکه در سند نبود، افزوده شد

۱) **بسیاری از کاربران هیچ پاره‌ای ندارند.** تنها به یاد دارند
   «آن نوحهٔ حاج محمود کریمی». بی جست‌وجوی متنی، ربات برایشان
   بی‌فایده است.

۲) **هزینه‌اش نزدیک به هیچ است.** یک بازجویی صوتی، ده‌ها هزار عدد
   را می‌سنجد؛ این یکی، یک پرسش ساده از پایگاه داده است. از این رو
   توکنی هم نمی‌ستاند.

۳) **حالت درون‌خطی، نیرومندترین اهرم گسترش ربات‌های تلگرامی است.**
   کاربر در هر گفتگویی می‌نویسد ‎@YourBot مهدی رسولی‎ و نتیجه را
   همان‌جا می‌فرستد. هر بازفرست، همراه تازه می‌آورد — و چون
   هم‌نشینی در کانال شرط است، هر همراه تازه، هم‌نشین تازه است.

## هنجارسازی

پرسش کاربر پیش از جست‌وجو هنجار می‌شود؛ وگرنه «کریمی» و «كريمي»
و «حاج‌محمود» سه چیز جداگانه شمرده می‌شوند. سنجیده شده است که هر
سه املا به یک نتیجه می‌رسند.
"""

from __future__ import annotations

import logging

from telegram import (
    InlineQueryResultCachedAudio,
    InlineQueryResultArticle,
    InputTextMessageContent,
    Update,
)
from telegram.constants import ChatType
from telegram.ext import ContextTypes

from bot.guards import require_verified
from bot.keyboards import inline, reply
from bot.states import clear_state
from config import config
from core import texts
from core.db import database, searches
from core.normalize import format_duration, to_persian_digits

logger = logging.getLogger(__name__)

MAX_INLINE_RESULTS = 25
MIN_QUERY_LENGTH = 2


# ═════════════════════════════════════════════════════════════
#  جست‌وجوی متنی درون گفتگو
# ═════════════════════════════════════════════════════════════

@require_verified
async def on_text_search(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    کاربر نام مداحی یا نوایی را نوشته است.

    ## سکه

    این جریان هم مانند جست‌وجوی صوتی سکه می‌ستاند — و تنها هنگامی
    که راستی چیزی **یافت و فرستاده شود**. پیش‌تر رایگان بود، ولی
    یافتنِ نوا از هر راهی که باشد همان ارزش را دارد؛ رایگان بودنِ
    یک راه، تنها کاربر را به همان راه می‌راند.
    """
    message = update.effective_message
    if message is None or not message.text:
        return

    clear_state(context.user_data)
    term = message.text.strip()

    # کیسهٔ تهی پیش از گشتن سنجیده می‌شود، نه پس از آن: نشان دادنِ
    # نتیجه و سپس گفتن «سکه نداری» هم آزردن است و هم دیر.
    user = update.effective_user
    if user is not None and database.get_tokens(user.id) <= 0:
        from bot.handlers.search import show_empty_purse

        await show_empty_purse(message, user.id)
        return

    # ردیفی در دفتر بازجویی، تا اگر پاسخ غلط بود سکه بازگردد.
    # بی این ردیف، دکمهٔ «این نیست» جایی برای نشستن ندارد.
    search_id = None
    if user is not None:
        search_id = searches.create(
            user_id=user.id, input_kind="text", query_text=term
        )

    found = await reply_with_matches(
        message, term, bot_username=context.bot.username or "",
        charge_user_id=user.id if user else None,
        search_id=search_id,
    )
    if found:
        return

    # پلهٔ دوم: گنجینه چیزی نداشت، سراغ تارنماها. همان ترتیبی که
    # در جست‌وجوی صوتی هم هست — نخست آنچه خودمان داریم.
    from bot.handlers import websearch

    try:
        await websearch.offer(message, context, term, search_id)
    except Exception:  # noqa: BLE001
        logger.exception("پلهٔ تارنماها در جست‌وجوی نوشتاری شکست خورد.")


async def reply_with_matches(
    message,
    term: str,
    bot_username: str = "",
    charge_user_id: int | None = None,
    search_id: int | None = None,
) -> int:
    """
    جست‌وجوی متنی و فرستادن نتیجه‌ها.

    از دو جا فراخوانده می‌شود: نوشتار ساده‌ای که کاربر می‌فرستد، و
    نامی که پس از ناکامی اثر انگشت می‌دهد. یک تن بودنشان بایسته
    است — وگرنه دیر یا زود یکی‌شان از دیگری وامی‌ماند و کاربر
    نمی‌فهمد چرا همان نام از یک راه نتیجه می‌دهد و از راه دیگر نه.

    بازگشتی: شمار نواهای یافته‌شده.
    """
    if len(term) < MIN_QUERY_LENGTH:
        await message.reply_html(texts.msg("text_search_too_short"))
        return 0

    found = database.search_tracks_by_text(term, limit=10)

    # ── واپسین کوشش: بیتی از شعر ────────────────────────────
    #
    # جست‌وجوی بالا عبارت را **یکپارچه** می‌جوید. کسی که بیتی را
    # به یاد دارد، عیناً به یاد ندارد — واژه‌ای را جابه‌جا
    # می‌گوید یا «که» و «را» را می‌اندازد. پس اگر چیزی نیامد،
    # همان واژه‌ها جدا-جدا در متنِ نواها سنجیده می‌شوند.
    #
    # تنها برای عبارتِ چندواژه‌ای: یک واژهٔ تنها در متنِ چند هزار
    # نوا، هر چیزی را برمی‌گرداند.
    if not found and len(term.split()) >= 2:
        found = database.search_tracks_by_lyrics(term, limit=10)
        if found:
            logger.info("عبارت «%s» از راهِ متنِ نوا یافت شد.", term[:40])

    if not found:
        await message.reply_html(
            texts.msg("text_search_empty", term=term), reply_markup=reply.main_menu()
        )
        return 0

    await message.reply_html(
        texts.msg(
            "text_search_results",
            term=term,
            count=to_persian_digits(str(len(found))),
        )
    )

    # نواها یکی‌یکی فرستاده می‌شوند تا کاربر بتواند هر کدام را
    # جداگانه نگه دارد یا بازفرستد.
    for track in found[:5]:
        try:
            from services.tagger import audio_labels

            database.bump_sent_count(int(track["id"]))
            await message.reply_audio(
                audio=track["file_id"],
                caption=texts.msg(
                    "text_search_item",
                    madah=track["madah"] or "نامعلوم",
                    style=track["style"] or "—",
                    duration=format_duration(track["duration"]),
                ),
                parse_mode="HTML",
                protect_content=True,
                # «درست است / این نیست» — همان دکمه‌هایی که زیر
                # یافتهٔ اثر انگشت هستند. بی این‌ها، سکه‌ای که این
                # جست‌وجو می‌ستاند راهِ بازگشتی نداشت — و اکنون
                # قفلِ فایل هم با همان‌ها برداشته می‌شود.
                reply_markup=(
                    inline.search_result(search_id)
                    if search_id is not None
                    else None
                ),
                **audio_labels(track),
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("فرستادن نوای %s شکست خورد: %s", track["id"], exc)

    if len(found) > 5:
        await message.reply_html(
            texts.msg(
                "text_search_more",
                more=to_persian_digits(str(len(found) - 5)),
                bot=bot_username,
            ),
            reply_markup=reply.main_menu(),
        )

    # سکه پس از رسیدنِ نوا برداشته می‌شود، نه پیش از آن — همان
    # ترتیبی که جست‌وجوی صوتی دارد. یک سکه برای کلِ این جست‌وجو،
    # نه برای هر نوا.
    if charge_user_id is not None:
        _charge(charge_user_id, term, search_id)
        if search_id is not None:
            # «fulfilled» نه «found»: کارِ موتور اثر انگشت نبود و
            # آمارِ موتور نباید این را به حساب خودش بگذارد.
            searches.finish(
                search_id, "fulfilled", matched_track_id=int(found[0]["id"])
            )

    return len(found)


def _charge(user_id: int, term: str, search_id: int | None = None) -> None:
    """سکهٔ یک جست‌وجوی نامیِ کامیاب."""
    from core.db.database import InsufficientTokens

    try:
        balance = database.adjust_tokens(
            user_id,
            -config.token_cost_per_search,
            reason="search",
            ref_type="search",
            ref_id=search_id,
            note=f"جست‌وجوی نام: {term[:60]}",
        )
        if search_id is not None:
            # بی این نشان، «این نیست» سکه را بازنمی‌گرداند.
            searches.mark_charged(search_id)
        logger.info("سکهٔ کاربر %s پس از جست‌وجوی نامی شد %s.", user_id, balance)
    except InsufficientTokens:
        logger.warning("کاربر %s سکه نداشت ولی نتیجهٔ نامی گرفت.", user_id)
    except Exception:  # noqa: BLE001
        logger.exception("برداشتن سکهٔ جست‌وجوی نامیِ %s نشد.", user_id)


# ═════════════════════════════════════════════════════════════
#  حالت درون‌خطی
# ═════════════════════════════════════════════════════════════

async def on_inline_query(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    کاربر در گفتگویی دیگر ‎@YourBot ...‎ نوشته است.

    نکتهٔ سنجش دسترسی: در حالت درون‌خطی نمی‌توان کاربر را به منو
    فرستاد یا پیام بلند داد؛ تنها می‌توان نتیجه‌ای نمایاند. پس
    کاربر تأییدنشده، یک «نتیجهٔ» راهنما می‌بیند که او را به ربات
    می‌خواند — نه خاموشی که سردرگمش کند.
    """
    query = update.inline_query
    if query is None:
        return

    user = query.from_user
    record = database.get_user(user.id) if user else None

    if record is None or not record["is_verified"] or record["is_banned"]:
        await query.answer(
            results=[],
            cache_time=10,
            is_personal=True,
            button=_start_button(context),
        )
        return

    term = (query.query or "").strip()

    if len(term) < MIN_QUERY_LENGTH:
        await query.answer(
            results=[_hint_article()],
            cache_time=60,
            is_personal=True,
        )
        return

    found = database.search_tracks_by_text(term, limit=MAX_INLINE_RESULTS)

    results = [
        InlineQueryResultCachedAudio(
            id=str(track["id"]),
            audio_file_id=track["file_id"],
            caption=texts.msg(
                "inline_caption",
                madah=track["madah"] or "نامعلوم",
                style=track["style"] or "—",
                bot=context.bot.username or "",
            ),
            parse_mode="HTML",
        )
        for track in found
        if track["file_id"]
    ]

    if not results:
        results = [_empty_article(term)]

    await query.answer(results=results, cache_time=60, is_personal=True)
    logger.debug("بازجویی درون‌خطی «%s» -> %s نتیجه", term, len(results))


def _start_button(context):
    """
    دکمه‌ای که کاربر تأییدنشده را به ربات می‌خواند.

    برخی نسخه‌های کتابخانه این پارامتر را ندارند؛ نبودنش نباید
    بازجویی را بشکند.
    """
    try:
        from telegram import InlineQueryResultsButton

        return InlineQueryResultsButton(
            text=texts.messages.raw("inline_need_start"), start_parameter="inline",
        )
    except ImportError:  # pragma: no cover
        return None


def _hint_article() -> InlineQueryResultArticle:
    return InlineQueryResultArticle(
        id="hint",
        title=texts.messages.raw("inline_hint_title"),
        description=texts.messages.raw("inline_hint_body"),
        input_message_content=InputTextMessageContent(
            message_text=texts.messages.raw("inline_hint_body")
        ),
    )


def _empty_article(term: str) -> InlineQueryResultArticle:
    return InlineQueryResultArticle(
        id="empty",
        title=texts.messages.raw("inline_empty_title"),
        description=texts.msg("inline_empty_body", term=term),
        input_message_content=InputTextMessageContent(
            message_text=texts.msg("inline_empty_body", term=term)
        ),
    )
