"""
نگهبانان دسترسی.

سه شرط پیش از هر کار سنجیده می‌شود: کاربر بن نباشد، هم‌نشینی‌اش
تأیید شده باشد، و در جاهای ویژه، گرداننده باشد.

این‌ها به شکل آرایه (decorator) نوشته شده‌اند تا در هر گرداننده
تکرار نشوند؛ فراموش کردن یکی از این سنجش‌ها در یک گرداننده، همان
جایی است که رخنه پدید می‌آید.
"""

from __future__ import annotations

import functools
import logging
from typing import Any, Awaitable, Callable

from telegram import Update
from telegram.error import TelegramError
from telegram.ext import ContextTypes

from config import config
from core import texts
from core.db import database

logger = logging.getLogger(__name__)

Handler = Callable[[Update, ContextTypes.DEFAULT_TYPE], Awaitable[Any]]


async def _reply(update: Update, text: str) -> None:
    """پاسخ می‌دهد، چه از پیام آمده باشد چه از دکمهٔ درون‌خطی."""
    if update.callback_query is not None:
        await update.callback_query.answer(text, show_alert=True)
    elif update.effective_message is not None:
        await update.effective_message.reply_html(text)


async def answer_quietly(query, text: str | None = None, alert: bool = False) -> None:
    """
    نواخت را پاسخ می‌دهد و اگر شبکه لغزید، کار را نمی‌ایستاند.

    ## چرا این تابع هست

    تلگرام تا پاسخِ یک نواخت را نگیرد، چرخِ روی دکمه را می‌چرخاند.
    پس هر گردانندهٔ فراخوانی که خاموش بازگردد، دکمه را برای همیشه
    «گیر کرده» نشان می‌دهد — و هیچ نشانی هم در گزارش نمی‌گذارد،
    که یافتنش را دشوار می‌کند.

    وارونه‌اش هم درست است: اگر پاسخ نرسید، دلیلی ندارد بقیهٔ کار
    زمین بماند؛ پاسخِ نواخت تنها چرخ را می‌خواباند.
    """
    if query is None:
        return
    try:
        await query.answer(text, show_alert=alert)
    except TelegramError as exc:
        logger.debug("پاسخ نواخت نرسید: %s", exc)


def require_verified(func: Handler) -> Handler:
    """
    تنها کاربری که بن نیست و هم‌نشینی‌اش تأیید شده، می‌گذرد.

    کاربر ناشناخته هم رد می‌شود؛ نبودنش در پایگاه داده یعنی هرگز
    /start نزده است.
    """

    @functools.wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE) -> Any:
        user = update.effective_user
        if user is None:
            return None

        record = database.get_user(user.id)
        if record is None:
            await _reply(update, texts.msg("must_verify_first"))
            return None

        if record["is_banned"]:
            await _reply(update, texts.msg("error_banned"))
            logger.info("کاربر بن‌شدهٔ %s کوشید وارد شود.", user.id)
            return None

        if not record["is_verified"]:
            await _reply(update, texts.msg("must_verify_first"))
            return None

        # ── عضویت، همیشه ────────────────────────────────────
        #
        # تا امروز عضویت تنها **یک بار** سنجیده می‌شد و
        # `set_verified(False)` هیچ‌جا صدا نمی‌شد؛ کسی که یک بار
        # عضو شد و بیرون رفت، برای همیشه دسترسی داشت.
        if not await _still_member(context, user.id, record):
            await _reply(update, texts.msg("left_channel"))
            return None

        return await func(update, context)

    return wrapper


# هر چند ثانیه یک بار عضویت دوباره سنجیده شود.
#
# سنجیدنش در **هر** کنش یعنی یک فراخوانِ تلگرام برای هر پیام —
# کند، و روی سقفِ نرخ. پنج دقیقه میانه‌ای است که هم فشار نمی‌آورد
# و هم کسی که بیرون رفته بیش از این مهمانِ ما نمی‌ماند.
MEMBERSHIP_TTL = 300


async def _still_member(context, user_id: int, record) -> bool:
    """
    آیا هنوز عضوِ کانال‌های اجباری است.

    تنها کانال‌هایی سنجیده می‌شوند که `enforce = always` دارند؛
    آنکه «once» است، وظیفه‌اش را در تأییدِ نخست انجام داده.

    ناکامیِ سنجش — شبکه لغزید، ربات از کانال بیرون افتاد — به
    **سودِ کاربر** خوانده می‌شود. بستنِ درِ ربات به روی کسی به
    خاطر لغزشِ خودمان، بدترین پیامدِ ممکن است.
    """
    from datetime import datetime, timedelta

    seen = record["membership_checked_at"] if "membership_checked_at" in record.keys() else None
    if seen:
        try:
            when = datetime.strptime(str(seen), "%Y-%m-%d %H:%M:%S")
            if datetime.utcnow() - when < timedelta(seconds=MEMBERSHIP_TTL):
                return True
        except (TypeError, ValueError):
            pass

    try:
        from bot.handlers.start import missing_channels
        from core.db import channels

        always = set(channels.always_ids())
        if not always:
            return True
        missing = [
            c for c in await missing_channels(context, user_id)
            if int(c["chat_id"]) in always
        ]
    except Exception:  # noqa: BLE001
        logger.debug("سنجشِ دوبارهٔ عضویت نشد.", exc_info=True)
        return True

    if missing:
        database.set_verified(user_id, False)
        logger.info(
            "کاربر %s از کانال بیرون رفته؛ دسترسی‌اش بسته شد.", user_id
        )
        return False

    database.execute(
        "UPDATE users SET membership_checked_at = datetime('now')"
        " WHERE user_id = ?",
        (int(user_id),),
    )
    return True


def admin_only(func: Handler) -> Handler:
    """
    تنها گردانندگان می‌گذرند.

    غیرگرداننده خاموش رد می‌شود — پاسخ ندادن، بهتر از آگاه کردن
    کسی است که دارد فرمان‌های نهانی را می‌آزماید.
    """

    @functools.wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE) -> Any:
        user = update.effective_user
        if user is None or not config.is_admin(user.id):
            if update.callback_query is not None:
                await update.callback_query.answer(
                    texts.msg("admin_only"), show_alert=True
                )
            else:
                logger.debug(
                    "کاربر ناگرداننده %s فرمان گردانندگی را آزمود.",
                    user.id if user else "؟",
                )
            return None
        return await func(update, context)

    return wrapper
