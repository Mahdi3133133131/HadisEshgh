"""
دفتر پذیرش — یک جریان یگانه برای هر نوایی که گرداننده می‌افزاید.

## چرا این پرونده پدید آمد

نوا از سه راه به دست گرداننده به گنجینه می‌رفت، و هر راه جریان
جدای خود را داشت:

  • افزودن انبوه در گروه — شناسنامه را از برچسب ID3 برمی‌داشت و
    هیچ نمی‌پرسید. نامِ آمده از فایل معمولاً چیزی مانند
    `voice_0032` است؛ همان روی نسخهٔ آراسته می‌نشست.
  • نوای بازفرستاده — بی هیچ پرسشی می‌افزود و در جا نمایه می‌کرد.
  • پر کردن بازجویی ناکام — می‌پرسید، ولی پاسخ‌ها را بی هیچ
    بازبینی‌ای می‌نشاند؛ یک غلط تایپی در نام مداح، برای همیشه
    می‌ماند.

اکنون هر سه از همین‌جا می‌گذرند: نوا به نوا پرسیده می‌شود (مداح،
سبک، بیتی از شعر)، شناسنامه‌اش نشان داده می‌شود، و تا گرداننده
تأیید نکرده چیزی در گنجینه نمی‌نشیند. دکمهٔ ویرایش هم همان‌جاست،
با همان چیدمانی که در پیشکشِ همراهان هست — تا آموختن یکی، آموختن
هر دو باشد.

## چرا کارت‌ها شماره دارند

تلگرام دکمه‌های پیامِ کهنه را برنمی‌دارد. بی شماره، گرداننده‌ای که
کارتِ نوای پیشین را بالاتر در گروه می‌دید و «تأیید» را می‌نواخت،
نوای **کنونی** را تأیید می‌کرد. هر کارت شمارهٔ خودش را دارد و
نواختنِ کارتِ کهنه، خاموش نمی‌گذرد — گفته می‌شود که کهنه است.
"""

from __future__ import annotations

import asyncio
import logging
import time

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.error import Forbidden, TelegramError
from telegram.ext import ContextTypes

from bot.keyboards import inline
from bot.states import (
    AWAITING_INTAKE_CARD,
    AWAITING_INTAKE_SCREEN,
    AWAITING_INTAKE_EDIT,
    AWAITING_INTAKE_MADAH,
    AWAITING_INTAKE_STYLE,
    AWAITING_INTAKE_TITLE,
    STYLES,
    clear_state,
    get_data,
    get_state,
    set_state,
)
from config import config
from core import net, texts
from core.db import database, searches
from core.normalize import fix_characters, format_duration, to_persian_digits

logger = logging.getLogger(__name__)

# نام پارسی هر بخش — همان واژه‌ها که در پیشکشِ همراهان به کار
# می‌روند، تا دو نام برای یک چیز نداشته باشیم.
FIELDS = {
    "madah": "نام مداح",
    "style": "سبک مداحی",
    "title": "اسم مداحی",
}

LIMITS = {"madah": 120, "style": 40, "title": 200}

# نوشتاری که گرداننده برای گذشتن از یک بخش می‌فرستد
SKIP_WORDS = {"-", "—", "ندارد", "نمی‌دانم", "نمیدانم", "نمی دانم", "رد"}


def _fa(value: object) -> str:
    return to_persian_digits(str(value))


def _header(data: dict) -> str:
    """
    سرنویسِ گامِ کنونی: چندمین مداحی از چند، و نام پرونده‌اش.

    روی **همهٔ** پرسش‌های یک نوا می‌نشیند. پیش‌تر تنها پرسش نخست
    نام پرونده را داشت و از گام «سبک» به بعد، گرداننده در دسته‌ای
    ده‌تایی نمی‌دانست دربارهٔ کدام فایل نظر می‌دهد.

    جداکنندهٔ پایانی هم اینجاست، نه در خودِ متن: `texts.raw` هر
    نوشتار را strip می‌کند و خط خالیِ پایانی را می‌خورد، پس
    شمارنده به پرسش می‌چسبید.
    """
    item = data.get("current") or {}
    name = item.get("file_name") or "بی‌نام"
    total = int(data.get("total", 1) or 1)

    if total > 1:
        index = int(data.get("done", 0)) + int(data.get("skipped", 0)) + 1
        head = texts.msg(
            "intake_header_many", index=_fa(index), total=_fa(total), name=name
        )
    else:
        head = texts.msg("intake_header_one", name=name)
    return head + "\n\n"


def _clean(text: str, field: str) -> str | None:
    """نوشتار را می‌پیراید؛ اگر گذشتن خواسته شده باشد، تهی می‌دهد."""
    raw = text.strip()
    if raw in SKIP_WORDS or raw == texts.btn("skip_title"):
        return None
    return fix_characters(raw)[: LIMITS[field]] or None


# ═════════════════════════════════════════════════════════════
#  آغاز
# ═════════════════════════════════════════════════════════════

async def start(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    items: list[dict],
    batch_madah: str | None = None,
) -> None:
    """
    پذیرش یک یا چند نوا را آغاز می‌کند.

    هر «آیتم» دست‌کم file_id و file_unique_id دارد؛ اگر search_id
    هم داشته باشد، پس از نشستن در گنجینه برای همان جویندهٔ ناکام
    فرستاده می‌شود.
    """
    if not items:
        return

    set_state(
        context.user_data,
        AWAITING_INTAKE_SCREEN,
        chat_id=chat_id,
        # `screen` هنوز سنجیده نشده؛ `queue` بازماندگانِ غربال است.
        screen=list(items),
        queue=[],
        current=None,
        batch_madah=batch_madah,
        total=len(items),
        done=0,
        skipped=0,
        dropped=0,
        seq=0,
    )
    data = get_data(context.user_data)
    _persist(context, data)
    if len(items) > 1:
        await _say(
            context, chat_id,
            texts.msg("screen_started", count=_fa(len(items))),
        )
    await _screen_next(context, data)


# ═════════════════════════════════════════════════════════════
#  نشستِ گروه — صف مالِ گروه است، نه مالِ یک گرداننده
# ═════════════════════════════════════════════════════════════
#
# ## چرا
#
# پیش‌تر وضعیت در `context.user_data` بود، یعنی برای هر گرداننده
# جدا. اگر نتِ کسی وسطِ کار قطع می‌شد، صفِ نیمه‌کاره‌اش در
# `user_data` او حبس می‌ماند و هیچ‌کس نمی‌توانست ادامه بدهد.
#
# اکنون صف در دیتابیس است و کلیدش **گفتگو**ست. قفلی هم رویش هست
# که پس از دو دقیقه بی‌کنشی آزاد می‌شود — آنگاه هر گرداننده‌ای،
# از جمله خودِ آغازگر، می‌تواند دنباله‌اش را بگیرد.


def _persist(context, data: dict) -> None:
    """
    وضعیت را هم در `user_data` می‌نشاند و هم در نشستِ گروه.

    هر دو، چون گردانندگانِ موجود از `user_data` می‌خوانند و
    بازنویسیِ همه‌شان، خطرِ بی‌سود بود. نشست، منبعِ حقیقت است و
    `user_data` رونوشتِ کاریِ همین گرداننده.
    """
    state = get_state(context.user_data)
    if state:
        data["_state"] = state
    try:
        from core.db import intake_sessions

        intake_sessions.ensure_table()
        intake_sessions.save(int(data["chat_id"]), data)
    except Exception:  # noqa: BLE001
        logger.debug("نشاندنِ نشستِ پذیرش نشد.", exc_info=True)


def _adopt(context, chat_id: int) -> dict | None:
    """
    صفِ این گروه را در `user_data` این گرداننده می‌نشاند.

    این همان لحظهٔ **تحویلِ کار** است: گردانندهٔ B که قفلِ رهاشدهٔ
    A را گرفته، از همین‌جا صفِ نیمه‌کارهٔ A را به ارث می‌برد.
    """
    try:
        from core.db import intake_sessions

        intake_sessions.ensure_table()
        data = intake_sessions.load(int(chat_id))
    except Exception:  # noqa: BLE001
        logger.debug("خواندنِ نشستِ پذیرش نشد.", exc_info=True)
        return None
    if not data:
        return None

    state = data.get("_state") or AWAITING_INTAKE_STYLE
    set_state(context.user_data, state, **data)
    _persist(context, data)
    return get_data(context.user_data)


async def _claim(update, context, chat_id: int) -> dict | None:
    """
    قفلِ گروه را می‌گیرد و صف را برمی‌دارد.

    بازگشتی: دادهٔ جریان، یا None اگر گردانندهٔ دیگری مشغول است.

    نکتهٔ ریز: پس از گرفتنِ قفل، مهلت از نو کشیده می‌شود — پس
    گرداننده‌ای که پیوسته کار می‌کند هرگز قفلش را از دست نمی‌دهد،
    و آنکه رفته پس از دو دقیقه رهایش می‌کند.
    """
    user = update.effective_user
    if user is None:
        return None

    from core.db import intake_sessions

    intake_sessions.ensure_table()
    if not intake_sessions.try_take(int(chat_id), user.id):
        return None

    data = get_data(context.user_data)
    if not data or int(data.get("chat_id", 0)) != int(chat_id):
        # کارِ کسِ دیگری است یا وضعیتِ محلی نداریم؛ از نشست بگیر.
        data = _adopt(context, chat_id)
    if data is not None:
        intake_sessions.touch(int(chat_id))
    return data


def _close(context, chat_id: int) -> None:
    """نشست را می‌بندد — پایانِ کار یا رهاکردنش."""
    try:
        from core.db import intake_sessions

        intake_sessions.clear(int(chat_id))
    except Exception:  # noqa: BLE001
        logger.debug("بستنِ نشستِ پذیرش نشد.", exc_info=True)


# ═════════════════════════════════════════════════════════════
#  پیام‌های گذرا — آنچه پس از کار باید برداشته شود
# ═════════════════════════════════════════════════════════════
#
# ## چرا ثبت می‌شوند
#
# جریانِ پذیرش برای هر نوا چند پیام می‌سازد: خودِ صوت، پرسشِ سبک،
# کارتِ شناسنامه، «به گنجینه افزوده شد». در دسته‌ای بیست‌تایی
# می‌شود صدها پیام، و گروه بایگانی چنان شلوغ می‌شود که نسخه‌های
# آراسته — که تنها چیزِ ماندنی‌اند — میانشان گم می‌شوند.
#
# ## قاعده، و چرا وارونه است
#
# تنها آنچه **صریح ثبت شده** پاک می‌شود. پس اگر روزی جایی ثبت
# کردنش فراموش شود، بدترین پیامد این است که پیامی بماند — نه
# اینکه نسخهٔ آراسته پاک شود. صوتِ آراسته هرگز ثبت نمی‌شود و
# همین، نگهبانش است.


def _remember(chat_id, sent, kind: str = "intake") -> None:
    """پیامی گذرا را برای پاک‌سازیِ بعدی نشان می‌کند."""
    if sent is None:
        return
    try:
        from core.db import bot_messages

        bot_messages.remember(int(chat_id), int(sent.message_id), kind)
    except Exception:  # noqa: BLE001
        # نشان‌کردن، کارِ فرعی است؛ ناکامی‌اش نباید پذیرش را بشکند.
        logger.debug("نشان‌کردنِ پیامِ گذرا نشد.", exc_info=True)


async def _say(context, chat_id: int, body: str, **kwargs):
    """`net.say` با نشان‌کردنِ خودکار."""
    sent = await net.say(context.bot, int(chat_id), body, **kwargs)
    _remember(chat_id, sent)
    return sent


async def _audio(context, chat_id: int, file_id: str, **kwargs):
    """`send_audio` با نشان‌کردنِ خودکار."""
    sent = await context.bot.send_audio(
        chat_id=int(chat_id), audio=file_id, **kwargs
    )
    _remember(chat_id, sent, "intake_audio")
    return sent


async def _sweep(context, chat_id: int) -> int:
    """
    پیام‌های گذرای این گفتگو را برمی‌دارد.

    بازگشتی: شمارِ آنچه راستی رفت. ربات تنها پیامِ زیر ۴۸ ساعت را
    می‌تواند بردارد؛ کهنه‌ترها می‌مانند و همان‌جا فراموش می‌شوند
    تا دفعهٔ بعد بیهوده کوشیده نشود.
    """
    try:
        from core.db import bot_messages

        rows = bot_messages.pending(int(chat_id), limit=400)
        ids = [int(r["message_id"]) for r in rows]
        if not ids:
            return 0
        gone = await net.drop(context.bot, int(chat_id), *ids)
        bot_messages.forget(int(chat_id), ids)
        return gone
    except Exception:  # noqa: BLE001
        logger.debug("پاک‌سازیِ پیام‌های گذرا نشد.", exc_info=True)
        return 0


async def _screen_next(context: ContextTypes.DEFAULT_TYPE, data: dict) -> None:
    """
    فایل‌ها را یکی‌یکی با گنجینه می‌سنجد، پیش از هر پرسشی.

    ## چرا پیش از پرسش‌ها، و نه در میانشان

    پرسیدنِ سبک و نامِ نوایی که از پیش داریم، پرسشِ بیهوده است —
    و در دسته‌ای بیست‌تایی، بیست بار بیهوده. گرداننده می‌خواهد
    نخست بداند کدام‌ها تازه‌اند و بعد دربارهٔ همان‌ها پاسخ بدهد.

    ## چرا پرسیده می‌شود و خودکار کنار گذاشته نمی‌شود

    خطِ آهنگ گمانه می‌زند نه یقین: دو اجرای همانند از یک مداح
    می‌توانند راستی دو چیز باشند. پس تصمیم با آدم است. خودِ نوای
    موجود هم فرستاده می‌شود تا بشنود و داوری کند — «نوای ۱۲ شبیه
    این است» چیزی نمی‌گوید، شنیدنش همه‌چیز را می‌گوید.
    """
    screen: list[dict] = data.get("screen") or []

    while screen:
        item = screen.pop(0)
        data["seq"] = int(data.get("seq", 0)) + 1
        file_id = item.get("file_id")
        if not file_id:
            data.setdefault("queue", []).append(item)
            continue

        from services import dedup

        found = await dedup.identify(context.bot, file_id, item.get("madah"))
        if found is None:
            # تازه است؛ بی پرسش به صفِ پذیرش می‌رود.
            data.setdefault("queue", []).append(item)
            continue

        track_id, exact = found
        track = database.get_track(int(track_id))
        if track is None:
            data.setdefault("queue", []).append(item)
            continue

        # داوری با گرداننده است؛ اینجا می‌ایستیم.
        data["screening"] = item
        data["screen"] = screen
        set_state(context.user_data, AWAITING_INTAKE_SCREEN, **data)
        _persist(context, data)
        await _ask_screen(context, data, track, exact)
        return

    data["screen"] = []
    await _end_screen(context, data)


async def _ask_screen(context, data: dict, track, exact: bool) -> None:
    """نوای موجود را می‌فرستد و داوری می‌خواهد."""
    chat_id = int(data["chat_id"])
    caption = texts.msg(
        "screen_ask",
        madah=track["madah"] or "—",
        title=track["title"] or "—",
        track_id=_fa(track["id"]),
        how="همان ضبط" if exact else "همان نوحه، شاید اجرای دیگر",
    )
    markup = inline.intake_screen(data["seq"])
    try:
        if track["file_id"]:
            await _audio(
                context, chat_id, track["file_id"], caption=caption,
                parse_mode="HTML", reply_markup=markup,
            )
        else:
            await _say(context, chat_id, caption, reply_markup=markup)
        return
    except TelegramError as exc:
        logger.warning("پرسشِ غربال فرستاده نشد: %s", exc)

    # نتوانستیم بپرسیم؛ نگهش می‌داریم — کنار گذاشتنِ خاموشِ نوایی
    # که شاید تازه باشد، از یک پرسشِ نپرسیده بدتر است.
    item = data.pop("screening", None)
    if item:
        data.setdefault("queue", []).append(item)
    await _screen_next(context, data)


async def _end_screen(context: ContextTypes.DEFAULT_TYPE, data: dict) -> None:
    """غربال تمام شد؛ حالا پرسش‌ها."""
    kept = len(data.get("queue") or [])
    dropped = int(data.get("dropped", 0))
    chat_id = int(data["chat_id"])

    if not kept:
        await _say(context, chat_id, texts.msg("screen_all_dropped"))
        await _finish(context, data)
        return

    if dropped or int(data.get("total", 0)) > 1:
        await _say(
            context, chat_id,
            texts.msg("screen_done", kept=_fa(kept), dropped=_fa(dropped)),
        )
    await _next(context, data)


async def on_screen_dup(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """«بله، همین است» — از صف بیرون می‌رود."""
    query = update.callback_query
    data = await _tapped_screen(update, context)
    if data is None or query is None:
        return
    await _ack(query)
    await _strip(query, texts.msg("screen_dropped"))
    data.pop("screening", None)
    data["dropped"] = int(data.get("dropped", 0)) + 1
    await _screen_next(context, data)


async def on_screen_new(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """«نه، تازه است» — در صف می‌ماند."""
    query = update.callback_query
    data = await _tapped_screen(update, context)
    if data is None or query is None:
        return
    await _ack(query)
    await _strip(query, texts.msg("screen_kept"))
    item = data.pop("screening", None)
    if item:
        data.setdefault("queue", []).append(item)
    await _screen_next(context, data)


async def _tapped_screen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """نواختی بر دکمه‌های غربال را می‌سنجد."""
    query = update.callback_query
    user = update.effective_user
    if query is None:
        return None
    if user is None or not query.data:
        await _ack(query)
        return None
    if not config.is_admin(user.id):
        await _ack(query, texts.msg("admin_only"), alert=True)
        return None

    if query.message is None:
        await _ack(query)
        return None

    data = await _claim(update, context, query.message.chat_id)
    if data is None:
        await _ack(query, await _busy_note(query.message.chat_id), alert=True)
        return None
    if data.get("screening") is None:
        await _ack(query, texts.msg("intake_gone"), alert=True)
        return None
    try:
        seq = int(query.data.split(":")[2])
    except (IndexError, ValueError):
        await _ack(query)
        return None
    if seq != int(data.get("seq", 0)):
        await _ack(query, texts.msg("intake_stale"), alert=True)
        return None
    return data


async def _next(context: ContextTypes.DEFAULT_TYPE, data: dict) -> None:
    """به نوای پسین می‌رود، یا اگر نمانده باشد، کار را می‌بندد."""
    queue: list[dict] = data.get("queue") or []
    chat_id = int(data["chat_id"])

    if not queue:
        await _finish(context, data)
        return

    item = queue.pop(0)
    # نگارشی که از برچسبِ فایل آمده، پیش از هر کاری به نامِ
    # درستش رسانده می‌شود — فینگلیش، نامِ ناقص، یا غلطِ املایی.
    raw_madah = item.get("madah")
    if raw_madah:
        # ── چرا نگارشِ خام نگه داشته می‌شود ──────────────────
        #
        # این خط، تنها جایی است که نگارشِ اصلیِ برچسب دیده
        # می‌شود؛ خطِ بعد رویش می‌نویسد. بی نگه داشتنش، وقتی
        # گرداننده نام را در کارت تصحیح می‌کند، نامِ مستعار با
        # کلیدِ **حدسِ فارسی** ثبت می‌شد نه نگارشِ لاتینِ خام —
        # و آن دو کلید یکی نیستند:
        #
        #     Mahdi Rasoli -> mhdyrsly   ولی   مهدی رسلی -> mhdrsl
        #
        # پس تصحیح دفعهٔ بعد روی همان فایل نمی‌گرفت، و جدولِ
        # `madah_aliases` تا امروز **صفر ردیف** داشت.
        item["madah_raw"] = raw_madah
        try:
            from services.captions import resolve_madah

            item["madah"] = resolve_madah(raw_madah) or raw_madah
        except Exception:  # noqa: BLE001
            logger.debug("رساندنِ نامِ مداح نشد.", exc_info=True)
    else:
        # ── نام نبود؟ از آوایش بپرس ─────────────────────────
        #
        # خواستهٔ کاربر: «اگر از اون شخص قبلاً گوش داده باشم،
        # بدون اینکه بهم بگه این کیه، می‌گم فلانیه. ربات هم
        # همین‌طوری باشه.»
        #
        # `core/audio/classifier.py` مرکزِ آواییِ هر مداح را از
        # نواهای برچسب‌خورده می‌سازد و نزدیک‌ترین را می‌گوید. تا
        # امروز این گمانه تنها در «نواهای همانند» به کار می‌رفت،
        # نه اینجا که راستی به دردش می‌خورد.
        #
        # زیر آستانهٔ اطمینان `None` برمی‌گردد و کارت مثل همیشه
        # نامِ خالی نشان می‌دهد — گمانهٔ سست بدتر از نبودِ گمانه
        # است. آنچه می‌آید هم در کارت به تأییدِ گرداننده می‌رسد.
        try:
            from services import voice

            heard = await voice.identify_madah(context.bot, item.get("file_id"))
            if heard:
                item["madah"] = heard[0]
                item["madah_by_voice"] = round(heard[1], 3)
                logger.info(
                    "نامِ نوای بی‌برچسب از آوا درآمد: «%s» (%.0f٪).",
                    heard[0], heard[1] * 100,
                )
        except Exception:  # noqa: BLE001
            logger.debug("شناختِ آوایی نشد.", exc_info=True)

    # اسمِ نوا هم همان پیرایش را می‌خواهد: «شور | ماهم حضرت رضا»
    # باید پیش از دیده شدن در کارت، «ماهم حضرت رضا» شده باشد —
    # وگرنه گرداننده همان زباله را تأیید می‌کند.
    raw_title = item.get("title")
    if raw_title:
        try:
            from services.captions import clean_title

            item["title"] = clean_title(raw_title) or raw_title
        except Exception:  # noqa: BLE001
            logger.debug("پیراستنِ اسمِ نوا نشد.", exc_info=True)
    item.setdefault("madah", data.get("batch_madah"))
    item.setdefault("style", None)
    item.setdefault("title", None)
    data["current"] = item
    data["seq"] = int(data.get("seq", 0)) + 1

    # ── تنها یک پرسش: سبک ───────────────────────────────
    #
    # نام مداح و اسم مداحی از برچسب خودِ فایل آمده‌اند. پرسیدنشان
    # از گرداننده، پرسیدنِ چیزی بود که از پیش می‌دانستیم — و در
    # دسته‌ای پنجاه‌تایی یعنی صد پرسشِ بیهوده.
    #
    # نامِ دسته (`/bulk محمود کریمی`) بر برچسب می‌چربد: گرداننده‌ای
    # که آن را نوشته، خودش دیده که برچسب‌ها چه می‌گویند.
    if data.get("batch_madah"):
        item["madah"] = data["batch_madah"]

    # ── خودِ نوا، پیش از پرسش‌هایش ───────────────────────────
    #
    # ## چرا
    #
    # در دسته‌ای بیست‌تایی، پرسشِ «سبکش چیست؟» به‌تنهایی بی‌معناست:
    # گرداننده باید بیست پیام بالا برود تا بیابد کدام فایل است، و
    # گوش کند. با فرستادنِ خودِ نوا درست پیش از پرسش، فایل و
    # پرسشش کنار هم می‌نشینند.
    #
    # یک بار در آغازِ هر نوا، نه پیش از هر پرسش: پرسش‌های پسین
    # همگی زیرِ همین صوت می‌آیند و بافتشان روشن است.
    await _echo_current(context, data)

    # سنجشِ تکراری اینجا **نیست**: مرحلهٔ غربال پیش از همهٔ
    # پرسش‌ها انجامش داده و هرچه به اینجا رسیده، تازه است.

    set_state(context.user_data, AWAITING_INTAKE_STYLE, **data)
    _persist(context, data)
    await _ask(
        context,
        data,
        texts.msg(
            "intake_ask_style_known",
            madah=item.get("madah") or "—",
            title=item.get("title") or "—",
        ),
        reply_markup=inline.intake_styles(data["seq"]),
    )


async def _echo_current(context: ContextTypes.DEFAULT_TYPE, data: dict) -> None:
    """
    نوایی که اکنون پرسش‌هایش پرسیده می‌شود را بازمی‌فرستد.

    ناکامی‌اش کار را نمی‌شکند: نبودِ این صوت آزاردهنده است، ولی
    ایستاندنِ پذیرش بدتر.
    """
    item = data.get("current") or {}
    file_id = item.get("file_id")
    if not file_id:
        return

    total = len(data.get("queue") or []) + 1
    caption = texts.msg("intake_now_this", left=_fa(total - 1))
    try:
        await _audio(
            context, int(data["chat_id"]), file_id,
            caption=caption,
            parse_mode="HTML",
            disable_notification=True,
        )
    except TelegramError as exc:
        logger.debug("بازفرستادنِ نوای جاری نشد: %s", exc)


async def _ask(context, data: dict, body: str, reply_markup=None) -> bool:
    """
    پرسشی از پذیرش را با سرنویسش می‌فرستد.

    یک درگاه برای همهٔ پرسش‌ها، تا سرنویس در پنج جا دستی تکرار
    نشود و روزی یکی از قلم نیفتد.

    ناکامی‌اش دیگر خاموش نمی‌گذرد: `net.say` خطای همیشگی را بالا
    می‌دهد و پیش‌تر هیچ‌کس نمی‌گرفتش — پرسش نمی‌آمد، وضعیت از پیش
    پیش رفته بود، و کاربر می‌دید «دکمه را زدم و هیچ نشد».
    """
    try:
        await _say(
            context, int(data["chat_id"]),
            _header(data) + body,
            reply_markup=reply_markup,
        )
        return True
    except TelegramError as exc:
        logger.warning("پرسشِ پذیرش فرستاده نشد: %s", exc)
        return False


# ═════════════════════════════════════════════════════════════
#  گام‌ها
# ═════════════════════════════════════════════════════════════

def _mine(update: Update, context: ContextTypes.DEFAULT_TYPE) -> dict | None:
    """
    دادهٔ پذیرش، اگر این پیام به همان گفتگوی پذیرش تعلق داشته باشد.

    سنجشِ گفتگو بایسته است: user_data برای هر کاربر یکی است، پس
    گرداننده‌ای که پذیرشی در گروه دارد و در گفتگوی خصوصی چیزی
    می‌نویسد، آن نوشتار به چشم «نام مداح» می‌آمد.
    """
    message = update.effective_message
    if message is None:
        return None

    data = get_data(context.user_data)
    if not data or int(data.get("chat_id", 0)) != message.chat_id:
        # شاید صفِ گروه دستِ گردانندهٔ دیگری بوده و رها شده؛
        # اگر قفل آزاد است، همین‌جا به دست گرفته می‌شود.
        data = _sync(update, context, message.chat_id)
    if not data or data.get("current") is None:
        return None
    if int(data.get("chat_id", 0)) != message.chat_id:
        return None

    # ── چرا اینجا هم مهلت نو می‌شود ─────────────────────────
    #
    # این ایرادِ راستینی بود: مهلت تنها با **دکمه** نو می‌شد، و
    # کندترین گامِ کار — نوشتنِ نامِ نوا — متنی است. گرداننده‌ای
    # که داشت تایپ می‌کرد، قفلش زیرِ دستش سر می‌رفت و ربات
    # اعلامِ رهاشدن می‌داد.
    try:
        from core.db import intake_sessions

        intake_sessions.touch(message.chat_id)
    except Exception:  # noqa: BLE001
        logger.debug("نو کردنِ مهلتِ نشست نشد.", exc_info=True)
    return data


def _sync(update, context, chat_id: int) -> dict | None:
    """
    کوششی هم‌زمان برای گرفتنِ قفل و برداشتنِ صف، بی پیام دادن.

    برای مسیرهای متنی که نمی‌خواهیم با هر نوشتهٔ نامربوط در گروه
    هشدار بدهند.
    """
    user = update.effective_user
    if user is None:
        return None
    try:
        from core.db import intake_sessions

        intake_sessions.ensure_table()
        if not intake_sessions.try_take(int(chat_id), user.id):
            return None
        data = _adopt(context, chat_id)
        if data is not None:
            intake_sessions.touch(int(chat_id))
        return data
    except Exception:  # noqa: BLE001
        logger.debug("هم‌گام‌سازیِ نشست نشد.", exc_info=True)
        return None


async def on_madah(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    data = _mine(update, context)
    if data is None or message is None or not message.text:
        return

    data["current"]["madah"] = _clean(message.text, "madah")
    set_state(context.user_data, AWAITING_INTAKE_STYLE, **data)
    _persist(context, data)
    await _ask(
        context,
        data,
        texts.msg("intake_ask_style"),
        reply_markup=inline.intake_styles(data["seq"]),
    )


async def on_style(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    data = _mine(update, context)
    if data is None or message is None or not message.text:
        return

    data["current"]["style"] = _clean(message.text, "style")
    await _show_card(context, data)


async def on_style_tap(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """سبک از راه دکمه — در گروه، صفحه‌کلید زیرین برای همه پدیدار می‌شد."""
    query = update.callback_query
    if query is None:
        return
    if not query.data:
        await _ack(query)
        return

    data = await _tapped(update, context)
    if data is None:
        return

    parts = query.data.split(":")
    try:
        index = int(parts[3])
    except (IndexError, ValueError):
        await _ack(query)
        return
    if not 0 <= index < len(STYLES):
        await _ack(query)
        return

    data["current"]["style"] = STYLES[index]
    await _ack(query)
    await _strip(query)
    await _show_card(context, data)


# `_ask_title` از اینجا برداشته شد: اسم مداحی از برچسب فایل
# می‌آید و اگر غلط باشد، دکمهٔ «ویرایش» روی کارت هست. پرسیدنش
# یک گامِ اضافه بود برای چیزی که از پیش می‌دانستیم.


async def on_title(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    data = _mine(update, context)
    if data is None or message is None or not message.text:
        return

    data["current"]["title"] = _clean(message.text, "title")
    await _show_card(context, data)


async def on_skip_title(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """دکمهٔ «رد شدن» در گام نام."""
    query = update.callback_query
    data = await _tapped(update, context)
    if data is None or query is None:
        return
    data["current"]["title"] = None
    await _ack(query)
    await _strip(query)
    await _show_card(context, data)


# ═════════════════════════════════════════════════════════════
#  کارت شناسنامه
# ═════════════════════════════════════════════════════════════

def _card_text(item: dict, header_key: str = "intake_card") -> str:
    return texts.msg(
        header_key,
        madah=item.get("madah") or "—",
        style=item.get("style") or "—",
        title=item.get("title") or "—",
        duration=format_duration(item.get("duration")),
    )


async def _show_card(context: ContextTypes.DEFAULT_TYPE, data: dict) -> None:
    """
    شناسنامه با تأیید و لغو کنار هم و ویرایش زیرشان.

    سنجشِ تکراری اینجا **نیست**، و این درسِ یک باگ است: این تابع
    از پنج جا صدا می‌شود — پس از سبک، پس از نام، و پس از هر
    ویرایشِ میدان. سنجش که اینجا بود، برای هر نوا پنج بار فایل را
    فرو می‌گرفت و رمزگشایی می‌کرد و صوتِ هشدار را دوباره
    می‌فرستاد. اکنون یک بار در `_next` می‌رود، پیش از هر پرسشی.
    """
    set_state(context.user_data, AWAITING_INTAKE_CARD, **data)
    _persist(context, data)
    await _ask(
        context,
        data,
        _card_text(data["current"]),
        reply_markup=inline.intake_card(data["seq"]),
    )


async def _tapped(update: Update, context: ContextTypes.DEFAULT_TYPE) -> dict | None:
    """
    نواختی بر یکی از دکمه‌های پذیرش را می‌سنجد.

    سه چیز سنجیده می‌شود: نوازنده گرداننده باشد، پذیرشی در جریان
    باشد، و کارت کهنه نباشد.
    """
    query = update.callback_query
    user = update.effective_user
    if query is None:
        return None
    if user is None or not query.data:
        await _ack(query)
        return None

    # پیش‌تر اینجا خاموش بازمی‌گشتیم. تلگرام تا وقتی پاسخِ نواخت را
    # نگیرد، چرخِ روی دکمه را می‌چرخاند — پس آن بازگشتِ خاموش، دکمه
    # را برای همیشه «گیر کرده» نشان می‌داد و هیچ نشانی هم در گزارش
    # نمی‌گذاشت.
    if query.message is None:
        await _ack(query)
        return None

    if not config.is_admin(user.id):
        await _ack(query, texts.msg("admin_only"), alert=True)
        return None

    # ── قفلِ گروه ───────────────────────────────────────────
    #
    # پیش‌تر اینجا `user_data`ی **خودِ نوازنده** خوانده می‌شد؛
    # گردانندهٔ B که کارتِ A را می‌نواخت پیامِ گمراه‌کنندهٔ «پذیرشی
    # در جریان نیست» می‌گرفت و کارتِ A دست‌نخورده می‌ماند.
    data = await _claim(update, context, query.message.chat_id)
    if data is None:
        await _ack(query, await _busy_note(query.message.chat_id), alert=True)
        return None

    if data.get("current") is None:
        await _ack(query, texts.msg("intake_gone"), alert=True)
        return None

    try:
        seq = int(query.data.split(":")[2])
    except (IndexError, ValueError):
        await _ack(query)
        return None

    if seq != int(data.get("seq", 0)):
        await _ack(query, texts.msg("intake_stale"), alert=True)
        return None

    return data


async def _busy_note(chat_id: int) -> str:
    """
    «گردانندهٔ دیگری مشغول است» — یا «کاری در جریان نیست».

    نامِ دارنده گفته نمی‌شود: تنها شناسهٔ عددی‌اش را داریم و آن
    برای بقیهٔ گردانندگان چیزی نمی‌گوید. آنچه به کارشان می‌آید
    این است که کسی هست و مهلتش کِی سر می‌آید.
    """
    try:
        from core.db import intake_sessions

        owner = intake_sessions.holder(int(chat_id))
    except Exception:  # noqa: BLE001
        owner = None
    return texts.msg("intake_gone" if owner is None else "intake_busy")


async def _ack(query, text: str | None = None, alert: bool = False) -> None:
    """
    نواخت را پاسخ می‌دهد و اگر شبکه لغزید، کار را نمی‌ایستاند.

    پاسخِ نواخت تنها چرخِ روی دکمه را می‌خواباند؛ اگر نرسید، هیچ
    دلیلی ندارد که بقیهٔ کار هم زمین بماند. پیش‌تر همین یک خطای
    شبکه، کارتِ پس از آن را هم از میان می‌برد.
    """
    try:
        await query.answer(text, show_alert=alert)
    except TelegramError as exc:
        logger.debug("پاسخ نواخت نرسید: %s", exc)


async def _strip(query, note: str | None = None) -> None:
    """
    دکمه‌های کارت را برمی‌دارد تا دوبار نواخته نشود.

    ناکامی‌اش بی‌اهمیت است: نگهبانِ راستینِ دوبار-نواختن، شمارهٔ
    کارت است نه برداشتن دکمه‌ها.
    """
    try:
        if note:
            body = getattr(query.message, "text", None) or ""
            await query.edit_message_text(
                f"{body}\n\n{note}".strip(),
                parse_mode="HTML",
                reply_markup=None,
            )
        else:
            await query.edit_message_reply_markup(reply_markup=None)
    except TelegramError as exc:
        # کوشش دوباره با همان فراخوان، همان شکست را می‌دهد و تنها
        # مهلت را دو برابر می‌کند. پیش‌تر همین‌جا بود.
        logger.debug("برداشتن دکمه‌های کارت نشد: %s", exc)


# ═════════════════════════════════════════════════════════════
#  ویرایش
# ═════════════════════════════════════════════════════════════

async def on_edit(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """«کدام بخش را می‌خواهید اصلاح کنید؟»"""
    query = update.callback_query
    data = await _tapped(update, context)
    if data is None or query is None:
        return
    await _ack(query)
    await _render_fields(query, data)


async def _render_fields(query, data: dict) -> None:
    try:
        await query.edit_message_text(
            _header(data) + _card_text(data["current"], "intake_edit_which"),
            parse_mode="HTML",
            reply_markup=inline.intake_fields(data["seq"]),
        )
    except TelegramError as exc:
        logger.debug("نمایش فهرست بخش‌های پذیرش نشد: %s", exc)


async def on_field(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """بخشی برگزیده شد؛ اکنون نوشتار تازه خواسته می‌شود."""
    query = update.callback_query
    data = await _tapped(update, context)
    if data is None or query is None:
        return

    parts = query.data.split(":")
    field = parts[3] if len(parts) > 3 else ""
    if field not in FIELDS:
        await _ack(query)
        return

    data["field"] = field
    set_state(context.user_data, AWAITING_INTAKE_EDIT, **data)
    _persist(context, data)
    await _ack(query)
    body = _header(data) + texts.msg(
        "intake_edit_ask",
        field=FIELDS[field],
        current=data["current"].get(field) or "—",
    )
    try:
        await query.edit_message_text(
            body,
            parse_mode="HTML",
            reply_markup=inline.intake_back(data["seq"]),
        )
    except TelegramError:
        try:
            await _say(
                context, int(data["chat_id"]),
                body,
                reply_markup=inline.intake_back(data["seq"]),
            )
        except TelegramError as exc:
            logger.warning("پرسشِ ویرایشِ پذیرش فرستاده نشد: %s", exc)


async def on_value(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """نوشتار تازهٔ یک بخش رسید."""
    message = update.effective_message
    data = _mine(update, context)
    if data is None or message is None or not message.text:
        return

    field = data.get("field")
    if field not in FIELDS:
        return

    value = _clean(message.text, field)

    # ── تصحیحِ نامِ مداح، آموخته می‌شود ──────────────────────
    #
    # ## چرا اینجا
    #
    # این همان لحظه‌ای است که آدمی می‌گوید «آن نگارش، این نام
    # است». استوارترین گواهی که می‌شود داشت — و پیش‌تر خاموش
    # دور ریخته می‌شد.
    #
    # از این پس، هر فایلی که همان نگارش را داشته باشد خودکار به
    # نامِ درست می‌رسد و گرداننده دوباره پرسیده نمی‌شود.
    if field == "madah" and value:
        # نگارشِ **خام** می‌چربد: کلیدِ نامِ مستعار باید همانی
        # باشد که دفعهٔ بعد از برچسبِ فایل می‌آید، نه حدسی که
        # خودمان ساخته‌ایم.
        previous = (
            data["current"].get("madah_raw")
            or data["current"].get("madah")
            or ""
        ).strip()
        if previous and previous != value:
            try:
                from core.db import madah_aliases

                madah_aliases.remember(
                    previous, value, added_by=update.effective_user.id
                    if update.effective_user else None
                )
            except Exception:  # noqa: BLE001
                logger.debug("آموختنِ نامِ مستعار نشد.", exc_info=True)

    data["current"][field] = value
    if field == "title":
        # اسمی که آدمی نوشته، بیتِ شعر است و روی جلد می‌نشیند؛
        # اسمی که از برچسب آمده، تنها یک نام است.
        data["current"]["title_typed"] = True
    data.pop("field", None)
    set_state(context.user_data, AWAITING_INTAKE_CARD, **data)
    _persist(context, data)

    await _ask(
        context,
        data,
        texts.msg("intake_edit_done", field=FIELDS[field], value=value or "—")
        + "\n\n"
        + _card_text(data["current"], "intake_edit_which"),
        reply_markup=inline.intake_fields(data["seq"]),
    )


async def on_back(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """از خواستنِ نوشتار، به فهرست بخش‌ها."""
    query = update.callback_query
    data = await _tapped(update, context)
    if data is None or query is None:
        return
    data.pop("field", None)
    set_state(context.user_data, AWAITING_INTAKE_CARD, **data)
    _persist(context, data)
    await _ack(query)
    await _render_fields(query, data)


# ═════════════════════════════════════════════════════════════
#  تأیید و لغو
# ═════════════════════════════════════════════════════════════

async def on_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """تأیید — نوا در گنجینه می‌نشیند."""
    query = update.callback_query
    admin = update.effective_user
    data = await _tapped(update, context)
    if data is None or query is None or admin is None:
        return

    item = data["current"]
    await _ack(query)
    await _strip(query, texts.msg("intake_confirmed_mark"))

    # کارت را همین‌جا می‌بندیم تا نواختِ دوباره — که تلگرام گاه
    # می‌فرستد — نوایی دوقلو نسازد.
    data["current"] = None
    data["seq"] = int(data.get("seq", 0)) + 1

    track_id = await _commit(context, item, admin.id, int(data["chat_id"]))
    if track_id is None:
        await _say(context, int(data["chat_id"]), texts.msg("intake_duplicate"))
    else:
        data["done"] = int(data.get("done", 0)) + 1
        await _say(
            context, int(data["chat_id"]),
            texts.msg(
                "intake_saved",
                madah=item.get("madah") or "—",
                title=item.get("title") or "—",
                track_id=_fa(track_id),
            ),
        )

    await _next(context, data)


async def on_drop(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """لغو — از این نوا می‌گذریم."""
    query = update.callback_query
    data = await _tapped(update, context)
    if data is None or query is None:
        return

    await _ack(query)
    await _strip(query, texts.msg("intake_dropped_mark"))
    data["current"] = None
    data["seq"] = int(data.get("seq", 0)) + 1
    data["skipped"] = int(data.get("skipped", 0)) + 1
    await _next(context, data)


async def _commit(
    context: ContextTypes.DEFAULT_TYPE, item: dict, admin_id: int, chat_id: int
) -> int | None:
    """
    نوا را در گنجینه می‌نشاند و کارهای پس از آن را می‌راند.

    تکراری بودن **اینجا دوباره** سنجیده می‌شود، نه تنها هنگام
    گرفتن فایل: میان گرفتن و تأیید، دقیقه‌ها می‌گذرد و در آن میان
    شاید همان نوا از راه دیگری افزوده شده باشد.
    """
    duplicate = database.find_duplicate_track(
        file_unique_id=item.get("file_unique_id")
    )
    if duplicate is not None:
        track_id = int(duplicate["id"])
    else:
        track_id = database.add_track(
            file_id=item["file_id"],
            file_unique_id=item.get("file_unique_id"),
            source="admin",
            title=item.get("title") or item.get("madah") or item.get("file_name"),
            madah=item.get("madah"),
            style=item.get("style"),
            duration=item.get("duration"),
            file_size=item.get("file_size"),
            source_chat_id=item.get("source_chat_id"),
            source_msg_id=item.get("source_msg_id"),
            added_by=admin_id,
        )
        # lyrics_snippet روی جلد نقش می‌بندد، پس تنها بیتی که
        # گرداننده خودش نوشته آنجا می‌نشیند. نامِ آمده از برچسب،
        # همان نام است و نشاندنش روی جلد یعنی یک نوشته دوبار.
        if item.get("title") and item.get("title_typed"):
            database.execute(
                "UPDATE tracks SET lyrics_snippet = ? WHERE id = ?",
                (item["title"], track_id),
            )
        # برچسب و جلد و نسخهٔ آراسته، سپس نمایه — در پس‌زمینه، تا
        # گرداننده چشم‌به‌راه نماند.
        context.application.create_task(_finalize(context, track_id))

    if item.get("search_id"):
        await _fulfil(
            context, int(item["search_id"]), track_id, item, admin_id, chat_id
        )

    return None if duplicate is not None else track_id


async def _finalize(context: ContextTypes.DEFAULT_TYPE, track_id: int) -> None:
    from services import indexer

    try:
        await indexer.finalize_track(context.bot, track_id)
    except Exception:  # noqa: BLE001
        logger.exception("کار پایانی نوای %s شکست خورد.", track_id)


async def _fulfil(
    context: ContextTypes.DEFAULT_TYPE,
    search_id: int,
    track_id: int,
    item: dict,
    admin_id: int,
    notify_chat: int,
) -> None:
    """بازجویی ناکام را می‌بندد و نوا را برای جویندهٔ نخست می‌فرستد."""
    record = searches.get(search_id)
    if record is None:
        return
    if not searches.mark_fulfilled(search_id, track_id, admin_id):
        return  # گردانندهٔ دیگری پیش‌دستی کرد

    # ── قفلِ پرکردن، آزاد ───────────────────────────────────
    #
    # `searches.release_fill` نوشته شده بود و **هیچ‌جا صدا
    # نمی‌شد**؛ قفل تنها با سر آمدنِ مهلت باز می‌شد. یعنی
    # گرداننده‌ای که کارش را تمام کرده بود، تا پایانِ مهلت جلوِ
    # بقیه را می‌گرفت. کار که تمام شد، قفل هم باید برود.
    try:
        searches.release_fill(search_id)
    except Exception:  # noqa: BLE001
        logger.debug("آزاد کردنِ قفلِ پرکردن نشد.", exc_info=True)

    user_id = int(record["user_id"])
    try:
        await net.say(
            context.bot,
            user_id,
            texts.msg(
                "fill_delivered_to_user",
                madah=item.get("madah") or "نامعلوم",
                style=item.get("style") or "—",
            ),
        )
        from bot.keyboards import inline
        from services.tagger import audio_labels

        database.bump_sent_count(track_id)
        await net.retry(
            lambda: context.bot.send_audio(
                chat_id=user_id,
                audio=item["file_id"],
                protect_content=True,
                # «درست است / این نیست» — چون این نوا سکه می‌ستاند،
                # باید راهی برای پس گرفتنش باشد؛ و همان دکمه قفلِ
                # فایل را هم برمی‌دارد.
                reply_markup=inline.search_result(search_id),
                **audio_labels(item),
            ),
            label="رساندن نوای پرشده",
        )
        # گرداننده کار کرد و نوا رسید؛ اکنون سکه برداشته می‌شود.
        # جست‌وجوی این کاربر ناکام مانده بود و سکه‌ای نگرفته
        # بودیم — ولی سرانجام آنچه می‌خواست به دستش رسید، و
        # همان است که سکه بهایش را می‌دهد.
        _charge_fulfilled(user_id, search_id)
        # درخواست کار در گروه، دیگر بی‌معناست.
        from bot.handlers.search import close_report

        await close_report(context.bot, search_id)
        return
    except Forbidden:
        database.mark_blocked_bot(user_id)
        logger.info("جویندهٔ %s ربات را مسدود کرده است.", user_id)
    except TelegramError as exc:
        logger.warning("رساندن نوای پرشده به کاربر %s شکست خورد: %s", user_id, exc)

    # گرداننده باید بداند نرسید. خاموش گذشتن اینجا یعنی او گمان
    # می‌کند کارش تمام شده، حال آنکه جوینده هنوز چشم‌به‌راه است.
    try:
        await _say(context, notify_chat, texts.msg("fill_user_gone"))
    except TelegramError:
        pass


def _charge_fulfilled(user_id: int, search_id: int) -> None:
    """
    سکهٔ نوایی که گرداننده دستی رساند.

    ناکامی‌اش نوا را پس نمی‌گیرد — فایل از پیش رفته است. تنها
    گزارش می‌شود.
    """
    from core.db.database import InsufficientTokens

    try:
        balance = database.adjust_tokens(
            user_id,
            -config.token_cost_per_search,
            reason="search",
            ref_type="search",
            ref_id=search_id,
            note="نوایی که گرداننده رساند",
        )
        searches.mark_charged(search_id)
        logger.info("سکهٔ کاربر %s پس از پر شدن بازجویی شد %s.", user_id, balance)
    except InsufficientTokens:
        logger.warning("کاربر %s سکه نداشت ولی نوای پرشده رفت.", user_id)
    except Exception:  # noqa: BLE001
        logger.exception("برداشتن سکهٔ بازجویی %s نشد.", search_id)


async def _finish(context: ContextTypes.DEFAULT_TYPE, data: dict) -> None:
    chat_id = int(data["chat_id"])
    done = int(data.get("done", 0))
    skipped = int(data.get("skipped", 0))
    clear_state(context.user_data)

    # ── رُفت‌وروب، پیش از پیامِ پایانی ──────────────────────
    #
    # هرچه در این دسته ساخته شد — صوت‌های بازفرستاده، پرسش‌ها،
    # کارت‌ها، «به گنجینه افزوده شد» — برداشته می‌شود و تنها
    # نسخهٔ آراسته در گروه می‌ماند، که هرگز ثبت نشده.
    #
    # ترتیب مهم است: پیامِ پایانی **پس از** رُفت‌وروب می‌رود و
    # خودش ثبت نمی‌شود، وگرنه همان‌جا پاک می‌شد و گرداننده
    # خبری از پایانِ کار نمی‌گرفت.
    gone = await _sweep(context, int(data["chat_id"]))
    if gone:
        logger.info("پاک‌سازیِ پایانِ پذیرش: %s پیام برداشته شد.", gone)

    # نشست بسته می‌شود: کاری نمانده که کسی بخواهد دنباله‌اش را
    # بگیرد، و ماندنش یعنی قفلِ بی‌سبب بر گروه.
    _close(context, chat_id)

    await net.say(
        context.bot, chat_id,
        texts.msg("intake_finished", added=_fa(done), skipped=_fa(skipped)),
    )
    logger.info("پذیرش پایان یافت: %s افزوده، %s رهاشده.", done, skipped)


async def sweep_locks(context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    قفل‌هایی که مهلتشان گذشته را آزاد می‌کند و خبر می‌دهد.

    ## چرا خبر دادن، و نه آزاد کردنِ خاموش

    گرداننده‌ای که نتش قطع شده نمی‌داند کارش رها شده؛ و بقیه هم
    نمی‌دانند می‌توانند دنباله‌اش را بگیرند. یک پیام، هر دو را
    می‌گوید — و همان است که کاربر خواست: «تموم شدن زمان ۲ دقیقه
    ربات اعلام می‌کنه که کی از ادمین‌ها ادامه بده».

    صف **پاک نمی‌شود**؛ تنها قفلش برداشته می‌شود. کارِ نیمه‌کاره
    سرِ جایش می‌ماند تا هر گرداننده‌ای — از جمله خودِ آغازگر —
    برش دارد.
    """
    from core.db import intake_sessions

    try:
        intake_sessions.ensure_table()
        rows = intake_sessions.expired()
    except Exception:  # noqa: BLE001
        logger.debug("سنجشِ قفل‌های سرآمده نشد.", exc_info=True)
        return

    for row in rows:
        chat_id = int(row["chat_id"])
        try:
            data = intake_sessions.load(chat_id) or {}
            intake_sessions.release(chat_id)
        except Exception:  # noqa: BLE001
            logger.debug("آزاد کردنِ قفلِ گفتگوی %s نشد.", chat_id, exc_info=True)
            continue

        left = len(data.get("queue") or []) + len(data.get("screen") or [])
        # `items` فایل‌هایی است که در گامِ گردآوری (`/bulk`) رسیده‌اند
        # و هنوز به صفِ پذیرش نرفته‌اند. نشمردنشان یعنی جاروب،
        # نشستِ نیمه‌گردآورده را **پاک** می‌کرد و همهٔ فایل‌های
        # فرستاده‌شده از دست می‌رفت.
        left += len(data.get("items") or [])
        if data.get("current") or data.get("screening"):
            left += 1
        if not left:
            # کاری نمانده؛ نشست بیهوده است.
            intake_sessions.clear(chat_id)
            continue

        logger.info("قفلِ پذیرشِ گفتگوی %s آزاد شد؛ %s نوا مانده.", chat_id, left)
        try:
            await net.say(
                context.bot, chat_id,
                texts.msg("intake_handover", count=_fa(left)),
            )
        except TelegramError as exc:
            logger.debug("اعلامِ آزاد شدنِ قفل نشد: %s", exc)


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """
    `/cancel` در میانهٔ پذیرش.

    بازگشتی می‌گوید آیا پذیرشی بود که بسته شود — تا فراخوان بداند
    پیام دیگری بایسته است یا نه.
    """
    from bot.states import INTAKE_STATES

    if get_state(context.user_data) not in INTAKE_STATES:
        return False

    data = get_data(context.user_data)
    left = len(data.get("queue") or []) + (1 if data.get("current") else 0)

    # قفلِ پرکردنِ هر بازجویی که در این صف بود، آزاد شود — وگرنه
    # رها کردنِ کار، آن ناکامی را تا پایانِ مهلت برای بقیه
    # می‌بندد.
    pending = list(data.get("queue") or [])
    if data.get("current"):
        pending.append(data["current"])
    for item in pending:
        sid = item.get("search_id") if isinstance(item, dict) else None
        if sid:
            try:
                searches.release_fill(int(sid))
            except Exception:  # noqa: BLE001
                logger.debug("آزاد کردنِ قفلِ پرکردن نشد.", exc_info=True)

    clear_state(context.user_data)

    message = update.effective_message
    if message is not None:
        await message.reply_html(texts.msg("intake_cancelled", left=_fa(left)))
    return True
