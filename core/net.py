"""
پایداری شبکه.

پیوند این ربات به تلگرام از ایران می‌گذرد: کند، و گاه‌به‌گاه
گسسته. گزارش‌های یک شب کار واقعی این را بی‌ابهام نشان دادند —
ConnectError ×۹، NetworkError ×۱۰، TimedOut ×۳، و هفده بار
«برچسب‌گذاری شکست خورد: Timed out».

دو چاره اینجاست، و هر دو دربارهٔ **هدر ندادن** است:

۱) **کوشش دوباره با درنگ فزاینده.** گسستِ گذرا خطا نیست، وضعِ
   عادیِ این پیوند است. کاری که یک بار می‌شکند، بار دوم معمولاً
   می‌گذرد. بی این، هر گسست یک‌ثانیه‌ای یعنی از دست رفتن کاری که
   دقیقه‌ها زمان برده.

۲) **مدارشکن.** اگر گفتگویی «یافت نشد» بدهد، دوباره آزمودنش
   بیهوده است؛ آن خطا گذرا نیست. بدتر: پیش از هر آزمودن، فایل
   چندمگابایتی فرو گرفته می‌شد و پس از آن شکست می‌خورد. مدارشکن
   می‌گوید «این گفتگو نشدنی است» و از همان آغاز جلوی کار را
   می‌گیرد — هفده فرو گرفتن بیهوده، صفر می‌شود.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Awaitable, Callable, TypeVar

from telegram.error import (
    BadRequest,
    Forbidden,
    InvalidToken,
    NetworkError,
    RetryAfter,
    TelegramError,
    TimedOut,
)

logger = logging.getLogger(__name__)

T = TypeVar("T")

# خطاهایی که گذرایند و کوشش دوباره معنا دارد
TRANSIENT = (TimedOut, NetworkError)

# خطاهایی که هرگز گذرا نیستند؛ کوشش دوباره تنها زمان می‌برد
PERMANENT = (BadRequest, Forbidden, InvalidToken)


class ChatUnreachable(RuntimeError):
    """این گفتگو در دسترس نیست و آزمودنش بیهوده است."""


async def retry(
    action: Callable[[], Awaitable[T]],
    *,
    attempts: int = 3,
    base_delay: float = 2.0,
    label: str = "کار شبکه‌ای",
) -> T:
    """
    کاری شبکه‌ای را با کوشش دوباره می‌راند.

    درنگ میان کوشش‌ها دو برابر می‌شود (۲، ۴، ۸ ثانیه). اگر تلگرام
    خودش درنگ خواسته باشد (RetryAfter)، همان عدد پاس داشته می‌شود
    نه عدد ما.

    خطای همیشگی — مانند «گفتگو یافت نشد» — بی‌درنگ بالا می‌رود؛
    آزمودن دوباره‌اش تنها زمان می‌برد.
    """
    last: BaseException | None = None
    for attempt in range(1, attempts + 1):
        try:
            return await action()
        except RetryAfter as exc:
            wait = float(exc.retry_after) + 1
            logger.info("%s: تلگرام %s ثانیه درنگ خواست.", label, wait)
            await asyncio.sleep(wait)
            last = exc
        except PERMANENT:
            raise
        except TRANSIENT as exc:
            last = exc
            if attempt == attempts:
                break
            wait = base_delay * (2 ** (attempt - 1))
            logger.info(
                "%s در کوشش %s از %s شکست خورد (%s)؛ %s ثانیه دیگر دوباره.",
                label, attempt, attempts, exc, wait,
            )
            await asyncio.sleep(wait)

    assert last is not None
    raise last


# ═════════════════════════════════════════════════════════════
#  مدارشکن گفتگوها
# ═════════════════════════════════════════════════════════════

# گفتگوهایی که ناشدنی بودنشان ثابت شده. تا بازراه‌اندازی ربات
# می‌ماند؛ چون «گفتگو یافت نشد» با گذشت زمان درست نمی‌شود، با
# افزودن ربات به آن گفتگو درست می‌شود — و آن، بازراه‌اندازی دارد.
_unreachable: dict[int, str] = {}
_marked_at: dict[int, float] = {}

# نشانِ ناشدنی بودن، پس از این اندازه از نو آزموده می‌شود.
#
# پیش‌تر تا بازراه‌اندازی می‌ماند، و این یک لغزش بود: آن گفتگو با
# **افزودن ربات به آن** درست می‌شود، و کسی که ربات را همین حالا
# افزوده، انتظار ندارد ناگزیر از بازراه‌اندازی باشد. ربع ساعت
# آزمودن دوباره، نه چیزی هدر می‌دهد و نه کسی را چشم‌به‌راه می‌گذارد.
RECHECK_AFTER = 900.0


def mark_unreachable(chat_id: int, reason: str) -> None:
    if chat_id not in _unreachable:
        logger.warning(
            "گفتگوی %s ناشدنی شناخته شد (%s). تا ربع ساعت دیگر کاری "
            "برایش انجام نمی‌شود — تا وقت و پهنای باند هدر نرود.",
            chat_id, reason,
        )
    _unreachable[chat_id] = reason
    _marked_at[chat_id] = time.monotonic()


def is_unreachable(chat_id: int) -> str | None:
    """
    آیا این گفتگو هم‌اکنون ناشدنی شمرده می‌شود.

    اگر نشانش کهنه شده باشد، برداشته می‌شود تا کوشش تازه‌ای بشود.
    """
    if chat_id not in _unreachable:
        return None
    if time.monotonic() - _marked_at.get(chat_id, 0.0) > RECHECK_AFTER:
        clear_unreachable(chat_id)
        return None
    return _unreachable.get(chat_id)


def clear_unreachable(chat_id: int | None = None) -> None:
    if chat_id is None:
        _unreachable.clear()
        _marked_at.clear()
        _resolved.clear()
    else:
        _unreachable.pop(chat_id, None)
        _marked_at.pop(chat_id, None)
        _resolved.pop(chat_id, None)


def unreachable_chats() -> dict[int, str]:
    return dict(_unreachable)


# شناسه‌هایی که شکل درستشان یافته شده: نوشته‌شده در .env → کارآمد.
_resolved: dict[int, int] = {}


def variants(chat_id: int) -> list[int]:
    """
    شکل‌های هم‌ارز یک شناسه، به ترتیبِ ارزشِ آزمودن.

    ## چرا این لازم شد

    شناسهٔ ابرگروه در تلگرام دو نمایش دارد: شمارهٔ درونی
    (۵۳۰۷۷۹۰۱۸۹) و شناسهٔ API که ۱۰۰ به سرش می‌چسبد و منفی
    می‌شود (‎-۱۰۰۵۳۰۷۷۹۰۱۸۹). بسیاری از ابزارها شکل درونی را
    نشان می‌دهند و کاربر همان را با یک منها در .env می‌نویسد:
    ‎-۵۳۰۷۷۹۰۱۸۹. آن عدد به هیچ گفتگویی اشاره نمی‌کند و تلگرام
    «Chat not found» می‌دهد — همان که هفته‌ها گروه بایگانی را
    خاموش نگه داشت.

    گروه سادهٔ راستین هم شناسهٔ منفیِ بی‌پیشوند دارد، پس نمی‌شود
    یکی را نادرست شمرد و دیگری را درست. چاره، آزمودن هر دوست.
    """
    out = [chat_id]
    digits = str(abs(chat_id))
    if chat_id < 0 and not digits.startswith("100"):
        out.append(-int("100" + digits))
    return out


async def resolve_chat(bot: Any, chat_id: int, label: str = "گفتگو") -> int | None:
    """
    شکلِ کارآمدِ یک شناسه را می‌یابد و به یاد می‌سپارد.

    بازگشتی همان شناسه‌ای است که باید به آن فرستاد — که شاید با
    آنچه در .env است فرق کند. اگر هیچ شکلی کار نکرد، None.
    """
    if chat_id in _resolved:
        return _resolved[chat_id]
    if is_unreachable(chat_id):
        return None

    last: str = "؟"
    for candidate in variants(chat_id):
        try:
            await bot.get_chat(candidate)
        except PERMANENT as exc:
            last = str(exc)
            continue
        except TelegramError as exc:
            # گذرا بود؛ نشانه‌گذاری نمی‌کنیم تا دفعهٔ بعد دوباره بیازماید
            logger.debug("سنجش دسترسی %s (%s) گذرا شکست خورد: %s", label, candidate, exc)
            return None

        _resolved[chat_id] = candidate
        if candidate != chat_id:
            logger.warning(
                "شناسهٔ %s در پیکربندی %s است ولی گفتگوی راستین %s است. "
                "تا بازراه‌اندازی خودمان درستش می‌کنیم، ولی بهتر است در "
                ".env هم %s نوشته شود.",
                label, chat_id, candidate, candidate,
            )
        return candidate

    mark_unreachable(chat_id, last)
    return None


def resolved(chat_id: int) -> int | None:
    """شکلِ کارآمدِ شناسه، اگر پیش‌تر یافته شده باشد."""
    return _resolved.get(chat_id)


async def ensure_reachable(bot: Any, chat_id: int, label: str = "گفتگو") -> bool:
    """
    یک بار می‌سنجد که گفتگو در دسترس است.

    اگر نبود، نشانه‌گذاری می‌شود و از آن پس بی‌درنگ False می‌دهد —
    بی هیچ رفت‌وآمد شبکه‌ای.
    """
    return await resolve_chat(bot, chat_id, label) is not None


# ═════════════════════════════════════════════════════════════
#  گفتنِ پایدار
# ═════════════════════════════════════════════════════════════

async def drop(bot: Any, chat_id: int, *message_ids: int | None) -> int:
    """
    چند پیام را پاک می‌کند و می‌گوید چندتا رفت.

    ناکامی‌اش بی‌اهمیت است و بالا نمی‌رود: پیامی که پیش‌تر پاک
    شده، یا کهنه‌تر از آن است که تلگرام اجازهٔ پاکش را بدهد، خطا
    می‌دهد — و هیچ‌کدام دلیلی نیست که کارِ فراخوان بشکند.
    """
    gone = 0
    for message_id in message_ids:
        if not message_id:
            continue
        try:
            await bot.delete_message(chat_id=chat_id, message_id=message_id)
            gone += 1
        except TelegramError as exc:
            logger.debug("پاک کردن پیام %s نشد: %s", message_id, exc)
    return gone


async def say(bot: Any, chat_id: int, text: str, **kwargs: Any):
    """
    پیامی می‌فرستد و اگر شبکه لغزید، دوباره می‌کوشد.

    چرا این لازم شد: پرسش‌های یک جریان گام‌به‌گام — «نام مداح
    چیست؟» و مانند آن — با یک TimedOut گم می‌شدند، حال آنکه وضعیت
    از پیش پیش رفته بود. کاربر پرسشی نمی‌دید و ربات چشم‌به‌راه
    پاسخی می‌ماند که هرگز نمی‌آمد؛ همان که «قاطی کردن» به چشم
    می‌آمد. یک کوشش دوباره، این گسست را می‌بندد.

    خطای همیشگی (مسدود کردن ربات، گفتگوی ناموجود) بالا می‌رود تا
    فراخوان بتواند دربارهٔ آن تصمیم بگیرد.
    """
    kwargs.setdefault("parse_mode", "HTML")
    return await retry(
        lambda: bot.send_message(chat_id=chat_id, text=text, **kwargs),
        label="فرستادن پیام",
    )
