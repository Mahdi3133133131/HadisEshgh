"""
پیشکش نوا.

جریان: کاربر دکمه را می‌زند ← نوا می‌فرستد ← نام مداح ← سبک ←
بیتی از شعر (نام نوا) ← در گروه گردانندگان با دکمهٔ تأیید/رد پدیدار
می‌گردد ← با تأیید، نوا به گنجینه می‌رود و سکه‌ای بازمی‌گردد.

## چرا بیت شعر پرسیده می‌شود

نام فایل، معمولاً چیزی مانند `voice_0032.mp3` است و به کار کسی
نمی‌آید. آنچه مردم نوا را با آن به یاد می‌آورند، خودِ شعر است. پس
همان بیت را نام نوا می‌کنیم؛ از آن پس هم روی فایل می‌نشیند، هم روی
جلد، و هم — چون add_track خودش هنجارش می‌کند — کلید یافتنش در
جست‌وجوی متنی و حالت درون‌خطی می‌شود.

## همراه مورد اعتماد

گردانندگان می‌توانند به همراهی اعتماد کنند؛ آنگاه پیشکشش بی داوری
یک‌راست به گنجینه می‌رود. ولی **سنجش تکراری از این پرش مستثنا
نیست**: اعتماد یعنی پریدن از داوری، نه از آن نگهبان. وگرنه همان
همراه می‌توانست یک فایل را بارها بفرستد و بی‌پایان سکه بستاند.

دو نگهبان دیگر که در سند نبود و اینجا افزوده شده:
  • سنجش تکراری پیش از دادن سکه.
  • داوری تک‌بارمصرف — تلگرام گاه یک نواخت را دوباره می‌فرستد.
"""

from __future__ import annotations

import logging

from telegram import Update
from telegram.error import Forbidden, TelegramError
from telegram.ext import ContextTypes

from bot.guards import require_verified
from bot.guards import answer_quietly
from bot.keyboards import inline, reply
from bot.states import (
    AWAITING_EDIT_VALUE,
    AWAITING_SUBMISSION_FILE,
    AWAITING_SUBMISSION_MADAH,
    AWAITING_SUBMISSION_STYLE,
    AWAITING_SUBMISSION_TITLE,
    clear_state,
    get_data,
    set_state,
)
from config import config
from core import effects, texts
from core.db import database, searches, submissions
from core.normalize import clean_tag, fix_characters, format_duration, to_persian_digits

from services import dedup

logger = logging.getLogger(__name__)

# نوشتاری که کاربر برای گذشتن از گام نام می‌فرستد
_SKIP_WORDS = {"-", "—", "نمی‌دانم", "نمیدانم", "نمی دانم", "رد", "هیچ"}


# ═════════════════════════════════════════════════════════════
#  سوی کاربر
# ═════════════════════════════════════════════════════════════

@require_verified
async def begin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    if message is None:
        return
    set_state(context.user_data, AWAITING_SUBMISSION_FILE)
    await message.reply_html(texts.msg("submit_ask_file"))


async def on_audio(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """نوای فرستاده‌شده را می‌گیرد و نام مداح را می‌پرسد."""
    message = update.effective_message
    user = update.effective_user
    if message is None or user is None:
        return

    audio = message.audio or message.voice or message.document
    if audio is None:
        await message.reply_html(texts.msg("submit_only_audio"))
        return

    # سند گفته بود تنها ام‌پی‌تری پذیرفته شود. پیام صوتی (voice) هم
    # رد می‌شود، چون فشرده‌سازی‌اش برای گنجینه شایسته نیست.
    if message.voice is not None:
        await message.reply_html(texts.msg("submit_no_voice"))
        return

    duplicate = database.find_duplicate_track(file_unique_id=audio.file_unique_id)
    if duplicate is not None:
        clear_state(context.user_data)
        await message.reply_html(
            texts.msg("submit_duplicate", title=duplicate["title"] or "بی‌نام"),
            reply_markup=reply.main_menu(),
        )
        logger.info("پیشکش تکراری از کاربر %s (نوای %s)", user.id, duplicate["id"])
        return

    # ── سنجشِ راستین، پیش از هر پرسشی ───────────────────────
    #
    # ## چرا اینجا و نه سرِ «فرستادن»
    #
    # سنجشِ بالا تنها `file_unique_id` را می‌بیند، یعنی فایلِ
    # بایت‌به‌بایت یکسان. نسخهٔ بازفشرده رد می‌شد و کاربر سبک و
    # نام و همه را وارد می‌کرد و **آن‌وقت** می‌شنید «این را
    # داریم». خواسته روشن بود: پیش از وارد کردنِ اطلاعات بگو.
    #
    # بهایش یک فرو گرفتن و رمزگشایی است، پس پیامِ «دارم می‌بینم»
    # می‌رود تا کاربر پشتِ سکوت نماند.
    tag_madah = clean_tag(getattr(audio, "performer", None), 120)
    checking = None
    try:
        checking = await message.reply_html(texts.msg("submit_checking"))
    except TelegramError:
        pass

    twin = await dedup.identify(context.bot, audio.file_id, tag_madah)
    if checking is not None:
        try:
            await checking.delete()
        except TelegramError:
            pass

    if twin is not None:
        existing = database.get_track(int(twin[0]))
        if existing is not None:
            clear_state(context.user_data)
            await message.reply_html(
                texts.msg(
                    "submit_duplicate", title=existing["title"] or "بی‌نام"
                ),
                reply_markup=reply.main_menu(),
            )
            logger.info(
                "پیشکش کاربر %s پیش از پرسش تکراری درآمد (نوای %s).",
                user.id, existing["id"],
            )
            return

    # اگر این پیشکش پاسخِ یک جست‌وجوی ناکامِ خودِ کاربر است،
    # شماره‌اش را نگه می‌داریم: با پذیرفته شدنش، گزارشی که به
    # گروه گردانندگان رفته بود برداشته می‌شود.
    origin = get_data(context.user_data).get("search_id")

    submission_id = submissions.create(
        user_id=user.id,
        file_id=audio.file_id,
        file_unique_id=audio.file_unique_id,
        file_name=getattr(audio, "file_name", None),
        duration=getattr(audio, "duration", None),
        origin_search_id=int(origin) if origin else None,
    )

    # ── شناسنامه از خودِ فایل ────────────────────────────────
    #
    # تلگرام برچسب ID3 را با پیام می‌آورد: performer همان نام مداح
    # است و title همان اسم مداحی. پرسیدنشان از کاربر، پرسیدنِ
    # چیزی بود که در دست داشتیم — و سه پرسشِ پیاپی، بیشترِ مردم را
    # نیمه‌راه می‌پراند.
    madah = tag_madah
    title = clean_tag(getattr(audio, "title", None), 200)
    submissions.set_details(submission_id, madah, None, title)

    set_state(context.user_data, AWAITING_SUBMISSION_STYLE, submission_id=submission_id)
    await message.reply_html(
        texts.msg(
            "submit_ask_style_tags",
            madah=madah or "—",
            title=title or "—",
        ),
        reply_markup=reply.styles_keyboard(),
    )


async def on_madah(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    if message is None or not message.text:
        return

    data = get_data(context.user_data)
    submission_id = data.get("submission_id")
    if submission_id is None:
        clear_state(context.user_data)
        return

    madah = fix_characters(message.text.strip())[:120]
    set_state(
        context.user_data,
        AWAITING_SUBMISSION_STYLE,
        submission_id=submission_id,
        madah=madah,
    )
    await message.reply_html(
        texts.msg("submit_ask_style"), reply_markup=reply.styles_keyboard()
    )


async def on_style(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    سبک را می‌گیرد و شناسنامه را نشان می‌دهد.

    این تنها پرسشِ این جریان است؛ نام مداح و اسم مداحی در
    `on_audio` از برچسب فایل خوانده شده‌اند.
    """
    message = update.effective_message
    if message is None or not message.text:
        return

    data = get_data(context.user_data)
    submission_id = data.get("submission_id")
    if submission_id is None:
        clear_state(context.user_data)
        return

    record = submissions.get(int(submission_id))
    if record is None:
        clear_state(context.user_data)
        await message.reply_html(
            texts.msg("error_generic"), reply_markup=reply.main_menu()
        )
        return

    style = fix_characters(message.text.strip())[:40]
    submissions.set_details(
        int(submission_id), record["madah"], style, record["title"]
    )
    clear_state(context.user_data)

    record = submissions.get(int(submission_id))

    # شناسنامه پیش از هر فرستادنی: کاربر یک بار خودش می‌بیند چه
    # چیزی می‌رود، و اگر برچسب فایل غلط بوده همان‌جا اصلاح می‌کند.
    await message.reply_html(
        _summary(record, "submit_review"),
        reply_markup=inline.submission_summary(int(submission_id)),
        )


async def on_title(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """بیت شعر را می‌گیرد و پیشکش را به سرانجام می‌رساند."""
    message = update.effective_message
    user = update.effective_user
    if message is None or user is None or not message.text:
        return

    data = get_data(context.user_data)
    submission_id = data.get("submission_id")
    if submission_id is None:
        clear_state(context.user_data)
        return

    raw = message.text.strip()
    skipped = raw in _SKIP_WORDS or raw == texts.btn("skip_title")
    title = None if skipped else fix_characters(raw)[:200]

    submissions.set_details(submission_id, data.get("madah", ""), data.get("style", ""), title)
    clear_state(context.user_data)

    record = submissions.get(submission_id)
    if record is None:
        await message.reply_html(texts.msg("error_generic"), reply_markup=reply.main_menu())
        return

    # ── شناسنامه، پیش از هر فرستادنی ─────────────────────────
    # سه چیز از کاربر پرسیده‌ایم و هر سه ممکن است اشتباه نوشته شده
    # باشند. نشان دادنشان پیش از فرستادن، هم لغزش را می‌گیرد و هم
    # کار گردانندگان را سبک می‌کند: پیشکشی که خودِ فرستنده یک بار
    # وارسی کرده، کمتر پس فرستاده می‌شود.
    await message.reply_html(
        _summary(record, "submit_review"),
        reply_markup=inline.submission_summary(submission_id),
    )


# ═════════════════════════════════════════════════════════════
#  همراه مورد اعتماد — بی داوری
# ═════════════════════════════════════════════════════════════

async def _already_have(context, record):
    """
    آیا این پیشکش از پیش در گنجینه هست؟

    ## چرا فراتر از `find_duplicate_track`

    آن تنها `file_unique_id` را می‌سنجد، یعنی **همان فایلِ
    تلگرام**. کاربری که همان مداحی را از جای دیگری گرفته و
    بازآپلود کرده، شناسهٔ دیگری دارد و بی‌مانع رد می‌شد — و
    گردانندگان ناچار بودند دستی بگیرندش.

    اینجا خودِ صوت سنجیده می‌شود: اثر انگشت، و اگر نشد خطِ آهنگ.
    سنجشِ ارزان نخست می‌آید، تا فایل بی‌سبب فرو گرفته نشود.

    بازگشتی: ردیفِ نوای موجود، یا None.
    """
    track = database.find_duplicate_track(
        file_unique_id=record["file_unique_id"]
    )
    if track is not None:
        return track

    found = await dedup.identify(
        context.bot, record["file_id"], record["madah"]
    )
    if found is None:
        return None
    return database.get_track(int(found[0]))


async def _accept_trusted(message, context, record, user) -> None:
    """
    پیشکش همراه مورد اعتماد را یک‌راست به گنجینه می‌نشاند.

    سنجش تکراری همچنان انجام می‌شود؛ اعتماد، پریدن از داوری است نه
    از آن نگهبان.
    """
    submission_id = int(record["id"])

    duplicate = await _already_have(context, record)
    if duplicate is not None:
        submissions.mark_duplicate(submission_id, int(duplicate["id"]))
        await message.reply_html(
            texts.msg("submit_duplicate", title=duplicate["title"] or "بی‌نام"),
            reply_markup=reply.main_menu(),
        )
        return

    track_id = _create_track(record, source="trusted")
    submissions.resolve(submission_id, "approved", user.id, track_id)
    await _settle_origin(context, record, track_id)

    balance = database.adjust_tokens(
        record["user_id"],
        config.token_reward_per_approved,
        reason="contribution",
        ref_type="submission",
        ref_id=submission_id,
        note="پیشکش همراه مورد اعتماد",
    )

    context.application.create_task(_index_new_track(context, track_id))

    await message.reply_html(
        texts.msg("submit_trusted_received", tokens=to_persian_digits(str(balance))),
        reply_markup=reply.main_menu(),
    )

    # آگاهی بی‌دکمه در گروه: گردانندگان ببینند چه افزوده شد، بی‌آنکه
    # کاری از آن‌ها خواسته شود.
    try:
        await context.bot.send_message(
            chat_id=config.madahi_group_id,
            text=texts.msg(
                "trusted_group_notice",
                madah=record["madah"] or "—",
                style=record["style"] or "—",
                title=record["title"] or "—",
                name=user.full_name,
                user_id=str(user.id),
                track_id=str(track_id),
            ),
            parse_mode="HTML",
            disable_notification=True,
        )
    except TelegramError as exc:
        logger.debug("آگاهی پیشکش مورد اعتماد به گروه نرفت: %s", exc)

    logger.info(
        "پیشکش %s از همراه مورد اعتماد %s بی داوری پذیرفته شد؛ نوای %s.",
        submission_id, user.id, track_id,
    )


async def _settle_origin(context, record, track_id: int) -> None:
    """
    اگر این پیشکش پاسخِ یک جست‌وجوی ناکامِ خودِ فرستنده بود، آن
    پرونده را می‌بندد.

    دو کار: گزارشِ گروه گردانندگان برداشته می‌شود (دیگر کسی لازم
    نیست دنبالش بگردد)، و خودِ بازجویی «پرشده» نشان می‌خورد.

    **سکه‌ای کم نمی‌شود.** کاربر خودش آورده است؛ گرفتن سکه از او
    بابت چیزی که خودش به گنجینه افزود، وارونهٔ انصاف است — و
    پاداشِ پیشکش را هم از پیش گرفته.
    """
    try:
        origin = record["origin_search_id"]
    except (KeyError, IndexError):
        return
    if not origin:
        return

    from bot.handlers.search import close_report

    await close_report(context.bot, int(origin))
    try:
        searches.mark_fulfilled(int(origin), track_id, 0)
    except Exception:  # noqa: BLE001
        logger.debug("بستن بازجویی %s نشد.", origin)


def _create_track(record, source: str) -> int:
    """
    نوا را از روی پیشکش در گنجینه می‌نشاند.

    عنوان، بیت شعری است که کاربر نوشت؛ اگر ننوشته باشد، نام فایل.
    همان بیت در lyrics_snippet هم می‌نشیند تا tagger روی جلد
    بنشاندش.
    """
    title = record["title"] or record["file_name"]
    track_id = database.add_track(
        file_id=record["file_id"],
        file_unique_id=record["file_unique_id"],
        source=source,
        title=title,
        madah=record["madah"],
        style=record["style"],
        duration=record["duration"],
        added_by=record["user_id"],
    )
    if record["title"]:
        database.execute(
            "UPDATE tracks SET lyrics_snippet = ? WHERE id = ?",
            (record["title"], track_id),
        )
    return track_id


async def accept_batch(context, chat_id: int, user, items: list[dict]) -> None:
    """
    دسته‌ای نوا از همراهِ مورد اعتماد را یک‌راست به گنجینه می‌نشاند.

    ## چرا جدا از جریانِ گردانندگان

    `intake.start` برای **گرداننده** ساخته شده: سبک و نام را
    یکی‌یکی می‌پرسد و کارت تأیید نشان می‌دهد. آن جریان در گفتگوی
    خصوصیِ یک همراه نه شدنی است و نه خواسته — خواسته این بود که
    «چند مداحی بارگذاری کنند و به ازای هر مداحی یک سکه بگیرند».

    پس شناسنامه از برچسبِ خودِ فایل برداشته می‌شود، و آنچه ناقص
    ماند بعداً از پنل گردانندگان درست می‌شود.

    ## دو نگهبان که برداشته نشدند

    اعتماد یعنی پریدن از **داوری**، نه از سنجشِ تکراری. هر نوا
    پیش از نشستن سنجیده می‌شود، وگرنه یک نفر می‌توانست یک فایل
    را ده بار بفرستد و ده سکه بگیرد.
    """
    from services.captions import clean_title, resolve_madah

    added = skipped = 0
    balance = None

    for item in items:
        record = {
            "id": None,
            "user_id": user.id,
            "file_id": item.get("file_id"),
            "file_unique_id": item.get("file_unique_id"),
            "file_name": item.get("file_name"),
            "duration": item.get("duration"),
            "madah": item.get("madah"),
            "style": item.get("style"),
            "title": item.get("title"),
        }

        # نامِ فارسی و پیراسته، همان زنجیرهٔ همیشگی.
        if record["madah"]:
            try:
                record["madah"] = resolve_madah(record["madah"]) or record["madah"]
            except Exception:  # noqa: BLE001
                logger.debug("رساندنِ نامِ مداح نشد.", exc_info=True)
        if record["title"]:
            try:
                record["title"] = clean_title(record["title"]) or record["title"]
            except Exception:  # noqa: BLE001
                logger.debug("پیراستنِ اسمِ نوا نشد.", exc_info=True)

        try:
            twin = await _already_have(context, record)
        except Exception:  # noqa: BLE001
            logger.debug("سنجشِ تکراری نشد.", exc_info=True)
            twin = None
        if twin is not None:
            skipped += 1
            continue

        track_id = _create_track(record, source="trusted")
        added += 1
        balance = database.adjust_tokens(
            user.id,
            config.token_reward_per_approved,
            reason="contribution",
            ref_type="track",
            ref_id=track_id,
            note="بارگذاری دسته‌ای همراه مورد اعتماد",
        )
        context.application.create_task(_index_new_track(context, track_id))

        try:
            await context.bot.send_message(
                chat_id=config.madahi_group_id,
                text=texts.msg(
                    "trusted_group_notice",
                    madah=record["madah"] or "—",
                    style=record["style"] or "—",
                    title=record["title"] or "—",
                    name=user.full_name,
                    user_id=str(user.id),
                    track_id=str(track_id),
                ),
                parse_mode="HTML",
                disable_notification=True,
            )
        except TelegramError as exc:
            logger.debug("آگاهی بارگذاری دسته‌ای به گروه نرفت: %s", exc)

    if balance is None:
        balance = database.get_tokens(user.id)

    await context.bot.send_message(
        chat_id=chat_id,
        text=texts.msg(
            "trusted_batch_done",
            added=to_persian_digits(str(added)),
            skipped=to_persian_digits(str(skipped)),
            tokens=to_persian_digits(str(balance)),
        ),
        parse_mode="HTML",
        reply_markup=reply.main_menu(),
    )
    logger.info(
        "بارگذاری دسته‌ای همراه %s: %s نشست، %s تکراری.",
        user.id, added, skipped,
    )


async def _post_to_group(
    context: ContextTypes.DEFAULT_TYPE, record, user
) -> int | None:
    """نوا را با شناسنامه و دکمه‌های داوری در گروه می‌گذارد."""
    caption_lines = [
        "🎁 <b>پیشکش تازه</b>",
        "",
        f"<b>مداح:</b> {texts.escape(record['madah'] or '—')}",
        f"<b>سبک:</b> {texts.escape(record['style'] or '—')}",
        f"<b>نام نوا:</b> {texts.escape(record['title'] or '—')}",
        f"<b>زمان:</b> {format_duration(record['duration'])}",
        "",
        f"<b>پیشکش‌کننده:</b> {texts.escape(user.full_name)}",
        f"<b>نام‌کاربری:</b> @{user.username}" if user.username else "<b>نام‌کاربری:</b> —",
        f"<b>شناسه:</b> <code>{user.id}</code>",
    ]
    try:
        sent = await context.bot.send_audio(
            chat_id=config.madahi_group_id,
            audio=record["file_id"],
            caption="\n".join(caption_lines),
            parse_mode="HTML",
            reply_markup=inline.submission_review(record["id"]),
        )
        return sent.message_id
    except TelegramError as exc:
        logger.error("فرستادن پیشکش %s به گروه شکست خورد: %s", record["id"], exc)
        return None


# ═════════════════════════════════════════════════════════════
#  سوی گردانندگان
# ═════════════════════════════════════════════════════════════

async def on_review(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """داوری گرداننده بر یک پیشکش."""
    query = update.callback_query
    admin = update.effective_user
    if query is None:
        return
    if admin is None or not query.data:
        await answer_quietly(query)
        return

    if not config.is_admin(admin.id):
        await query.answer(texts.msg("admin_only"), show_alert=True)
        return

    action, _, raw_id = query.data.rpartition(":")
    try:
        submission_id = int(raw_id)
    except ValueError:
        await query.answer()
        return

    record = submissions.get(submission_id)
    if record is None:
        await query.answer("این پیشکش دیگر در دفتر نیست.", show_alert=True)
        return

    # اعتماد، داوری نیست: روی پیشکشِ داوری‌شده هم رواست.
    if action == inline.SUB_TRUST:
        await _grant_trust(update, context, record, admin)
        return

    if record["status"] != "pending":
        await query.answer(
            f"این پیشکش پیش‌تر داوری شده است ({record['status']}).", show_alert=True
        )
        return

    if action == inline.SUB_APPROVE:
        await _approve(update, context, record, admin)
    else:
        await _reject(update, context, record, admin)


async def _grant_trust(update: Update, context, record, admin) -> None:
    """
    همراه را مورد اعتماد می‌کند — با یک نواخت، روی همان پیشکشی که
    پیش چشم است.

    راه دیگرش /trust با شناسهٔ عددی است؛ ولی شناسه را باید از جایی
    برداشت و جایی نوشت، و همان اصطکاک کوچک بس است که کسی هرگز از
    این امکان بهره نبرد.
    """
    query = update.callback_query
    user_id = int(record["user_id"])

    user_row = database.get_user(user_id)
    name = (user_row["first_name"] if user_row else None) or str(user_id)

    if database.is_trusted(user_id):
        database.set_trusted(user_id, False)
        await query.answer("اعتماد پس گرفته شد.", show_alert=True)
        await context.bot.send_message(
            chat_id=config.madahi_group_id,
            text=texts.msg("trusted_revoked", name=name),
            parse_mode="HTML",
        )
        logger.info("اعتماد به کاربر %s پس گرفته شد (به دست %s).", user_id, admin.id)
        return

    if not database.set_trusted(user_id, True, by_admin=admin.id):
        await query.answer("این همراه در دفتر نیست.", show_alert=True)
        return

    await query.answer("اعتماد شد. 🤝", show_alert=True)
    await context.bot.send_message(
        chat_id=config.madahi_group_id,
        text=texts.msg("trusted_granted", name=name),
        parse_mode="HTML",
    )
    await _notify_user(context, user_id, texts.msg("trusted_user_notice"))
    logger.info("کاربر %s مورد اعتماد شد (به دست %s).", user_id, admin.id)


async def _approve(update: Update, context, record, admin) -> None:
    query = update.callback_query
    submission_id = int(record["id"])

    # واپسین سنجش تکراری — میان فرستادن و داوری، شاید همان نوا
    # از راه دیگری به گنجینه رسیده باشد.
    duplicate = database.find_duplicate_track(file_unique_id=record["file_unique_id"])
    if duplicate is not None:
        submissions.mark_duplicate(submission_id, int(duplicate["id"]))
        await query.answer("این نوا پیش‌تر در گنجینه بود؛ سکه‌ای داده نشد.", show_alert=True)
        await _mark_caption(query, f"♻️ تکراری — همانند نوای {duplicate['id']}")
        await _notify_user(
            context, record["user_id"], texts.msg("submit_duplicate_admin")
        )
        return

    track_id = _create_track(record, source="user")

    # نوای تازه باید نمایه شود، وگرنه در بازجویی یافته نمی‌شود.
    # در پس‌زمینه انجام می‌گیرد تا گرداننده چشم‌به‌راه نماند.
    context.application.create_task(_index_new_track(context, track_id))
    await _settle_origin(context, record, track_id)

    if not submissions.resolve(submission_id, "approved", admin.id, track_id):
        # گردانندهٔ دیگری در همان دم داوری کرد.
        await query.answer("گردانندهٔ دیگری هم‌اکنون داوری کرد.", show_alert=True)
        return

    balance = database.adjust_tokens(
        record["user_id"],
        config.token_reward_per_approved,
        reason="contribution",
        ref_type="submission",
        ref_id=submission_id,
        note="پیشکش پذیرفته شد",
    )

    await query.answer("پذیرفته شد. 🌿")
    await _mark_caption(
        query, f"✅ پذیرفته — به دست {texts.escape(admin.full_name)}"
    )

    await _notify_user(
        context,
        record["user_id"],
        texts.msg("token_earned", tokens=to_persian_digits(str(balance))),
        sticker_key="submission_approved",
        with_effect=True,
    )
    logger.info(
        "پیشکش %s پذیرفته شد؛ نوای %s ساخته شد؛ سکهٔ کاربر %s شد %s.",
        submission_id, track_id, record["user_id"], balance,
    )


async def _reject(update: Update, context, record, admin) -> None:
    query = update.callback_query
    submission_id = int(record["id"])

    if not submissions.resolve(submission_id, "rejected", admin.id):
        await query.answer("گردانندهٔ دیگری هم‌اکنون داوری کرد.", show_alert=True)
        return

    await query.answer("رد شد.")
    await _mark_caption(
        query, f"❌ رد شده — به دست {texts.escape(admin.full_name)}"
    )
    await _notify_user(context, record["user_id"], texts.msg("submit_rejected"))
    logger.info("پیشکش %s رد شد.", submission_id)


async def _mark_caption(query, note: str) -> None:
    """
    نشان داوری را به زیرنویس پیام گروه می‌افزاید و دکمه‌ها را
    برمی‌دارد، تا گردانندگان ببینند چه کسی و چه هنگام داوری کرد.

    ## چرا دو پلهٔ فرو افتادن دارد

    این تابع، تنها نشانهٔ دیداریِ «داوری انجام شد» است. اگر
    بشکند، ردیفِ پایگاه داده درست شده ولی **دکمه‌ها سر جایشان
    می‌مانند** — و گرداننده می‌بیند که «دکمه کار نمی‌کند»، حال
    آنکه کارش را کرده بود.

    و شکستنش آسان بود: نام نمایشیِ گرداننده گریزِ HTML نمی‌خورد،
    پس یک `<` در نامش کل ویرایش را با «Can't parse entities» رد
    می‌کرد — همان خطایی که پیش‌تر جای دیگری هم زده بود. اکنون
    نام گریز می‌خورد، و اگر باز هم نشد دست‌کم دکمه‌ها برداشته
    می‌شوند تا داوری دیده شود.
    """
    try:
        caption = (query.message.caption or "") + f"\n\n{note}"
        await query.edit_message_caption(
            caption=caption, parse_mode="HTML", reply_markup=None
        )
        return
    except TelegramError as exc:
        logger.warning("دگرگون کردن زیرنویس داوری نشد: %s", exc)

    try:
        await query.edit_message_reply_markup(reply_markup=None)
    except TelegramError as exc:
        logger.warning("برداشتن دکمه‌های داوری هم نشد: %s", exc)


async def _notify_user(
    context: ContextTypes.DEFAULT_TYPE,
    user_id: int,
    text: str,
    sticker_key: str | None = None,
    with_effect: bool = False,
) -> None:
    """
    کاربر را آگاه می‌کند و مسدود کردن ربات را برمی‌تابد.

    اگر کاربر ربات را مسدود کرده باشد، نشانه‌گذاری می‌شود تا در
    همگانی‌رسانی‌های آینده تلاش بیهوده نشود.
    """
    from bot.handlers.start import _send_sticker

    try:
        if sticker_key:
            await _send_sticker(context, user_id, sticker_key)

        kwargs: dict = {"chat_id": user_id, "text": text, "parse_mode": "HTML"}
        if with_effect:
            # پیش‌تر شناسهٔ **آتش** اینجا نشسته بود و کنارش 🎉 نوشته
            # شده بود؛ پس کد یک چیز می‌گفت و کاربر چیز دیگری
            # می‌دید. اکنون نام‌ها در core/effects نشسته‌اند تا این
            # لغزش تکرارشدنی نباشد.
            kwargs.update(effects.for_chat(user_id, effects.PARTY))

        await context.bot.send_message(**kwargs)
    except Forbidden:
        database.mark_blocked_bot(user_id)
        logger.info("کاربر %s ربات را مسدود کرده است.", user_id)
    except TelegramError as exc:
        logger.warning("آگاه کردن کاربر %s شکست خورد: %s", user_id, exc)


async def _index_new_track(context: ContextTypes.DEFAULT_TYPE, track_id: int) -> None:
    """
    نوای تازه‌پذیرفته را برچسب می‌زند و نمایه می‌کند.

    بی نمایه‌سازی، نوا در گنجینه هست ولی در بازجویی یافته نمی‌شود —
    و این، خرابی خاموشی است که کسی نمی‌فهمد چرا.
    """
    from services import indexer

    await indexer.finalize_track(context.bot, track_id)


# ═════════════════════════════════════════════════════════════
#  بازبینی و ویرایش
#
#  یک جریان، دو سو. همراه پیش از فرستادن به گروه بازبینی می‌کند،
#  گرداننده پس از رسیدن. دکمه‌ها و پرسش‌ها یکی‌اند؛ تنها معنای
#  «تأیید» فرق می‌کند — برای همراه یعنی «بفرست»، برای گرداننده
#  یعنی «به گنجینه ببر».
#
#  چرا یک جریان و نه دو: هر تفاوتی میان این دو، دیر یا زود به
#  ناسازگاری می‌انجامید — ویرایشی که در یک سو کار می‌کرد و در سوی
#  دیگر نه.
# ═════════════════════════════════════════════════════════════

# نام پارسی هر بخش، برای نشان دادن در پیام‌ها
_FIELD_NAMES = {
    "madah": "نام مداح",
    "style": "سبک مداحی",
    "title": "اسم مداحی",
}

# بلندترین اندازهٔ پذیرفته برای هر بخش
_FIELD_LIMITS = {"madah": 120, "style": 40, "title": 200}


def _summary(record, header_key: str) -> str:
    """شناسنامهٔ پیشکش، به یک شکل در هر دو سو."""
    return texts.msg(
        header_key,
        madah=record["madah"] or "—",
        style=record["style"] or "—",
        title=record["title"] or "—",
        duration=format_duration(record["duration"]),
    )


async def _show_summary(context, chat_id: int, submission_id: int) -> None:
    """شناسنامه را با دکمه‌های تأیید/لغو/ویرایش نشان می‌دهد."""
    record = submissions.get(submission_id)
    if record is None:
        return
    await context.bot.send_message(
        chat_id=chat_id,
        text=_summary(record, "submit_review"),
        parse_mode="HTML",
        reply_markup=inline.submission_summary(submission_id),
    )


def _side_of(user_id: int, chat_id: int) -> str:
    """
    این نواخت از سوی همراه است یا گرداننده.

    بر پایهٔ گفتگو داوری می‌شود نه بر پایهٔ شخص: گرداننده‌ای که خودش
    نوایی پیشکش می‌کند، در گفتگوی خصوصی همان جریانِ همراه را دارد —
    و باید داشته باشد.
    """
    return "admin" if chat_id == config.madahi_group_id else "user"


async def on_edit_open(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """دکمهٔ «ویرایش» — فهرست بخش‌ها را می‌گشاید."""
    query = update.callback_query
    user = update.effective_user
    if query is None or user is None or not query.data or query.message is None:
        await answer_quietly(query)
        return

    submission_id = _sub_id(query.data)
    if submission_id is None:
        await query.answer()
        return

    side = _side_of(user.id, query.message.chat_id)
    if side == "admin" and not config.is_admin(user.id):
        await query.answer(texts.msg("admin_only"), show_alert=True)
        return

    record = submissions.get(submission_id)
    if record is None:
        await query.answer(texts.msg("submit_gone"), show_alert=True)
        return

    await query.answer()
    await _render_fields(query, record, side)


async def _render_fields(query, record, side: str) -> None:
    """
    فهرست بخش‌ها را در همان پیام می‌نشاند.

    ویرایشِ همان پیام، نه فرستادن پیام تازه: وگرنه پس از سه ویرایش،
    گفتگو پر از شناسنامه‌های کهنه می‌شد و کاربر نمی‌دانست کدام‌یک
    اکنون درست است.
    """
    submission_id = int(record["id"])
    body = _summary(record, "submit_edit_which")
    markup = inline.submission_fields(submission_id, side)
    try:
        if query.message.caption is not None:
            await query.edit_message_caption(
                caption=body, parse_mode="HTML", reply_markup=markup
            )
        else:
            await query.edit_message_text(
                body, parse_mode="HTML", reply_markup=markup
            )
    except TelegramError as exc:
        logger.debug("نمایش فهرست بخش‌ها نشد: %s", exc)


async def on_edit_field(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """یکی از سه بخش برگزیده شد؛ اکنون نوشتار تازه خواسته می‌شود."""
    query = update.callback_query
    user = update.effective_user
    if query is None or user is None or not query.data or query.message is None:
        await answer_quietly(query)
        return

    parts = query.data.split(":")
    if len(parts) < 4:
        await query.answer()
        return
    try:
        submission_id = int(parts[2])
    except ValueError:
        await query.answer()
        return
    field = parts[3]
    if field not in _FIELD_NAMES:
        await query.answer()
        return

    side = _side_of(user.id, query.message.chat_id)
    if side == "admin" and not config.is_admin(user.id):
        await query.answer(texts.msg("admin_only"), show_alert=True)
        return

    record = submissions.get(submission_id)
    if record is None:
        await query.answer(texts.msg("submit_gone"), show_alert=True)
        return

    set_state(
        context.user_data,
        AWAITING_EDIT_VALUE,
        submission_id=submission_id,
        field=field,
        side=side,
        chat_id=query.message.chat_id,
    )
    await query.answer()

    body = texts.msg(
        "submit_edit_ask",
        field=_FIELD_NAMES[field],
        current=record[field] or "—",
    )
    markup = inline.submission_back(submission_id)
    try:
        if query.message.caption is not None:
            await query.edit_message_caption(
                caption=body, parse_mode="HTML", reply_markup=markup
            )
        else:
            await query.edit_message_text(body, parse_mode="HTML", reply_markup=markup)
    except TelegramError:
        await context.bot.send_message(
            chat_id=query.message.chat_id, text=body, parse_mode="HTML",
            reply_markup=markup,
        )


async def on_edit_value(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """نوشتار تازه رسید؛ می‌نشیند و فهرست بخش‌ها دوباره می‌آید."""
    message = update.effective_message
    if message is None or not message.text:
        return

    data = get_data(context.user_data)
    submission_id = data.get("submission_id")
    field = data.get("field")
    if submission_id is None or field not in _FIELD_NAMES:
        clear_state(context.user_data)
        return

    # پیامی از گفتگوی دیگر، ویرایش این پیشکش نیست. بی این سنجش،
    # گرداننده‌ای که در گروه ویرایش را آغاز کرده و سپس در گفتگوی
    # خصوصی چیزی می‌نویسد، همان را به عنوان نام مداح می‌نشاند.
    if data.get("chat_id") and message.chat_id != data["chat_id"]:
        return

    value = fix_characters(message.text.strip())[: _FIELD_LIMITS[field]]
    clear_state(context.user_data)

    if not value:
        await message.reply_html(texts.msg("submit_edit_empty"))
        return

    submissions.set_field(submission_id, field, value)
    record = submissions.get(submission_id)
    if record is None:
        await message.reply_html(texts.msg("submit_gone"))
        return

    side = data.get("side", "user")
    await message.reply_html(
        texts.msg(
            "submit_edit_done",
            field=_FIELD_NAMES[field],
            value=value,
        )
        + "\n\n"
        + _summary(record, "submit_edit_which"),
        reply_markup=inline.submission_fields(submission_id, side),
    )


async def on_edit_back(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """دکمهٔ بازگشت — از خواستنِ نوشتار به فهرست بخش‌ها."""
    query = update.callback_query
    user = update.effective_user
    if query is None or user is None or query.message is None:
        await answer_quietly(query)
        return

    submission_id = _sub_id(query.data or "")
    clear_state(context.user_data)
    if submission_id is None:
        await query.answer()
        return

    record = submissions.get(submission_id)
    if record is None:
        await query.answer(texts.msg("submit_gone"), show_alert=True)
        return

    await query.answer()
    await _render_fields(query, record, _side_of(user.id, query.message.chat_id))


async def on_user_send(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """همراه تأیید کرد؛ پیشکش به گروه می‌رود (یا یک‌راست به گنجینه)."""
    query = update.callback_query
    user = update.effective_user
    if query is None or user is None:
        await answer_quietly(query)
        return

    submission_id = _sub_id(query.data or "")
    if submission_id is None:
        await query.answer()
        return

    clear_state(context.user_data)
    record = submissions.get(submission_id)
    if record is None or int(record["user_id"]) != user.id:
        await query.answer(texts.msg("submit_gone"), show_alert=True)
        return
    if record["status"] != "pending":
        await query.answer(texts.msg("submit_already"), show_alert=True)
        return

    await query.answer()
    await _strip(query, texts.msg("submit_sent_mark"))

    if database.is_trusted(user.id):
        await _accept_trusted(query.message, context, record, user)
        return

    # ── نگهبانِ پیش از گردانندگان ──────────────────────────
    #
    # خواستهٔ روشن: اگر داریمش، **اصلاً** به گروه نرود و همان‌جا
    # به کاربر گفته شود. پیش‌تر تنها فایلِ بایت‌به‌بایت یکسان
    # گرفته می‌شد و بقیه به گردانندگان می‌رسید تا دستی رد کنند.
    duplicate = await _already_have(context, record)
    if duplicate is not None:
        submissions.mark_duplicate(submission_id, int(duplicate["id"]))
        await context.bot.send_message(
            chat_id=query.message.chat_id,
            text=texts.msg(
                "submit_duplicate", title=duplicate["title"] or "بی‌نام"
            ),
            parse_mode="HTML",
            reply_markup=reply.main_menu(),
        )
        logger.info(
            "پیشکش %s تکراری بود (نوای %s)؛ به گروه نرفت.",
            submission_id, duplicate["id"],
        )
        return

    sent = await _post_to_group(context, record, user)
    if sent is None:
        await context.bot.send_message(
            chat_id=query.message.chat_id, text=texts.msg("error_generic"),
            parse_mode="HTML",
        )
        return

    submissions.set_group_message(submission_id, sent)
    await context.bot.send_message(
        chat_id=query.message.chat_id,
        text=texts.msg("submit_received"),
        parse_mode="HTML",
        reply_markup=reply.main_menu(),
    )
    logger.info("پیشکش %s از کاربر %s به گروه رفت.", submission_id, user.id)


async def on_user_drop(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """همراه از پیشکش چشم پوشید."""
    query = update.callback_query
    user = update.effective_user
    if query is None or user is None:
        await answer_quietly(query)
        return

    submission_id = _sub_id(query.data or "")
    clear_state(context.user_data)
    if submission_id is not None:
        record = submissions.get(submission_id)
        if record is not None and int(record["user_id"]) == user.id:
            submissions.resolve(submission_id, "cancelled", user.id)

    await query.answer()
    await _strip(query, texts.msg("submit_dropped_mark"))
    await context.bot.send_message(
        chat_id=query.message.chat_id,
        text=texts.msg("cancelled"),
        parse_mode="HTML",
        reply_markup=reply.main_menu(),
    )


def _sub_id(data: str) -> int | None:
    try:
        return int(data.rpartition(":")[2])
    except ValueError:
        return None


async def _strip(query, note: str) -> None:
    """دکمه‌ها را برمی‌دارد و نشانی از سرانجام می‌گذارد."""
    try:
        if query.message.caption is not None:
            await query.edit_message_caption(
                caption=(query.message.caption or "") + f"\n\n{note}",
                parse_mode="HTML", reply_markup=None,
            )
        else:
            await query.edit_message_text(
                (query.message.text or "") + f"\n\n{note}",
                parse_mode="HTML", reply_markup=None,
            )
    except TelegramError:
        try:
            await query.edit_message_reply_markup(reply_markup=None)
        except TelegramError:
            pass
