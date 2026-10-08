"""
بازیابی پایگاه داده از فایل پشتیبان — تنها مالک، تنها در گفتگوی خصوصی.

روش کار:
  ۱) مالک فایل `.db` را در گفتگوی خصوصی برای ربات می‌فرستد.
  ۲) ربات فایل را می‌سنجد و شمار سطرها را با پایگاه کنونی مقایسه می‌کند.
  ۳) مالک «بازیابی» را می‌زند؛ ربات فایل را آماده می‌کند و خودش را
     می‌بندد. در اجرای بعدی (`services.restore.apply_pending`) فایل
     جایگزین می‌شود.

چرا تنها مالک: بازیابی همهٔ دادهٔ کنونی را کنار می‌گذارد.
"""

from __future__ import annotations

import asyncio
import logging
import os

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.error import TelegramError
from telegram.ext import ContextTypes

from config import config
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


async def on_document(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    user = update.effective_user
    if message is None or user is None or message.document is None:
        return
    if not config.is_owner(user.id):
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

    if not config.is_owner(user.id):
        try:
            await query.answer("این کار تنها از دست مالک برمی‌آید.", show_alert=True)
        except TelegramError:
            pass
        return

    try:
        await query.answer()
    except TelegramError:
        pass

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
