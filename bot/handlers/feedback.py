"""
نقد و انتقادات، و پاسخ‌گویی گردانندگان.

جریان: کاربر هر گونه محتوایی می‌فرستد ← در گروه نقد با سربرگ
شناسنامهٔ فرستنده و دکمهٔ پاسخ‌گویی پدیدار می‌شود ← گرداننده دکمه را
می‌زند و قفل را می‌گیرد ← پاسخش را در همان گروه می‌فرستد ← ربات
آن را به کاربر می‌رساند و قفل را رها می‌کند.

قفل، خواستهٔ سند بود. آنچه سند نگفته بود و اینجا افزوده شده مهلت
است: بی مهلت، گرداننده‌ای که دکمه را زد و کار را رها کرد، آن انتقاد
را برای همیشه بی‌پاسخ نگه می‌داشت.

نکتهٔ برپایی: برای آنکه ربات پاسخ گرداننده را در گروه ببیند، باید
Privacy Mode در BotFather خاموش باشد. وگرنه این جریان خاموش
می‌شکند و کسی نمی‌فهمد چرا.
"""

from __future__ import annotations

import logging

from telegram import Update
from telegram.error import Forbidden, TelegramError
from telegram.ext import ContextTypes

from bot.guards import answer_quietly, require_verified
from bot.keyboards import inline, reply
from bot.states import (
    AWAITING_ADMIN_REPLY,
    AWAITING_FEEDBACK,
    clear_state,
    get_data,
    set_state,
)
from config import config
from core import texts
from core.db import database, feedbacks

logger = logging.getLogger(__name__)

_KIND_BY_ATTR = (
    ("text", "text"),
    ("photo", "photo"),
    ("audio", "audio"),
    ("voice", "voice"),
    ("video", "video"),
    ("video_note", "video_note"),
    ("animation", "animation"),
    ("document", "document"),
    ("sticker", "sticker"),
)


def _detect_kind(message) -> str:
    for attr, kind in _KIND_BY_ATTR:
        if getattr(message, attr, None):
            return kind
    return "unknown"


# ═════════════════════════════════════════════════════════════
#  سوی کاربر
# ═════════════════════════════════════════════════════════════

@require_verified
async def begin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    if message is None:
        return
    set_state(context.user_data, AWAITING_FEEDBACK)
    await message.reply_html(texts.msg("feedback_ask"))


# ── زیرنویس، تنها بر آنچه زیرنویس می‌پذیرد ──────────────────
#
# برچسب و یادداشتِ ویدیویی زیرنویس نمی‌گیرند؛ فرستادنشان با
# `caption` خطا می‌دهد. پس تنها این‌ها یک‌پیامی می‌روند.
_CAPTIONABLE = frozenset(
    {"photo", "audio", "voice", "video", "animation", "document"}
)

# سقفِ زیرنویسِ تلگرام. سرنویس حدود ۱۵۰ نویسه است، ولی سخنِ کاربر
# می‌تواند درازتر باشد — و آنگاه باید به دو پیام برگردیم.
_CAPTION_LIMIT = 1024


def _header_for(user, feedback_id: int) -> str:
    """
    سرنویسِ گروه نقد.

    نامِ کاربر از راهِ `texts.msg` می‌گذرد تا از HTML گریز داده
    شود. پیش‌تر مستقیم در رشته می‌نشست و نامی با «<» کلِ پیام را
    می‌شکست — تلگرام آن را نشانه‌گذاری می‌خواند و پس می‌زد.
    """
    return texts.msg(
        "feedback_group_header",
        name=user.full_name,
        username=f"@{user.username}" if user.username else "—",
        user_id=user.id,
        feedback_id=feedback_id,
    ).rstrip()


async def _post(context, message, kind: str, header: str, feedback_id: int) -> int:
    """
    سخن را به گروه می‌رساند و شناسهٔ پیامِ دکمه‌دار را برمی‌گرداند.

    ## چرا رونوشت و نه بازفرستادن

    رونوشت نشانِ «فرستاده‌شده از» نمی‌خورد و نهانیِ کاربر را نگه
    می‌دارد. این از پیش چنین بود و همان می‌ماند.

    ## چرا یک پیام و نه دو

    پیش‌تر سرنویس پیامی جدا بود و محتوا پیامی دیگر — گروه دوبرابر
    شلوغ می‌شد و در گوشی، سرنویس و عکس از هم جدا می‌افتادند.
    اکنون سرنویس **زیرنویسِ خودِ رسانه** است، درست زیرش.

    سه راه، چون تلگرام سه رفتار دارد:
      • رسانهٔ زیرنویس‌پذیر → یک رونوشت با زیرنویس
      • متنِ ساده          → یک پیام، سرنویس و متن با هم
      • برچسب و یادداشتِ ویدیویی → ناچار دو پیام
    """
    markup = inline.feedback_reply(feedback_id)
    group = config.feedback_group_id
    gap = "\n\n"

    if kind == "text":
        body = header + gap + texts.escape(message.text or "")
        sent = await context.bot.send_message(
            chat_id=group, text=body[:4096],
            parse_mode="HTML", reply_markup=markup,
        )
        return sent.message_id

    if kind in _CAPTIONABLE:
        own = (message.caption or "").strip()
        caption = header + gap + texts.escape(own) if own else header
        if len(caption) <= _CAPTION_LIMIT:
            copied = await context.bot.copy_message(
                chat_id=group,
                from_chat_id=message.chat_id,
                message_id=message.message_id,
                caption=caption,
                parse_mode="HTML",
                reply_markup=markup,
            )
            return copied.message_id
        # سخنِ کاربر درازتر از سقفِ زیرنویس است؛ به دو پیام
        # برمی‌گردیم تا هیچ واژه‌ای بریده نشود.

    sent = await context.bot.send_message(
        chat_id=group, text=header, parse_mode="HTML", reply_markup=markup,
    )
    await context.bot.copy_message(
        chat_id=group,
        from_chat_id=message.chat_id,
        message_id=message.message_id,
        reply_to_message_id=sent.message_id,
    )
    return sent.message_id


async def on_content(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """محتوای کاربر را می‌گیرد و به گروه نقد می‌رساند."""
    message = update.effective_message
    user = update.effective_user
    if message is None or user is None:
        return

    kind = _detect_kind(message)
    if kind == "unknown":
        await message.reply_html(texts.msg("feedback_unsupported"))
        return

    feedback_id = feedbacks.create(
        user_id=user.id,
        content_kind=kind,
        content_text=message.text or message.caption,
    )
    clear_state(context.user_data)

    header = _header_for(user, feedback_id)

    try:
        sent = await _post(context, message, kind, header, feedback_id)
        feedbacks.set_group_message(feedback_id, sent)
    except TelegramError as exc:
        logger.error("رساندن سخن %s به گروه شکست خورد: %s", feedback_id, exc)
        await message.reply_html(texts.msg("error_generic"), reply_markup=reply.main_menu())
        return

    await message.reply_html(texts.msg("feedback_received"), reply_markup=reply.main_menu())
    logger.info("سخن %s از کاربر %s به گروه رفت.", feedback_id, user.id)


# ═════════════════════════════════════════════════════════════
#  سوی گردانندگان
# ═════════════════════════════════════════════════════════════

async def on_reply_tap(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    گرفتن قفل پاسخ‌گویی.

    اگر گردانندهٔ دیگری قفل را در دست داشته باشد، پنجرهٔ هشدار
    نمایان می‌شود — همان چیزی که سند خواسته بود.
    """
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

    try:
        feedback_id = int(query.data.rpartition(":")[2])
    except ValueError:
        await query.answer()
        return

    record = feedbacks.get(feedback_id)
    if record is None:
        await query.answer("این سخن دیگر در دفتر نیست.", show_alert=True)
        return

    if record["status"] == "answered":
        await query.answer("به این سخن پیش‌تر پاسخ داده شده است.", show_alert=True)
        return

    acquired, record = feedbacks.try_acquire_lock(
        feedback_id, admin.id, config.admin_reply_lock_timeout
    )

    if not acquired:
        await query.answer(texts.msg("feedback_locked"), show_alert=True)
        return

    set_state(context.user_data, AWAITING_ADMIN_REPLY, feedback_id=feedback_id)
    await query.answer("قفل پاسخ‌گویی در دست شماست. 🌿")

    try:
        await query.edit_message_reply_markup(
            reply_markup=inline.feedback_reply(feedback_id, locked=True)
        )
    except TelegramError:
        pass

    await context.bot.send_message(
        chat_id=config.feedback_group_id,
        text=texts.msg(
            "feedback_lock_taken",
            admin=admin.full_name,
            minutes=str(config.admin_reply_lock_timeout // 60),
        ),
        parse_mode="HTML",
        reply_to_message_id=record["group_msg_id"],
    )


async def on_release_tap(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """رهاکردن دستی قفل، بی چشم‌به‌راهِ سرآمدن مهلت."""
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

    try:
        feedback_id = int(query.data.rpartition(":")[2])
    except ValueError:
        await query.answer()
        return

    feedbacks.release_lock(feedback_id)
    clear_state(context.user_data)
    await query.answer("قفل رها شد.")

    try:
        await query.edit_message_reply_markup(
            reply_markup=inline.feedback_reply(feedback_id)
        )
    except TelegramError:
        pass


async def on_admin_reply(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    پاسخ گرداننده را به کاربر می‌رساند.

    هر گونه محتوایی پذیرفته است: نوشتار، عکس، صوت، نماهنگ و جز آن.
    """
    message = update.effective_message
    admin = update.effective_user
    if message is None or admin is None:
        return

    data = get_data(context.user_data)
    feedback_id = data.get("feedback_id")
    if feedback_id is None:
        clear_state(context.user_data)
        return

    record = feedbacks.get(feedback_id)
    if record is None:
        clear_state(context.user_data)
        return

    user_id = int(record["user_id"])

    try:
        await context.bot.send_message(
            chat_id=user_id, text=texts.msg("feedback_answer_header"), parse_mode="HTML"
        )
        await context.bot.copy_message(
            chat_id=user_id,
            from_chat_id=message.chat_id,
            message_id=message.message_id,
        )
    except Forbidden:
        database.mark_blocked_bot(user_id)
        clear_state(context.user_data)
        feedbacks.release_lock(feedback_id, admin.id)
        await message.reply_html(texts.msg("feedback_user_blocked"))
        return
    except TelegramError as exc:
        logger.error("رساندن پاسخ به کاربر %s شکست خورد: %s", user_id, exc)
        await message.reply_html(texts.msg("error_generic"))
        return

    if not feedbacks.mark_answered(feedback_id, admin.id):
        # گردانندهٔ دیگری در همان دم پاسخ داد.
        clear_state(context.user_data)
        return

    clear_state(context.user_data)
    await message.reply_html(texts.msg("feedback_answer_sent"))
    logger.info("سخن %s به دست گردانندهٔ %s پاسخ داده شد.", feedback_id, admin.id)
