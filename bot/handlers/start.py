"""
آغاز و آستانهٔ ورود.

جریان کار: /start ← پیام خوش‌آمد با سه دکمه ← کاربر در کانال
هم‌نشین می‌شود و بر دکمهٔ صفحه می‌نوازد ← «بررسی هم‌نشینی» ←
منو گشوده می‌شود.

سنجش هم‌نشینی تنها آنگاه شدنی است که ربات در کانال گرداننده باشد.
اگر نباشد، تلگرام خطا می‌دهد؛ آن خطا اینجا گرفته می‌شود و به جای
رد کردن کاربرِ بی‌گناه، به گزارش می‌رود تا گردانندگان بدانند.
"""

from __future__ import annotations

import logging
import re

from telegram import Update
from telegram.constants import ChatMemberStatus
from telegram.error import TelegramError
from telegram.ext import ContextTypes

from bot.guards import answer_quietly
from bot.keyboards import inline, reply
from bot.states import clear_state
from config import config
from core import net, texts
from core.db import database
from core.normalize import to_persian_digits

logger = logging.getLogger(__name__)

_MEMBER_STATUSES = {
    ChatMemberStatus.MEMBER,
    ChatMemberStatus.ADMINISTRATOR,
    ChatMemberStatus.OWNER,
}


async def _member_of(context: ContextTypes.DEFAULT_TYPE, chat_id: int, user_id: int):
    """
    آیا کاربر در این یک کانال عضو است — یا None اگر نشد سنجید.

    سه پاسخ دارد نه دو: True، False، و «ندانستم». تفاوتشان
    سرنوشت‌ساز است — نگاه کنید به `missing_channels`.
    """
    try:
        member = await context.bot.get_chat_member(chat_id, user_id)
    except TelegramError as exc:
        logger.error(
            "سنجش عضویت کاربر %s در کانال %s نشد: %s "
            "(آیا ربات در آن کانال مدیر است؟)",
            user_id, chat_id, exc,
        )
        return None

    if member.status in _MEMBER_STATUSES:
        return True
    if member.status == ChatMemberStatus.RESTRICTED:
        return bool(getattr(member, "is_member", False))
    return False


async def missing_channels(
    context: ContextTypes.DEFAULT_TYPE, user_id: int
) -> list[dict]:
    """
    کانال‌هایی که کاربر هنوز در آن‌ها عضو نشده است.

    ## چرا کانالِ نسنجیدنی، کاربر را رد نمی‌کند

    اگر ربات از کانالی بیرون انداخته شده باشد یا شناسه‌اش عوض شده
    باشد، `get_chat_member` خطا می‌دهد. اگر آن را «عضو نیست»
    بشماریم، یک کانالِ خرابِ فراموش‌شده **کلِ ربات را برای همهٔ
    کاربران می‌بندد** — و هیچ‌کس نمی‌فهمد چرا.

    پس «ندانستم» به سود کاربر خوانده می‌شود و تنها در گزارش
    می‌نشیند تا گرداننده ببیند و درستش کند.
    """
    from core.db import channels

    missing: list[dict] = []
    for channel in channels.required_all():
        state = await _member_of(context, int(channel["chat_id"]), user_id)
        if state is False:
            missing.append(channel)
    return missing


async def is_channel_member(context: ContextTypes.DEFAULT_TYPE, user_id: int) -> bool:
    """آیا کاربر در همهٔ کانال‌های اجباری عضو است."""
    return not await missing_channels(context, user_id)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    message = update.effective_message
    if user is None or message is None:
        return

    clear_state(context.user_data)

    record, is_new = database.upsert_user(
        user_id=user.id,
        username=user.username,
        first_name=user.first_name,
        last_name=user.last_name,
    )

    if record["is_banned"]:
        await message.reply_html(texts.msg("error_banned"))
        return

    # ── دعوت ────────────────────────────────────────────────
    #
    # `/start inv_12345` — تلگرام پارامترِ لینکِ عمیق را در
    # `context.args` می‌آورد. تنها برای همراهِ **تازه** خوانده
    # می‌شود: کسی که از پیش هست، با لینکِ دیگری «دعوت» نمی‌شود.
    #
    # پاداش اینجا داده **نمی‌شود** — تنها نامِ دعوت‌کننده ثبت
    # می‌شود. شرطِ شما «استارت **و** عضویت کانال» بود، و عضویت
    # هنوز سنجیده نشده.
    if is_new:
        _note_inviter(user.id, getattr(context, "args", None))

    logger.info(
        "%s: %s (%s)",
        "همراه تازه" if is_new else "بازگشت همراه",
        user.id,
        user.username or user.first_name,
    )

    name = user.first_name or "همراه"

    # کسی که پیش‌تر تأیید شده، نباید دگربار از آستانه بگذرد.
    if record["is_verified"]:
        await message.reply_html(
            texts.msg("welcome_back", name=name), reply_markup=reply.main_menu()
        )
        return

    await _send_sticker(context, user.id, "welcome")
    await message.reply_html(
        texts.msg("welcome", name=name),
        reply_markup=inline.gate(instagram_tapped=bool(record["tapped_instagram"])),
        disable_web_page_preview=True,
    )


async def on_instagram_tap(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    نواختن بر دکمهٔ صفحه را ثبت می‌کند و دکمه را به پیوند راستین
    دگرگون می‌سازد.

    این همان چاره‌ای است که در سرآغاز inline.py شرح داده شد؛ بی آن،
    نواختن بر دکمهٔ پیوند برای ربات نادیدنی است.
    """
    query = update.callback_query
    user = update.effective_user
    if query is None:
        return
    if user is None:
        await answer_quietly(query)
        return

    database.set_instagram_tapped(user.id)
    # نوشتار از YAML می‌آید، نه از دل کد. آگاهی شناور HTML را
    # نمی‌نمایاند، پس نشانه‌گذاری برداشته می‌شود.
    await query.answer(
        re.sub(r"<[^>]+>", "", texts.msg("instagram_tapped")).strip(),
        show_alert=False,
    )

    try:
        await query.edit_message_reply_markup(
            reply_markup=inline.gate(instagram_tapped=True)
        )
    except TelegramError:
        # اگر پیام دگرگون نشد (مثلاً همان بود)، زیانی ندارد.
        pass


async def on_check_membership(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    هر دو شرط را می‌سنجد و در صورت کامیابی، منو را می‌گشاید.
    """
    query = update.callback_query
    user = update.effective_user
    if query is None:
        return
    if user is None:
        await answer_quietly(query)
        return

    record = database.get_user(user.id)
    if record is None:
        await query.answer(texts.msg("must_verify_first"), show_alert=True)
        return

    if record["is_banned"]:
        await query.answer(texts.msg("error_banned"), show_alert=True)
        return

    if record["is_verified"]:
        await query.answer("هم‌نشینی شما پیش‌تر تأیید شده است. 🌿")
        return

    await query.answer()

    missing = await missing_channels(context, user.id)
    tapped = bool(record["tapped_instagram"])

    if missing or not tapped:
        reasons = []
        for channel in missing:
            reasons.append(
                texts.msg("not_verified_reason_one", title=channel["title"])
            )
        if not tapped:
            reasons.append(texts.messages.raw("not_verified_reason_instagram"))

        await query.edit_message_text(
            texts.msg("not_verified", reasons="\n".join(reasons)),
            parse_mode="HTML",
            reply_markup=inline.gate(instagram_tapped=tapped),
            disable_web_page_preview=True,
        )
        return

    # ── هر دو شرط برآورده شد ────────────────────────────────
    database.set_verified(user.id, True)
    logger.info("هم‌نشینی کاربر %s تأیید شد.", user.id)

    # اکنون هر دو شرط برآورده شده — استارت زده و عضو شده — پس
    # اگر با لینکِ کسی آمده، پاداشش می‌رود.
    await _reward_inviter(context, user)

    try:
        await query.edit_message_reply_markup(reply_markup=None)
    except TelegramError:
        pass

    await _send_sticker(context, user.id, "verified")

    await context.bot.send_message(
        chat_id=user.id,
        text=texts.msg(
            "verified",
            name=user.first_name or "همراه",
            tokens=_fa(record["tokens"]),
        ),
        parse_mode="HTML",
        reply_markup=reply.main_menu(),
    )

    # گزارش به گروه کاربران — در پس‌زمینه. کاربر نباید چشم‌به‌راه
    # رسیدنِ پیامی بماند که به خودش ربطی ندارد.
    context.application.create_task(_report_new_user(context, user, record))


async def _report_new_user(context: ContextTypes.DEFAULT_TYPE, user, record) -> None:
    """
    کاربر تازه را در گروه کاربران گزارش می‌کند.

    ## چرا پس از تأیید، نه هنگام /start

    هر کسی یک بار /start می‌زند و می‌رود. گزارشِ آن‌ها گروه را پر
    می‌کرد از کسانی که هرگز کاربر نشدند. تأیید عضویت، مرزِ راستینِ
    «این یک کاربر است».

    ناکامی‌اش خاموش می‌ماند: گروهی که ربات در آن نیست، نباید ورود
    کاربر را بشکند.
    """
    if not config.users_group_id:
        return

    username = f"@{user.username}" if user.username else "—"
    try:
        await net.say(
            context.bot,
            config.users_group_id,
            texts.msg(
                "user_joined",
                name=user.full_name,
                username=username,
                user_id=str(user.id),
                tokens=_fa(record["tokens"]),
            ),
            disable_notification=True,
        )
    except TelegramError as exc:
        logger.debug("گزارش کاربر تازه به گروه کاربران نرفت: %s", exc)


def _note_inviter(user_id: int, args) -> None:
    """
    دعوت‌کننده را از پارامترِ لینک برمی‌دارد و می‌نشاند.

    شکلِ پارامتر `inv_<شناسه>` است. هر چیز دیگری نادیده گرفته
    می‌شود — لینکِ دست‌کاری‌شده نباید چیزی بشکند.
    """
    if not args:
        return
    raw = str(args[0]).strip()
    if not raw.startswith("inv_"):
        return
    try:
        inviter = int(raw[4:])
    except ValueError:
        return
    if inviter <= 0:
        return
    try:
        if database.set_inviter(user_id, inviter):
            logger.info("کاربر %s با لینکِ %s آمد.", user_id, inviter)
    except Exception:  # noqa: BLE001
        logger.debug("نشاندنِ دعوت‌کننده نشد.", exc_info=True)


async def _reward_inviter(context, user) -> None:
    """
    سکهٔ دعوت را به دعوت‌کننده می‌دهد — یک بار به ازای هر نفر.

    `claim_invite_reward` نشان‌زدن و خواندن را در یک جمله انجام
    می‌دهد، پس دو فراخوانِ هم‌زمان دو بار پاداش نمی‌دهند.

    ناکامی‌اش تأییدِ عضویت را نمی‌شکند: همراهِ تازه باید وارد شود
    حتی اگر سکهٔ دعوت‌کننده نرسد.
    """
    try:
        inviter = database.claim_invite_reward(user.id)
    except Exception:  # noqa: BLE001
        logger.debug("سنجشِ پاداشِ دعوت نشد.", exc_info=True)
        return
    if not inviter:
        return

    try:
        balance = database.adjust_tokens(
            inviter, config.invite_reward,
            reason="invite", ref_type="user", ref_id=user.id,
            note=f"دعوتِ {user.id}",
        )
    except Exception:  # noqa: BLE001
        logger.warning("سکهٔ دعوت به %s نرسید.", inviter, exc_info=True)
        return

    logger.info(
        "سکهٔ دعوت: %s سکه به %s بابت آوردنِ %s (موجودی %s).",
        config.invite_reward, inviter, user.id, balance,
    )
    try:
        await net.say(
            context.bot, inviter,
            texts.msg(
                "invite_rewarded",
                name=user.first_name or "یک همراه",
                coins=to_persian_digits(str(config.invite_reward)),
                tokens=to_persian_digits(str(balance)),
            ),
        )
    except TelegramError as exc:
        # مسدود کرده یا گفتگو را پاک کرده؛ سکه‌اش سرِ جایش است.
        logger.debug("خبرِ سکهٔ دعوت به %s نرسید: %s", inviter, exc)


async def _send_sticker(
    context: ContextTypes.DEFAULT_TYPE, chat_id: int, key: str
) -> None:
    """
    برچسب را می‌فرستد، اگر تعریف شده باشد.

    نبودن برچسب خطا نیست: گنجینهٔ برچسب‌ها تدریجی پر می‌شود و ربات
    باید پیش از کامل شدنش هم بی‌عیب کار کند.
    """
    sticker_id = texts.sticker(key)
    if not sticker_id:
        return
    try:
        await context.bot.send_sticker(chat_id=chat_id, sticker=sticker_id)
    except TelegramError as exc:
        logger.warning("فرستادن برچسب «%s» شکست خورد: %s", key, exc)


def _fa(value: object) -> str:
    from core.normalize import to_persian_digits

    return to_persian_digits(str(value))
