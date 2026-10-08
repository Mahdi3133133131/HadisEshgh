"""
بازجویی نوا — کاری که همهٔ کاربران به خاطرش این ربات را می‌گشایند.

## جریان

کاربر تکه‌ای می‌فرستد ← پرسش «نام مداح را می‌دانید؟» ← جست‌وجو در
گنجینه ← نتیجه با درصد همانندی و دو دکمه.

## سکه

سکه تنها هنگامی برداشته می‌شود که نوایی **یافته و فرستاده شود**.
اگر کاربر «این آن نیست» را بنوازد، سکه بازمی‌گردد؛ چون خطای ما
بوده است، نه او.

## چهار چیز که پس از آزمون زندهٔ کاربر دگرگون شد

۱) **پرسش نام مداح، پیش از جست‌وجو.** اگر کاربر نام را بداند، هم
   جست‌وجوی متنی ممکن می‌شود و هم گزارش ناکامی به گردانندگان معنا
   پیدا می‌کند — که وگرنه تنها یک شناسهٔ عددی می‌دیدند.

۲) **آوای استخراجی، تنها هنگام نیاز.** پیش‌تر آوای هر نماهنگ *پیش
   از* جست‌وجو فرستاده می‌شد. اگر نسخهٔ اصلی یافته می‌شد، آن پیام
   زائد بود. اکنون استخراج انجام می‌گیرد ولی فایل نگه داشته می‌شود؛
   تنها هنگام ناکامی — یا هنگامی که کاربر بگوید «این آن نیست» —
   فرستاده می‌شود.

۳) **گمانهٔ نواهای همانند هرگز خودکار فرستاده نمی‌شود.** پیش‌تر تا
   دو نوا بی‌پرسش می‌رفت و با گنجینهٔ کوچک، نتیجه‌اش این بود که
   کاربرِ یک بازجویی ناکام، هر چه در گنجینه بود را می‌گرفت. اکنون
   فهرست با دکمه پیش گذاشته می‌شود و گزینش با اوست.

۴) **ناکامی با خودِ کلیپ به گروه گردانندگان می‌رود**، با دکمه‌ای که
   هر گرداننده‌ای بتواند نسخهٔ کامل را بفرستد.

## آنچه این موتور نمی‌تواند

اثر انگشت تنها **همان ضبط** را می‌یابد. اگر کاربر تکه‌ای از اجرای
زنده بفرستد و در گنجینه نسخهٔ دیگری باشد، چیزی یافت نمی‌شود — هرچند
گوش انسان هر دو را یک نوا بشمارد. پیام «یافت نشد» باید همین را
با فروتنی برساند.
"""

from __future__ import annotations

import hashlib
import logging
import shutil
import time
from pathlib import Path

from telegram import Update
from telegram.error import BadRequest, TelegramError
from telegram.ext import ContextTypes

from bot.guards import answer_quietly, require_verified
from bot.keyboards import inline, reply
from bot.states import (
    AWAITING_HINT_AFTER_FAIL,
    AWAITING_SEARCH_HINT,
    AWAITING_SEARCH_INPUT,
    clear_state,
    get_data,
    set_state,
)
from config import config
from core import effects, net, texts
from core.audio import matcher
from core.audio.decode import (
    DecodeError,
    extract_audio,
    has_audio_stream,
    probe_duration,
)
from core.audio.fingerprint import (
    QUERY_RATES,
    SAMPLE_RATE,
    FingerprintError,
    fingerprint,
    fingerprint_query,
)
from core.db import database, searches
from core.db.database import InsufficientTokens
from core.normalize import fix_characters, format_duration, to_persian_digits
from services import instagram
from worker.queue import get_queue

logger = logging.getLogger(__name__)

# فرو گرفتن از تلگرام سقف دارد؛ فراتر از آن پیام روشن داده می‌شود.
MAX_INPUT_BYTES = 20 * 1024 * 1024

# آوای استخراج‌شده تا این هنگام نگه داشته می‌شود، تا اگر کاربر
# «این آن نیست» را نواخت، بی‌درنگ فرستاده شود.
CLIP_KEEP_HOURS = 12


def clip_path(search_id: int) -> Path:
    """جای نگهداری آوای استخراجی این بازجویی."""
    return config.tmp_dir / f"clip_{search_id}.mp3"


@require_verified
async def begin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    user = update.effective_user
    if message is None or user is None:
        return

    balance = database.get_tokens(user.id)
    if balance <= 0:
        clear_state(context.user_data)
        await show_empty_purse(message, user.id)
        return

    set_state(context.user_data, AWAITING_SEARCH_INPUT)
    await message.reply_html(
        texts.msg("search_ask", tokens=to_persian_digits(str(balance)))
    )


async def nudge(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    کاربر بی‌مقدمه چیزی فرستاده؛ راه درست را نشان می‌دهد.

    ## چرا دیگر خودکار نمی‌گردیم

    پیش‌تر هر آوا یا نماهنگی که در گفتگوی خصوصی می‌رسید، خودش
    جست‌وجوی کامل راه می‌انداخت — با این استدلال که «واداشتن کاربر
    به زدن دکمه، آزردن اوست». ولی نتیجه‌اش این بود که فرستادن یک
    فایل برای هر کاری — پیشکش، پرسش، یا حتی اشتباهی — جست‌وجو
    می‌شد و سکه در خطر می‌افتاد. اکنون آغازِ جست‌وجو یک تصمیمِ روشن
    است.

    دکمهٔ میان‌بر زیر پیام هست تا این سخت‌گیری، یک گام اضافه نشود.
    """
    message = update.effective_message
    if message is None:
        return
    clear_state(context.user_data)
    await message.reply_html(
        texts.msg("search_nudge"), reply_markup=inline.start_search()
    )


async def on_begin_tap(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """میان‌بر «پیدا کردن مداحی» از زیر پیام راهنما."""
    query = update.callback_query
    if query is None:
        return
    if query.message is None:
        await answer_quietly(query)
        return
    try:
        await query.answer()
    except TelegramError as exc:
        logger.debug("پاسخ نواخت آغاز جست‌وجو نرسید: %s", exc)
    try:
        await query.edit_message_reply_markup(reply_markup=None)
    except TelegramError:
        pass
    await begin(update, context)


async def show_empty_purse(message, user_id: int) -> None:
    """
    کیسهٔ تهی را نشان می‌دهد — با موجودی و راه‌های افزودن.

    از همان تابعی می‌آید که پنل کیسه به کار می‌برد، تا کاربرِ
    بی‌سکه همان اندازه بداند که کاربرِ باسکه.
    """
    from bot.handlers.tokens import purse_text

    await message.reply_html(purse_text(user_id), reply_markup=reply.main_menu())


# ═════════════════════════════════════════════════════════════
#  گام یکم: گرفتن ورودی و پرسیدن نام مداح
# ═════════════════════════════════════════════════════════════

@require_verified
async def on_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    تکهٔ فرستاده‌شده را می‌گیرد و پیش از جست‌وجو، نام مداح را می‌پرسد.

    نگهبان `require_verified` اینجا هم بایسته است، نه تنها روی
    `begin`: مسیریاب در چند جا یک‌راست همین را می‌خواند، و کاربری
    که تنها /start زده و عضویتش تأیید نشده، سکهٔ آغازینش را از پیش
    گرفته است — پس بی این نگهبان می‌توانست بی تأیید عضویت بجوید.

    خودِ ورودی هنوز فرو گرفته نمی‌شود؛ تنها شناسه‌اش نگه داشته
    می‌شود. اگر کاربر پاسخ ندهد و برود، هیچ پردازش گرانی هدر نرفته
    است.
    """
    message = update.effective_message
    user = update.effective_user
    if message is None or user is None:
        return

    link = instagram.find_url(message.text or message.caption)
    media = None

    if link:
        if not instagram.is_available():
            await message.reply_html(texts.msg("instagram_unavailable"))
            return
        kind = "instagram"
    else:
        media = message.audio or message.voice or message.video or message.video_note
        if media is None and message.document is not None:
            media = message.document
        if media is None:
            # نوشتار ساده، پس از زدن دکمهٔ جست‌وجو: نام مداح یا بیتی
            # از شعر. جست‌وجوی متنی در آرشیو، رایگان و بی سکه.
            #
            # این شاخه از آن روز بایسته شد که جست‌وجو پشت دکمه رفت:
            # پیش‌تر نوشتار از خودِ مسیریاب به جست‌وجوی متنی می‌رسید،
            # و بی این، آن راه یکسره بسته می‌شد.
            text = (message.text or "").strip()
            if 2 <= len(text) <= 60 and not text.startswith("/"):
                clear_state(context.user_data)
                from bot.handlers import inline_query

                await inline_query.on_text_search(update, context)
                return
            await message.reply_html(texts.msg("search_unsupported"))
            return

        file_size = getattr(media, "file_size", None) or 0
        if file_size > MAX_INPUT_BYTES and not config.local_bot_api_url:
            await message.reply_html(texts.msg("search_too_big"))
            return

        # سندی که گونه‌اش ویدیوست، ویدیوست.
        #
        # فایلِ MP4 که «به‌صورت فایل» فرستاده شود در `document`
        # می‌نشیند و پیش‌تر «صوت» شمرده می‌شد؛ آنگاه صدا از آن
        # بیرون کشیده نمی‌شد.
        doc_mime = (getattr(message.document, "mime_type", "") or "").lower()
        kind = (
            "video"
            if (message.video or message.video_note or doc_mime.startswith("video/"))
            else "audio"
        )

    if database.get_tokens(user.id) <= 0:
        clear_state(context.user_data)
        await show_empty_purse(message, user.id)
        return

    search_id = searches.create(
        user_id=user.id,
        input_kind=kind,
        input_file_id=getattr(media, "file_id", None),
        input_duration=getattr(media, "duration", None),
        query_text=link,
    )

    set_state(
        context.user_data,
        AWAITING_SEARCH_HINT,
        search_id=search_id,
        kind=kind,
        file_id=getattr(media, "file_id", None),
        link=link,
        # برچسبِ خودِ فایل، برای وقتی که کاربر نامی ندهد. اینجا
        # برداشته می‌شود چون `media` تنها همین‌جا در دست است.
        tag_term=_term_from_tags(media, message.caption),
    )

    await message.reply_html(
        texts.msg("search_ask_hint"), reply_markup=inline.hint_skip()
    )


def _term_from_tags(media, caption: str | None) -> str | None:
    """
    عبارتی برای جست‌وجوی سایت، از برچسبِ خودِ فایل.

    ## چرا این هست

    تا امروز وقتی اثر انگشت ناکام می‌ماند و کاربر نامی نداده بود،
    ربات یکسره «متأسفم» می‌گفت و **هیچ سایتی را نمی‌پرسید** —
    یعنی برای اصلی‌ترین کاربردش («کلیپ می‌فرستم، کاملش را بده»)
    جست‌وجوی سایت هرگز اجرا نمی‌شد.

    ولی نامی در دست هست: تلگرام برچسب ID3 را با پیام می‌آورد، و
    کپشن هم اغلب نام مداح دارد. `captions.read` همان را
    بیرون می‌کشد و از زنجیرهٔ نامِ فارسی هم می‌گذراند.

    بازگشتی None است اگر راستی چیزی نبود — آنگاه مثل امروز از
    کاربر پرسیده می‌شود.
    """
    if media is None:
        return None
    try:
        from services.captions import read as read_tags

        madah, title = read_tags(media, caption)
    except Exception:  # noqa: BLE001
        logger.debug("برداشتنِ برچسبِ فایل نشد.", exc_info=True)
        return None

    parts = [p.strip() for p in (madah, title) if p and p.strip()]
    if not parts:
        return None

    term = " ".join(parts)[:80].strip()
    # `websearch.offer` زیر سه نویسه را رد می‌کند؛ همان‌جا هم
    # سنجیده می‌شود ولی اینجا زودتر می‌فهمیم.
    return term if len(term) >= 3 else None


async def begin_for_file(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    file_id: str,
    duration: int | None = None,
) -> None:
    """
    بازجویی بر پایهٔ فایلی که از پیش در دست داریم.

    یک راه دارد: نوای بازفرستادهٔ گرداننده، که چون خواستش روشن
    نبود از او پرسیده شد و او «این را بجو» را برگزید. از اینجا به
    بعد هیچ فرقی با بازجویی معمولی ندارد.
    """
    message = update.effective_message
    user = update.effective_user
    if message is None or user is None:
        return

    if database.get_tokens(user.id) <= 0:
        clear_state(context.user_data)
        await show_empty_purse(message, user.id)
        return

    search_id = searches.create(
        user_id=user.id,
        input_kind="audio",
        input_file_id=file_id,
        input_duration=duration,
    )
    set_state(
        context.user_data,
        AWAITING_SEARCH_HINT,
        search_id=search_id,
        kind="audio",
        file_id=file_id,
        link=None,
    )
    await message.reply_html(
        texts.msg("search_ask_hint"), reply_markup=inline.hint_skip()
    )


async def on_hint(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """کاربر نام مداح یا بیتی از شعر را نوشت؛ اکنون می‌جوییم."""
    message = update.effective_message
    if message is None or not message.text:
        return

    data = dict(get_data(context.user_data))
    search_id = data.get("search_id")
    if search_id is None:
        clear_state(context.user_data)
        return

    hint = fix_characters(message.text.strip())[:120]
    searches.set_hint(int(search_id), hint)
    clear_state(context.user_data)

    await message.reply_html(texts.msg("search_hint_saved"))
    await _launch(message, context, data, hint=hint)


async def on_hint_skip(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """«نمی‌دانم» — بی‌درنگ می‌جوییم."""
    query = update.callback_query
    if query is None:
        return
    if query.message is None:
        await answer_quietly(query)
        return

    data = dict(get_data(context.user_data))
    await query.answer()
    try:
        await query.edit_message_reply_markup(reply_markup=None)
    except TelegramError:
        pass

    if not data.get("search_id"):
        return

    clear_state(context.user_data)
    await _launch(query.message, context, data, hint=None)


async def _launch(message, context, data: dict, hint: str | None) -> None:
    """جریان بازجویی را بر پایهٔ آنچه کاربر فرستاده بود می‌راند."""
    if data.get("kind") == "instagram":
        await _run_instagram(message, context, data, hint)
    else:
        await _run_media(message, context, data, hint)


# ═════════════════════════════════════════════════════════════
#  گام دوم: جست‌وجو
# ═════════════════════════════════════════════════════════════

async def _run_media(message, context, data: dict, hint: str | None) -> None:
    """بازجویی از آوا یا نماهنگ فرستاده‌شده."""
    user_id = message.chat_id
    search_id = int(data["search_id"])
    file_id = data.get("file_id")
    is_video = data.get("kind") == "video"

    status = await message.reply_html(texts.msg("search_checking"))

    temp_path = config.tmp_dir / f"query_{user_id}_{search_id}.bin"
    extracted: Path | None = None
    started = time.monotonic()

    try:
        try:
            # ── چرا کوششِ دوباره، و چرا تفکیکِ خطا ────────────
            #
            # پیش‌تر اینجا یک `except TelegramError` بود که
            # **همه‌چیز** را «فایلت بزرگ است» گزارش می‌کرد.
            # `TelegramError` ریشهٔ همهٔ خطاهای تلگرام است —
            # `NetworkError`، `TimedOut`، `RemoteProtocolError`.
            #
            # و این پیوند راستی می‌شکند: در لاگ‌های خودِ پروژه
            # `httpx.ReadError` هست که بی‌درنگ به کاربر «زیاده»
            # گفته شد. کاربر ویدیوی ۱۰ مگی فرستاده بود و سقف
            # ۲۰ مگابایت است — یعنی پیام از بن دروغ بود.
            #
            # همان الگوی `services/indexer.py` اینجا هم می‌آید:
            # کوششِ دوباره، و جدا کردنِ حجمِ راستین از لغزشِ شبکه.
            handle = await net.retry(
                lambda: context.bot.get_file(file_id),
                attempts=config.network_retries,
                label="گرفتن نشانی ورودی کاربر",
            )
            await net.retry(
                lambda: handle.download_to_drive(custom_path=temp_path),
                attempts=config.network_retries,
                label="فرو گرفتن ورودی کاربر",
            )
        except TelegramError as exc:
            logger.warning("فرو گرفتن ورودی کاربر %s شکست خورد: %s", user_id, exc)
            oversized = "too big" in str(exc).lower()
            await status.edit_text(
                texts.msg("search_too_big" if oversized else "search_network_failed"),
                parse_mode="HTML",
            )
            return

        if not has_audio_stream(temp_path):
            await status.edit_text(texts.msg("search_no_audio"), parse_mode="HTML")
            return

        input_duration = probe_duration(temp_path)
        digest = await _hash_file(temp_path)
        database.execute(
            "UPDATE searches SET input_sha256 = ?, input_duration = ? WHERE id = ?",
            (digest, int(input_duration) if input_duration else None, search_id),
        )

        # ── آوای نماهنگ: استخراج آری، فرستادن نه ─────────────
        # تا هنگامی که ندانیم نسخهٔ اصلی یافت می‌شود یا نه،
        # فرستادنش زائد است. نگه داشته می‌شود تا اگر نیاز شد
        # بی‌درنگ برود.
        if is_video:
            await status.edit_text(texts.msg("search_extracting"), parse_mode="HTML")
            extracted = clip_path(search_id)
            try:
                await get_queue().run(extract_audio, temp_path, extracted)
            except DecodeError as exc:
                logger.warning("استخراج صوت شکست خورد: %s", exc)
                extracted = None

        # ── کش ───────────────────────────────────────────────
        cached = searches.find_cached(digest)
        if cached is not None and cached["matched_track_id"]:
            track = database.get_track(int(cached["matched_track_id"]))
            if track is not None:
                await status.edit_text(texts.msg("search_seeking"), parse_mode="HTML")
                confidence = float(cached["confidence"] or 0.9)
                await _deliver(message, context, search_id, track, confidence)
                searches.finish(
                    search_id, "found",
                    matched_track_id=int(track["id"]),
                    confidence=confidence,
                    duration_ms=int((time.monotonic() - started) * 1000),
                )
                await _safe_delete(status)
                return

        # ── جست‌وجوی راستین ──────────────────────────────────
        queue = get_queue()
        estimate = queue.wait_estimate_seconds()
        await status.edit_text(
            texts.msg(
                "search_seeking_eta",
                seconds=to_persian_digits(str(int(estimate))),
            ) if estimate > 0 else texts.msg("search_seeking"),
            parse_mode="HTML",
        )

        try:
            found = await queue.run(_fingerprint_and_match, str(temp_path))
        except (DecodeError, FingerprintError) as exc:
            logger.info("پردازش ورودی کاربر %s شکست خورد: %s", user_id, exc)
            searches.finish(search_id, "failed", error_message=str(exc))
            await status.edit_text(
                texts.msg(_failure_message(exc)), parse_mode="HTML"
            )
            return

        elapsed_ms = int((time.monotonic() - started) * 1000)
        track = database.get_track(found.track_id) if found is not None else None

        if track is None:
            searches.finish(search_id, "not_found", duration_ms=elapsed_ms)
            # پیام وضعیت **پاک** می‌شود، نه ویرایش.
            #
            # پیش‌تر همین‌جا ویرایش می‌شد و متنِ «پیدا نشد» به جای
            # پیام وضعیتی می‌نشست که در همان آغاز کار ساخته شده
            # بود — یعنی بالاتر از هر چیزی که پس از آن می‌آمد. پس
            # کاربر نخست پایانِ کار را می‌دید و سپس گشتن در
            # سایت‌ها را؛ و متنی که می‌گفت «صدای ویدیو را بالا
            # فرستادم» به چیزی اشاره می‌کرد که پایین‌تر بود.
            await _safe_delete(status)
            # به کاربر گفته نمی‌شود «در آرشیو نبود».
            #
            # او نمی‌داند آرشیو ما چیست و برایش هم مهم نیست؛ تنها
            # می‌خواهد فایلش را بگیرد. خبر دادن از هر پلهٔ درونی،
            # انتظارِ بی‌سبب می‌سازد. پس یک‌راست سراغ اینترنت
            # می‌رویم و تنها پایانِ کار گفته می‌شود — آن هم همراهِ
            # صوتِ خودِ کلیپ، تا دست‌خالی نرود.
            await _after_failure(
                message, context, search_id, str(temp_path), hint, input_duration
            )
            return

        searches.finish(
            search_id, "found",
            matched_track_id=found.track_id,
            confidence=found.confidence,
            duration_ms=elapsed_ms,
        )
        await _deliver(message, context, search_id, track, found.confidence, found)
        await _safe_delete(status)

    finally:
        temp_path.unlink(missing_ok=True)
        # فایل استخراجی **پاک نمی‌شود**؛ اگر کاربر بگوید «این آن
        # نیست» همان را می‌فرستیم. کار دوره‌ای sweep_clips برش
        # می‌دارد.


async def _run_instagram(message, context, data: dict, hint: str | None) -> None:
    """
    بازجویی از راه نشانی اینستاگرام.

    خودِ نماهنگ تنها هنگام ناکامی فرستاده می‌شود؛ اگر نسخهٔ اصلی را
    یافتیم، بازفرستادن همان چیزی که کاربر پیوندش را داده نویز است.
    """
    user_id = message.chat_id
    search_id = int(data["search_id"])
    link = data.get("link") or ""

    status = await message.reply_html(texts.msg("instagram_downloading"))
    folder = config.tmp_dir / f"ig_{user_id}_{search_id}"
    started = time.monotonic()

    try:
        try:
            video = await get_queue().run(instagram.download, link, folder)
        except instagram.InstagramError as exc:
            logger.info(
                "فرو گرفتن اینستاگرام شکست خورد (%s): %s", exc.message_key, exc.detail
            )
            await status.edit_text(texts.msg(exc.message_key), parse_mode="HTML")
            return

        await status.edit_text(texts.msg("instagram_analyzing"), parse_mode="HTML")

        if not has_audio_stream(video.path):
            searches.finish(search_id, "failed", error_message="بی آوا")
            await status.edit_text(texts.msg("search_no_audio"), parse_mode="HTML")
            return

        digest = await _hash_file(video.path)
        database.execute(
            "UPDATE searches SET input_sha256 = ?, input_duration = ? WHERE id = ?",
            (digest, int(video.duration) if video.duration else None, search_id),
        )

        # آوا همین‌جا استخراج و نگه داشته می‌شود — چه بیابیم چه نه.
        #
        # نه به این سبب که می‌خواهیم بفرستیمش؛ اگر بیابیم نمی‌فرستیم.
        # به این سبب که پوشهٔ نماهنگ در پایان همین تابع برداشته
        # می‌شود، و بر خلاف آوای تلگرامی، نماهنگ اینستاگرام
        # input_file_id ندارد که بعدها بتوان دگربار از آن استخراج
        # کرد. پس اگر اکنون نگیریمش، وعدهٔ «با نواختن بر این آن
        # نیست، آوا را می‌فرستیم» شکستنی می‌شود.
        clip = clip_path(search_id)
        try:
            await get_queue().run(extract_audio, video.path, clip)
        except DecodeError as exc:
            logger.warning("استخراج آوای اینستاگرام شکست خورد: %s", exc)
            clip = None

        cached = searches.find_cached(digest)
        if cached is not None and cached["matched_track_id"]:
            track = database.get_track(int(cached["matched_track_id"]))
            if track is not None:
                confidence = float(cached["confidence"] or 0.9)
                await _deliver(message, context, search_id, track, confidence)
                searches.finish(
                    search_id, "found",
                    matched_track_id=int(track["id"]),
                    confidence=confidence,
                    duration_ms=int((time.monotonic() - started) * 1000),
                )
                await _safe_delete(status)
                return

        await status.edit_text(texts.msg("instagram_seeking"), parse_mode="HTML")

        try:
            found = await get_queue().run(_fingerprint_and_match, str(video.path))
        except (DecodeError, FingerprintError) as exc:
            searches.finish(search_id, "failed", error_message=str(exc))
            await status.edit_text(texts.msg("search_too_short"), parse_mode="HTML")
            return

        elapsed_ms = int((time.monotonic() - started) * 1000)
        track = database.get_track(found.track_id) if found is not None else None

        if track is None:
            searches.finish(search_id, "not_found", duration_ms=elapsed_ms)

            # همان ترتیبِ مسیر آوا: نخست پیام وضعیت پاک می‌شود تا
            # هرچه پس از آن می‌آید به ترتیبِ رسیدن بنشیند.
            await _safe_delete(status)

            # خودِ نماهنگ فرستاده می‌شود چون کاربر تنها پیوندی داده
            # بود و فایلی در دست ندارد. آوایش ولی نه: آن، همراهِ
            # پیام پایانی می‌رود.
            try:
                with video.path.open("rb") as handle:
                    await message.reply_video(
                        video=handle,
                        caption=texts.msg("instagram_video_caption"),
                        parse_mode="HTML",
                    )
            except (OSError, TelegramError) as exc:
                logger.warning("فرستادن نماهنگ اینستاگرام شکست خورد: %s", exc)

            await _after_failure(
                message, context, search_id, str(video.path), hint, video.duration
            )
            return

        searches.finish(
            search_id, "found",
            matched_track_id=found.track_id,
            confidence=found.confidence,
            duration_ms=elapsed_ms,
        )
        await _deliver(message, context, search_id, track, found.confidence, found)
        await _safe_delete(status)

    finally:
        shutil.rmtree(folder, ignore_errors=True)


# ═════════════════════════════════════════════════════════════
#  پس از ناکامی
# ═════════════════════════════════════════════════════════════

async def _after_failure(
    message, context, search_id: int, audio_path: str, hint: str | None, duration
) -> None:
    """
    کارهای پس از ناکامی، به همین ترتیب — و ترتیب، خودش بخشی از
    کار است.

    ۱) اگر کاربر نامی نداده، همین‌جا می‌پرسیم و بقیهٔ کار پس از
       پاسخش دنبال می‌شود. بی نام، نه جست‌وجوی متنی معنا دارد و نه
       گشتن در سایت‌ها.
    ۲) با همان نام در **آرشیو خودمان** می‌گردیم — رایگان، و بسیار
       کاراتر از گمانهٔ آوایی.
    ۳) اگر آرشیو چیزی نداشت، سراغ **سایت‌ها** می‌رویم. وارونه‌اش
       بی‌معناست: چیزی که خودمان داریم نباید از بیرون آورده شود.
    ۴) اگر سایت‌ها هم چیزی نداشتند: گمانهٔ نواهای همانند، و سپس
       پیام پایانی با دو دکمه.
    ۵) گزارش به گردانندگان، با خودِ کلیپ و دکمهٔ پرکردن.

    اگر سایت‌ها پیش‌نمایشی فرستاده باشند، پیام پایانی **اینجا**
    نمی‌آید: کاربر هنوز باید داوری کند، و «متأسفم» پیش از داوری،
    هم زودهنگام است و هم دروغ. آن پیام را websearch پس از رد شدن
    هر سه پیش‌نمایش می‌فرستد.
    """
    if not hint:
        # ── پیش از تسلیم: برچسبِ خودِ فایل ──────────────────
        #
        # کاربر نامی نداده، ولی فایل معمولاً خودش نام دارد. این
        # همان جایی بود که جست‌وجوی سایت هرگز صدا نمی‌شد.
        tag_term = get_data(context.user_data).get("tag_term")
        if tag_term:
            logger.info(
                "بازجویی %s نامی نداشت؛ با برچسبِ «%s» سراغ سایت‌ها می‌رویم.",
                search_id, tag_term,
            )
            await _continue_with_hint(
                message, context, search_id, tag_term, audio_path
            )
            await _report_failure(context, search_id, tag_term, duration)
            return

        # بی نام، نه جست‌وجوی متنی شدنی است و نه گشتن در اینترنت.
        # پس همین‌جا پایانِ کار گفته می‌شود — با صوت و دکمه‌ها، تا
        # کاربر دست‌خالی نماند — و نام هم پرسیده می‌شود تا اگر
        # گفت، دگربار بگردیم.
        await _report_failure(context, search_id, hint, duration)
        await send_sorry(context, message.chat_id, search_id)
        set_state(context.user_data, AWAITING_HINT_AFTER_FAIL, search_id=search_id)
        await message.reply_html(texts.msg("search_ask_hint_after_fail"))
        return

    await _continue_with_hint(message, context, search_id, hint, audio_path)
    await _report_failure(context, search_id, hint, duration)


async def _continue_with_hint(
    message, context, search_id: int | None, hint: str, audio_path: str | None = None
) -> None:
    """
    دو پلهٔ گشتن با نام، و پایانش.

    هم از `_after_failure` خوانده می‌شود و هم از `on_hint_after_fail`
    — چون هر دو یک کار می‌کنند و دوباره‌نویسی‌اش یعنی روزی یکی از
    آن دو عوض شود و دیگری نه.
    """
    if await _text_search_fallback(message, context, hint, search_id):
        return

    # «در اینترنت می‌گردم» خبرِ لحظه است، نه چیزی که باید بماند.
    # ماندنش، پیامِ ناکامی را از دو پیام به سه می‌رساند — و
    # کاربر از همین انباشت گلایه کرد، نه از بلندیِ یک متن.
    waiting = await message.reply_html(texts.msg("search_asking_sites"))
    try:
        if await _offer_sites(message, context, hint, search_id):
            return  # پیش‌نمایش رفت؛ پیام پایانی پس از داوری کاربر
    finally:
        await _safe_delete(waiting)

    if audio_path:
        await _offer_similar(message, audio_path)
    await send_sorry(context, message.chat_id, search_id)


async def send_sorry(context, chat_id: int, search_id: int | None) -> None:
    """
    پایانِ کار: صوتِ خودِ کلیپ، با پیام و دو دکمه زیرش.

    ## چرا صوت و پیام یکی‌اند

    کاربر خواست که وقتی چیزی پیدا نشد، دست‌خالی نرود و صوتِ همان
    کلیپی که فرستاده به او برسد — و دکمه‌ها زیرِ همان باشند. پس
    به جای سه پیام جدا (متن، صوت، دکمه‌ها)، یک صوت با زیرنویس و
    صفحه‌کلید می‌رود.

    اگر ورودی خودش آوا بوده، کلیپی برای دادن نیست — کاربر از پیش
    داردش — و تنها متن می‌رود.

    بیرون از این پرونده هم خوانده می‌شود (websearch، پس از رد شدن
    همهٔ پیش‌نمایش‌ها)، پس عمومی است.
    """
    record = searches.get(int(search_id)) if search_id else None
    keyboard = inline.not_found_actions(search_id)

    clip = await _ensure_clip(context, record) if record is not None else None
    if clip is not None:
        try:
            with clip.open("rb") as handle:
                await net.retry(
                    lambda: context.bot.send_audio(
                        chat_id=chat_id,
                        audio=handle,
                        caption=texts.msg("search_sorry"),
                        parse_mode="HTML",
                        title="صدای کلیپ شما",
                        reply_markup=keyboard,
                        read_timeout=config.read_timeout,
                        write_timeout=config.write_timeout,
                        connect_timeout=config.connect_timeout,
                    ),
                    label="فرستادن پایانِ ناکامی",
                )
            return
        except (OSError, TelegramError) as exc:
            logger.warning("فرستادن صوتِ پایانی نشد: %s", exc)

    try:
        await net.say(
            context.bot,
            chat_id,
            texts.msg("search_sorry_no_clip"),
            reply_markup=keyboard,
        )
    except TelegramError as exc:
        logger.warning("پیام پایانی ناکامی فرستاده نشد: %s", exc)


async def _ensure_clip(context, record):
    """
    آوای استخراجیِ یک بازجویی را آماده می‌کند؛ None اگر نشد.

    نخست فایل کش‌شده آزموده می‌شود؛ اگر رُفت‌وروب برش داشته باشد،
    از همان چیزی که کاربر فرستاده بود دگربار استخراج می‌کنیم — تا
    گذر زمان، این وعده را نشکند.
    """
    if record["input_kind"] not in ("video", "instagram"):
        return None  # ورودی خودش آوا بوده؛ کاربر از پیش داردش

    search_id = int(record["id"])
    path = clip_path(search_id)
    if path.exists():
        return path

    file_id = record["input_file_id"]
    if not file_id:
        return None

    source = config.tmp_dir / f"requery_{search_id}.bin"
    try:
        handle = await context.bot.get_file(file_id)
        await handle.download_to_drive(custom_path=source)
        await get_queue().run(extract_audio, source, path)
        return path
    except (TelegramError, DecodeError) as exc:
        logger.debug("استخراج دوبارهٔ آوای بازجویی %s نشد: %s", search_id, exc)
        return None
    finally:
        source.unlink(missing_ok=True)


async def on_hint_after_fail(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    نامی که کاربر پس از ناکامی داد.

    همان دو پله، به همان ترتیب: نخست گنجینه، سپس تارنماها. هر دو
    رایگان‌اند — بازجویی‌اش ناکام مانده بود و سکه‌ای نگرفته بودیم.
    """
    message = update.effective_message
    if message is None or not message.text:
        return

    data = get_data(context.user_data)
    search_id = data.get("search_id")
    clear_state(context.user_data)

    hint = fix_characters(message.text.strip())[:120]
    if search_id:
        searches.set_hint(int(search_id), hint)
        await _amend_failure_report(context, int(search_id), hint)

    # همان دو پله و همان پایان که `_after_failure` می‌رود. کلیپِ
    # روی دیسک اینجا در دست نیست، پس گمانهٔ نواهای همانند از قلم
    # می‌افتد؛ بقیه یکی است.
    await _continue_with_hint(message, context, search_id, hint)


async def _text_search_fallback(
    message, context, term: str, search_id: int | None = None
) -> bool:
    """
    جست‌وجوی نام در آرشیو.

    بازگشتی می‌گوید آیا چیزی یافت شد — و همین است که پلهٔ تارنماها
    را روشن یا خاموش می‌کند.

    سکه می‌ستاند، ولی روی **همان ردیف بازجویی** که اثر انگشت
    ناکام مانده بود. پس دکمهٔ «این نیست» زیر نتیجه، همان سکه را
    بازمی‌گرداند.
    """
    from bot.handlers import inline_query

    count = await inline_query.reply_with_matches(
        message,
        term,
        bot_username=context.bot.username or "",
        charge_user_id=message.chat_id,
        search_id=search_id,
    )
    return bool(count)


async def _offer_sites(message, context, term: str, search_id: int | None) -> bool:
    """پلهٔ دوم: تارنماها. ناکامی‌اش کار را نمی‌شکند."""
    from bot.handlers import websearch

    try:
        return await websearch.offer(message, context, term, search_id)
    except Exception:  # noqa: BLE001
        logger.exception("پلهٔ تارنماها شکست خورد.")
        return False


async def _amend_failure_report(context, search_id: int, hint: str) -> None:
    """
    نامی که کاربر دیرتر داد را به گزارش گروه می‌افزاید.

    بی این، گرداننده گزارشی می‌دید با «گمانهٔ خودِ جوینده: —» حال
    آنکه کاربر چند ثانیه بعد نام را گفته بود — و همان نام تنها
    سرنخِ یافتن است.
    """
    try:
        sent = await context.bot.send_message(
            chat_id=config.madahi_group_id,
            text=texts.msg("fill_hint_added", search_id=str(search_id), hint=hint),
            parse_mode="HTML",
            disable_notification=True,
        )
        _remember(config.madahi_group_id, sent.message_id, "hint")
    except TelegramError as exc:
        logger.debug("افزودن گمانه به گزارش ناکامی نشد: %s", exc)


async def _offer_similar(message, path: str) -> bool:
    """
    نواهای همانند را پیش می‌گذارد، اگر گمانه‌ای هست.

    **هیچ فایلی خودکار فرستاده نمی‌شود.** پیش‌تر تا دو نوا بی‌پرسش
    می‌رفت و با گنجینهٔ کوچک، کاربرِ یک بازجویی ناکام هر چه در
    گنجینه بود را می‌گرفت. اکنون فهرست با دکمه می‌آید و گزینش با
    اوست.

    بازگشتی: آیا چیزی پیشنهاد شد.
    """
    guess = await get_queue().run(_guess_similar, path)
    if not guess:
        return False

    read: list[str] = []
    if guess.get("madah"):
        read.append(
            texts.msg(
                "search_read_madah",
                madah=guess["madah"].label,
                percent=to_persian_digits(
                    str(int(guess["madah"].confidence * 100))
                ),
            )
        )
    if guess.get("style"):
        read.append(texts.msg("search_read_style", style=guess["style"].label))
    if guess.get("tempo"):
        read.append(texts.msg("search_read_tempo", tempo=guess["tempo"]))

    candidates: list[tuple[int, str]] = []
    lines: list[str] = []
    for track_id, score in guess.get("tracks") or ():
        track = database.get_track(track_id)
        if track is None or not track["file_id"]:
            continue
        label = f"{track['madah'] or 'نامعلوم'} — {track['title'] or 'بی‌نام'}"
        safe = texts.escape(label)
        percent = to_persian_digits(str(int(score * 100)))
        lines.append(f"• <b>{safe}</b> ({percent}٪)")
        candidates.append((track_id, f"{texts.btn('listen')} {label}"[:60]))

    if not candidates and not read:
        return False

    # سرآیند باید راست بگوید: «شاید یکی از این‌ها را می‌خواستید»
    # تنها آنگاه درست است که فهرستی در کار باشد. اگر تنها خوانشِ
    # آوا داریم و هیچ نوایی، سرآیندِ دیگری می‌آید — وگرنه کاربر
    # دنبال فهرستی می‌گردد که نیست.
    header = "search_similar_header" if candidates else "search_similar_read"
    body = [texts.messages.raw(header), ""]
    if read:
        body.extend(read)
        body.append("")
    if lines:
        body.extend(lines)
        body.append("")
    if candidates:
        body.append(texts.messages.raw("search_similar_note"))

    await message.reply_html(
        "\n".join(body),
        reply_markup=inline.similar_offer(candidates) if candidates else None,
    )
    return True


def _guess_similar(path: str) -> dict:
    """
    گمانهٔ نواهای همانند، هنگامی که اثر انگشت چیزی نیافت.

    این پاسخ قطعی نیست و هرگز نباید چنین نمایانده شود. ناکامی‌اش
    خطا نیست: اگر گنجینه هنوز کوچک است، دست خالی برمی‌گردد — و
    همان درست‌ترین کار است، چون گمانه‌زدن با آرشیو خُرد بیش از آنکه
    یاری کند گمراه می‌کند.
    """
    from core.audio.classifier import get_classifier
    from core.audio.decode import decode_cached
    from core.audio.features import describe_tempo, extract

    try:
        # همان فایلی است که `_fingerprint_and_match` تازه رمزگشایی
        # کرده؛ از کش می‌آید و ffmpeg دوباره اجرا نمی‌شود.
        features = extract(decode_cached(path))
    except Exception:  # noqa: BLE001
        return {}

    classifier = get_classifier()
    out: dict = {"tracks": [], "madah": None, "style": None, "tempo": None}

    try:
        out["tracks"] = classifier.similar_tracks(features, limit=3)
        out["madah"] = classifier.guess_madah(features)
        out["style"] = classifier.guess_style(features)
        out["tempo"] = describe_tempo(features.tempo, features.pulse_clarity)
    except Exception:  # noqa: BLE001
        logger.debug("گمانه‌زنی شکست خورد.", exc_info=True)

    return out


def _remember(chat_id: int, message_id: int, kind: str) -> None:
    """
    نشانیِ یک پیامِ گذرا را برای `/clean` نگه می‌دارد.

    تنها چیزهایی ثبت می‌شوند که کارشان روزی تمام می‌شود. نوایی
    که در گروه بایگانی می‌نشیند **هرگز** از این راه نمی‌گذرد، پس
    `/clean` هرگز نمی‌تواند برش دارد.
    """
    try:
        from core.db import bot_messages

        bot_messages.remember(chat_id, message_id, kind)
    except Exception:  # noqa: BLE001
        logger.debug("ثبت نشانیِ پیام گذرا نشد.", exc_info=True)


async def _report_failure(context, search_id: int, hint, duration) -> None:
    """
    ناکامی را با **خودِ کلیپ** به گروه گردانندگان می‌برد.

    پیش‌تر تنها یک شناسهٔ عددی و یک درازا می‌رفت؛ گرداننده آن را
    می‌دید و هیچ نمی‌دانست دنبال چه بگردد. اکنون خودِ فرستادهٔ کاربر
    هم می‌رود، همراه گمانهٔ خودش، و دکمه‌ای که هر گرداننده‌ای بتواند
    نسخهٔ کامل را بفرستد.

    چون بایگانی تنها از این پس پر می‌شود، همین گزارش‌ها تنها
    راهنمای رشد گنجینه‌اند.
    """
    record = searches.get(search_id)
    if record is None:
        return

    user = database.get_user(int(record["user_id"]))
    name = (user["first_name"] if user else None) or str(record["user_id"])
    handle = (user["username"] if user else None) or ""

    # `texts.msg` خودش هر مقدار را سپر می‌کند؛ ایمن‌سازی دوباره
    # اینجا، «&» را به «&amp;amp;» می‌کرد.
    caption = texts.msg(
        "fill_header",
        name=name,
        username=f"@{handle}" if handle else "—",
        user_id=str(record["user_id"]),
        search_id=str(search_id),
        duration=format_duration(int(duration) if duration else None),
        hint=hint or record["query_text"] or "—",
    )
    keyboard = inline.failure_fill(search_id)

    # ── یک پیام، نه دو ──────────────────────────────────────
    #
    # پیش‌تر سرشناسه جدا می‌رفت و کلیپ در پاسخ به آن. گرداننده
    # دو پیام می‌دید که باید خودش به هم می‌دوختشان، و اگر گروه
    # شلوغ بود میانشان چیز دیگری می‌نشست. اکنون نوشته سرنویسِ
    # خودِ کلیپ است و دکمه زیر همان — یک چیزِ یکپارچه.
    file_id = record["input_file_id"]
    if file_id:
        key = "video" if record["input_kind"] == "video" else "audio"
        sender = (
            context.bot.send_video if key == "video" else context.bot.send_audio
        )
        try:
            sent = await sender(
                chat_id=config.madahi_group_id,
                caption=caption,
                parse_mode="HTML",
                reply_markup=keyboard,
                **{key: file_id},
            )
            searches.set_report(search_id, sent.message_id)
            _remember(config.madahi_group_id, sent.message_id, "failure")
            return
        except TelegramError as exc:
            # کلیپ نرفت — ولی گزارش باید برود، وگرنه ناکامی بی
            # هیچ ردی گم می‌شود. پس به نوشتهٔ تنها فرو می‌افتیم.
            logger.info(
                "کلیپ ناکامی %s به گروه نرفت (%s)؛ تنها نوشته می‌رود.",
                search_id, exc,
            )

    try:
        sent = await context.bot.send_message(
            chat_id=config.madahi_group_id,
            text=caption,
            parse_mode="HTML",
            reply_markup=keyboard,
        )
        _remember(config.madahi_group_id, sent.message_id, "failure")
    except TelegramError as exc:
        logger.warning("گزارش ناکامی %s به گروه نرفت: %s", search_id, exc)
        return

    # جای این گزارش به یاد سپرده می‌شود: اگر خودِ کاربر نسخهٔ
    # کامل را بفرستد، همین پیام باید برداشته شود — کارِ
    # گردانندگان دیگر لازم نیست و گزارشِ مانده تنها گمراهشان
    # می‌کند.
    searches.set_report(search_id, sent.message_id)


async def close_report(bot, search_id: int | None) -> bool:
    """
    گزارشِ ناکامی را از گروه گردانندگان برمی‌دارد.

    ## چرا

    آن گزارش یک درخواست کار است: «این را کسی پیدا کند». وقتی نوا
    پیدا شد — از هر راهی — درخواست باید برداشته شود، وگرنه
    گرداننده‌ای وقت می‌گذارد برای چیزی که از پیش یافت شده.

    بازگشتی: آیا چیزی برداشته شد.
    """
    if not search_id:
        return False
    record = searches.get(int(search_id))
    if record is None:
        return False

    try:
        header = record["report_msg_id"]
        clip = record["report_clip_id"]
    except (KeyError, IndexError):
        return False
    if not header and not clip:
        return False

    gone = await net.drop(bot, config.madahi_group_id, clip, header)
    searches.clear_report(int(search_id))
    if gone:
        logger.info("گزارش ناکامی %s برداشته شد (%s پیام).", search_id, gone)
    return bool(gone)


# ═════════════════════════════════════════════════════════════
#  ابزار
# ═════════════════════════════════════════════════════════════

async def _send_clip(message, path: Path) -> bool:
    """آوای استخراجی را می‌فرستد."""
    try:
        with path.open("rb") as handle:
            await message.reply_audio(
                audio=handle,
                title="آوای نماهنگ شما",
                caption=texts.msg("search_extracted_caption"),
                parse_mode="HTML",
            )
        return True
    except (OSError, TelegramError) as exc:
        logger.warning("فرستادن آوای بیرون‌کشیده شکست خورد: %s", exc)
        return False


async def _safe_delete(message) -> None:
    try:
        await message.delete()
    except TelegramError:
        pass


def _failure_message(exc: Exception) -> str:
    """
    کدام پیام، برای کدام ناکامی.

    ## چرا این تابع هست

    پیش‌تر هر ناکامیِ رمزگشایی و اثر انگشت — **هر کدام** — با یک
    پیام پاسخ می‌گرفت: «این تکه برای جست‌وجو خیلی کوتاه است».

    ولی علت‌ها یکی نیستند: فایلی که جریان صوتی ندارد، ویدیویی که
    ffmpeg نمی‌گشایدش، و تکه‌ای که راستی کوتاه است، سه چیزند. به
    کاربری که ویدیوی یک‌دقیقه‌ای فرستاده گفته می‌شد «کوتاه است» —
    که هم نادرست بود و هم راهنمایی‌اش نمی‌کرد؛ او می‌دانست کوتاه
    نیست و می‌ماند که پس چه.

    نکتهٔ گویا: `search_no_audio` از پیش نوشته شده بود و **هرگز
    صدا زده نمی‌شد**؛ آزمون سازگاری هم در فهرست «پیام‌های
    بی‌کاربرد» نشانش می‌داد.
    """
    text = str(exc)

    # فایل صدا نداشت — رایج‌ترین ناکامیِ راستین، و آنکه بیش از
    # همه با «کوتاه است» اشتباه گرفته می‌شد.
    if "جریان صوتی" in text:
        return "search_no_audio"

    # راستی کوتاه بود.
    if "کوتاه" in text or "پنجره" in text:
        return "search_too_short"

    # هر چیز دیگر: ffmpeg نگشود، مهلت سر آمد، فایل خراب بود.
    return "search_broken"


def _fingerprint_and_match(path: str):
    """
    سه لایه را می‌راند و یک داوری برمی‌گرداند.

    ═══════════════════════════════════════════════════════════
      چرا هر سه در یک بار
    ═══════════════════════════════════════════════════════════

    رمزگشایی گران‌ترین گام است. اگر هر لایه خودش رمزگشایی می‌کرد،
    بهای بازجویی سه برابر می‌شد — و لایهٔ دوم و سوم تنها آنگاه به
    کار می‌آیند که لایهٔ نخست چیزی نیافته باشد، یعنی درست همان
    هنگامی که کاربر بیش از همه چشم‌به‌راه است.

    پس یک بار رمزگشایی، و لایه‌های پسین تنها اگر لازم شد.

    در ریسه‌ای جدا اجرا می‌شود تا ربات پاسخ‌گو بماند.
    """
    from core.audio import melody as melody_mod, verdict as verdict_mod
    from core.audio.decode import decode_cached
    from core.db import melody_store

    # کش‌شده، چون اگر این بازجویی ناکام بماند `_guess_similar`
    # همین فایل را دوباره می‌خواهد و رمزگشایی گران‌ترین گام است.
    samples = decode_cached(path)
    # پرس‌وجو از چند جابه‌جایی زیرقابی ساخته می‌شود، نه یکی.
    # کلیپ کاربر از نمونهٔ دلخواهی بریده شده و شبکهٔ STFT او با
    # شبکهٔ نمایه یکی نیست؛ همین، ۹۶٪ تطبیق‌ها را می‌خورد.
    query = fingerprint_query(samples)

    # ── لایهٔ یکم ────────────────────────────────────────────
    #
    # میان‌بر تنها برای تطبیقِ **استوار** است. تطبیقِ نازک —
    # آنکه از آستانهٔ شمارشی رد شد ولی نرخش در ثانیه کم است —
    # نباید کارِ لایه‌های دیگر را ببندد: پیش‌تر همین میان‌بر،
    # پاسخی با ۶٪ اطمینان را «یافتم» می‌خواند و لایهٔ خطِ آهنگ
    # که می‌توانست ردش کند یا گواهی‌اش دهد، هرگز اجرا نمی‌شد.
    #
    # تطبیق‌های نازک در همین فراخوان به دست می‌آیند، نه با پرسشی
    # جدا: هر دو از یک بافهٔ هم‌ترازی برمی‌آیند و پیش‌تر گنجینه
    # برای همان یک اثر انگشت **دو بار** پرسیده می‌شد.
    exact, weak = matcher.match_and_weak(
        query, weak_limit=5, weak_min_aligned=verdict_mod.WEAK_ALIGNED_MIN
    )
    if exact is not None and exact.confidence >= verdict_mod.EXACT_CONFIDENCE_MIN:
        return verdict_mod.decide(exact, [], [], [])

    # ── لایهٔ یکم، دگربار: سرعتِ دیگر ────────────────────────
    #
    # ## چرا
    #
    # اثر انگشت در برابر تغییر سرعت شکننده است. اندازه‌گیری:
    # کلیپ ۱۵ ثانیه‌ای که تنها **یک درصد** تند شده باشد، از ۵۹۳
    # عدد هم‌راستا به ۹ می‌افتد — زیر آستانهٔ ۱۵، یعنی ناکام.
    # ریلزهای اینستاگرام و ویدیوهای بازفشرده تقریباً همیشه چنین‌اند.
    #
    # پس کلیپ در چند نرخ دیگر هم آزموده می‌شود. با نرخِ درست،
    # همان کلیپ ۳۹۵ عدد می‌دهد.
    #
    # ## چرا اینجا و نه بالاتر
    #
    # تنها آنگاه که نرخِ یک چیزی نیافت. کلیپِ دست‌نخورده — که
    # بیشترِ کارهاست — هیچ بهای افزوده‌ای نمی‌دهد، و نخستین نرخی
    # که بیابد کار را می‌بندد.
    #
    # ## چرا تنها تطبیقِ استوار پذیرفته می‌شود
    #
    # هر نرخ، یک تیرِ دیگر به گنجینه است؛ سیزده تیر یعنی سیزده
    # بختِ نادرست. پس اینجا تنها پاسخی پذیرفته می‌شود که از
    # آستانهٔ استواری بگذرد — تطبیقِ نازک از این راه نمی‌آید.
    for rate in QUERY_RATES:
        try:
            shifted = fingerprint_query(samples, rate=rate)
        except Exception:  # noqa: BLE001
            continue
        found = matcher.match(shifted)
        if found is not None and found.confidence >= verdict_mod.EXACT_CONFIDENCE_MIN:
            logger.info(
                "تطبیق با سرعتِ دگرگون یافت شد: نرخ %.2f، نوای %s، اطمینان %.0f٪",
                rate, found.track_id, found.confidence * 100,
            )
            return verdict_mod.decide(found, [], [], [])

    # ── لایهٔ دوم: خطِ آهنگ ─────────────────────────────────
    #
    # ## چرا اینجا پیام می‌دهیم و نه `logger.debug`
    #
    # این دو لایه پیش‌تر با `except Exception` و `logger.debug`
    # خاموش رد می‌شدند. یعنی کلیپ کوتاه‌تر از ۱۲ ثانیه هیچ لایهٔ
    # پشتیبانی نداشت و **هیچ‌کس نمی‌فهمید چرا** — نه کاربر، نه
    # گرداننده، نه لاگ.
    seconds = samples.size / SAMPLE_RATE
    melody_matches = []
    if seconds < melody_mod.MIN_SECONDS:
        logger.info(
            "خطِ آهنگ اجرا نشد: کلیپ %.1f ثانیه است و دست‌کم %.0f بایسته است.",
            seconds, melody_mod.MIN_SECONDS,
        )
    else:
        try:
            corpus = melody_store.corpus()
            if corpus:
                signature = melody_mod.signature(samples)
                melody_matches = melody_mod.search(signature, corpus, limit=3)
        except Exception:  # noqa: BLE001
            logger.warning("لایهٔ خطِ آهنگ شکست خورد.", exc_info=True)

    # ── لایهٔ سوم: رنگ آوا — اینجا اجرا نمی‌شود ─────────────
    #
    # ## چرا برداشته شد
    #
    # گمانهٔ رنگ آوا تنها به یک شاخهٔ داوری می‌رفت: `Kind.GUESS`.
    # و همان شاخه، چند سطر پایین‌تر، عمداً `None` می‌شود — چون
    # «صدای این مداح شبیه اوست» نوا را نیافته و کاربر مداحیِ
    # دیگری می‌گیرد.
    #
    # پس این لایه در مسیر اصلی، **قطعاً** دور ریخته می‌شد؛ ولی
    # بهایش را می‌گرفت: یک `features.extract` (که `librosa.yin`
    # را روی هر پنجرهٔ دوازده‌ثانیه‌ای می‌راند) به‌علاوهٔ پویشِ
    # کامل جدول ویژگی‌ها، در هر بازجویی.
    #
    # گمانهٔ آوا از میان نرفته: پس از ناکامی، `_offer_similar`
    # همان را با دکمه و با لحنِ «شاید» پیش می‌گذارد. رفتاری که
    # کاربر می‌بیند، ذره‌ای عوض نشده.
    voice_guesses = []

    # ── لایهٔ چهارم: متنِ خوانده‌شده ────────────────────────
    #
    # واپسین لایه، و گران‌ترین — پس تنها آنگاه که بقیه چیزی
    # نگفته‌اند. از ضبط مستقل است: همان نوحه با کیفیت دیگر و گام
    # دیگر، کلماتش یکی است.
    text_match = None
    try:
        from core.audio import transcribe as asr
        from core import lyrics as lyrics_mod

        if asr.available():
            heard = asr.transcribe(
                samples,
                SAMPLE_RATE,
                model_size=config.whisper_model,
                device=config.whisper_device,
                compute_type=config.whisper_compute,
            )
            if heard and lyrics_mod.enough_words(heard):
                corpus = [
                    (int(r["id"]), r["transcript"])
                    for r in database.tracks_with_transcript()
                ]
                text_match = lyrics_mod.best_match(heard, corpus)
                if text_match:
                    logger.info(
                        "لایهٔ متن بر نوای %s انگشت گذاشت (هم‌پوشانی %.0f٪).",
                        text_match[0], text_match[1] * 100,
                    )
    except Exception:  # noqa: BLE001
        logger.warning("لایهٔ متن شکست خورد.", exc_info=True)

    answer = verdict_mod.decide(
        exact, weak, melody_matches, voice_guesses, text_match
    )

    # ── گمانه دستِ کاربر داده نمی‌شود ───────────────────────
    #
    # ## چرا
    #
    # `GUESS` تنها بر رنگ آوا تکیه دارد: «صدای این مداح شبیه
    # اوست». حتی وقتی درست باشد، **نوا** را نیافته — کاربر
    # مداحیِ دیگری از همان مداح می‌گیرد و همان است که «چرت و پرت
    # فرستاد» به چشم می‌آید.
    #
    # نیافتن، پاسخِ درست‌تری است: آنگاه سراغ تارنماها می‌رویم و
    # اگر آنجا هم نبود، سفارشش ثبت می‌شود. هر دو راه از دادنِ
    # نوای نادرست بهترند.
    #
    # بهایش امروز صفر است: سنجیدم که لایهٔ رنگ آوا با گنجینهٔ
    # کنونی همیشه تهی برمی‌گردد، پس این گره هنوز هیچ پاسخی را
    # نمی‌بندد. ولی روزی که آن لایه زنده شود، از پیش بسته است.
    if answer is not None and answer.kind is verdict_mod.Kind.GUESS:
        logger.info(
            "گمانهٔ رنگ آوا بر نوای %s کنار گذاشته شد؛ به کاربر نمی‌رود.",
            answer.track_id,
        )
        return None

    return answer


async def _hash_file(path: Path) -> str:
    """درهم‌سازی محتوا — کلید کش."""
    return await get_queue().run(
        lambda p: hashlib.sha256(Path(p).read_bytes()).hexdigest(), str(path)
    )


async def _deliver(
    message, context, search_id: int, track, confidence: float, verdict=None
) -> None:
    """
    نوای یافته‌شده را می‌فرستد و سکه را برمی‌دارد.

    سکه پس از فرستادن کامیاب برداشته می‌شود، نه پیش از آن؛ اگر
    فرستادن بشکند، کاربر نباید چیزی از دست بدهد.
    """
    percent = int(round(confidence * 100))

    # ── لحن باید با استواریِ پاسخ بخواند ─────────────────────
    #
    # تطبیق اثر انگشت «یافتیم» است؛ خطِ آهنگ «به گمانم این است».
    # اگر هر دو با یک لحن گفته شوند، کاربر گمانه را قطعی می‌شمارد
    # و اعتمادش به پاسخ‌های راستین هم می‌ریزد.
    key = verdict.message_key if verdict is not None else "search_found"
    fields = {
        "madah": track["madah"] or "نامعلوم",
        "style": track["style"] or "—",
        "duration": format_duration(track["duration"]),
        "percent": to_persian_digits(str(percent)),
        "bar": _bar(confidence),
    }
    if verdict is not None and verdict.semitones:
        direction = "بالاتر" if verdict.semitones > 0 else "پایین‌تر"
        fields["shift"] = (
            f"{to_persian_digits(str(abs(verdict.semitones)))} نیم‌پرده {direction}"
        )
    else:
        fields["shift"] = "همان گام"
    caption = texts.msg(key, **fields)

    from services.tagger import audio_labels

    sent_count = database.bump_sent_count(int(track["id"]))
    caption += _sent_note(sent_count)

    # کانفتی روی کل صفحهٔ گفتگو — لحظه‌ای که کاربر برای همان
    # آمده بود. تنها در گفتگوی خصوصی رواست، و `for_chat` خودش
    # می‌سنجد؛ در گروه تلگرام کل پیام را رد می‌کند نه فقط افکت را.
    # ── چرا قفل‌شده می‌رود ──────────────────────────────────
    #
    # تا کاربر نگفته این همان است که می‌خواست، فایل نباید ذخیره یا
    # فوروارد شود. `protect_content` همین را می‌کند.
    #
    # و چرا با «تأیید» پیام پاک می‌شود و از نو می‌رود: این پارامتر
    # **تنها هنگام فرستادن** تنظیم می‌شود. هیچ‌کدام از متدهای
    # `edit_*` آن را نمی‌پذیرند، پس بازکردنِ قفلِ پیامی که رفته
    # ناشدنی است. تنها راه، فرستادنِ دوبارهٔ همان `file_id` بی قفل
    # است.
    try:
        await message.reply_audio(
            audio=track["file_id"],
            caption=caption,
            parse_mode="HTML",
            protect_content=True,
            reply_markup=inline.search_result(search_id),
            **effects.for_chat(message.chat_id),
            **audio_labels(track),
        )
    except BadRequest:
        # سرور قدیمی‌تر یا افکتِ ناشناخته نباید نوا را زمین بگذارد.
        logger.debug("افکت پذیرفته نشد؛ بی افکت فرستاده می‌شود.")
        await message.reply_audio(
            audio=track["file_id"],
            caption=caption,
            parse_mode="HTML",
            protect_content=True,
            reply_markup=inline.search_result(search_id),
            **audio_labels(track),
        )

    user_id = message.chat_id

    # ── سکه تنها بابت پاسخِ استوار ──────────────────────────
    #
    # ## چرا
    #
    # پیش‌تر هر پاسخی یک سکه می‌گرفت — چه «پیدا شد» و چه «تنها یک
    # گمانه». ولی گمانه، یافتن نیست: لایهٔ خطِ آهنگ از سه نوا به
    # بالا کار می‌کند، و با گنجینهٔ کوچک «نزدیک‌ترینِ پنج تا»
    # کمابیش هیچ نمی‌گوید. کاربر مداحیِ دیگری از همان مداح
    # می‌گرفت و سکه‌اش هم می‌رفت.
    #
    # اکنون تنها EXACT (همان ضبط) و CORROBORATED (دو نشانه بر یک
    # نوا) بها دارند. گمانه رایگان می‌رود، با همان لحنِ تردیدآمیز
    # که از پیش داشت و دکمهٔ «این نیست» زیرش.
    from core.audio.verdict import Kind

    solid = verdict is None or verdict.kind in (Kind.EXACT, Kind.CORROBORATED)
    if not solid:
        # `finish` اینجا صدا زده نمی‌شود: فراخوانِ بالادست از پیش
        # آن را با اطمینان و زمانِ سنجش نوشته، و `finish` همهٔ
        # ستون‌ها را بی‌قید بازمی‌نویسد — پس فراخوانِ دوباره همان
        # دو عدد را تهی می‌کرد.
        logger.info(
            "بازجویی %s گمانه بود (%s، نوای %s)؛ سکه‌ای گرفته نشد.",
            search_id, verdict.kind.value, track["id"],
        )
    else:
        try:
            balance = database.adjust_tokens(
                user_id, -config.token_cost_per_search,
                reason="search", ref_type="search", ref_id=search_id,
            )
            searches.mark_charged(search_id)
            logger.info(
                "بازجویی %s کامیاب بود (نوای %s، %s٪)؛ سکهٔ کاربر %s شد %s.",
                search_id, track["id"], percent, user_id, balance,
            )
        except InsufficientTokens:
            logger.warning("کاربر %s سکه نداشت ولی نوا فرستاده شد.", user_id)

    from bot.handlers.start import _send_sticker

    await _send_sticker(context, user_id, "search_found")


def _bar(confidence: float) -> str:
    """نوار دیداری همانندی — سند نمایش تصویری درصد را خواسته بود."""
    filled = int(round(max(0.0, min(1.0, confidence)) * 10))
    return "▰" * filled + "▱" * (10 - filled)


def _sent_note(count: int) -> str:
    """
    «چند بار فرستاده شده»، برای افزودن به زیرنویس نوا.

    در نخستین بار چیزی نوشته نمی‌شود: «۱ بار فرستاده شده» هم
    بی‌معناست و هم به کاربر می‌گوید کسی پیش از او این را
    نخواسته — که نه راست است و نه به کار می‌آید.
    """
    if count < 2:
        return ""
    return "\n\n" + texts.msg("track_sent_count", count=to_persian_digits(str(count)))


# `_not_found` از اینجا برداشته شد. سه گونه پیامِ ناکامی داشت که
# هر سه، پیامِ وضعیت را **ویرایش** می‌کردند — و همان ویرایش بود که
# ترتیب کل بلوک ناکامی را وارونه می‌کرد. اکنون یک `search_not_found`
# ساده در جای خودش فرستاده می‌شود و پیام پایانی، `send_sorry` است.


# ═════════════════════════════════════════════════════════════
#  بازخورد کاربر
# ═════════════════════════════════════════════════════════════

async def on_feedback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """نواختن بر «همین است» یا «این آن نیست»."""
    query = update.callback_query
    user = update.effective_user
    if query is None:
        return
    if user is None or not query.data:
        await answer_quietly(query)
        return

    action, _, raw_id = query.data.rpartition(":")
    try:
        search_id = int(raw_id)
    except ValueError:
        await query.answer()
        return

    record = searches.get(search_id)
    if record is None or int(record["user_id"]) != user.id:
        await query.answer()
        return

    if action == inline.SEARCH_CORRECT:
        if searches.set_feedback(search_id, "correct"):
            logger.info("بازجویی %s درست بود.", search_id)
        await query.answer("خدا را شکر که یافت شد. 🌿")
        await _unlock(query, context, record)
        # پاسخ درست بود؛ آوای استخراجی دیگر به کار نمی‌آید
        clip_path(search_id).unlink(missing_ok=True)
        return

    # ── نادرست بود: سکه بازگردانده شود ──────────────────────
    searches.set_feedback(search_id, "wrong")

    if searches.mark_refunded(search_id):
        balance = database.adjust_tokens(
            user.id, config.token_cost_per_search,
            reason="refund", ref_type="search", ref_id=search_id,
            note="پاسخ نادرست بود",
        )
        await query.answer("پوزش می‌خواهیم؛ سکهٔ شما بازگشت. 🌿", show_alert=True)
        await _drop_locked(query)
        await net.say(
            context.bot, query.message.chat_id,
            texts.msg("search_feedback_wrong", tokens=to_persian_digits(str(balance))),
        )
        logger.info("بازجویی %s نادرست بود؛ سکه بازگردانده شد.", search_id)
    else:
        await query.answer("پوزش می‌خواهیم.")
        await _drop_locked(query)
        await net.say(
            context.bot, query.message.chat_id,
            texts.msg("search_feedback_wrong_again"),
        )

    # اکنون که پاسخمان نادرست بوده، دست کاربر نباید تهی بماند:
    # آوای نماهنگی که فرستاده بود را می‌دهیم — همان که هنگام
    # کامیابی از فرستادنش خودداری کرده بودیم.
    await _deliver_clip_after_wrong(query.message, context, record)


async def _drop_locked(query) -> None:
    """
    نسخهٔ قفل‌شده را برمی‌دارد.

    ناکامی‌اش کار را نمی‌شکند و یک دلیلِ عادی دارد: ربات تنها
    پیامِ زیر ۴۸ ساعت را می‌تواند پاک کند. کاربری که فردا پس‌فردا
    دکمه بزند، نسخهٔ آزادش را می‌گیرد ولی قفل‌شده می‌ماند — و آن
    از ندادنِ نسخهٔ آزاد بهتر است.
    """
    try:
        await query.message.delete()
    except TelegramError as exc:
        logger.debug("برداشتنِ نسخهٔ قفل‌شده نشد: %s", exc)
        # دست‌کم دکمه‌ها برداشته شوند تا دوباره نواخته نشوند.
        try:
            await query.edit_message_reply_markup(reply_markup=None)
        except TelegramError:
            pass


async def _unlock(query, context, record) -> None:
    """
    نسخهٔ آزاد را می‌فرستد و قفل‌شده را برمی‌دارد.

    ترتیب مهم است: **نخست** نسخهٔ آزاد فرستاده می‌شود و تنها اگر
    رفت، قفل‌شده برداشته می‌شود. وارونه‌اش یعنی اگر فرستادن بشکند،
    کاربر هر دو را از دست داده باشد — و او همین حالا سکه‌اش را
    داده است.
    """
    # ── صوت از خودِ پیامِ قفل‌شده برداشته می‌شود ─────────────
    #
    # نه از دیتابیس. پیامی که هم‌اکنون دکمه‌اش نواخته شد، خودش
    # صوت را دارد — و این یعنی همین یک تابع برای **همهٔ** مسیرها
    # کار می‌کند: یافتهٔ موتور، فهرست محبوب‌ترین‌ها، `/madahs`،
    # نوای تارنما، جست‌وجوی متنی. هیچ‌کدام لازم نیست شناسهٔ نوا را
    # جایی نشانده باشند.
    audio = getattr(query.message, "audio", None)
    file_id = getattr(audio, "file_id", None)

    if not file_id:
        # صوتی در کار نیست؛ به دیتابیس برمی‌گردیم.
        track_id = record["matched_track_id"]
        track = database.get_track(int(track_id)) if track_id else None
        file_id = track["file_id"] if track is not None else None

    if not file_id:
        # دستِ کاربر تهی نماند: قفل‌شده بماند، دکمه‌ها برداشته شوند.
        await _strip_buttons(query, texts.msg("search_feedback_correct"))
        return

    labels = {}
    if audio is not None:
        if audio.title:
            labels["title"] = audio.title
        if audio.performer:
            labels["performer"] = audio.performer

    try:
        await net.retry(
            lambda: context.bot.send_audio(
                chat_id=query.message.chat_id,
                audio=file_id,
                caption=texts.msg("search_unlocked"),
                parse_mode="HTML",
                **labels,
            ),
            label="فرستادن نسخهٔ آزاد",
        )
    except TelegramError as exc:
        logger.warning("فرستادن نسخهٔ آزاد نشد: %s", exc)
        await _strip_buttons(query, texts.msg("search_feedback_correct"))
        return

    await _drop_locked(query)


async def _deliver_clip_after_wrong(message, context, record) -> None:
    """آوای استخراجی را پس از «این آن نیست» می‌فرستد."""
    path = await _ensure_clip(context, record)
    if path is not None:
        await _send_clip(message, path)


async def on_similar_play(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    کاربر یکی از گمانه‌ها را برای شنیدن برگزید.

    سکه‌ای نمی‌ستاند: این یافتن نبود، گمانه بود؛ و کاربر خودش دارد
    می‌آزماید که آیا گمانهٔ ما درست بوده یا نه. ستاندن سکه بابت
    گمانه، جریمه کردن او بابت ناتوانی ماست.
    """
    query = update.callback_query
    if query is None:
        return
    if not query.data or query.message is None:
        await answer_quietly(query)
        return

    try:
        track_id = int(query.data.rpartition(":")[2])
    except ValueError:
        await query.answer()
        return

    track = database.get_track(track_id)
    if track is None or not track["file_id"]:
        await query.answer("این نوا دیگر در گنجینه نیست.", show_alert=True)
        return

    await query.answer()
    try:
        from services.tagger import audio_labels

        database.bump_sent_count(int(track["id"]))
        await context.bot.send_audio(
            chat_id=query.message.chat_id,
            audio=track["file_id"],
            **audio_labels(track),
        )
    except TelegramError as exc:
        logger.warning("فرستادن نوای گمانه شکست خورد: %s", exc)


async def on_send_full(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    «نسخهٔ کامل را دارم» — کاربر خودش نوا را یافته و می‌خواهد
    برایمان بفرستد.

    این همان راهی است که سند برایش ارزش قائل بود: گنجینه از دل
    خودِ کاربران پر می‌شود.
    """
    query = update.callback_query
    if query is None:
        return
    if query.message is None:
        await answer_quietly(query)
        return

    from bot.states import AWAITING_SUBMISSION_FILE

    # شمارهٔ جست‌وجو با پیشکش می‌رود تا وقتی پذیرفته شد بدانیم
    # کدام گزارشِ گروه را باید برداریم.
    parts = (query.data or "").split(":")
    search_id = None
    if len(parts) > 2:
        try:
            search_id = int(parts[2])
        except ValueError:
            search_id = None

    set_state(context.user_data, AWAITING_SUBMISSION_FILE, search_id=search_id)
    await query.answer()
    try:
        await query.edit_message_reply_markup(reply_markup=None)
    except TelegramError:
        pass

    await context.bot.send_message(
        chat_id=query.message.chat_id,
        text=texts.msg("submit_ask_file"),
        parse_mode="HTML",
    )


async def on_notify(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    «اگر پیدا شد خبرم کن» — ناکامی به سفارش بدل می‌شود.

    ## چرا این هست

    تا امروز ناکامی پایانِ راه بود: کاربر دست‌خالی می‌رفت و دیگر
    برنمی‌گشت. حالا نام و نشانش می‌ماند، و هر گاه آن نوا به
    گنجینه بیاید — از هر راهی — خودش می‌رسد.

    رایگان است. سکه هنگام **رسیدنِ** نوا هم گرفته نمی‌شود؛ این
    بازجویی از پیش ناکام مانده بود و بهایش را نگرفته بودیم.
    """
    query = update.callback_query
    if query is None:
        return
    if not query.data or ":" not in query.data:
        await answer_quietly(query)
        return

    try:
        search_id = int(query.data.rpartition(":")[2])
    except ValueError:
        await answer_quietly(query)
        return

    record = searches.get(search_id)
    if record is None:
        await answer_quietly(query)
        return

    # بی نام، سفارش بی‌معناست: نمی‌دانیم چه چیزی را بپاییم.
    hint = (record["hint_text"] or record["query_text"] or "").strip()
    if not hint:
        await answer_quietly(query)
        set_state(
            context.user_data, AWAITING_HINT_AFTER_FAIL, search_id=search_id
        )
        await query.message.reply_html(texts.msg("search_ask_hint_after_fail"))
        return

    searches.want_notice(search_id)
    await answer_quietly(query)
    await _strip_buttons(query, "")
    await query.message.reply_html(texts.msg("notify_registered"))
    logger.info("سفارشِ خبر برای بازجویی %s ثبت شد: %s", search_id, hint)


async def sweep_wishes(context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    سفارش‌های باز را با گنجینه می‌سنجد و برآورده‌شان می‌کند.

    ## چرا کارِ دوره‌ای، و نه قلاب بر افزودنِ نوا

    نوا از پنج راه به گنجینه می‌آید (بایگانی، پذیرش، پیشکش،
    تارنما، خزنده). قلاب گذاشتن بر هر پنج، یعنی پنج جا برای
    هم‌گام نگه داشتن — و راهِ ششمی که فردا افزوده شود، خاموش از
    قلم می‌افتد.

    گشتِ دوره‌ای همهٔ راه‌ها را یکجا می‌گیرد، و درنگش بی‌زیان است:
    «آنچه می‌خواستی رسید» شتاب نمی‌خواهد. نوایی که تازه افزوده
    شده هنوز آراسته نیست و شناسهٔ فایلِ درستی ندارد؛ این درنگ
    خودش می‌گذارد کار تمام شود.

    ## چگونه تطبیق داده می‌شود

    سفارش تنها یک **نام** است، نه اثر انگشت؛ کلیپِ آن بازجویی
    شاید ماه‌ها پیش رُفته باشد. پس نام با شناسنامهٔ نوا سنجیده
    می‌شود، روی شکلِ هنجارشده تا نگارش‌های گوناگون یکی شمرده شوند.

    شرط سخت‌گیرانه است: **همهٔ** واژه‌های سفارش باید در شناسنامه
    باشند. سست‌تر از این، خبرِ نادرست می‌فرستاد — و خبرِ نادرست
    بدتر از بی‌خبری است.

    بازگشتی: شمار سفارش‌هایی که برآورده شد.
    """
    from core.normalize import normalize
    from services.tagger import audio_labels

    wishes = searches.open_wishes()
    if not wishes:
        return 0

    sent = 0
    for wish in wishes:
        term = (wish["hint_text"] or wish["query_text"] or "").strip()
        words = [w for w in normalize(term).split() if len(w) > 1]
        if not words:
            continue

        # درازترین واژه پالایهٔ ارزانی است؛ سنجشِ سخت‌گیرانه پس
        # از آن روی نامزدهای اندک انجام می‌شود.
        anchor = max(words, key=len)
        match = None
        for candidate in database.search_tracks_by_text(anchor, limit=25):
            if not candidate["file_id"]:
                continue
            haystack = normalize(
                " ".join(
                    filter(
                        None,
                        [
                            candidate["madah"],
                            candidate["title"],
                            candidate["style"],
                        ],
                    )
                )
            )
            if haystack and all(w in haystack for w in words):
                match = candidate
                break

        if match is None:
            continue

        track_id = int(match["id"])
        try:
            await net.retry(
                lambda w=wish, t=match: context.bot.send_audio(
                    chat_id=int(w["user_id"]),
                    audio=t["file_id"],
                    caption=texts.msg(
                        "notify_found",
                        madah=t["madah"] or "نامعلوم",
                        style=t["style"] or "—",
                    ),
                    parse_mode="HTML",
                    **audio_labels(t),
                ),
                label="فرستادن سفارشِ برآورده",
            )
        except TelegramError as exc:
            # کاربری که ربات را مسدود کرده، نباید بقیه را بایستاند.
            # نشان می‌خورد تا هر گشت دوباره نکوشد.
            logger.info(
                "سفارشِ %s به کاربر %s نرسید: %s",
                wish["id"], wish["user_id"], exc,
            )
            searches.mark_notified(int(wish["id"]), track_id)
            continue

        searches.mark_notified(int(wish["id"]), track_id)
        database.bump_sent_count(track_id)
        sent += 1
        logger.info(
            "سفارشِ بازجویی %s با نوای %s برآورده شد.", wish["id"], track_id
        )

    if sent:
        logger.info("گشتِ سفارش‌ها: %s سفارش برآورده شد.", sent)
    return sent


async def on_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    «بی‌خیال» زیر پیام پایانیِ ناکامی.

    پیش‌تر تنها دکمه‌ها را برمی‌داشت و کاربر با دست خالی می‌ماند.
    اکنون اگر ورودی‌اش نماهنگ بوده، صدای همان نماهنگ را می‌گیرد —
    چیزی که از پیش داشتیم و ندادنش تنها خست بود.
    """
    query = update.callback_query
    if query is None:
        return
    if query.message is None:
        await answer_quietly(query)
        return
    clear_state(context.user_data)
    try:
        await query.answer()
    except TelegramError as exc:
        logger.debug("پاسخ نواخت بی‌خیال نرسید: %s", exc)
    try:
        await query.edit_message_reply_markup(reply_markup=None)
    except TelegramError:
        pass

    # صوتِ کلیپ همراهِ همین پیام از پیش رفته است، پس اینجا تنها
    # بستنِ کار است. پیش‌تر صوت اینجا فرستاده می‌شد؛ اکنون جایش
    # درست‌تر است — کاربر دیگر ناچار نیست دکمه‌ای بزند تا چیزی که
    # وعده‌اش داده شده به دستش برسد.
    await net.say(context.bot, query.message.chat_id, texts.msg("cancelled"))


async def _strip_buttons(query, note: str) -> None:
    """دکمه‌ها را برمی‌دارد تا دوباره نواخته نشوند."""
    try:
        caption = (query.message.caption or "") + f"\n\n{note}"
        await query.edit_message_caption(
            caption=caption, parse_mode="HTML", reply_markup=None
        )
    except TelegramError:
        try:
            await query.edit_message_reply_markup(reply_markup=None)
        except TelegramError:
            pass


# ═════════════════════════════════════════════════════════════
#  رُفت‌وروب
# ═════════════════════════════════════════════════════════════

async def sweep_clips(context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    آوای استخراجیِ کهنه را برمی‌دارد.

    این فایل‌ها تنها برای آنند که اگر کاربر «این آن نیست» را نواخت،
    بی‌درنگ فرستاده شوند. پس از چند ساعت دیگر کسی سراغشان نمی‌آید و
    ماندنشان دیسک را بی‌سبب پر می‌کند. برداشتنشان چیزی را نمی‌شکند:
    اگر کاربری دیر بنوازد، از فرستادهٔ خودش دگربار استخراج می‌شود.
    """
    cutoff = time.time() - CLIP_KEEP_HOURS * 3600
    removed = 0
    for path in config.tmp_dir.glob("clip_*.mp3"):
        try:
            if path.stat().st_mtime < cutoff:
                path.unlink()
                removed += 1
        except OSError:
            continue
    if removed:
        logger.info("رُفت‌وروب: %s آوای استخراجی کهنه برداشته شد.", removed)
