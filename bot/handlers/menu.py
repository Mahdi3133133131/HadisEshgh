"""
مسیریابی منوی اصلی.

هر دکمهٔ منو نخست وضعیت پیشین را پاک می‌کند. این یک سطر، همان
دامی را می‌بندد که کاربر در میانهٔ پیشکش نوا پشیمان می‌شود، دکمهٔ
دیگری می‌زند، و ربات همچنان چشم‌به‌راه فایل صوتی می‌ماند.

ولی تنها وضعیتِ **همین گفتگو** پاک می‌شود. گرداننده‌ای که پذیرشی
نیمه‌کاره در گروه دارد و اینجا «منو» می‌زند، نباید کارِ آنجا را از
دست بدهد — و پیش‌تر می‌داد.
"""

from __future__ import annotations

import logging

from telegram import Update
from telegram.ext import ContextTypes

from bot.guards import require_verified
from bot.keyboards import reply
from bot.states import clear_state_here
from config import config
from core import texts
from core.db import database
from core.normalize import to_persian_digits

logger = logging.getLogger(__name__)


@require_verified
async def show_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    if message is None:
        return
    clear_state_here(context.user_data, message.chat_id)

    await message.reply_html(
        texts.msg(
            "main_menu",
            user_count=to_persian_digits(str(database.count_users(only_verified=True))),
            track_count=to_persian_digits(str(database.count_tracks())),
        ),
        reply_markup=reply.main_menu(),
    )


@require_verified
async def show_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    if message is None:
        return
    clear_state_here(context.user_data, message.chat_id)

    await message.reply_html(
        texts.msg("help", initial=to_persian_digits(str(config.initial_tokens))),
        reply_markup=reply.main_menu(),
    )


@require_verified
async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """از هر جریانی که کاربر در آن است بیرون می‌آید."""
    message = update.effective_message
    if message is None:
        return
    clear_state_here(context.user_data, message.chat_id)
    await message.reply_html(texts.msg("cancelled"), reply_markup=reply.main_menu())
