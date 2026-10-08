"""
کیسهٔ سکه.

سکه همان است که پیش‌تر «توکن» می‌نامیدیمش؛ تنها نام کاربرپسندش
دگرگون شد. نام ستون‌ها و کلیدهای دفتر (`token_ledger`، `reason`)
دست‌نخورده ماند — دگرگون کردنشان مهاجرتی بی‌سود بود و رد داد و
ستدهای گذشته را می‌گسست.

دو چیز که در نسخهٔ نخست کم بود و کاربر بر هر دو انگشت گذاشت:

۱) **موجودی همیشه دیده شود.** پیش‌تر کاربرِ بی‌سکه بازگشت زودهنگام
   می‌خورد و اصلاً عددی نمی‌دید — یعنی درست همان کسی که بیش از همه
   می‌خواست بداند چقدر دارد.

۲) **گفته شود سکه چیست.** «سه سکه دارید» بی گفتن اینکه سکه به چه
   کار می‌آید، کِی کم می‌شود و چگونه افزوده می‌گردد، چیزی نمی‌رساند.
"""

from __future__ import annotations

import logging

from telegram import Update
from telegram.ext import ContextTypes

from bot.guards import require_verified
from bot.keyboards import reply
from bot.states import clear_state
from core import texts
from config import config
from core.db import database
from core.normalize import to_persian_digits

logger = logging.getLogger(__name__)

# شرح خواناى هر گونه داد و ستد
_REASONS = {
    "initial": "🎁 هدیهٔ آغازین",
    "search": "🔍 بازجویی نوا",
    "refund": "↩️ بازگردانده شد",
    "contribution": "🌿 پیشکش پذیرفته‌شده",
    "admin": "⚙️ دست گردانندگان",
    "invite": "🎁 دعوت از همراه",
}


def history_text(user_id: int, limit: int = 8) -> str:
    """کارنامهٔ داد و ستد، آمادهٔ نشاندن در پیام."""
    rows = database.token_history(user_id, limit=limit)
    if not rows:
        return texts.messages.raw("token_history_empty")

    lines = [texts.messages.raw("token_history_title")]
    for row in rows:
        delta = int(row["delta"])
        sign = "+" if delta > 0 else "−"
        label = _REASONS.get(row["reason"], row["reason"])
        lines.append(f"  {sign}{to_persian_digits(str(abs(delta)))}  {label}")
    return "\n".join(lines)


def purse_text(user_id: int) -> str:
    """
    نوشتار کیسه — پر یا تهی.

    یک تابع برای هر دو حالت، چون هر جای دیگری که می‌خواهد بگوید
    «کیسه‌تان تهی است» هم باید همان موجودی و همان کارنامه را نشان
    دهد. اگر هر فراخوان خودش می‌ساخت، دیر یا زود یکی‌شان از قلم
    می‌افتاد.
    """
    balance = database.get_tokens(user_id)
    key = "token_balance" if balance > 0 else "token_empty"
    return texts.msg(
        key,
        tokens=to_persian_digits(str(balance)),
        history=history_text(user_id),
    )


async def invite_block(context, user_id: int) -> str:
    """
    بخشِ دعوت — لینکِ اختصاصیِ این همراه و شمارِ آورده‌هایش.

    ## چرا لینکِ عمیق و نه لینکِ دعوتِ تلگرام

    لینکِ دعوتِ گروه/کانال نمی‌گوید **چه کسی** آورده است؛ لینکِ
    عمیقِ ربات می‌گوید، چون پارامترش در `/start` به دستمان
    می‌رسد. و همان است که شرطِ «استارت زدن» را هم می‌سنجد.

    اگر نامِ کاربریِ ربات به دست نیاید، این بخش خالی می‌ماند و
    کیسه بی آن نشان داده می‌شود — بهتر از لینکِ شکسته.
    """
    try:
        me = await context.bot.get_me()
        username = me.username
    except Exception:  # noqa: BLE001
        logger.debug("نامِ کاربریِ ربات به دست نیامد.", exc_info=True)
        return ""
    if not username:
        return ""

    brought = database.count_invites(user_id)
    return texts.msg(
        "invite_block",
        link=f"https://t.me/{username}?start=inv_{user_id}",
        reward=to_persian_digits(str(config.invite_reward)),
        brought=to_persian_digits(str(brought)),
    )


@require_verified
async def show_balance(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    clear_state(context.user_data)
    user = update.effective_user
    message = update.effective_message
    if user is None or message is None:
        return

    body = purse_text(user.id)
    invite = await invite_block(context, user.id)
    if invite:
        body = body.rstrip() + "\n\n" + invite

    await message.reply_html(body, reply_markup=reply.main_menu())
