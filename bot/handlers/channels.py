"""
مدیریت کانال‌ها در زمان اجرا — دو فهرست، شش دستور.

## عضویت اجباری

کانال‌هایی که کاربر باید در همه‌شان عضو باشد. به کار تبلیغ می‌آید:
با مدیر کانالی توافق می‌شود، کانالش برای مدتی به فهرست می‌آید، و
بعد برداشته می‌شود — بی آنکه ربات از نو راه بیفتد.

## کانال منبع

کانال‌های مداحی که مدیرانشان ربات را در آن‌ها مدیر کرده‌اند. هر
فایل تازه‌ای که آنجا گذاشته شود خودکار به آرشیو می‌آید، با
شناسنامه‌ای که از **کپشن** خوانده می‌شود.

⚠️ ربات تلگرام هیچ راهی برای خواندن پست‌های **گذشتهٔ** یک کانال
ندارد. این محدودیت خودِ تلگرام است، نه کاستی ما. پس کانالی که
افزوده می‌شود تنها از همان لحظه به بعد نمایه می‌شود — و همین باید
به گرداننده گفته شود، وگرنه می‌نشیند و چشم‌به‌راه هزاران فایلی
می‌ماند که هرگز نمی‌آیند.

## چرا گردانندگی ربات پیش از افزودن سنجیده می‌شود

هر دو کار — سنجش عضویت و گرفتن پست تازه — بی گردانندگیِ ربات
ناممکن‌اند. اگر همان لحظه نسنجیم، ایراد ساعت‌ها بعد و بر سرِ
کاربران پیدا می‌شود: کانالی در فهرست که هیچ‌کس نمی‌تواند عضویتش را
بگذراند.
"""

from __future__ import annotations

import logging
import re

from telegram import Update
from telegram.error import TelegramError
from telegram.ext import ContextTypes

from bot.guards import admin_only
from bot.states import (
    AWAITING_CHANNEL_INPUT,
    clear_state,
    get_data,
    set_state,
)
from core import texts
from core.db import channels
from core.normalize import to_persian_digits

logger = logging.getLogger(__name__)

# @نام یا نشانی t.me
_USERNAME = re.compile(r"(?:https?://)?(?:t\.me/|telegram\.me/|@)([A-Za-z][\w\d_]{3,})")
_CHAT_ID = re.compile(r"(-\d{6,})")
_URL = re.compile(r"https?://\S+")


def _fa(value: object) -> str:
    return to_persian_digits(str(value))


# ═════════════════════════════════════════════════════════════
#  افزودن
# ═════════════════════════════════════════════════════════════

@admin_only
async def add_required(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    `/addchannel <نشانی> [once]` — کانالی به فهرست عضویت.

    بی «once»، عضویت **همیشگی** است: هر وقت کاربر بیرون برود،
    ربات برایش از کار می‌افتد.

    با «once»، تنها برای تأییدِ نخست لازم است و پس از آن اختیاری
    — همان که برای کانال‌های تبلیغاتی خواسته شد: «عضویت اولیه
    اجباریه، بعد دیگه اختیاریه».
    """
    await _ask(update, context, channels.REQUIRED)


async def _apply_enforce(context, chat_id: int) -> str:
    """
    وضعیتِ اجبار را از آرگومان‌ها برمی‌دارد و می‌نشاند.

    بازگشتی: واژه‌ای برای گزارش به گرداننده.
    """
    args = [str(a).strip().lower() for a in (context.args or [])]
    once = "once" in args or "یک‌باره" in args or "یکباره" in args
    if not once:
        return "همیشگی"
    try:
        channels.set_enforce(int(chat_id), "once")
        return "یک‌باره"
    except Exception:  # noqa: BLE001
        logger.debug("نشاندنِ وضعیتِ اجبار نشد.", exc_info=True)
        return "همیشگی"


@admin_only
async def add_source(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """`/addsource` — کانالی که ربات در آن هم بگردد."""
    await _ask(update, context, channels.SOURCE)


async def _ask(update: Update, context: ContextTypes.DEFAULT_TYPE, kind: str) -> None:
    message = update.effective_message
    if message is None:
        return
    set_state(
        context.user_data,
        AWAITING_CHANNEL_INPUT,
        kind=kind,
        chat_id=message.chat_id,
    )
    key = "channel_ask_required" if kind == channels.REQUIRED else "channel_ask_source"
    await message.reply_html(texts.msg(key))


async def on_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    پاسخِ گرداننده به پرسشِ افزودن.

    سه شکل پذیرفته می‌شود و هر سه به یک جا می‌رسند: `@نام`، نشانی
    `t.me`، یا شناسهٔ عددی همراه پیوند.
    """
    message = update.effective_message
    admin = update.effective_user
    if message is None or admin is None or not message.text:
        return

    data = get_data(context.user_data)
    kind = data.get("kind")
    if kind not in (channels.REQUIRED, channels.SOURCE):
        clear_state(context.user_data)
        return
    if data.get("chat_id") and message.chat_id != data["chat_id"]:
        return

    text = message.text.strip()
    clear_state(context.user_data)

    chat_id, url = _parse(text)
    if chat_id is None and not url:
        await message.reply_html(texts.msg("channel_bad_input"))
        return

    # ── شناسایی خودِ کانال ───────────────────────────────────
    target = chat_id if chat_id is not None else url
    try:
        chat = await context.bot.get_chat(target)
    except TelegramError as exc:
        await message.reply_html(texts.msg("channel_not_found", error=str(exc)[:150]))
        return

    # ── ربات باید آنجا مدیر باشد ────────────────────────────
    if not await _bot_is_admin(context, chat.id):
        await message.reply_html(
            texts.msg("channel_not_admin", title=chat.title or str(chat.id))
        )
        return

    link = url or (f"https://t.me/{chat.username}" if chat.username else "")
    if not link:
        await message.reply_html(texts.msg("channel_need_link"))
        return

    fresh = channels.add(kind, chat.id, link, chat.title, admin.id)

    # وضعیتِ اجبار تنها برای کانالِ عضویت معنا دارد؛ کانالِ
    # سرچشمه اصلاً عضویتی نمی‌خواهد.
    mode = ""
    if kind == channels.REQUIRED:
        mode = await _apply_enforce(context, chat.id)

    key = "channel_added" if fresh else "channel_already"
    await message.reply_html(
        texts.msg(
            key,
            title=chat.title or str(chat.id),
            chat_id=str(chat.id),
            kind=_kind_name(kind) + (f" ({mode})" if mode else ""),
        )
    )

    # کانالِ منبعِ تازه باید همین حالا شنیده شود، نه پس از
    # بازراه‌اندازی. پالایهٔ گرداننده در جا گشوده می‌شود.
    if kind == channels.SOURCE and fresh:
        from bot.handlers import router

        router.watch_source(chat.id)
        await message.reply_html(texts.msg("channel_source_note"))

    logger.info(
        "کانال %s (%s) به فهرست %s افزوده شد به دست %s.",
        chat.id, chat.title, kind, admin.id,
    )


def _parse(text: str) -> tuple[int | None, str]:
    """شناسه و پیوند را از نوشتار بیرون می‌کشد."""
    chat_id = None
    id_match = _CHAT_ID.search(text)
    if id_match:
        try:
            chat_id = int(id_match.group(1))
        except ValueError:
            chat_id = None

    url = ""
    url_match = _URL.search(text)
    if url_match:
        url = url_match.group(0)
    else:
        name_match = _USERNAME.search(text)
        if name_match:
            url = f"https://t.me/{name_match.group(1)}"

    # اگر شناسهٔ عددی ندادند ولی @نام دادند، خودِ نام برای
    # get_chat بس است.
    if chat_id is None and not url:
        name_match = _USERNAME.search(text)
        if name_match:
            url = f"https://t.me/{name_match.group(1)}"
    return chat_id, url


async def _bot_is_admin(context: ContextTypes.DEFAULT_TYPE, chat_id: int) -> bool:
    try:
        me = await context.bot.get_me()
        member = await context.bot.get_chat_member(chat_id, me.id)
    except TelegramError as exc:
        logger.debug("سنجش گردانندگی ربات در %s نشد: %s", chat_id, exc)
        return False
    return member.status in ("administrator", "creator")


# ═════════════════════════════════════════════════════════════
#  فهرست و برداشتن
# ═════════════════════════════════════════════════════════════

@admin_only
async def list_required(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """`/channels`"""
    await _show(update, channels.REQUIRED)


@admin_only
async def list_sources(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """`/sources`"""
    await _show(update, channels.SOURCE)


async def _show(update: Update, kind: str) -> None:
    message = update.effective_message
    if message is None:
        return

    if kind == channels.REQUIRED:
        rows = channels.required_all()
        lines = [texts.messages.raw("channel_list_required"), ""]
        for index, row in enumerate(rows, start=1):
            pin = " 📌" if row.get("pinned") else ""
            # «همیشگی» یعنی بیرون رفتن، دسترسی را می‌بندد؛
            # «یک‌باره» یعنی تنها برای تأییدِ نخست لازم بوده.
            once = (row.get("enforce") or "always") == "once"
            mark = " 🔓 یک‌باره" if once else " 🔒 همیشگی"
            lines.append(
                f"<b>{_fa(index)}.</b> {texts.escape(row['title'])}{pin}{mark}\n"
                f"     <code>{row['chat_id']}</code>"
            )
        if len(rows) <= 1:
            lines.append("")
            lines.append(texts.messages.raw("channel_list_hint_required"))
    else:
        rows = channels.active(channels.SOURCE)
        lines = [texts.messages.raw("channel_list_source"), ""]
        for index, row in enumerate(rows, start=1):
            lines.append(
                f"<b>{_fa(index)}.</b> {texts.escape(row['title'] or '—')}\n"
                f"     <code>{row['chat_id']}</code>"
            )
        if not rows:
            lines.append(texts.messages.raw("channel_list_empty"))

    await message.reply_html("\n".join(lines))


@admin_only
async def remove_required(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """`/delchannel <شناسه>`"""
    await _drop(update, context, channels.REQUIRED)


@admin_only
async def remove_source(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """`/delsource <شناسه>`"""
    await _drop(update, context, channels.SOURCE)


async def _drop(update: Update, context: ContextTypes.DEFAULT_TYPE, kind: str) -> None:
    message = update.effective_message
    if message is None:
        return

    raw = " ".join(context.args) if context.args else ""
    match = _CHAT_ID.search(raw)
    if not match:
        await message.reply_html(texts.msg("channel_need_id", kind=_kind_name(kind)))
        return

    chat_id = int(match.group(1))
    if channels.remove(kind, chat_id):
        if kind == channels.SOURCE:
            from bot.handlers import router

            router.unwatch_source(chat_id)
        await message.reply_html(texts.msg("channel_removed", chat_id=str(chat_id)))
        logger.info("کانال %s از فهرست %s برداشته شد.", chat_id, kind)
    else:
        await message.reply_html(texts.msg("channel_not_in_list"))


def _kind_name(kind: str) -> str:
    return "عضویت اجباری" if kind == channels.REQUIRED else "منبع"
