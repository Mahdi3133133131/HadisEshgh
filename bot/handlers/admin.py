"""
فرمان‌های گردانندگان.

/textall — همگانی‌رسانی. سند تأکید داشت پیام‌ها نباید یکباره بروند
تا ربات مسدود نشود. تلگرام روی هم‌رفته حدود سی پیام در ثانیه را
برمی‌تابد؛ با فاصلهٔ پیش‌فرض، آسوده زیر آن سقف می‌مانیم.

/stats — شمار همراهان و گنجینه.
/reload_texts — بارگذاری دوبارهٔ نوشتارها بی‌آنکه ربات بازایستد.

نکتهٔ برپایی: این فرمان‌ها در گروه تنها آنگاه کار می‌کنند که
Privacy Mode در BotFather خاموش باشد؛ وگرنه ربات محتوایی را که
گرداننده پس از /textall می‌فرستد اصلاً نمی‌بیند.
"""

from __future__ import annotations

import asyncio
import logging

from telegram import Update
from telegram.error import Forbidden, RetryAfter, TelegramError
from telegram.ext import ContextTypes

from bot.guards import admin_only, answer_quietly
from bot.keyboards import inline
from bot.states import AWAITING_BROADCAST, clear_state, set_state
from config import config
from core import net, texts
from core.db import broadcasts, database, feedbacks, submissions
from core.normalize import to_persian_digits

logger = logging.getLogger(__name__)

# هر چند پیام یک‌بار پیشرفت گزارش شود
_PROGRESS_EVERY = 50


@admin_only
async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    if message is None:
        return

    lines = [
        "📊 <b>آمار حدیث عشق</b>",
        "",
        f"همراهان: <b>{_fa(database.count_users())}</b>",
        f"هم‌نشینان تأییدشده: <b>{_fa(database.count_users(only_verified=True))}</b>",
        "",
        f"نواهای گنجینه: <b>{_fa(database.count_tracks())}</b>",
        f"نمایه‌شده: <b>{_fa(database.count_tracks(indexed_only=True))}</b>",
        "",
        f"پیشکش‌های در انتظار: <b>{_fa(submissions.pending_count())}</b>",
        f"سخنان بی‌پاسخ: <b>{_fa(feedbacks.open_count())}</b>",
    ]
    await message.reply_html("\n".join(lines))


@admin_only
async def engine(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    وضعیت موتور بازجویی.

    نرخ کامیابی، مهم‌ترین سنجهٔ سلامت این ربات است: اگر پایین باشد،
    یعنی گنجینه از آنچه مردم می‌جویند تهی است — نه آنکه موتور خراب
    باشد. این دو را نباید با هم اشتباه گرفت.
    """
    message = update.effective_message
    if message is None:
        return

    from core.db import fingerprints as fp_store, searches
    from worker.queue import get_queue

    queue = get_queue()
    found, total = searches.success_rate(days=7)
    rate = f"{round(100 * found / total)}٪" if total else "—"

    rows = fp_store.count_rows()
    indexed = fp_store.count_indexed_tracks()
    pending = len(fp_store.pending_tracks(limit=999))

    lines = [
        "⚙️ <b>موتور بازجویی</b>",
        "",
        f"نواهای نمایه‌شده: <b>{_fa(indexed)}</b>",
        f"در انتظار نمایه: <b>{_fa(pending)}</b>",
        f"عددهای اثر انگشت: <b>{_fa(f'{rows:,}')}</b>",
        "",
        f"نرخ کامیابی (۷ روز): <b>{_fa(rate)}</b>  ({_fa(found)} از {_fa(total)})",
        "",
        "<b>صف پردازش</b>",
        f"در دست انجام: <b>{_fa(queue.running)}</b>",
        f"در صف: <b>{_fa(queue.waiting)}</b>",
        f"انجام‌شده: <b>{_fa(queue.stats.completed)}</b> · ناکام: <b>{_fa(queue.stats.failed)}</b>",
    ]
    if queue.stats.average_seconds:
        lines.append(f"میانگین زمان: <b>{_fa(round(queue.stats.average_seconds, 1))}</b> ثانیه")

    await message.reply_html("\n".join(lines))


@admin_only
async def failures(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    بازجویی‌های ناکام تازه.

    چون بایگانی تنها از این پس پر می‌شود، همین فهرست تنها راهنمای
    رشد گنجینه است: می‌گوید مردم دنبال چه می‌گردند که ما نداریم.
    """
    message = update.effective_message
    if message is None:
        return

    from core.db import searches
    from core.normalize import format_duration

    rows = searches.recent_failures(limit=15)
    if not rows:
        await message.reply_html("🌿 بازجویی ناکامی در دفتر نیست.")
        return

    lines = ["🔍 <b>بازجویی‌های ناکام تازه</b>", ""]
    for row in rows:
        name = row["first_name"] or row["username"] or str(row["user_id"])
        lines.append(
            f"• <code>{row['id']}</code> — {name} — "
            f"{format_duration(row['input_duration'])} — {row['created_at'][:16]}"
        )
        # گمانهٔ خودِ جوینده، مهم‌ترین سرنخ این فهرست است: بی آن،
        # گرداننده یک شناسهٔ عددی می‌بیند و نمی‌داند دنبال چه بگردد.
        hint = row["hint_text"] or row["query_text"]
        if hint:
            lines.append(f"   ↳ <b>{hint}</b>")
    lines.append("")
    lines.append(
        "<i>این نواها در گنجینه نبودند. اگر دارید، زیر همان گزارشِ گروه"
        " دکمهٔ «نسخهٔ کامل را می‌فرستم» را بنوازید.</i>"
    )

    await message.reply_html("\n".join(lines))


@admin_only
async def alias(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    نام‌های مستعارِ مداحان — دیدن، افزودن، برداشتن.

        /alias                       فهرست
        /alias Borna = رسول برنا     افزودن
        /alias -Borna                برداشتن

    ربات این‌ها را از تصحیح‌های خودتان هم می‌آموزد؛ این دستور
    برای جاهایی است که می‌خواهید بی‌واسطه بگویید.
    """
    message = update.effective_message
    if message is None:
        return

    from core.db import madah_aliases

    raw = " ".join(context.args).strip() if context.args else ""

    # ── برداشتن ─────────────────────────────────────────────
    if raw.startswith("-"):
        target = raw[1:].strip()
        gone = madah_aliases.forget(target)
        await message.reply_html(
            texts.msg("alias_removed" if gone else "alias_missing", alias=target)
        )
        return

    # ── افزودن ──────────────────────────────────────────────
    if "=" in raw:
        left, _, right = raw.partition("=")
        left, right = left.strip(), right.strip()
        if not left or not right:
            await message.reply_html(texts.msg("alias_usage"))
            return
        if madah_aliases.remember(left, right, added_by=update.effective_user.id):
            await message.reply_html(
                texts.msg("alias_added", alias=left, canonical=right)
            )
        else:
            await message.reply_html(texts.msg("alias_useless", alias=left))
        return

    # ── فهرست ───────────────────────────────────────────────
    rows = madah_aliases.all_aliases()
    if not rows:
        await message.reply_html(texts.msg("alias_empty"))
        return

    lines = ["🔤 <b>نام‌های مستعارِ آموخته</b>", ""]
    for row in rows[:40]:
        hits = int(row["hits"] or 0)
        tail = f" · {_fa(hits)} بار" if hits else ""
        lines.append(
            f"• <code>{texts.escape(row['alias_text'])}</code> ← "
            f"<b>{texts.escape(row['canonical'])}</b>{tail}"
        )
    lines.append("")
    lines.append(texts.msg("alias_usage"))
    await message.reply_html("\n".join(lines))


@admin_only
async def clean(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    پیام‌های گذرای ربات را از این گروه برمی‌دارد.

    ## چه چیزی پاک می‌شود و چه چیزی نه

    تنها آنچه در `bot_messages` ثبت شده: گزارش ناکامی، کارت
    داوری، پیام وضعیت، و همهٔ پیام‌های جریانِ پذیرش — پرسش‌ها،
    کارت‌های شناسنامه، صوت‌های بازفرستاده، «به گنجینه افزوده شد»
    — و نیز **صوت‌هایی که خودِ گردانندگان در `/bulk` فرستاده‌اند**.
    اینها کارشان تمام شده و ماندنشان تنها شلوغی است.

    **نواهای گروه بایگانی هرگز ثبت نمی‌شوند، پس هرگز پاک
    نمی‌شوند.** قاعده وارونه است تا فراموشی به بی‌خطری بینجامد نه
    به فاجعه: چیزی می‌رود که صریح نشان خورده باشد.

    پیام‌های آدم‌ها هم دست نمی‌خورند.
    """
    message = update.effective_message
    if message is None:
        return

    from core.db import bot_messages

    chat_id = message.chat_id

    # خودِ فرمانِ `/clean` هم گذراست و باید برود — گرچه نه در همین
    # دور، چون هنوز داریم پاسخش را می‌دهیم.
    bot_messages.remember(chat_id, message.message_id, "clean")

    waiting = bot_messages.count(chat_id)
    if waiting <= 1:
        sent = await message.reply_html(texts.msg("clean_nothing"))
        bot_messages.remember(chat_id, sent.message_id, "clean")
        return

    rows = bot_messages.pending(chat_id, limit=400)
    ids = [int(r["message_id"]) for r in rows]

    status = await message.reply_html(
        texts.msg("clean_working", count=to_persian_digits(str(len(ids))))
    )

    gone = await net.drop(context.bot, chat_id, *ids)
    # نشانی‌ها در هر حال برداشته می‌شوند: آنکه پاک شد که رفت، و
    # آنکه نشد (کهنه‌تر از دو روز) دیگر هرگز پاک نخواهد شد، پس
    # نگه داشتنش تنها انبار را باد می‌کند.
    bot_messages.forget(chat_id, ids)

    stale = len(ids) - gone
    await status.edit_text(
        texts.msg(
            "clean_done",
            gone=to_persian_digits(str(gone)),
            stale=to_persian_digits(str(stale)),
        ),
        parse_mode="HTML",
    )
    # گزارشِ پاک‌سازی، خودش پیامِ گذرای دورِ بعد است. بی این خط،
    # هر بار یک پیام ته گروه جا می‌ماند و روی هم انباشته می‌شد.
    bot_messages.remember(chat_id, status.message_id, "clean")


@admin_only
async def wanted(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    پرخواسته‌ترین نواهایی که نداریم — فهرستِ خرید.

    خواهرِ `/failures` است و کارِ دیگری می‌کند: آن می‌گوید «همین
    حالا چه ناکام ماند»، این می‌گوید «کجا وقت بگذارم». با گنجینهٔ
    کوچک، دومی مهم‌تر است.
    """
    message = update.effective_message
    if message is None:
        return

    from core.db import searches
    from core.normalize import to_persian_digits

    rows = searches.most_wanted(limit=20)
    if not rows:
        await message.reply_html(
            "🌿 هنوز خواسته‌ای در دفتر نیست.\n\n"
            "<i>هر بازجویی ناکام که جوینده در آن نامی داده باشد، "
            "اینجا گرد می‌شود.</i>"
        )
        return

    lines = ["📋 <b>پرخواسته‌ترین‌هایی که نداریم</b>", ""]
    for index, (term, count, people) in enumerate(rows, start=1):
        fa = lambda v: to_persian_digits(str(v))
        # «چند نفر» از «چند بار» جداست: یک نفر که ده بار کوشیده،
        # ده برابرِ ده نفر ارزش ندارد.
        who = f"{fa(people)} نفر" if people == count else (
            f"{fa(people)} نفر · {fa(count)} بار"
        )
        lines.append(f"<b>{fa(index)}.</b> {texts.escape(term)} — <i>{who}</i>")

    lines.append("")
    lines.append(
        "<i>این‌ها را مردم خواسته‌اند و ما نداشته‌ایم. هر کدام را که"
        " افزودید، از فهرست بیرون می‌رود.</i>"
    )
    await message.reply_html("\n".join(lines))


@admin_only
async def broken(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    نواهایی که نمایه نشدند — هر کدام با صوتش، برای اصلاح.

    ## چرا این دستور هست

    نوایی که اثر انگشت ندارد، در گنجینه هست ولی موتور
    **نمی‌بیندش**: کاربر مداحی‌اش را می‌فرستد و پاسخی نمی‌گیرد،
    و هیچ‌کس نمی‌فهمد چرا. تا امروز این نام‌ها تنها به لاگ
    می‌رفتند و کسی لاگ نمی‌خواند.

    خودِ صوت فرستاده می‌شود، نه تنها نامش: گرداننده باید بتواند
    بشنود و ببیند فایل راستی خراب است یا ffmpeg لغزیده.
    """
    message = update.effective_message
    if message is None:
        return

    from core.db import fingerprints as fp_store

    rows = fp_store.broken_tracks()
    if not rows:
        await message.reply_html(texts.msg("broken_none"))
        return

    await message.reply_html(texts.msg("broken_header", count=_fa(len(rows))))

    for row in rows:
        caption = texts.msg(
            "broken_item",
            title=texts.escape(row.get("title") or "بی‌نام"),
            madah=texts.escape(row.get("madah") or "—"),
            track_id=_fa(row["id"]),
            attempts=_fa(row.get("index_attempts") or 0),
        )
        track = database.get_track(int(row["id"]))
        markup = inline.broken_actions(int(row["id"]))
        try:
            if track is not None and track["file_id"]:
                await context.bot.send_audio(
                    chat_id=message.chat_id,
                    audio=track["file_id"],
                    caption=caption,
                    parse_mode="HTML",
                    reply_markup=markup,
                )
            else:
                await net.say(context.bot, message.chat_id, caption,
                              reply_markup=markup)
        except TelegramError as exc:
            # فایلی که تلگرام هم نمی‌دهدش، خودش خبرِ سودمندی است.
            logger.warning("فرستادنِ نوای شکستهٔ %s نشد: %s", row["id"], exc)
            await net.say(context.bot, message.chat_id, caption,
                          reply_markup=markup)


async def on_broken_retry(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """شمارندهٔ کوشش صفر شود تا نوا به صفِ نمایه‌سازی بازگردد."""
    query = update.callback_query
    user = update.effective_user
    if query is None or user is None or not query.data:
        return
    if not config.is_admin(user.id):
        try:
            await query.answer(texts.msg("admin_only"), show_alert=True)
        except TelegramError:
            pass
        return
    try:
        track_id = int(query.data.rpartition(":")[2])
    except ValueError:
        try:
            await query.answer()
        except TelegramError:
            pass
        return

    from core.db import fingerprints as fp_store
    from services import indexer

    fp_store.clear_attempts(track_id)
    try:
        await query.answer("به صف بازگشت.")
    except TelegramError:
        pass

    # همین‌جا یک کوشش زده می‌شود، نه اینکه تا دورِ بعدیِ کارِ
    # دوره‌ای صبر کنیم: گرداننده هم‌اکنون اینجاست و می‌خواهد
    # بداند درست شد یا نه.
    try:
        rows = await indexer.index_track(context.bot, track_id)
        note = texts.msg("broken_retried", track_id=_fa(track_id))
        if rows:
            note += chr(10) + f"✅ نمایه شد ({_fa(rows)} عدد)."
    except Exception as exc:  # noqa: BLE001
        logger.info("کوششِ دوبارهٔ نوای %s باز هم نشد: %s", track_id, exc)
        note = texts.msg("broken_retried", track_id=_fa(track_id))
        note += chr(10) + f"⚠️ باز هم نشد: {texts.escape(str(exc)[:160])}"

    try:
        await query.edit_message_reply_markup(reply_markup=None)
    except TelegramError:
        pass
    await net.say(context.bot, query.message.chat_id, note)


@admin_only
async def reindex(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """نمایه‌سازی دستی نواهای در انتظار."""
    message = update.effective_message
    if message is None:
        return

    from services import indexer

    status = await message.reply_html("⏳ نمایه‌سازی آغاز شد…")
    ok, failed = await indexer.index_pending(context.bot, limit=50)
    await status.edit_text(
        f"✅ نمایه‌سازی پایان یافت.\n\nکامیاب: <b>{_fa(ok)}</b>\nناکام: <b>{_fa(failed)}</b>",
        parse_mode="HTML",
    )


@admin_only
async def reload_texts(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    if message is None:
        return
    try:
        texts.reload_all()
    except Exception as exc:  # noqa: BLE001
        await message.reply_html(f"بارگذاری شکست خورد:\n<code>{exc}</code>")
        return
    await message.reply_html("🌿 گنجینهٔ نوشتارها از نو بارگذاری شد.")


@admin_only
async def begin_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    if message is None:
        return

    if broadcasts.running() is not None:
        await message.reply_html(texts.msg("broadcast_already_running"))
        return

    total = len(database.iter_broadcast_targets())
    set_state(context.user_data, AWAITING_BROADCAST)
    await message.reply_html(texts.msg("broadcast_ask", count=_fa(total)))


async def on_broadcast_content(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """محتوای همگانی‌رسانی را می‌گیرد و پخش را در پس‌زمینه می‌آغازد."""
    message = update.effective_message
    admin = update.effective_user
    if message is None or admin is None:
        return

    clear_state(context.user_data)
    targets = database.iter_broadcast_targets()

    if not targets:
        await message.reply_html(texts.msg("broadcast_no_targets"))
        return

    broadcast_id = broadcasts.create(
        admin_id=admin.id,
        from_chat_id=message.chat_id,
        from_msg_id=message.message_id,
        total=len(targets),
    )

    status = await message.reply_html(
        texts.msg("broadcast_started", count=_fa(len(targets))),
        reply_markup=inline.broadcast_cancel(broadcast_id),
    )

    # در پس‌زمینه، تا ربات در سراسر پخش پاسخ‌گو بماند.
    context.application.create_task(
        _run_broadcast(
            context=context,
            broadcast_id=broadcast_id,
            targets=targets,
            from_chat_id=message.chat_id,
            from_msg_id=message.message_id,
            status_chat_id=status.chat_id,
            status_msg_id=status.message_id,
        )
    )


async def _run_broadcast(
    context: ContextTypes.DEFAULT_TYPE,
    broadcast_id: int,
    targets: list[int],
    from_chat_id: int,
    from_msg_id: int,
    status_chat_id: int,
    status_msg_id: int,
) -> None:
    sent = failed = 0

    for index, user_id in enumerate(targets, start=1):
        if broadcasts.is_cancelled(broadcast_id):
            logger.info("همگانی‌رسانی %s بازایستاده شد.", broadcast_id)
            break

        try:
            await context.bot.copy_message(
                chat_id=user_id, from_chat_id=from_chat_id, message_id=from_msg_id
            )
            sent += 1
        except Forbidden:
            # کاربر ربات را مسدود کرده؛ نشانه‌گذاری تا دفعهٔ بعد
            # تلاش بیهوده نشود.
            database.mark_blocked_bot(user_id)
            failed += 1
        except RetryAfter as exc:
            # تلگرام خواسته است بیاساییم؛ می‌آساییم و همان کاربر را
            # دگربار می‌آزماییم.
            logger.warning("تلگرام %s ثانیه آسایش خواست.", exc.retry_after)
            await asyncio.sleep(float(exc.retry_after) + 1)
            try:
                await context.bot.copy_message(
                    chat_id=user_id, from_chat_id=from_chat_id, message_id=from_msg_id
                )
                sent += 1
            except TelegramError:
                failed += 1
        except TelegramError as exc:
            logger.debug("رساندن به کاربر %s شکست خورد: %s", user_id, exc)
            failed += 1

        if index % _PROGRESS_EVERY == 0:
            broadcasts.bump(broadcast_id, sent=sent, failed=failed)
            sent = failed = 0
            await _update_status(
                context, broadcast_id, status_chat_id, status_msg_id, index, len(targets)
            )

        await asyncio.sleep(config.broadcast_delay)

    broadcasts.bump(broadcast_id, sent=sent, failed=failed)
    cancelled = broadcasts.is_cancelled(broadcast_id)
    broadcasts.finish(broadcast_id, "cancelled" if cancelled else "done")

    record = broadcasts.get(broadcast_id)
    try:
        await context.bot.edit_message_text(
            chat_id=status_chat_id,
            message_id=status_msg_id,
            text=texts.msg(
                "broadcast_finished",
                sent=_fa(record["sent"]),
                failed=_fa(record["failed"]),
                total=_fa(record["total"]),
            ),
            parse_mode="HTML",
        )
    except TelegramError:
        pass

    logger.info(
        "همگانی‌رسانی %s پایان یافت: %s رسید، %s نرسید.",
        broadcast_id, record["sent"], record["failed"],
    )


async def _update_status(
    context, broadcast_id: int, chat_id: int, message_id: int, done: int, total: int
) -> None:
    record = broadcasts.get(broadcast_id)
    if record is None:
        return
    try:
        await context.bot.edit_message_text(
            chat_id=chat_id,
            message_id=message_id,
            text=texts.msg(
                "broadcast_progress",
                done=_fa(done),
                total=_fa(total),
                sent=_fa(record["sent"]),
                failed=_fa(record["failed"]),
            ),
            parse_mode="HTML",
            reply_markup=inline.broadcast_cancel(broadcast_id),
        )
    except TelegramError:
        pass


async def on_broadcast_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    admin = update.effective_user
    if query is None:
        return
    if admin is None or not query.data:
        await answer_quietly(query)
        return

    if not config.is_admin(admin.id):
        await query.answer(texts.msg("admin_only"), show_alert=True)
        return

    try:
        broadcast_id = int(query.data.rpartition(":")[2])
    except ValueError:
        await query.answer()
        return

    broadcasts.cancel(broadcast_id)
    await query.answer("همگانی‌رسانی بازایستانده می‌شود…")


def _fa(value: object) -> str:
    return to_persian_digits(str(value))


# ═════════════════════════════════════════════════════════════
#  مرحلهٔ شش و هفت: پشتیبان، کرال، گمانه‌زن
# ═════════════════════════════════════════════════════════════

@admin_only
async def backup_now(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    پشتیبان دستی.

    پشتیبان «سبک» جدول اثر انگشت را ندارد و چند مگابایت بیش نیست؛
    پس در تلگرام جا می‌شود. پشتیبان «کامل» می‌تواند گیگابایت‌ها
    باشد و تنها روی دیسک می‌ماند.
    """
    message = update.effective_message
    if message is None:
        return

    from services import backup
    from worker.queue import get_queue

    full = bool(context.args and context.args[0].lower() in ("full", "کامل"))
    status = await message.reply_html("⏳ در حال ساختن پشتیبان…")

    try:
        # پشتیبان‌گیری از پایگاه دادهٔ بزرگ، ثانیه‌ها می‌برد و
        # بازدارنده است؛ در ریسه‌ای جدا انجام می‌شود تا ربات در
        # آن میان پاسخ‌گو بماند.
        path = await get_queue().run(backup.create, not full)
    except Exception as exc:  # noqa: BLE001
        await status.edit_text(f"پشتیبان‌گیری شکست خورد:\n<code>{exc}</code>",
                               parse_mode="HTML")
        return

    from core.normalize import format_size

    size = path.stat().st_size
    if full:
        await status.edit_text(
            f"✅ پشتیبان کامل ساخته شد.\n\n"
            f"<code>{path}</code>\n{format_size(size)}\n\n"
            f"<i>به سبب بزرگی، فرستاده نشد؛ روی دیسک است.</i>",
            parse_mode="HTML",
        )
        return

    try:
        with path.open("rb") as handle:
            await message.reply_document(
                document=handle, filename=path.name,
                caption=f"💾 پشتیبان سبک — {format_size(size)}",
            )
        await status.delete()
    except TelegramError as exc:
        await status.edit_text(f"ساخته شد ولی فرستاده نشد: {exc}")


@admin_only
async def train_classifier(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    آموزش دوبارهٔ گمانه‌زن سبک و مداح.

    هرچه نواهای برچسب‌خورده بیشتر شوند، گمانه‌ها استوارتر می‌گردند؛
    پس این فرمان را هر چند وقت یک‌بار بزنید.
    """
    message = update.effective_message
    if message is None:
        return

    from core.audio.classifier import retrain

    status = await message.reply_html("⏳ در حال آموزش…")
    madah, style, samples = retrain()

    if not (madah or style):
        await status.edit_text(texts.msg("classifier_untrained"), parse_mode="HTML")
        return

    await status.edit_text(
        texts.msg(
            "classifier_trained",
            madah=_fa(madah), style=_fa(style), samples=_fa(samples),
        ),
        parse_mode="HTML",
    )


@admin_only
async def features_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """وضعیت برداشت ویژگی و گمانه‌زن."""
    message = update.effective_message
    if message is None:
        return

    import numpy as np

    from core.audio.classifier import get_classifier
    from core.audio.features import FEATURE_VERSION, METRICAL_THRESHOLD
    from core.db import features_store, melody_store

    features_store.ensure_table()
    melody_store.ensure_table()
    classifier = get_classifier()

    outdated = features_store.outdated_count()
    pending = len(features_store.pending(limit=9999))
    melody_pending = len(melody_store.pending(limit=9999))

    lines = [
        "🎼 <b>لایه‌های تشخیص</b>",
        "",
        "<b>خطِ آهنگ</b>  <i>— اجرای دیگرِ همان نوحه</i>",
        f"نواهای دارای نشان: <b>{_fa(melody_store.count())}</b>",
        f"در انتظار: <b>{_fa(melody_pending)}</b>",
        "",
        "<b>رنگ آوا</b>  <i>— گمانهٔ مداح و سبک</i>",
        f"نواهای دارای ویژگی: <b>{_fa(features_store.current_count())}</b>",
        f"در انتظار برداشت: <b>{_fa(pending)}</b>",
    ]
    if outdated:
        # ساختار بردار ویژگی دگرگون شده؛ بردارهای کهنه دیگر خوانده
        # نمی‌شوند و باید از نو برداشته گردند.
        lines.append(
            f"با ساختار کهنه: <b>{_fa(outdated)}</b> "
            f"<i>(نسخهٔ کنونی {_fa(FEATURE_VERSION)})</i>"
        )
    lines += [
        "",
        f"آموزش‌دیده: <b>{'آری' if classifier.is_trained else 'نه'}</b>",
    ]
    if classifier.is_trained:
        lines += [
            f"مداحان شناخته‌شده: <b>{_fa(classifier.madah_count)}</b>",
            f"سبک‌های شناخته‌شده: <b>{_fa(classifier.style_count)}</b>",
            f"تصویر جداساز: <b>{'فعال' if classifier.uses_projection else 'خاموش'}</b>",
        ]
        if not classifier.uses_projection:
            # علتِ راستین گفته می‌شود، نه علتِ محتمل.
            #
            # پیش‌تر اینجا همیشه «داده کم است» نوشته می‌شد — و روی
            # نصبِ تمیز دروغ بود: علت، نبودِ scikit-learn بود.
            reason = classifier.projection_reason or "علتش روشن نیست"
            lines.append(f"<i>خاموش است چون {texts.escape(reason)}.</i>")
    if pending:
        lines += ["", f"<i>برای نو کردن، <code>/reindex</code> بزنید.</i>"]
    # ── توزیع رسایی ضربان ───────────────────────────────────
    #
    # آستانهٔ وزن (`METRICAL_THRESHOLD`) از آوای ساختگی درآمده و
    # مستنداتش خودش می‌گوید با نواهای راستین شاید جابه‌جایی
    # بخواهد. این چند سطر همان دادهٔ راستین را نشان می‌دهد تا
    # اگر روزی روضه «وزن‌دار» خوانده شد، از روی توزیع میزان شود
    # نه از روی گمان.
    clarity = features_store.pulse_clarity_values()
    if clarity.size:
        below = int((clarity < METRICAL_THRESHOLD).sum())
        lines += [
            "",
            "<b>رسایی ضربان</b>  <i>— پایهٔ داوریِ وزن</i>",
            f"آستانه: <b>{METRICAL_THRESHOLD:.2f}</b>",
            f"میانه: <b>{np.median(clarity):.2f}</b> · "
            f"کمینه: <b>{clarity.min():.2f}</b> · بیشینه: <b>{clarity.max():.2f}</b>",
            f"بی‌وزن شمرده‌شده: <b>{_fa(below)}</b> از {_fa(int(clarity.size))}",
        ]

    lines += [
        "",
        "<i>یادآوری: این لایه گمانه می‌زند. یافتن قطعی کار اثر انگشت است.</i>",
    ]
    await message.reply_html("\n".join(lines))


@admin_only
async def sites_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    `/sites` — وضعیت پلهٔ دوم جست‌وجو.

    با `/sites تازه` نمایه همان‌جا از سیت‌مپ‌ها تازه می‌شود، بی آنکه
    چشم‌به‌راه کار شبانه بمانیم.
    """
    message = update.effective_message
    if message is None:
        return

    from core.db import site_index
    from services import sites

    if context.args and context.args[0] in ("تازه", "refresh"):
        status = await message.reply_html("⏳ سیت‌مپ‌ها را می‌خوانم…")
        added = await sites.refresh_index()
        filled = await sites.top_up_titles(limit=40)
        body = ["✅ <b>نمایه تازه شد</b>", ""]
        for name, count in added.items():
            body.append(f"{sites.label_of(name)}: <b>{_fa(count)}</b> نشانی")
        body.append("")
        body.append(f"نام تازه به دست آمد: <b>{_fa(filled)}</b>")
        try:
            await status.edit_text("\n".join(body), parse_mode="HTML")
        except TelegramError:
            await message.reply_html("\n".join(body))
        return

    site_index.ensure_table()
    counts = site_index.counts()
    lines = [
        "🕸 <b>جست‌وجو در سایت‌ها</b>",
        "",
        "<i>ترتیب کار: اول آرشیو خودمان، بعد سایت‌ها. هرچه از سایت "
        "آورده شود، در آرشیو می‌ماند و دفعهٔ بعد لازم نیست دوباره "
        "برویم.</i>",
        "",
    ]
    for row in sites.diagnose():
        live = "جست‌وجوی زنده" if row["live"] else "فقط از راه سیت‌مپ"
        blind = row["total"] - row["named"]
        block = [
            f"<b>{row['label']}</b> — {live}",
            f"   نام‌دار: {_fa(row['named'])} · بی‌نام: {_fa(blind)}"
            f" · robots: {row['robots']}",
        ]
        for trouble in row["troubles"]:
            block.append(f"   ⚠️ {trouble}")
        lines.append("\n".join(block))

    named_all = site_index.titled()
    blind_all = site_index.total() - named_all
    lines += [
        "",
        f"<b>روی‌هم:</b> {_fa(named_all)} صفحهٔ جست‌وجو‌شدنی"
        f" (و {_fa(blind_all)} بی‌نام که دیده نمی‌شوند)",
        "",
        "<i>صفحهٔ بی‌نام در جست‌وجو نمی‌آید؛ کار شبانه نوبتی "
        "نامشان را پر می‌کند.</i>",
        "",
        "<i>برای تازه کردن همین حالا: <code>/sites تازه</code></i>",
    ]
    await message.reply_html("\n".join(lines))


@admin_only
async def chat_id(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    `/id` — شناسهٔ همین گفتگو را می‌گوید.

    ## چرا این فرمان بایسته بود

    گروه بایگانی هفته‌ها خاموش ماند، چون شناسه‌اش در .env نادرست
    بود و هیچ راهی برای دیدنِ شناسهٔ درست نداشتیم. شناسهٔ ابرگروه
    دو نمایش دارد — شمارهٔ درونی، و شناسهٔ API که ۱۰۰ به سرش
    می‌چسبد — و ابزارها معمولاً شکل درونی را نشان می‌دهند.

    این فرمان همان عددی را می‌دهد که خودِ تلگرام به ربات گفته
    است، پس جای گمانه‌زنی نمی‌ماند. اجرایش در همان گروه، هم‌زمان
    ثابت می‌کند که ربات آنجا هست.
    """
    message = update.effective_message
    chat = update.effective_chat
    if message is None or chat is None:
        return

    kinds = {
        "private": "گفتگوی خصوصی",
        "group": "گروه ساده",
        "supergroup": "ابرگروه",
        "channel": "کانال",
    }
    lines = [
        "🪪 <b>شناسهٔ این گفتگو</b>",
        "",
        f"<code>{chat.id}</code>",
        "",
        f"<b>گونه:</b> {kinds.get(chat.type, chat.type)}",
    ]
    if chat.title:
        lines.append(f"<b>نام:</b> {chat.title}")
    lines += [
        "",
        "<i>همین عدد را — با منها و بی هیچ دست‌کاری — در پروندهٔ .env "
        "بنشانید.</i>",
    ]
    await message.reply_html("\n".join(lines))


@admin_only
async def health(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    تندرستی ربات: شبکه، گفتگوها، صف.

    این فرمان از دلِ یک شب کار واقعی درآمد. گزارش‌ها پر بود از
    «برچسب‌گذاری شکست خورد: Chat not found» و کسی نمی‌دانست چرا —
    ربات به گروه نسخهٔ آراسته افزوده نشده بود. چنین چیزی باید با
    یک فرمان دیده شود، نه با خواندن هزار سطر گزارش.
    """
    message = update.effective_message
    if message is None:
        return

    from core import net
    from worker.queue import get_queue

    status = await message.reply_html("⏳ در حال سنجش…")

    lines = [texts.messages.raw("health_title"), ""]

    # ── گفتگوها ─────────────────────────────────────────────
    lines.append("<b>گفتگوها</b>")
    checks = [
        ("کانال هم‌نشینی", config.channel_id),
        ("گروه مداحی", config.madahi_group_id),
        ("گروه انتقادات", config.feedback_group_id),
        ("گروه نسخهٔ آراسته", config.ornate_group_id),
        ("گروه کاربران", config.users_group_id),
        ("کانال مخزن", config.archive_channel_id),
    ]
    for label, chat_id in checks:
        if not chat_id:
            lines.append(f"➖ {label} — <i>پیکربندی نشده</i>")
            continue
        marked = net.is_unreachable(chat_id)
        if marked:
            lines.append(texts.msg("health_chat_bad", label=label, reason=marked))
            continue
        try:
            chat = await context.bot.get_chat(chat_id)
            lines.append(
                texts.msg("health_chat_ok", label=f"{label} — {chat.title or chat_id}")
            )
        except TelegramError as exc:
            lines.append(texts.msg("health_chat_bad", label=label, reason=str(exc)))

    # ── شبکه ────────────────────────────────────────────────
    lines += [
        "",
        "<b>شبکه</b>",
        f"پروکسی: <b>{'دارد' if config.proxy_url else 'ندارد'}</b>",
        f"مهلت پیوند/خواندن/نوشتن: <b>{_fa(int(config.connect_timeout))}</b> · "
        f"<b>{_fa(int(config.read_timeout))}</b> · <b>{_fa(int(config.write_timeout))}</b> ثانیه",
        f"کوشش دوباره: <b>{_fa(config.network_retries)}</b> بار",
    ]

    # ── صف ──────────────────────────────────────────────────
    queue = get_queue()
    lines += [
        "",
        "<b>صف پردازش</b>",
        f"در دست: <b>{_fa(queue.running)}</b> · در صف: <b>{_fa(queue.waiting)}</b>",
        f"انجام‌شده: <b>{_fa(queue.stats.completed)}</b> · "
        f"ناکام: <b>{_fa(queue.stats.failed)}</b>",
    ]
    if queue.stats.average_seconds:
        lines.append(
            f"میانگین زمان: <b>{_fa(round(queue.stats.average_seconds, 1))}</b> ثانیه"
        )

    # ── بایگانی ─────────────────────────────────────────────
    # ناکامی برچسب‌گذاری خاموش می‌گذشت. اکنون شمرده می‌شود، تا
    # «چند نوا از بایگانی بیرون مانده‌اند» پرسشی پاسخ‌دار باشد.
    from services import indexer

    waiting_ornate = indexer.ornate_pending_count()
    lines += [
        "",
        "<b>بایگانی نسخهٔ آراسته</b>",
        f"چشم‌به‌راه: <b>{_fa(waiting_ornate)}</b> نوا",
    ]
    if waiting_ornate:
        lines.append(
            "<i>هر ربع ساعت چند تایی دوباره آزموده می‌شوند؛ "
            "اگر گروه در دسترس باشد، خودشان می‌نشینند.</i>"
        )

    lines += ["", texts.messages.raw("health_note")]

    body = "\n".join(lines)
    try:
        await status.edit_text(body, parse_mode="HTML")
    except TelegramError:
        await message.reply_html(body)


@admin_only
async def crawl_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """وضعیت کرالر تارنماها."""
    message = update.effective_message
    if message is None:
        return

    from services import crawler

    counts = crawler.stats()
    enabled = [site.name for site in crawler.SITES if site.enabled]
    disabled = [site.name for site in crawler.SITES if not site.enabled]

    lines = [
        "🕸 <b>کرالر تارنماها</b>",
        "",
        f"نمایه‌شده: <b>{_fa(counts.get('indexed', 0))}</b>",
        f"ناکام: <b>{_fa(counts.get('failed', 0))}</b>",
        f"رد شده: <b>{_fa(counts.get('skipped', 0))}</b>",
        "",
        f"<b>روشن:</b> {'، '.join(enabled) if enabled else '—'}",
        f"<b>خاموش:</b> {'، '.join(disabled) if disabled else '—'}",
        "",
        "<i>تارنماها پیش از روشن شدن باید وارسی شوند؛ ساختارشان</i>",
        "<i>مدام دگرگون می‌شود و کرالرِ کور، بیهوده می‌گردد.</i>",
    ]
    await message.reply_html("\n".join(lines))
