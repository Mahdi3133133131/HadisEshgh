"""
بازیابی پایگاه داده از فایل پشتیبان — گروه مداحی (ادمین‌ها)، و خصوصی (مالک).

## دو راه، یک کار

۱) **گروه مداحی** — ادمین `/restore` می‌زند؛ ربات می‌پرسد فایل
   `.db` را بفرستد. فایل می‌آید، سنجیده می‌شود و شمار سطرها با
   پایگاه کنونی مقایسه می‌شود؛ ادمین «بازیابی» می‌زند؛ ربات فایل
   را آماده می‌کند و خودش را می‌بندد. در اجرای بعدی
   (`services.restore.apply_pending`) فایل جایگزین می‌شود.
۲) **گفتگوی خصوصی** — مالک همان‌جا فایل `.db` را می‌فرستد، بی‌نیاز
   از فرمان؛ همان جریانِ سنجش و تأیید.

چرا ادمین‌ها و نه تنها مالک: بازیابی کاری است که مالک معمولاً از
راه همین گروه از ادمین می‌خواهد انجام دهند؛ و گره زدنش به حضور
مالک، بازیابیِ فوریِ یک شبِ بی‌شبکه را ناممکن می‌کند.
"""

from __future__ import annotations

import asyncio
import logging
import os

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.error import TelegramError
from telegram.ext import ContextTypes

from bot import states
from bot.guards import admin_only
from config import config
from core import texts
from core.db import database
from core.normalize import format_size, to_persian_digits
from services import backup
from services import restore as restore_service

logger = logging.getLogger(__name__)

CB_YES = "rst:yes"
CB_NO = "rst:no"

# سقف دانلود ربات‌ها در Bot API رسمی
_MAX_BYTES = 20 * 1024 * 1024

_LABELS = (
    ("users", "همراهان"),
    ("tracks", "نواها"),
    ("searches", "بازجویی‌ها"),
    ("submissions", "پیشکش‌ها"),
)


def _fa(value: object) -> str:
    return to_persian_digits(str(value))


@admin_only
async def begin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    `/restore` — در گروه مداحی، از ادمین‌ها می‌خواهد فایل پشتیبان را بفرستند.

    خودِ فرمان کاری نمی‌کند؛ تنها وضعیت را روشن می‌کند تا سندِ
    `.db`ای که بعد می‌آید بی‌اعتبار رد نشود. بی این، هر سندی که
    کسی در گروه بفرستد به چشم پشتیبان گرفته می‌شد.
    """
    message = update.effective_message
    if message is None:
        return
    if message.chat_id != config.madahi_group_id:
        await message.reply_html(texts.msg("restore_wrong_chat"))
        return

    states.set_state(
        context.user_data,
        states.AWAITING_RESTORE_FILE,
        chat_id=message.chat_id,
    )
    await message.reply_html(texts.msg("restore_ask_file"))


async def on_document(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    فایل پشتیبان — هم از راه فرمان در گروه، هم فرستادنِ مستقیمِ مالک در خصوصی.
    """
    message = update.effective_message
    user = update.effective_user
    if message is None or user is None or message.document is None:
        return

    state = states.get_state(context.user_data)
    group_flow = state == states.AWAITING_RESTORE_FILE

    if group_flow:
        # وضعیت تنها با `/restore` و تنها در گروه مداحی روشن می‌شود.
        if message.chat_id != config.madahi_group_id or not config.is_admin(user.id):
            return
        # فایل رسید؛ تا فرمان دوباره زده نشود سندِ دیگری پذیرفته نمی‌شود.
        states.clear_state(context.user_data)
    elif not (config.is_owner(user.id) and message.chat_id > 0):
        # مسیر خصوصی: تنها مالک، و تنها در گفتگوی خصوصی.
        return

    document = message.document
    if document.file_size and document.file_size > _MAX_BYTES:
        await message.reply_html(
            "⚠️ این فایل از ۲۰ مگابایت بزرگ‌تر است و ربات نمی‌تواند آن را "
            "از تلگرام بگیرد. از پشتیبان «سبک» استفاده کنید."
        )
        return

    status = await message.reply_html("⏳ در حال گرفتن و سنجیدن فایل…")

    config.tmp_dir.mkdir(parents=True, exist_ok=True)
    incoming = restore_service.incoming_path()
    try:
        tg_file = await document.get_file()
        await tg_file.download_to_drive(custom_path=incoming)
    except TelegramError as exc:
        await status.edit_text(f"گرفتن فایل نشد: {exc}")
        return

    try:
        counts = await asyncio.to_thread(restore_service.inspect, incoming)
    except restore_service.RestoreError as exc:
        restore_service.discard_incoming()
        await status.edit_text(f"❌ فایل پذیرفته نشد:\n{exc}")
        return

    current = backup.summary()
    size = incoming.stat().st_size

    lines = [
        "♻️ <b>بازیابی پایگاه داده</b>",
        "",
        f"<b>فایل:</b> <code>{document.file_name or '—'}</code> ({format_size(size)})",
        "",
        "<b>             در فایل  ←  کنونی</b>",
    ]
    for key, label in _LABELS:
        lines.append(f"{label}: <b>{_fa(counts.get(key, 0))}</b>  ←  {_fa(current.get(key, 0))}")

    if not counts.get("fingerprints"):
        lines += [
            "",
            "<i>این پشتیبان اثر انگشت ندارد (سبک است). پس از بازیابی، ربات "
            "خودش نواها را دوباره نمایه می‌کند؛ تا پایانش جست‌وجوی صوتی "
            "ناقص است. فایل‌ها در تلگرام‌اند و چیزی از دست نمی‌رود.</i>",
        ]

    lines += [
        "",
        "⚠️ <b>همهٔ دادهٔ کنونی کنار گذاشته می‌شود</b> (نسخه‌اش روی دیسک "
        "با پسوند <code>.before_restore</code> می‌ماند) و ربات یک دقیقه "
        "خاموش و دوباره روشن می‌شود.",
    ]

    keyboard = InlineKeyboardMarkup(
        [[
            InlineKeyboardButton("✅ بازیابی کن", callback_data=CB_YES),
            InlineKeyboardButton("✖️ انصراف", callback_data=CB_NO),
        ]]
    )
    await status.edit_text("\n".join(lines), parse_mode="HTML", reply_markup=keyboard)


async def on_choice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    user = update.effective_user
    if query is None or user is None:
        return

    # مسیر خصوصی تنها مالک؛ مسیر گروه هر ادمینِ همان گروه.
    chat_id = getattr(getattr(query, "message", None), "chat_id", 0) or 0
    in_group = chat_id == config.madahi_group_id
    allowed = config.is_owner(user.id) or (in_group and config.is_admin(user.id))
    if not allowed:
        try:
            await query.answer("این کار تنها از دست ادمین‌ها می‌آید.", show_alert=True)
        except TelegramError:
            pass
        return

    try:
        await query.answer()
    except TelegramError:
        pass

    states.clear_state(context.user_data)

    if query.data == CB_NO:
        restore_service.discard_incoming()
        await query.edit_message_text("✖️ بازیابی رها شد. چیزی تغییر نکرد.")
        return

    try:
        await asyncio.to_thread(restore_service.stage)
    except restore_service.RestoreError as exc:
        await query.edit_message_text(
            f"❌ آماده‌سازی نشد:\n{exc}\n\nفایل را دوباره بفرستید."
        )
        return

    await query.edit_message_text(
        "♻️ فایل آماده شد. ربات اکنون خود را می‌بندد و دوباره راه می‌افتد؛ "
        "حدود یک دقیقه صبر کنید و سپس <code>/stats</code> را در گروه بزنید.",
        parse_mode="HTML",
    )
    context.application.create_task(_restart_soon())


async def _restart_soon() -> None:
    """
    پردازش را با کد ۱ می‌بندد تا Railway (سیاست «در خطا ریستارت»)
    دوباره بالایش بیاورد. اگر ربات روی رایانهٔ خودتان اجرا می‌شود،
    باید دستی دوباره اجرایش کنید.
    """
    await asyncio.sleep(2)
    logger.warning("ربات برای بازیابی پایگاه داده بسته می‌شود.")
    try:
        database.close_connection()
    except Exception:  # noqa: BLE001
        pass
    os._exit(1)
