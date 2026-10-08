#!/usr/bin/env python
"""
حدیث عشق — نقطهٔ آغاز.

اجرا:  python main.py

پیش از آنکه ربات به کار بیفتد، «پیش‌پرواز» انجام می‌شود: درستی توکن،
رسیدن به کانال و گروه‌ها، و گردانندگی ربات در کانال سنجیده می‌گردد.
دلیلش این است که این خطاها وگرنه خاموش می‌مانند — ربات بالا می‌آید،
ولی بررسی هم‌نشینی هرگز کار نمی‌کند و کسی نمی‌فهمد چرا.
"""

from __future__ import annotations

import asyncio
import logging
import sys

from telegram import Update
from telegram.constants import ChatMemberStatus
from telegram.error import InvalidToken, NetworkError, TelegramError
from telegram.ext import (
    AIORateLimiter,
    Application,
    ApplicationBuilder,
    ContextTypes,
)

from bot.handlers import router
from config import config
from core.db import database
from core.logging_setup import setup_logging

logger = logging.getLogger(__name__)


# ═════════════════════════════════════════════════════════════
#  پیش‌پرواز
# ═════════════════════════════════════════════════════════════

class PreflightError(RuntimeError):
    """سنجش پیش از پرواز ناکام ماند."""


async def preflight(app: Application) -> None:
    bot = app.bot
    problems: list[str] = []

    # ── ربات ────────────────────────────────────────────────
    me = await bot.get_me()
    logger.info("ربات شناسایی شد: @%s (%s)", me.username, me.id)

    # شناسهٔ ربات در تنظیمات می‌نشیند تا برچسب‌زن بتواند بی هیچ
    # رفت‌وآمد شبکه‌ای، خانهٔ «آلبوم» هر فایل را با آن پر کند.
    database.set_setting("bot_username", me.username or "")

    # ── کانال هم‌نشینی ──────────────────────────────────────
    try:
        chat = await bot.get_chat(config.channel_id)
        logger.info("کانال یافت شد: %s", chat.title)

        member = await bot.get_chat_member(config.channel_id, me.id)
        if member.status != ChatMemberStatus.ADMINISTRATOR:
            problems.append(
                f"ربات در کانال «{chat.title}» گرداننده نیست (وضعیت کنونی: {member.status}).\n"
                f"    بدون گردانندگی، بررسی هم‌نشینی کاربران ناممکن است.\n"
                f"    چاره: ربات را در کانال، گرداننده کنید."
            )
        else:
            logger.info("گردانندگی ربات در کانال تأیید شد.")
    except TelegramError as exc:
        problems.append(
            f"دسترسی به کانال با شناسهٔ {config.channel_id} ممکن نشد: {exc}\n"
            f"    شناسهٔ کانال همواره منفی و با -100 آغاز می‌شود.\n"
            f"    همچنین ربات باید نخست در کانال افزوده شده باشد."
        )

    # ── گروه‌ها ─────────────────────────────────────────────
    for label, chat_id in (
        ("گروه مداحی", config.madahi_group_id),
        ("گروه نقد و انتقادات", config.feedback_group_id),
    ):
        try:
            chat = await bot.get_chat(chat_id)
            logger.info("%s یافت شد: %s", label, chat.title)
        except TelegramError as exc:
            problems.append(
                f"دسترسی به {label} با شناسهٔ {chat_id} ممکن نشد: {exc}\n"
                f"    ربات باید در این گروه افزوده و گرداننده شده باشد."
            )

    # ── نسخهٔ اثر انگشت ─────────────────────────────────────
    # اگر الگوریتم عوض شده باشد، نمایهٔ کهنه بی‌اعتبار است و باید
    # از نو ساخته شود؛ وگرنه پرس‌وجوی تازه با آن هیچ اشتراکی
    # ندارد و ربات هیچ‌چیز پیدا نمی‌کند.
    from core.db import database as _db

    _db.ensure_fingerprint_version()

    # ── گروه‌های اختیاری ────────────────────────────────────
    # نبودنشان کار را نمی‌ایستاند، پس هشدارند نه ایراد مرگبار:
    # نسخهٔ آراسته به گروه مداحی فرو می‌افتد و گزارش کاربران
    # فرستاده نمی‌شود. ولی خاموش گذشتن هم درست نیست — همین گروه
    # بایگانی هفته‌ها بی‌صدا از کار افتاده بود.
    for label, chat_id, env_key, fallback in (
        ("گروه نسخهٔ آراسته", config.ornate_group_id, "ORNATE_GROUP_ID",
         "نسخه‌های آراسته تا رفع این، به گروه مداحی می‌روند"),
        ("گروه کاربران", config.users_group_id, "USERS_GROUP_ID",
         "گزارش کاربران تازه فرستاده نمی‌شود"),
    ):
        if chat_id:
            await _soft_check(bot, label, chat_id, env_key, fallback)

    if problems:
        raise PreflightError(
            "\n\n".join(f"  ✗ {problem}" for problem in problems)
        )


# ═════════════════════════════════════════════════════════════
#  رسیدگی به خطا
# ═════════════════════════════════════════════════════════════

async def _soft_check(
    bot, label: str, chat_id: int, env_key: str, fallback: str
) -> None:
    """
    گفتگویی اختیاری را می‌سنجد و تنها هشدار می‌دهد.

    resolve_chat شکل دیگرِ شناسه را هم می‌آزماید: شناسهٔ ابرگروه دو
    نمایش دارد و رونویسیِ شکلِ درونی — که بیشتر ابزارها نشان
    می‌دهند — به هیچ گفتگویی اشاره نمی‌کند.
    """
    from core import net

    found = await net.resolve_chat(bot, chat_id, label)
    if found is None:
        logger.warning(
            "دسترسی به %s (%s) ممکن نشد — %s.\n"
            "    دو چیز را بسنجید: ۱) ربات در آن گروه افزوده شده باشد؛ "
            "۲) شناسه درست باشد — برای دیدن شناسهٔ قطعی، در همان گروه "
            "فرمان /id را بفرستید.",
            label, chat_id, fallback,
        )
        return

    try:
        chat = await bot.get_chat(found)
        logger.info("%s یافت شد: %s", label, chat.title)
    except TelegramError:
        logger.info("%s یافت شد: %s", label, found)

    if found != chat_id:
        logger.warning(
            "%s در .env برابر %s است ولی شناسهٔ راستین %s است. تا "
            "بازراه‌اندازی خودمان درستش می‌کنیم؛ بهتر است در .env هم "
            "%s نوشته شود.",
            env_key, chat_id, found, found,
        )


async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.exception("خطای رسیدگی‌نشده", exc_info=context.error)


# ═════════════════════════════════════════════════════════════
#  برپایی
# ═════════════════════════════════════════════════════════════

async def _post_init(app: Application) -> None:
    await preflight(app)

    # صف پردازش را همین آغاز برپا می‌کنیم تا اگر پیکربندی‌اش ایراد
    # داشت، همین‌جا پیدا شود نه هنگام نخستین بازجویی کاربر.
    from worker.queue import get_queue

    get_queue()

    # نواهایی که نمایه‌سازی‌شان پیش‌تر شکست خورده بود، هر ربع
    # ساعت دوباره آزموده می‌شوند. بی این، یک قطعی گذرای شبکه
    # نوایی را برای همیشه نایافتنی می‌گذاشت.
    # جدول‌هایی که پس از ساختار نخستین افزوده شده‌اند
    from core.db import features_store, melody_store, site_index
    from services import crawler

    features_store.ensure_table()
    melody_store.ensure_table()
    site_index.ensure_table()
    crawler._ensure_table()

    # فهرست دستورها — همان که با دکمهٔ «/» کنار کادر نوشتن
    # گشوده می‌شود. هر بار آغاز به کار از نو نشانده می‌شود تا
    # اگر دستوری افزوده یا برداشته شد، خودبه‌خود به‌روز گردد.
    from bot import commands as bot_commands

    await bot_commands.publish(app.bot)

    # گمانه‌زن سبک و مداح، از نواهای برچسب‌خورده آموزش می‌بیند.
    # اگر هنوز برچسب بسنده نباشد، خاموش می‌ماند و آسیبی نمی‌زند.
    try:
        from core.audio.classifier import retrain

        madah_count, style_count, samples = retrain()
        if samples:
            logger.info(
                "گمانه‌زن آماده شد: %s مداح، %s سبک، از %s نمونه.",
                madah_count, style_count, samples,
            )
    except Exception:  # noqa: BLE001
        logger.exception("آموزش گمانه‌زن شکست خورد؛ ربات بی آن پیش می‌رود.")

    if app.job_queue is not None:
        from bot.handlers.archive import reindex_pending, republish_pending
        from services import backup

        # نمایه‌سازی نواهایی که پیش‌تر شکست خورده بودند
        app.job_queue.run_repeating(reindex_pending, interval=900, first=60)

        # نسخهٔ آراسته‌ای که در گروه بایگانی ننشسته. دو دقیقه پس از
        # نمایه‌سازی، تا اگر گروه تازه افزوده شده باشد همان دور
        # نخست، عقب‌ماندگی را جبران کند.
        app.job_queue.run_repeating(republish_pending, interval=900, first=120)

        # آوای استخراجیِ کهنه. این فایل‌ها تنها برای آنند که اگر
        # کاربر «این آن نیست» را نواخت بی‌درنگ فرستاده شوند؛ پس از
        # چند ساعت دیگر کسی سراغشان نمی‌آید.
        from bot.handlers.search import sweep_clips

        app.job_queue.run_repeating(sweep_clips, interval=3600, first=300)

        # سفارش‌های «خبرم کن» — هر ربع ساعت سنجیده می‌شوند.
        #
        # کارِ دوره‌ای است نه قلاب بر افزودنِ نوا: نوا از پنج راه
        # می‌آید و قلاب بر هر پنج، یعنی پنج جا برای هم‌گام نگه
        # داشتن. درنگش هم بی‌زیان است — «آنچه می‌خواستی رسید»
        # شتاب نمی‌خواهد، و این مهلت می‌گذارد نوای تازه آراسته و
        # شناسه‌دار شود.
        from bot.handlers.search import sweep_wishes

        app.job_queue.run_repeating(sweep_wishes, interval=900, first=180)

        # قفلِ پذیرش در گروه‌ها. مهلتش دو دقیقه است، پس هر دقیقه
        # سنجیده می‌شود — دیرتر یعنی گرداننده تا دو برابرِ مهلت
        # چشم‌به‌راه بماند.
        from bot.handlers.intake import sweep_locks

        app.job_queue.run_repeating(sweep_locks, interval=60, first=90)

        # رونویسیِ نواها — لایهٔ متن.
        #
        # جدا از نمایه‌سازی و با دستهٔ کوچک: رونویسی چند ده ثانیه
        # برای هر نوا می‌برد و نباید نمایه‌سازی را که فوری‌تر است
        # پشت خود نگه دارد. اگر مدل نصب نباشد، بی‌صدا بازمی‌گردد.
        async def _transcribe_job(context):
            from services import indexer

            done, failed = await indexer.transcribe_pending(context.bot)
            if done or failed:
                logger.info("رونویسی دوره‌ای: %s کامیاب، %s ناکام.", done, failed)

        app.job_queue.run_repeating(_transcribe_job, interval=600, first=240)

        # پشتیبان شبانه — گنجینهٔ اثر انگشت باارزش‌ترین دارایی این
        # پروژه است و بازسازی‌اش ناشدنی.
        app.job_queue.run_daily(backup.nightly, time=_at(3, 0))

        # کرال تارنماها؛ اگر هیچ تارنمایی روشن نباشد، خودش
        # بی‌سروصدا بازمی‌گردد.
        app.job_queue.run_daily(crawler.nightly, time=_at(4, 0))

        # گردشِ خودکار: ربات خودش از تارنماها نوا می‌یابد و در
        # گروه بایگانی به داوری می‌گذارد. ساعتی جدا از خزندهٔ
        # کهنه، تا دو کارِ سنگین روی هم نیفتند.
        from services import harvest as harvest_service

        app.job_queue.run_daily(harvest_service.nightly, time=_at(4, 45))

        # نمایهٔ تارنماها: سیت‌مپ‌ها خوانده و نام‌ها پر می‌شوند.
        # هرچه این نمایه پرتر شود، جست‌وجوی کاربر کمتر به رفتن به
        # تارنما نیاز دارد — و آنچه یک بار آورده شد، دیگر در
        # گنجینهٔ خودمان است.
        from services import sites as sites_service

        app.job_queue.run_daily(sites_service.nightly, time=_at(4, 30))

        # و یک بار در راه‌اندازی، اگر نمایه نحیف باشد.
        #
        # کارِ شبانهٔ بالا ساعت ۴:۳۰ می‌رفت و ربات هرگز آن ساعت
        # روشن نبود؛ نمایه با ۹۴ نشانی مانده بود و دو تارنما
        # یکسره تهی. جست‌وجوی تارنما «نیافتم» می‌گفت، نه چون نبود،
        # بلکه چون جایی برای گشتن نداشت. اگر نمایه پر باشد، این
        # بی‌درنگ بازمی‌گردد.
        app.job_queue.run_once(sites_service.bootstrap, when=90)

        # آموزش دوبارهٔ گمانه‌زن، پس از آنکه نواهای تازه نمایه شدند
        app.job_queue.run_daily(_retrain_job, time=_at(5, 0))

        logger.info("کارهای دوره‌ای زمان‌بندی شدند.")

    from core.db import fingerprints as fp_store

    logger.info(
        "گنجینه: %s نوا، %s نمایه‌شده، %s عدد اثر انگشت.",
        database.count_tracks(),
        database.count_tracks(indexed_only=True),
        fp_store.count_rows(),
    )
    logger.info("پیش‌پرواز بی‌عیب گذشت؛ ربات آمادهٔ خدمت است.")


def _at(hour: int, minute: int = 0):
    """
    زمانی در روز، به وقت ایران.

    بی گفتن منطقهٔ زمانی، کارها به وقت جهانی اجرا می‌شوند و
    «پشتیبان ساعت سه بامداد» در میانهٔ شلوغی روز می‌افتد.
    """
    from datetime import time as dt_time, timedelta, timezone

    return dt_time(hour=hour, minute=minute, tzinfo=timezone(timedelta(hours=3, minutes=30)))


async def _retrain_job(context) -> None:
    """آموزش دوبارهٔ گمانه‌زن، شبانه."""
    try:
        from core.audio.classifier import retrain

        madah_count, style_count, samples = retrain()
        if samples:
            logger.info(
                "گمانه‌زن از نو آموخت: %s مداح، %s سبک، از %s نمونه.",
                madah_count, style_count, samples,
            )
    except Exception:  # noqa: BLE001
        logger.exception("آموزش دوره‌ای گمانه‌زن شکست خورد.")


async def _post_shutdown(app: Application) -> None:
    from worker.queue import get_queue

    get_queue().shutdown()
    database.close_connection()


def build_application() -> Application:
    builder = (
        ApplicationBuilder()
        .token(config.bot_token)
        .rate_limiter(AIORateLimiter())
        .post_init(_post_init)
        .post_shutdown(_post_shutdown)
        # ── مهلت‌ها ──────────────────────────────────────────
        # پیش‌فرض PTB پنج ثانیه برای هر چهار مهلت است. برای
        # پیوندی که از ایران به تلگرام می‌رود، آن عدد به معنای
        # شکست خوردنِ هر بارگذاری فایل است — و گزارش‌ها همین را
        # نشان می‌دادند: هفده بار «برچسب‌گذاری شکست خورد».
        #
        # write_timeout از همه بلندتر است، چون بارگذاری نوای
        # چند مگابایتی درازترین کار شبکه‌ای این ربات است.
        .connect_timeout(config.connect_timeout)
        .read_timeout(config.read_timeout)
        .write_timeout(config.write_timeout)
        .pool_timeout(config.pool_timeout)
        .media_write_timeout(config.write_timeout)
        .connection_pool_size(config.connection_pool_size)
        # ── رسیدگی هم‌زمان ───────────────────────────────────
        # پیش‌فرض PTB یک به‌روزرسانی در هر لحظه است. با این پیوند،
        # یک فرستادنِ کند، هر نواختِ دیگری را پشت خود نگه می‌داشت —
        # و دکمه‌ها «گیر کرده» به چشم می‌آمدند، حال آنکه تنها در صف
        # بودند. هر کاربر جریان خودش را دارد، پس هم‌زمانی اینجا
        # چیزی را به هم نمی‌ریزد.
        .concurrent_updates(config.concurrent_updates)
        # گرفتن به‌روزرسانی‌ها پیوند درازآهنگ خودش را دارد و نباید
        # با پیوندهای کاری یک استخر را بخورد.
        .get_updates_connect_timeout(config.connect_timeout)
        .get_updates_read_timeout(config.read_timeout)
        .get_updates_pool_timeout(config.pool_timeout)
    )
    if config.proxy_url:
        builder = builder.proxy(config.proxy_url).get_updates_proxy(config.proxy_url)
        logger.info("پروکسی به کار گرفته شد: %s", _mask(config.proxy_url))
    if config.local_bot_api_url:
        builder = builder.base_url(config.local_bot_api_url)
        logger.info("سرور محلی Bot API به کار گرفته شد: %s", config.local_bot_api_url)

    app = builder.build()
    router.register(app)
    app.add_error_handler(on_error)
    return app


def main() -> int:
    setup_logging()
    logger.info("═" * 50)
    logger.info("  حدیث عشق — آغاز به کار")
    logger.info("═" * 50)

    database.init_db()
    logger.info("پایگاه داده آماده است: %s", config.database_path)

    app = build_application()
    try:
        app.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)
    except PreflightError as exc:
        _fail("پیش‌پرواز ناکام ماند", str(exc))
        return 1
    except InvalidToken:
        _fail(
            "توکن پذیرفته نشد",
            "  ✗ توکنی که در .env گذاشته‌اید را تلگرام نمی‌شناسد.\n"
            "    از @BotFather توکن تازه بگیرید و در کلید BOT_TOKEN بنشانید.\n"
            "    اگر توکن پیشتر جایی منتشر شده، نخست /revoke بزنید.",
        )
        return 1
    except NetworkError as exc:
        _fail(
            "رسیدن به تلگرام ممکن نشد",
            f"  ✗ {exc}\n"
            "    پیوند اینترنت یا ابزار گذر از تحریم را بررسی کنید.",
        )
        return 1
    except (KeyboardInterrupt, SystemExit):
        logger.info("ربات به خواست گرداننده متوقف شد.")
    finally:
        database.close_connection()

    return 0


def _mask(url: str) -> str:
    """نشانی پروکسی را برای گزارش، بی رمز می‌نمایاند."""
    import re

    return re.sub(r"//[^@/]+@", "//***@", url)


def _fail(title: str, body: str) -> None:
    """خطای مرگبار را خوانا چاپ می‌کند — نه به شکل ردِ پشتهٔ خام."""
    print(f"\n{'═' * 62}", file=sys.stderr)
    print(f"  {title}", file=sys.stderr)
    print("═" * 62, file=sys.stderr)
    print(f"\n{body}\n", file=sys.stderr)


if __name__ == "__main__":
    sys.exit(main())
