"""
فرو گرفتن نماهنگ از اینستاگرام.

═══════════════════════════════════════════════════════════════
  هشدار: شکننده‌ترین بخش این ربات
═══════════════════════════════════════════════════════════════

اینستاگرام فرو گرفتن خودکار را فعالانه می‌بندد. آنچه امروز کار
می‌کند، ممکن است ماه دیگر نکند. از این رو:

  • این بخش هرگز نباید مسیر اصلی شمرده شود. اگر شکست، کاربر باید
    راه دیگری پیش رو ببیند — «خودِ نماهنگ را بفرستید».
  • هر گونه شکست به پیامی روشن و راهنما ترجمه می‌شود، نه به
    «خطای ناشناخته» که کاربر را سردرگم می‌گذارد.
  • برای پایداری بیشتر، پروندهٔ کوکی یک اکانت جانبی می‌تواند در
    INSTAGRAM_COOKIES_FILE نهاده شود. آن اکانت ممکن است محدود
    گردد؛ پس اکانت اصلی خود را به کار نبرید.

ابزار کار yt-dlp است، نه aiohttp. سند aiohttp را نام برده بود ولی
aiohttp تنها یک کتابخانهٔ شبکه است و از رمزگشایی صفحهٔ اینستاگرام
و یافتن نشانی راستین نماهنگ چیزی نمی‌داند.
"""

from __future__ import annotations

import logging
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

# میزبان‌های پذیرفته. جز این‌ها پذیرفته نمی‌شود تا ربات به ابزاری
# برای فرو گرفتن از هر جای اینترنت دگرگون نشود.
_ALLOWED_HOSTS = {
    "instagram.com",
    "www.instagram.com",
    "m.instagram.com",
    "instagr.am",
    "www.instagr.am",
    "ddinstagram.com",
}

_URL_PATTERN = re.compile(
    r"https?://(?:www\.|m\.)?(?:instagram\.com|instagr\.am|ddinstagram\.com)/\S+",
    re.IGNORECASE,
)

# بیشترین درازای نماهنگ پذیرفته — فراتر از آن، نشانهٔ نشانی نادرست
MAX_DURATION_SECONDS = 15 * 60
MAX_FILESIZE = 45 * 1024 * 1024


class InstagramError(RuntimeError):
    """فرو گرفتن شکست خورد؛ پیام آن، خواندنی برای کاربر است."""

    def __init__(self, message_key: str, detail: str = "") -> None:
        super().__init__(detail or message_key)
        self.message_key = message_key
        self.detail = detail


@dataclass(frozen=True)
class InstagramVideo:
    path: Path
    title: str | None
    duration: float | None
    uploader: str | None


def find_url(text: str | None) -> str | None:
    """نشانی اینستاگرام را در نوشتار می‌یابد."""
    if not text:
        return None
    found = _URL_PATTERN.search(text)
    return found.group(0).rstrip(".,!?)»") if found else None


def is_instagram_url(url: str) -> bool:
    """
    درستی نشانی را می‌سنجد.

    سنجش بر پایهٔ میزبانِ رمزگشایی‌شده است نه جست‌وجوی رشته، تا
    نشانی‌هایی مانند ‎evil.com/instagram.com‎ نگذرند.
    """
    try:
        parsed = urlparse(url)
    except ValueError:
        return False
    if parsed.scheme not in ("http", "https"):
        return False
    return (parsed.hostname or "").lower() in _ALLOWED_HOSTS


def _cookies_file() -> str | None:
    from config import config

    raw = getattr(config, "instagram_cookies_file", "")
    if not raw:
        return None
    path = Path(raw)
    if not path.is_absolute():
        path = config.base_dir / path
    if not path.exists():
        logger.warning("پروندهٔ کوکی «%s» یافت نشد؛ بی آن پیش می‌رویم.", path)
        return None
    return str(path)


def download(url: str, destination_dir: Path) -> InstagramVideo:
    """
    نماهنگ را فرو می‌گیرد.

    این تابع بازدارنده است و باید در ریسه‌ای جدا (از راه صف)
    فراخوانده شود، وگرنه حلقهٔ رویداد ربات می‌ایستد.
    """
    if not is_instagram_url(url):
        raise InstagramError("instagram_bad_url")

    try:
        import yt_dlp
    except ImportError as exc:  # pragma: no cover
        raise InstagramError("instagram_unavailable", "yt-dlp نصب نیست") from exc

    destination_dir.mkdir(parents=True, exist_ok=True)
    template = str(destination_dir / "%(id)s.%(ext)s")

    options = {
        "outtmpl": template,
        "format": "best[ext=mp4]/best",
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "nocheckcertificate": True,
        "retries": 3,
        "socket_timeout": 30,
        "max_filesize": MAX_FILESIZE,
        # اینستاگرام درخواست‌های بی‌نشان را زودتر می‌بندد
        "http_headers": {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/122.0 Safari/537.36"
            )
        },
    }

    cookies = _cookies_file()
    if cookies:
        options["cookiefile"] = cookies

    try:
        with yt_dlp.YoutubeDL(options) as downloader:
            info = downloader.extract_info(url, download=True)
    except Exception as exc:  # noqa: BLE001 — yt-dlp گونه‌های بسیاری می‌پراند
        raise _translate(exc) from exc

    if info is None:
        raise InstagramError("instagram_failed")

    # نشانی گاه به چند نماهنگ می‌رسد؛ نخستین را برمی‌داریم
    if "entries" in info:
        entries = [entry for entry in info.get("entries") or [] if entry]
        if not entries:
            raise InstagramError("instagram_no_video")
        info = entries[0]

    duration = info.get("duration")
    if duration and duration > MAX_DURATION_SECONDS:
        raise InstagramError("instagram_too_long")

    path = _locate(info, destination_dir)
    if path is None:
        raise InstagramError("instagram_failed", "پروندهٔ فرو گرفته یافت نشد")

    return InstagramVideo(
        path=path,
        title=info.get("title") or info.get("description"),
        duration=duration,
        uploader=info.get("uploader") or info.get("uploader_id"),
    )


def _locate(info: dict, destination_dir: Path) -> Path | None:
    """پروندهٔ فرو گرفته را می‌یابد."""
    for candidate in info.get("requested_downloads") or ():
        raw = candidate.get("filepath")
        if raw and Path(raw).exists():
            return Path(raw)

    video_id = info.get("id")
    if video_id:
        matches = sorted(destination_dir.glob(f"{video_id}.*"))
        if matches:
            return matches[0]

    # واپسین چاره: تازه‌ترین پروندهٔ پوشه
    files = sorted(
        (path for path in destination_dir.iterdir() if path.is_file()),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    return files[0] if files else None


def _translate(exc: Exception) -> InstagramError:
    """
    خطای yt-dlp را به پیامی که کاربر بفهمد برمی‌گرداند.

    گفتن «خطای ناشناخته» به کاربر، او را در تاریکی می‌گذارد؛ هر
    یک از این حالت‌ها چارهٔ جداگانه‌ای دارد که باید بداند.
    """
    text = str(exc).lower()

    # ── «ورود لازم است» با «این پست خصوصی است» یکی نیست ──────
    #
    # پیش‌تر هر خطایی که واژهٔ login داشت، «خصوصی است» خوانده
    # می‌شد. ولی اینستاگرام امروز برای دسترسیِ **ناشناس** هم ورود
    # می‌خواهد — شرطی همگانی، نه ویژگیِ آن پست. پس کاربری که
    # نشانیِ یک پست عمومی را می‌داد، می‌شنید «خصوصی است» و
    # می‌ماند که چرا رباتِ دیگری همان را می‌آورد. (می‌آورد، چون
    # نشست دارد.)
    if any(
        word in text
        for word in ("login required", "log in", "cookies", "authenticat", "sign in",
                     "rate-limit reached", "requires login")
    ):
        return InstagramError("instagram_needs_login", str(exc)[:200])
    if "private" in text or "not available" in text:
        return InstagramError("instagram_private", str(exc)[:200])
    if any(word in text for word in ("not found", "404", "unavailable", "removed", "deleted")):
        return InstagramError("instagram_not_found", str(exc)[:200])
    if any(word in text for word in ("rate", "429", "too many", "wait a few")):
        return InstagramError("instagram_rate_limited", str(exc)[:200])
    if "filesize" in text or "file is larger" in text:
        return InstagramError("instagram_too_big", str(exc)[:200])
    if any(word in text for word in ("timed out", "timeout", "connection", "network", "resolve")):
        return InstagramError("instagram_network", str(exc)[:200])

    logger.warning("خطای ترجمه‌نشدهٔ اینستاگرام: %s", exc)
    return InstagramError("instagram_failed", str(exc)[:200])


def is_available() -> bool:
    """آیا ابزار فرو گرفتن در دسترس است."""
    try:
        import yt_dlp  # noqa: F401
    except ImportError:
        return False
    return True


def version() -> str | None:
    try:
        import yt_dlp

        return getattr(yt_dlp.version, "__version__", None)
    except ImportError:
        return None
