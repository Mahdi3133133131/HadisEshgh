"""
گنجینه‌ای که خودش بزرگ می‌شود.

## چرا این هست

تا امروز هر نوا را باید آدمی می‌فرستاد. گنجینه به همان اندازه‌ای
بزرگ می‌شد که کسی وقت می‌گذاشت — و کاربر می‌خواست ربات خودش برود
بیابد.

## چرا صف، و نه افزودنِ مستقیم

شناسنامهٔ تارنماها اغلب ناقص است، و آنچه «مداحی» خوانده می‌شود
گاه سخنرانی یا تیزر است. افزودنِ بی‌داوری، گنجینه را با آشغال پر
می‌کرد — و پاک کردنشان بسی سخت‌تر از نپذیرفتنشان است.

پس هر یافته در گروه بایگانی با دکمهٔ تأیید/لغو می‌نشیند و پیش از
تأیید، در `tracks` خبری نیست.

## چرا بر `sites.py` سوار است، نه `crawler.py`

هر دو کارِ گشتن می‌کردند، ولی `sites.py` در هر بخش جلوتر است:
نقشهٔ سایت به جای regexِ صفحهٔ فهرست، robots با الگوی ستاره‌دار،
درنگِ ادب بر پایهٔ میزبان، و رسیدنِ آزموده از صفحه به فایل. نگه
داشتنِ دو فهرستِ تارنما یعنی روزی یکی‌شان از قلم بیفتد.
"""

from __future__ import annotations

import asyncio
import logging
import re
from pathlib import Path
from urllib.parse import quote, urlparse, urlunparse

from config import config
from core.db.database import execute, query_all, query_one

logger = logging.getLogger(__name__)

# در هر گردش، بیش از این نوا به داوری نمی‌رود.
#
# هم ادبِ میزبان است و هم ادبِ گرداننده: صد کارت در گروه بایگانی،
# داوری را ناممکن می‌کند و کسی به هیچ‌کدام نمی‌رسد.
MAX_PER_RUN = 12

# بیش از این نشانی در یک گردش سنجیده نمی‌شود، حتی اگر همه رد شوند.
MAX_PROBES = 60

# ── بیرون کشیدنِ عنوان و مداح از تیترِ برگه ──────────────────
#
# madahi.ir تیترش را چنین می‌نویسد:
#     «دانلود مداحی <نام نوا> از <نام مداح>»
# پس هر دو با یک الگو به دست می‌آیند. تارنمای دیگری که افزوده
# شود، الگوی خودش را می‌آورد.
_TITLE_SPLIT = re.compile(r"\s+از\s+", re.UNICODE)
_TITLE_LEAD = re.compile(
    r"^\s*(?:دانلود\s*)?(?:مداحی|نوحه|روضه|مولودی)\s*", re.UNICODE
)


def _clean_url(url: str) -> str:
    """
    نشانی را برای فرو گرفتن آماده می‌کند.

    نشانیِ فایل‌ها گاه فاصله و نویسهٔ فارسی دارد؛ بی درصدنویسی،
    درخواست شکست می‌خورد.
    """
    parts = urlparse(url)
    return urlunparse(parts._replace(path=quote(parts.path, safe="/%")))


def split_title(raw: str | None) -> tuple[str | None, str | None]:
    """
    تیترِ برگه را به (نام نوا، نام مداح) می‌شکند.

    اگر الگو نخواند، همهٔ تیتر نامِ نواست و مداح نامعلوم می‌ماند —
    که بهتر از حدسِ نادرست است.
    """
    if not raw:
        return None, None
    text = _TITLE_LEAD.sub("", raw.strip())
    pieces = _TITLE_SPLIT.split(text, maxsplit=1)
    if len(pieces) == 2:
        title, madah = pieces[0].strip(), pieces[1].strip()
        return (title or None), (madah or None)
    return (text.strip() or None), None


# ═════════════════════════════════════════════════════════════
#  صف
# ═════════════════════════════════════════════════════════════

def pending(limit: int = 50) -> list:
    return query_all(
        "SELECT * FROM harvest_queue WHERE status = 'pending'"
        " ORDER BY created_at LIMIT ?",
        (limit,),
    )


def get(queue_id: int):
    return query_one("SELECT * FROM harvest_queue WHERE id = ?", (int(queue_id),))


def _enqueue(**fields) -> int | None:
    columns = ", ".join(fields)
    marks = ", ".join("?" for _ in fields)
    try:
        execute(
            f"INSERT OR IGNORE INTO harvest_queue ({columns}) VALUES ({marks})",
            tuple(fields.values()),
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug("نشاندن در صفِ داوری نشد: %s", exc)
        return None
    row = query_one(
        "SELECT id FROM harvest_queue WHERE page_url = ?", (fields["page_url"],)
    )
    return int(row["id"]) if row else None


def mark(queue_id: int, status: str, track_id: int | None = None) -> None:
    execute(
        "UPDATE harvest_queue SET status = ?, track_id = COALESCE(?, track_id)"
        " WHERE id = ?",
        (status, track_id, int(queue_id)),
    )


def set_card(queue_id: int, message_id: int) -> None:
    execute(
        "UPDATE harvest_queue SET card_msg_id = ? WHERE id = ?",
        (int(message_id), int(queue_id)),
    )


def counts() -> dict[str, int]:
    rows = query_all("SELECT status, COUNT(*) AS c FROM harvest_queue GROUP BY status")
    return {str(r["status"]): int(r["c"]) for r in rows}


# ═════════════════════════════════════════════════════════════
#  گردش
# ═════════════════════════════════════════════════════════════

async def _candidates(session, site) -> list[str]:
    """نشانی‌های تازهٔ این تارنما، از نقشهٔ سایتش."""
    from services import crawler, sites

    crawler._ensure_table()
    found: list[str] = []
    for sitemap in site.sitemaps:
        try:
            found.extend(await sites._walk_sitemap(session, sitemap))
        except Exception as exc:  # noqa: BLE001
            logger.info("نقشهٔ %s خوانده نشد: %s", site.name, exc)

    fresh = []
    for url in found:
        if crawler._seen(url):
            continue
        if site.page_pattern is not None and not site.is_track_page(url):
            continue
        fresh.append(url)
    return fresh


async def sweep(bot, limit: int = MAX_PER_RUN) -> int:
    """
    یک گردش: کشف، سنجش، و نشاندنِ کارت‌های داوری.

    بازگشتی: شمار نواهایی که به داوری رفتند.
    """
    from core.audio.decode import DecodeError, decode
    from services import crawler, dedup, sites

    target = config.ornate_target
    if not target:
        logger.info("گروه بایگانی تنظیم نشده؛ گردشِ خودکار اجرا نشد.")
        return 0

    active = [s for s in sites.SITES if s.enabled and s.sitemaps]
    if not active:
        logger.info("هیچ تارنمای روشنی برای گردش نیست.")
        return 0

    try:
        session = sites._session()
    except ImportError:
        logger.warning("aiohttp نیست؛ گردشِ خودکار انجام نشد.")
        return 0

    work = config.tmp_dir / "harvest"
    work.mkdir(parents=True, exist_ok=True)
    queued = 0

    async with session:
        for site in active:
            if queued >= limit:
                break
            fresh = await _candidates(session, site)
            logger.info("%s: %s نشانیِ تازه.", site.name, len(fresh))

            for url in fresh[:MAX_PROBES]:
                if queued >= limit:
                    break
                try:
                    made = await _consider(
                        session, bot, site, url, work, decode, DecodeError,
                        crawler, dedup, sites, target,
                    )
                except Exception:  # noqa: BLE001
                    logger.exception("سنجشِ %s شکست خورد.", url[:80])
                    made = False
                if made:
                    queued += 1

    if queued:
        logger.info("گردشِ خودکار: %s نوا به داوری رفت.", queued)
    return queued


async def _consider(
    session, bot, site, url, work, decode, DecodeError,
    crawler, dedup, sites, target,
) -> bool:
    """
    یک نشانی را می‌سنجد و اگر ارزشش را داشت به داوری می‌فرستد.

    هر ناکامی در `crawled_urls` نشان می‌خورد، تا گردشِ بعدی همان
    راه را دوباره نرود.
    """
    if not await sites._allowed(session, url):
        crawler._remember(url, site.name, "skipped", note="robots.txt")
        return False

    hit = sites.Hit(site=site.name, title="", page_url=url)
    hit = await sites.resolve(hit)
    if not hit.file_url:
        crawler._remember(url, site.name, "skipped", note="فایلی در برگه نبود")
        return False

    title, madah = split_title(hit.title)

    temp = work / f"h{abs(hash(url)) % 10**10}.mp3"
    try:
        got = await sites.download(_clean_url(hit.file_url), temp)
        if got is None:
            crawler._remember(url, site.name, "failed", note="فرو گرفتن نشد")
            return False

        loop = asyncio.get_running_loop()
        try:
            samples = await loop.run_in_executor(None, decode, temp)
        except DecodeError as exc:
            crawler._remember(url, site.name, "failed", note=str(exc)[:120])
            return False

        # ── تکراری، پیش از هر چیزِ دیگر ─────────────────────
        #
        # وگرنه گنجینه از نسخه‌های همانند پر می‌شود — همان ایرادی
        # که ادغام برای رفعش ساخته شد.
        twin = await loop.run_in_executor(
            None, dedup.find_same_recording, -1, samples
        )
        if twin is not None:
            crawler._remember(
                url, site.name, "skipped", note=f"تکراریِ نوای {twin[0]}"
            )
            return False

        # نامِ مداح از همان زنجیره‌ای می‌گذرد که فینگلیش و نامِ
        # ناقص را درست می‌کند.
        if madah:
            try:
                from services.captions import resolve_madah

                madah = resolve_madah(madah) or madah
            except Exception:  # noqa: BLE001
                logger.debug("رساندنِ نامِ مداح نشد.", exc_info=True)

        if title:
            try:
                from services.captions import clean_title

                title = clean_title(title) or title
            except Exception:  # noqa: BLE001
                logger.debug("پیراستنِ اسمِ نوا نشد.", exc_info=True)

        seconds = int(samples.size / 11025)
        queue_id = _enqueue(
            site=site.name, page_url=url, file_url=hit.file_url,
            title=title, madah=madah, duration=seconds,
        )
        if queue_id is None:
            return False

        sent = await _post_card(bot, target, queue_id, temp, title, madah, seconds, site)
        if not sent:
            # کارت نرفت؛ ردیف می‌ماند و گردشِ بعدی دوباره می‌کوشد.
            return False

        crawler._remember(url, site.name, "queued", note=f"صف {queue_id}")
        return True

    finally:
        temp.unlink(missing_ok=True)


async def _post_card(bot, target, queue_id, path, title, madah, seconds, site) -> bool:
    """کارتِ داوری را در گروه بایگانی می‌نشاند."""
    from telegram.error import TelegramError

    from bot.keyboards import inline
    from core import net, texts
    from core.normalize import format_duration

    caption = texts.msg(
        "harvest_card",
        title=title or "—",
        madah=madah or "—",
        duration=format_duration(seconds),
        site=site.label,
    )
    try:
        with Path(path).open("rb") as handle:
            message = await net.retry(
                lambda: bot.send_audio(
                    chat_id=target,
                    audio=handle,
                    caption=caption,
                    parse_mode="HTML",
                    title=title or None,
                    performer=madah or None,
                    reply_markup=inline.harvest_card(queue_id),
                    read_timeout=config.read_timeout,
                    write_timeout=config.write_timeout,
                    connect_timeout=config.connect_timeout,
                ),
                label="کارتِ داوریِ نوای یافته",
            )
    except (OSError, TelegramError) as exc:
        logger.info("کارتِ داوری فرستاده نشد: %s", exc)
        return False

    if message.audio is not None:
        execute(
            "UPDATE harvest_queue SET file_id = ?, file_unique_id = ? WHERE id = ?",
            (message.audio.file_id, message.audio.file_unique_id, int(queue_id)),
        )
    set_card(queue_id, message.message_id)
    return True


async def nightly(context) -> None:
    """کارِ شبانه."""
    try:
        await sweep(context.bot)
    except Exception:  # noqa: BLE001
        logger.exception("گردشِ شبانهٔ خودکار شکست خورد.")
