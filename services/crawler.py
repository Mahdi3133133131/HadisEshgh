"""
کرالر تارنماها — پیش‌نمایه‌سازی گنجینه‌های بیرونی.

═══════════════════════════════════════════════════════════════
  چرا این بخش با آنچه سند می‌خواست فرق دارد
═══════════════════════════════════════════════════════════════

سند می‌گفت: «دیتابیس ← کانال مخزن ← سایت‌ها را بگرد».

ولی هیچ‌یک از آن تارنماها جست‌وجو با صدا ندارند. نمی‌توان پاره‌ای
از آوا به تارنما داد و پرسید «این کدام است». پس «گشتن در تارنماها
هنگام بازجویی» به آن شکل ناشدنی است.

آنچه شدنی است، وارونهٔ آن است:

  **از پیش نمایه کن، نه هنگام بازجویی.**

این کرالر شب‌ها می‌گردد، فایل‌ها را فرو می‌گیرد، اثر انگشتشان را
می‌سازد، و **تنها اثر انگشت و نشانی مبدأ** را نگه می‌دارد؛ خودِ
فایل پاک می‌شود. هنگام تطبیق، فایل از همان نشانی مبدأ دوباره
فرو گرفته و فرستاده می‌شود.

پیامدش این است که گنجینهٔ شما تنها تا آنجاست که کرال کرده‌اید — نه
«همهٔ اینترنت». ولی این، یگانه راه راستین است.

═══════════════════════════════════════════════════════════════
  ادب کرال
═══════════════════════════════════════════════════════════════

این تارنماها میهمان‌نوازی می‌کنند و نباید آزرده شوند:

  • میان هر دو درخواست درنگ می‌شود
  • robots.txt خوانده و پاس داشته می‌شود
  • نشانی‌های دیده‌شده نگه داشته می‌شوند تا دوباره فرو گرفته نشوند
  • تنها یک تارنما در هر بار، نه همه با هم
  • سقف روزانه، تا بار سنگینی بر آن‌ها ننشیند

ساختار تارنماها دگرگون می‌شود و این کرالر شکننده است. از این رو
هر تارنما پیکربندی جداگانه دارد و شکستن یکی، بقیه را نمی‌ایستاند.
"""

from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import unquote, urljoin, urlparse
from urllib.robotparser import RobotFileParser

logger = logging.getLogger(__name__)

# ── ادب ──────────────────────────────────────────────────────
DELAY_SECONDS = 2.0
MAX_PER_SITE_PER_RUN = 40
REQUEST_TIMEOUT = 60
MAX_FILE_BYTES = 40 * 1024 * 1024

USER_AGENT = "HadisEshghBot/1.0 (archive indexer; contact via telegram)"

_AUDIO_PATTERN = re.compile(r'href=[\'"]([^\'"]+\.mp3[^\'"]*)[\'"]', re.IGNORECASE)


@dataclass
class Site:
    """پیکربندی یک تارنما."""

    name: str
    base_url: str
    list_paths: tuple[str, ...] = ()
    enabled: bool = True
    # اگر تارنما ساختار ویژه‌ای دارد، می‌توان الگوی دیگری داد
    link_pattern: re.Pattern[str] = field(default_factory=lambda: _AUDIO_PATTERN)


# تارنماهایی که سند نام برده بود.
# همه به‌جز نخستین، خاموش‌اند: پیش از روشن کردن هرکدام باید
# ساختارش را وارسی کرد، وگرنه کرالر بی‌هوده می‌گردد.
SITES: tuple[Site, ...] = (
    Site(
        name="madahionline",
        base_url="https://madahionline.ir/",
        list_paths=("",),
        enabled=False,
    ),
    Site(
        name="musics-fa",
        base_url="https://musics-fa.com/",
        list_paths=("",),
        enabled=False,
    ),
    Site(
        name="aghigh",
        base_url="https://radio.aghigh.ir/",
        list_paths=("",),
        enabled=False,
    ),
    Site(
        name="neynava",
        base_url="https://radioneynava.com/fa",
        list_paths=("",),
        enabled=False,
    ),
    Site(
        name="kashoob",
        base_url="https://kashoob.com/",
        list_paths=("",),
        enabled=False,
    ),
)


class CrawlError(RuntimeError):
    """کرال یک تارنما شکست خورد."""


# ═════════════════════════════════════════════════════════════
#  دفتر نشانی‌های دیده‌شده
# ═════════════════════════════════════════════════════════════

def _ensure_table() -> None:
    from core.db.database import execute

    execute(
        """
        CREATE TABLE IF NOT EXISTS crawled_urls (
            url         TEXT PRIMARY KEY,
            site        TEXT NOT NULL,
            status      TEXT NOT NULL,   -- indexed | failed | skipped
            track_id    INTEGER,
            note        TEXT,
            seen_at     TEXT NOT NULL DEFAULT (datetime('now'))
        )
        """
    )
    execute("CREATE INDEX IF NOT EXISTS idx_crawled_site ON crawled_urls(site, status)")


def _seen(url: str) -> bool:
    from core.db.database import query_one

    return query_one("SELECT 1 FROM crawled_urls WHERE url = ?", (url,)) is not None


def _remember(url: str, site: str, status: str, track_id: int | None = None,
              note: str | None = None) -> None:
    from core.db.database import execute

    execute(
        """
        INSERT INTO crawled_urls (url, site, status, track_id, note)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(url) DO UPDATE SET status = excluded.status,
                                       track_id = excluded.track_id,
                                       note = excluded.note,
                                       seen_at = datetime('now')
        """,
        (url, site, status, track_id, note),
    )


def stats() -> dict[str, int]:
    from core.db.database import query_all

    _ensure_table()
    rows = query_all(
        "SELECT status, COUNT(*) AS c FROM crawled_urls GROUP BY status"
    )
    return {row["status"]: int(row["c"]) for row in rows}


# ═════════════════════════════════════════════════════════════
#  robots.txt
# ═════════════════════════════════════════════════════════════

_robots_cache: dict[str, RobotFileParser | None] = {}


async def _robots_allows(session, base_url: str, url: str) -> bool:
    """
    آیا robots.txt این نشانی را روا می‌داند.

    اگر robots.txt نبود یا خوانده نشد، روا شمرده می‌شود — همان
    رفتاری که استاندارد می‌خواهد.
    """
    host = urlparse(base_url).netloc
    if host not in _robots_cache:
        parser: RobotFileParser | None = None
        try:
            robots_url = urljoin(base_url, "/robots.txt")
            async with session.get(robots_url, timeout=15) as response:
                if response.status == 200:
                    text = await response.text()
                    parser = RobotFileParser()
                    parser.parse(text.splitlines())
        except Exception:  # noqa: BLE001
            parser = None
        _robots_cache[host] = parser

    parser = _robots_cache[host]
    if parser is None:
        return True
    return parser.can_fetch(USER_AGENT, url)


# ═════════════════════════════════════════════════════════════
#  کرال
# ═════════════════════════════════════════════════════════════

async def discover(session, site: Site, path: str) -> list[str]:
    """نشانی فایل‌های صوتی را در یک صفحه می‌یابد."""
    page_url = urljoin(site.base_url, path)
    try:
        async with session.get(page_url, timeout=REQUEST_TIMEOUT) as response:
            if response.status != 200:
                logger.debug("%s پاسخ %s داد.", page_url, response.status)
                return []
            html = await response.text(errors="replace")
    except Exception as exc:  # noqa: BLE001
        logger.debug("گرفتن %s شکست خورد: %s", page_url, exc)
        return []

    found: list[str] = []
    for match in site.link_pattern.finditer(html):
        raw = match.group(1)
        absolute = urljoin(page_url, unquote(raw))
        # تنها همان میزبان؛ کرالر نباید به همهٔ اینترنت سرک بکشد
        if urlparse(absolute).netloc != urlparse(site.base_url).netloc:
            continue
        if absolute not in found:
            found.append(absolute)
    return found


async def fetch_file(session, url: str, destination: Path) -> Path | None:
    """فایل را فرو می‌گیرد؛ None اگر نشد یا بزرگ‌تر از سقف بود."""
    try:
        async with session.get(url, timeout=REQUEST_TIMEOUT) as response:
            if response.status != 200:
                return None
            length = response.headers.get("Content-Length")
            if length and int(length) > MAX_FILE_BYTES:
                logger.debug("%s بزرگ‌تر از سقف است.", url)
                return None

            destination.parent.mkdir(parents=True, exist_ok=True)
            written = 0
            with destination.open("wb") as handle:
                async for chunk in response.content.iter_chunked(65536):
                    written += len(chunk)
                    if written > MAX_FILE_BYTES:
                        handle.close()
                        destination.unlink(missing_ok=True)
                        return None
                    handle.write(chunk)
            return destination
    except Exception as exc:  # noqa: BLE001
        logger.debug("فرو گرفتن %s شکست خورد: %s", url, exc)
        return None


def _title_from_url(url: str) -> str:
    """نامی خوانا از نشانی بیرون می‌کشد."""
    from core.normalize import fix_display

    name = unquote(Path(urlparse(url).path).stem)
    name = re.sub(r"[-_]+", " ", name).strip()
    return fix_display(name)[:120] or "بی‌نام"


async def crawl_site(site: Site, limit: int = MAX_PER_SITE_PER_RUN) -> tuple[int, int]:
    """
    یک تارنما را می‌گردد و نواهای تازه را نمایه می‌کند.

    بازگشتی: (نمایه‌شده، ناکام)
    """
    import aiohttp

    from config import config
    from core.audio.decode import DecodeError, decode
    from core.audio.fingerprint import FAN_OUT_INDEX, FingerprintError, fingerprint
    from core.db import database, fingerprints as fp_store

    _ensure_table()
    indexed = failed = 0
    work_dir = config.tmp_dir / "crawl"
    work_dir.mkdir(parents=True, exist_ok=True)

    headers = {"User-Agent": USER_AGENT}
    async with aiohttp.ClientSession(headers=headers) as session:
        # ── یافتن نشانی‌ها ──────────────────────────────────
        candidates: list[str] = []
        for path in site.list_paths:
            candidates.extend(await discover(session, site, path))
            await asyncio.sleep(DELAY_SECONDS)

        fresh = [url for url in candidates if not _seen(url)][:limit]
        logger.info(
            "%s: %s نشانی یافت شد، %s تازه است.", site.name, len(candidates), len(fresh)
        )

        # ── فرو گرفتن و نمایه‌سازی ──────────────────────────
        for url in fresh:
            if not await _robots_allows(session, site.base_url, url):
                _remember(url, site.name, "skipped", note="robots.txt")
                continue

            temp = work_dir / f"{abs(hash(url))}.mp3"
            try:
                path = await fetch_file(session, url, temp)
                if path is None:
                    _remember(url, site.name, "failed", note="فرو گرفتن نشد")
                    failed += 1
                    continue

                loop = asyncio.get_running_loop()
                try:
                    samples = await loop.run_in_executor(None, decode, path)
                    print_ = await loop.run_in_executor(
                        None, lambda: fingerprint(samples, fan_out=FAN_OUT_INDEX)
                    )
                except (DecodeError, FingerprintError) as exc:
                    _remember(url, site.name, "failed", note=str(exc)[:120])
                    failed += 1
                    continue

                # نوا بی file_id ثبت می‌شود؛ فایل در تارنما می‌ماند
                # و هنگام نیاز از نشانی مبدأ دوباره فرو گرفته می‌شود.
                track_id = database.add_track(
                    file_id=None,
                    file_unique_id=None,
                    source="crawler",
                    title=_title_from_url(url),
                    duration=print_.duration_ms // 1000,
                    source_url=url,
                )
                fp_store.store(track_id, print_.hashes, print_.offsets)
                _remember(url, site.name, "indexed", track_id=track_id)
                indexed += 1

            finally:
                temp.unlink(missing_ok=True)
                await asyncio.sleep(DELAY_SECONDS)

    logger.info("%s: %s نمایه شد، %s ناکام.", site.name, indexed, failed)
    return indexed, failed


async def crawl_all(limit_per_site: int = MAX_PER_SITE_PER_RUN) -> dict[str, tuple[int, int]]:
    """
    همهٔ تارنماهای روشن را می‌گردد.

    شکستن یکی، بقیه را نمی‌ایستاند — ساختار این تارنماها مدام
    دگرگون می‌شود و شکنندگی، بیوسیدنی است.
    """
    results: dict[str, tuple[int, int]] = {}
    for site in SITES:
        if not site.enabled:
            continue
        try:
            results[site.name] = await crawl_site(site, limit_per_site)
        except Exception:  # noqa: BLE001
            logger.exception("کرال %s شکست خورد.", site.name)
            results[site.name] = (0, 0)
    return results


async def nightly(context) -> None:
    """کار زمان‌بندی‌شدهٔ شبانه."""
    enabled = [site.name for site in SITES if site.enabled]
    if not enabled:
        logger.debug("هیچ تارنمایی روشن نیست؛ کرال انجام نشد.")
        return

    try:
        results = await crawl_all()
        total_indexed = sum(indexed for indexed, _ in results.values())
        if total_indexed:
            logger.info("کرال شبانه: %s نوای تازه نمایه شد.", total_indexed)
    except Exception:  # noqa: BLE001
        logger.exception("کرال شبانه شکست خورد.")
