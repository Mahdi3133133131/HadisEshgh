"""
فهرست دستورها — همان که در تلگرام با دکمهٔ «/» کنار کادر نوشتن
گشوده می‌شود.

## چرا دامنه‌بندی می‌شود

تلگرام برای هر دامنه فهرست جدایی نگه می‌دارد. اگر یک فهرست برای
همه بگذاریم، همراهِ ساده هم `/bulk` و `/delete` را می‌بیند — و
دیدنِ دستوری که اجازه‌اش را ندارد، هم گیج‌کننده است و هم دعوت به
آزمودن.

پس هر گفتگو فهرست خودش را دارد:

  • گفتگوی خصوصی — چهار دستور سادهٔ همراه
  • گروه بایگانی — کار با خودِ گنجینه: افزودن و برداشتن
  • گروه مداحی — داوری پیشکش‌ها و گزارش‌ها
  • گروه انتقادات — تنها آنچه آنجا به کار می‌آید
  • گروه کاربران — تنها آمار

## چرا افزودن و برداشتن در گروه بایگانی است، نه گروه مداحی

نوایی که افزوده می‌شود، نسخهٔ آراسته‌اش در همان گروه بایگانی
می‌نشیند. پس افزودن و دیدن نتیجه‌اش در یک جا می‌گذرد. گروه مداحی
جای داوری پیشکشِ همراهان است، و آمیختن این دو، هر دو را شلوغ
می‌کرد.

دستورهای مالک در فهرستِ گروه مداحی نشان داده می‌شوند (`/addadmin`
روشن و خواسته شد) ولی همچنان تنها مالک را می‌پذیرند؛ دو تایِ دیگر
پنهان‌اند چون تنها یک نفر در کل ربات به آن‌ها دسترسی دارد و
نشاندنشان در فهرستِ همه، دعوت به آزمودنِ چیزی است که برایشان کار
نمی‌کند.
"""

from __future__ import annotations

import logging

from telegram import (
    BotCommand,
    BotCommandScopeAllPrivateChats,
    BotCommandScopeChat,
)
from telegram.error import TelegramError

from config import config
from core import net

logger = logging.getLogger(__name__)


# ── همراهان، در گفتگوی خصوصی ─────────────────────────────────
PRIVATE: tuple[tuple[str, str], ...] = (
    ("start", "🌿 آغاز و بررسی عضویت"),
    ("menu", "📋 منوی اصلی"),
    ("help", "📖 راهنما"),
    ("cancel", "✖️ رها کردن کار نیمه‌کاره"),
)

# ── گروه بایگانی: کار با خودِ گنجینه ──────────────────────────
ARCHIVE_GROUP: tuple[tuple[str, str], ...] = (
    ("bulk", "📂 افزودن مداحی — سپس فایل‌ها را پشت هم بفرستید"),
    ("bulk_end", "⏹ پایان گرفتن فایل‌ها و آغاز پرسیدن مشخصات"),
    ("delete", "🗑 برداشتن مداحی از آرشیو"),
    ("clean", "🧹 پاک کردن پیام‌های اضافهٔ ربات"),
    ("cancel", "✖️ رها کردن کار نیمه‌کاره"),
    ("id", "🪪 شناسهٔ این گروه"),
)

# ── گروه مداحی: داوری پیشکش‌ها و گزارش‌ها ─────────────────────
MADAHI_GROUP: tuple[tuple[str, str], ...] = (
    ("failures", "🔍 جست‌وجوهایی که به جایی نرسید"),
    ("wanted", "📋 پرخواسته‌ترین‌هایی که نداریم"),
    ("clean", "🧹 پاک کردن پیام‌های اضافهٔ ربات"),
    ("restore", "♻️ بازیابی پایگاه داده از پشتیبان"),
    ("addadmin", "👑 افزودن گرداننده (تنها مالک)"),
    ("alias", "🔤 نام‌های مستعار مداحان"),
    ("madahs", "🎤 مداحان و نواهایشان"),
    ("trust", "🤝 اعتماد به کاربر — پیشکشش داوری نمی‌خواهد"),
    ("untrust", "↩️ پس گرفتن اعتماد"),
    ("trusted", "👥 فهرست کاربران مورد اعتماد"),
    ("stats", "📊 آمار کاربران و آرشیو"),
    ("engine", "⚙️ وضعیت موتور و صف"),
    ("reindex", "🔄 نمایه‌سازی مداحی‌های در انتظار"),
    ("broken", "🩺 صوت‌های مشکل‌دار — برای اصلاح دوباره"),
    ("features", "🎼 وضعیت لایهٔ فهم مداحی"),
    ("train", "🎓 آموزش دوبارهٔ گمانه‌زن"),
    ("health", "🩺 تندرستی: شبکه، گروه‌ها، صف"),
    ("backup", "💾 پشتیبان"),
    ("crawl", "🕸 وضعیت خزنده"),
    ("sites", "🌐 جست‌وجو در سایت‌ها — وضعیت و تازه‌سازی"),
    ("addchannel", "🔗 افزودن کانال عضویت اجباری"),
    ("channels", "📋 کانال‌های عضویت اجباری"),
    ("delchannel", "❌ برداشتن کانال عضویت اجباری"),
    ("addsource", "🎧 افزودن کانال مداحی — ربات در آن هم بگردد"),
    ("sources", "📋 کانال‌های مداحی"),
    ("delsource", "❌ برداشتن کانال مداحی"),
    ("reload_texts", "📝 خواندن دوبارهٔ متن‌ها"),
    ("cancel", "✖️ رها کردن کار نیمه‌کاره"),
    ("id", "🪪 شناسهٔ این گروه"),
)

# ── گروه انتقادات ────────────────────────────────────────────
FEEDBACK_GROUP: tuple[tuple[str, str], ...] = (
    ("textall", "📢 پیام همگانی"),
    ("stats", "📊 آمار کاربران و آرشیو"),
    ("health", "🩺 تندرستی ربات"),
    ("id", "🪪 شناسهٔ این گروه"),
)

# ── گروه کاربران: تنها تماشا ─────────────────────────────────
USERS_GROUP: tuple[tuple[str, str], ...] = (
    ("stats", "📊 آمار کاربران و آرشیو"),
    ("id", "🪪 شناسهٔ این گروه"),
)


def _merge(*lists: tuple[tuple[str, str], ...]) -> tuple[tuple[str, str], ...]:
    """
    چند فهرست را یکی می‌کند، بی تکرار و با نگه داشتن ترتیب.

    وقتی به کار می‌آید که دو نقش به یک گفتگو افتاده باشند — مثلاً
    ORNATE_GROUP_ID تنظیم نشده و گروه بایگانی همان گروه مداحی است.
    بی این، فهرست دومی که نشانده می‌شود اولی را پاک می‌کرد و
    دستورهای یک نقش ناپدید می‌شدند.
    """
    seen: set[str] = set()
    out: list[tuple[str, str]] = []
    for pairs in lists:
        for name, description in pairs:
            if name in seen:
                continue
            seen.add(name)
            out.append((name, description))
    return tuple(out)


# ── دامنه‌بندی: هر فرمان در کدام گفتگوها کار می‌کند ────────────
#
# ## چرا این هست
#
# پیش‌تر هر فرمانی در هر جایی ثبت شده بود: `/clean` در گفتگوی
# خصوصی هم کار می‌کرد و هر کسی می‌توانست دستورهای گروه را در
# خصوصی بزند. خواستهٔ روشن شد: فرمانِ گروه در گروه خودش، و
# فرمانِ ناشناخته هیچ‌جا پاسخِ درست نگیرد.

# در هر گفتگویی — چون یا برای همه‌جاست (`/cancel`) یا برای
# یافتنِ شناسهٔ هر گروه تازه‌ای که ربات را به آن افزوده‌اند (`/id`).
_EVERYWHERE = frozenset({"id", "cancel"})

# در گفتگوی خصوصی، بی‌آنکه در فهرستِ خصوصی نشان داده شوند.
# `/upload` و `/done` تنها برای همراهِ مورد اعتمادند و نمایششان
# به همه گیج‌کننده است؛ `/madahs` اما هم برای گرداننده‌است هم
# برای همراه، و فهرستِ خصوصی فقط دستورهای ساده را نشان می‌دهد.
_EXTRA_PRIVATE = frozenset({"upload", "done", "madahs"})

# فرمان‌های مالک که فهرستِ گروه مداحی نشانشان نمی‌دهد ولی در همان
# گروه یا خصوصی (برای مالک) کار می‌کنند.
_OWNER_TOOLS = frozenset({"deladmin", "admins"})

# `/bulk` در هر دو گروهِ کاری رواست — دسته‌ای هم در گروه بایگانی
# هم در گروه مداحی آغاز می‌شود (برای هم‌زمان کار کردن دو گرداننده).
_EXTRA_KINDS: dict[str, tuple[str, ...]] = {
    "bulk": ("archive", "madahi"),
    "bulk_end": ("archive", "madahi"),
    "addadmin": ("madahi",),
    "deladmin": ("madahi",),
    "admins": ("madahi",),
}


def allowed_chats(name: str) -> tuple[str, ...] | None:
    """
    دامنهٔ یک فرمان: «private» و نامِ گروه‌ها. `None` یعنی همه‌جا.

    نامِ گروه‌ها: `archive` (گروه بایگانی)، `madahi`، `feedback`،
    `users`. شناسهٔ راستین را مسیریاب از همین‌جا می‌سازد، پس اگر
    ORNATE_GROUP_ID تنظیم نشده باشد همان گروه مداحی است — همان
    قاعدهٔ `ornate_target`.
    """
    if name in _EVERYWHERE:
        return None

    kinds: list[str] = []
    if any(n == name for n, _ in PRIVATE) or name in _EXTRA_PRIVATE:
        kinds.append("private")
    for pairs, kind in (
        (ARCHIVE_GROUP, "archive"),
        (MADAHI_GROUP, "madahi"),
        (FEEDBACK_GROUP, "feedback"),
        (USERS_GROUP, "users"),
    ):
        if any(n == name for n, _ in pairs) and kind not in kinds:
            kinds.append(kind)
    for kind in _EXTRA_KINDS.get(name, ()):
        if kind not in kinds:
            kinds.append(kind)
    if name in _OWNER_TOOLS:
        for kind in ("private", "madahi"):
            if kind not in kinds:
                kinds.append(kind)

    return tuple(kinds) if kinds else None


def _commands(pairs) -> list[BotCommand]:
    # تلگرام توضیح را تا ۲۵۶ نویسه می‌پذیرد، ولی کوتاه بهتر خوانده
    # می‌شود؛ فهرستِ دراز در پرده جا نمی‌شود.
    return [BotCommand(name, description[:256]) for name, description in pairs]


async def publish(bot) -> None:
    """
    فهرست‌ها را به تلگرام می‌سپارد.

    ناکامی هیچ‌کدام کار را نمی‌ایستاند: نبودِ فهرست یعنی کاربر باید
    دستور را از بر بنویسد، نه اینکه چیزی بشکند. پس تنها گزارش
    می‌شود.

    شناسه‌ها از راه net.resolved می‌گذرند: پیش‌پرواز پیش از این
    اجرا شده و اگر شناسهٔ .env شکل نادرستی داشته باشد، شکل کارآمدش
    را یافته است. بی این، فهرستِ گروهی که شناسه‌اش وارونه نوشته شده
    خاموش از دست می‌رفت.
    """
    targets: list[tuple[str, object, tuple[tuple[str, str], ...]]] = [
        ("گفتگوی خصوصی", BotCommandScopeAllPrivateChats(), PRIVATE),
    ]

    # هر گفتگو یک بار، با همهٔ نقش‌هایی که به آن افتاده. ترتیب
    # نگه داشته می‌شود تا فهرست هر گروه با کار اصلی‌اش آغاز شود.
    by_chat: dict[int, tuple[str, list[tuple[tuple[str, str], ...]]]] = {}

    def claim(chat_id: int, label: str, pairs: tuple[tuple[str, str], ...]) -> None:
        if not chat_id:
            return
        chat_id = net.resolved(chat_id) or chat_id
        if chat_id in by_chat:
            previous_label, lists = by_chat[chat_id]
            lists.append(pairs)
            by_chat[chat_id] = (f"{previous_label} + {label}", lists)
        else:
            by_chat[chat_id] = (label, [pairs])

    claim(config.ornate_target, "گروه بایگانی", ARCHIVE_GROUP)
    claim(config.madahi_group_id, "گروه مداحی", MADAHI_GROUP)
    claim(config.feedback_group_id, "گروه انتقادات", FEEDBACK_GROUP)
    claim(config.users_group_id, "گروه کاربران", USERS_GROUP)

    for chat_id, (label, lists) in by_chat.items():
        targets.append((label, BotCommandScopeChat(chat_id=chat_id), _merge(*lists)))

    done = 0
    for label, scope, pairs in targets:
        try:
            await bot.set_my_commands(_commands(pairs), scope=scope)
            done += 1
            logger.debug("فهرست «%s»: %s دستور.", label, len(pairs))
        except TelegramError as exc:
            logger.warning("نشاندن فهرست دستورهای «%s» نشد: %s", label, exc)

    if done:
        logger.info("فهرست دستورها در %s جا نشانده شد.", done)
