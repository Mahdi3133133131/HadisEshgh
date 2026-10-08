"""
برچسب‌گذاری نوا و ساختن جلد.

سند خواسته بود: «امکان داره فایل صوتی داخل دیتابیس تیکه‌ای از صوت
توش نوشته بشه و اسم مداح هم باشه توش همه به فارسی، بعد لوگو کانال
هم که تو پوشه هست اونم عکس مداحی باشه.»

پس دو کار اینجا انجام می‌شود:

۱. **برچسب ID3** — نام مداح، عنوان، سبک و بیتی از متن در خود فایل
   نوشته می‌شود. پس هر جا که فایل برود، شناسنامه‌اش با اوست.

۲. **جلد** — لوگوی کانال با نام مداح و بیتی از نوا روی آن، به
   عنوان تصویر فایل نشانده می‌شود.

## دشواری نوشتار پارسی روی تصویر

Pillow حروف پارسی را جدا جدا و از چپ به راست می‌کشد؛ «سلام» به
شکل «م ا ل س» درمی‌آید. دو کار باید انجام شود:

  • **شکل‌دهی**: هر حرف بسته به جایش (آغاز، میان، پایان، تنها)
    شکل دیگری دارد و باید به همان ریخت درآید.
  • **وارونه‌سازی**: ترتیب نمایش باید از راست به چپ شود.

کتابخانهٔ python-bidi وارونه‌سازی را انجام می‌دهد. شکل‌دهی را
خودمان با جدولی از ریخت‌های یونیکد انجام می‌دهیم تا وابستگی
تازه‌ای (arabic-reshaper) نیفزاییم.
"""

from __future__ import annotations

import logging
from pathlib import Path

from core.normalize import fix_display

logger = logging.getLogger(__name__)

# ── ریخت‌های چهارگانهٔ هر حرف ────────────────────────────────
# (تنها، آغازین، میانی، پایانی) — None یعنی آن ریخت را ندارد.
# حرف‌هایی که تنها دو ریخت دارند (مانند «ا» و «د»)، به حرف پس از
# خود نمی‌چسبند؛ در جدول با None در جای آغازین و میانی نشان
# داده شده‌اند.
_FORMS: dict[str, tuple[str, str | None, str | None, str]] = {
    "ا": ("ا", None, None, "ﺎ"),
    "آ": ("آ", None, None, "ﺂ"),
    "ب": ("ب", "ﺑ", "ﺒ", "ﺐ"),
    "پ": ("پ", "ﭘ", "ﭙ", "ﭗ"),
    "ت": ("ت", "ﺗ", "ﺘ", "ﺖ"),
    "ث": ("ث", "ﺛ", "ﺜ", "ﺚ"),
    "ج": ("ج", "ﺟ", "ﺠ", "ﺞ"),
    "چ": ("چ", "ﭼ", "ﭽ", "ﭻ"),
    "ح": ("ح", "ﺣ", "ﺤ", "ﺢ"),
    "خ": ("خ", "ﺧ", "ﺨ", "ﺦ"),
    "د": ("د", None, None, "ﺪ"),
    "ذ": ("ذ", None, None, "ﺬ"),
    "ر": ("ر", None, None, "ﺮ"),
    "ز": ("ز", None, None, "ﺰ"),
    "ژ": ("ژ", None, None, "ﮋ"),
    "س": ("س", "ﺳ", "ﺴ", "ﺲ"),
    "ش": ("ش", "ﺷ", "ﺸ", "ﺶ"),
    "ص": ("ص", "ﺻ", "ﺼ", "ﺺ"),
    "ض": ("ض", "ﺿ", "ﻀ", "ﺾ"),
    "ط": ("ط", "ﻃ", "ﻄ", "ﻂ"),
    "ظ": ("ظ", "ﻇ", "ﻈ", "ﻆ"),
    "ع": ("ع", "ﻋ", "ﻌ", "ﻊ"),
    "غ": ("غ", "ﻏ", "ﻐ", "ﻎ"),
    "ف": ("ف", "ﻓ", "ﻔ", "ﻒ"),
    "ق": ("ق", "ﻗ", "ﻘ", "ﻖ"),
    "ک": ("ک", "ﮐ", "ﮑ", "ﮏ"),
    "گ": ("گ", "ﮔ", "ﮕ", "ﮓ"),
    "ل": ("ل", "ﻟ", "ﻠ", "ﻞ"),
    "م": ("م", "ﻣ", "ﻤ", "ﻢ"),
    "ن": ("ن", "ﻧ", "ﻨ", "ﻦ"),
    "و": ("و", None, None, "ﻮ"),
    "ه": ("ه", "ﻫ", "ﻬ", "ﻪ"),
    "ی": ("ی", "ﯾ", "ﯿ", "ﯽ"),
    "ء": ("ء", None, None, "ء"),
}

# «لام‌الف» در پارسی یک نشانهٔ به‌هم‌پیوسته است و اگر جدا کشیده
# شود، به چشم خواننده ناخوش می‌آید.
_LAM_ALEF = {"لا": ("ﻻ", "ﻼ"), "لآ": ("ﻵ", "ﻶ")}


def _connects_forward(char: str) -> bool:
    """آیا این حرف به حرف پس از خود می‌چسبد."""
    forms = _FORMS.get(char)
    return bool(forms and forms[1] is not None)


def _connects_backward(char: str) -> bool:
    """آیا این حرف از حرف پیش از خود پیوند می‌گیرد."""
    return char in _FORMS


def reshape(text: str) -> str:
    """
    هر حرف را به ریخت درستش درمی‌آورد.

    بی این کار، Pillow حروف را جدا جدا می‌کشد و نوشتار پارسی
    ناخوانا می‌شود.
    """
    if not text:
        return ""

    text = fix_display(text)
    output: list[str] = []
    index = 0
    length = len(text)

    while index < length:
        char = text[index]

        # لام‌الف
        if char == "ل" and index + 1 < length:
            pair = text[index : index + 2]
            if pair in _LAM_ALEF:
                prev = text[index - 1] if index else ""
                joined = bool(prev) and _connects_forward(prev)
                output.append(_LAM_ALEF[pair][1 if joined else 0])
                index += 2
                continue

        forms = _FORMS.get(char)
        if forms is None:
            output.append(char)
            index += 1
            continue

        prev = text[index - 1] if index else ""
        nxt = text[index + 1] if index + 1 < length else ""

        # پیوند از پیش، تنها آنگاه که حرف پیشین رو به جلو می‌چسبد
        from_prev = bool(prev) and _connects_forward(prev)
        # پیوند به پس، تنها آنگاه که حرف پسین پیوند می‌گیرد
        to_next = bool(nxt) and _connects_backward(nxt) and forms[1] is not None

        if from_prev and to_next:
            output.append(forms[2] or forms[0])
        elif from_prev:
            output.append(forms[3])
        elif to_next:
            output.append(forms[1] or forms[0])
        else:
            output.append(forms[0])

        index += 1

    return "".join(output)


def prepare_persian(text: str) -> str:
    """
    نوشتار پارسی را برای کشیدن روی تصویر آماده می‌کند:
    شکل‌دهی، سپس وارونه‌سازی راست‌به‌چپ.
    """
    shaped = reshape(text)
    try:
        from bidi.algorithm import get_display

        return get_display(shaped)
    except ImportError:
        # بی python-bidi، دست‌کم وارونه‌سازی ساده انجام شود
        logger.debug("python-bidi نیست؛ وارونه‌سازی ساده به کار رفت.")
        return shaped[::-1]


# ═════════════════════════════════════════════════════════════
#  جلد
# ═════════════════════════════════════════════════════════════

COVER_SIZE = 640
_FONT_CANDIDATES = (
    "C:/Windows/Fonts/tahoma.ttf",
    "C:/Windows/Fonts/tahomabd.ttf",
    "C:/Windows/Fonts/arial.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
)


def _find_font(size: int):
    from PIL import ImageFont

    for candidate in _FONT_CANDIDATES:
        path = Path(candidate)
        if path.exists():
            try:
                return ImageFont.truetype(str(path), size)
            except OSError:
                continue
    logger.warning("هیچ فونتی یافت نشد؛ فونت پیش‌فرض به کار می‌رود.")
    return ImageFont.load_default()


def make_cover(
    madah: str | None = None,
    title: str | None = None,
    lyrics: str | None = None,
    logo_path: str | Path | None = None,
    output: str | Path | None = None,
) -> Path | None:
    """
    جلد نوا را می‌سازد: لوگو در بالا، نام مداح، و بیتی از نوا.

    اگر لوگویی نباشد، پس‌زمینه‌ای شیب‌دار کشیده می‌شود تا جلد
    همچنان آبرومند بماند.
    """
    from PIL import Image, ImageDraw, ImageFilter

    canvas = Image.new("RGB", (COVER_SIZE, COVER_SIZE), (12, 26, 22))
    draw = ImageDraw.Draw(canvas)

    # ── پس‌زمینهٔ شیب‌دار ────────────────────────────────────
    for y in range(COVER_SIZE):
        ratio = y / COVER_SIZE
        draw.line(
            [(0, y), (COVER_SIZE, y)],
            fill=(
                int(12 + 22 * ratio),
                int(38 + 30 * ratio),
                int(32 + 26 * ratio),
            ),
        )

    # ── لوگو ────────────────────────────────────────────────
    if logo_path and Path(logo_path).exists():
        try:
            logo = Image.open(logo_path).convert("RGBA")
            box = int(COVER_SIZE * 0.34)
            logo.thumbnail((box, box), Image.LANCZOS)
            position = ((COVER_SIZE - logo.width) // 2, int(COVER_SIZE * 0.10))
            canvas.paste(logo, position, logo)
        except Exception as exc:  # noqa: BLE001
            logger.warning("نشاندن لوگو شکست خورد: %s", exc)

    # ── نوشتارها ────────────────────────────────────────────
    def centered(text: str, y: int, size: int, fill=(255, 255, 255)) -> int:
        if not text:
            return y
        font = _find_font(size)
        prepared = prepare_persian(text)
        left, top, right, bottom = draw.textbbox((0, 0), prepared, font=font)
        width = right - left
        x = (COVER_SIZE - width) // 2
        # سایهٔ نرم، تا نوشتار روی هر پس‌زمینه‌ای خوانا بماند
        draw.text((x + 2, y + 2), prepared, font=font, fill=(0, 0, 0))
        draw.text((x, y), prepared, font=font, fill=fill)
        return y + (bottom - top) + int(size * 0.5)

    cursor = int(COVER_SIZE * 0.50)
    if madah:
        cursor = centered(madah, cursor, 44, (255, 246, 214))
    if title:
        cursor = centered(_shorten(title, 34), cursor, 30, (214, 232, 222))
    if lyrics:
        cursor += 10
        for line in _wrap(lyrics, 30)[:2]:
            cursor = centered(line, cursor, 24, (186, 210, 198))

    # ── نام گنجینه، پایین ───────────────────────────────────
    font = _find_font(22)
    brand = prepare_persian("حدیث عشق")
    left, top, right, bottom = draw.textbbox((0, 0), brand, font=font)
    draw.text(
        ((COVER_SIZE - (right - left)) // 2, COVER_SIZE - 60),
        brand, font=font, fill=(150, 180, 165),
    )

    destination = Path(output) if output else Path("cover.jpg")
    destination.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(destination, "JPEG", quality=88)
    return destination


def _shorten(text: str, limit: int) -> str:
    text = text.strip()
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _wrap(text: str, width: int) -> list[str]:
    """نوشتار را بر پایهٔ واژه‌ها می‌شکند، نه میان حرف‌ها."""
    words = text.split()
    lines: list[str] = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if len(candidate) <= width:
            current = candidate
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


# ═════════════════════════════════════════════════════════════
#  برچسب ID3
# ═════════════════════════════════════════════════════════════

def tag_audio(
    path: str | Path,
    madah: str | None = None,
    title: str | None = None,
    style: str | None = None,
    lyrics: str | None = None,
    cover: str | Path | None = None,
    source_label: str | None = None,
    source_url: str | None = None,
    track_number: int | None = None,
) -> bool:
    """
    برچسب ID3 را در فایل می‌نویسد.

    بازگشتی: آیا کامیاب بود. ناکامی، خطا نمی‌پراند — نوا باید
    فرستاده شود حتی اگر برچسب‌گذاری نگرفت.

    ## نشانِ سرچشمه

    نوایی که از تارنمای دیگری آمده باید نامِ همان تارنما و نشانی
    صفحه‌اش را با خود ببرد. سه جا نوشته می‌شود: نام آلبوم، یادداشت،
    و فریم‌های WOAS/WOAF که خودِ استاندارد ID3 برای «سرچشمهٔ رسمی»
    و «نشانی فایل» گذاشته است. پس هر کس فایل را با هر پخش‌کننده‌ای
    بگشاید، می‌بیند از کجا آمده.
    """
    from mutagen.id3 import (
        APIC,
        COMM,
        ID3,
        TALB,
        TCON,
        TIT2,
        TPE1,
        TRCK,
        USLT,
        WOAF,
        WOAS,
        ID3NoHeaderError,
    )

    path = Path(path)
    try:
        try:
            tags = ID3(path)
        except ID3NoHeaderError:
            tags = ID3()

        if title:
            tags["TIT2"] = TIT2(encoding=3, text=fix_display(title))
        if madah:
            tags["TPE1"] = TPE1(encoding=3, text=fix_display(madah))
        if style:
            tags["TCON"] = TCON(encoding=3, text=fix_display(style))

        # ── آلبوم: شناسهٔ خودِ ربات ─────────────────────────
        #
        # هرکه این فایل را در هر پخش‌کننده‌ای بگشاید، در خانهٔ
        # «آلبوم» می‌بیند از کجا آمده و کجا می‌تواند بازش جوید.
        # اگر نامِ ربات هنوز دانسته نشده (پیش از نخستین برخاستن)،
        # نام برند جایش می‌نشیند.
        album = _album_name()
        tags["TALB"] = TALB(encoding=3, text=album)

        if source_label:
            note = f"سرچشمه: {source_label}"
            if source_url:
                note = f"{note} — {source_url}"
            tags["COMM"] = COMM(encoding=3, lang="fas", desc="", text=note)
        else:
            tags["COMM"] = COMM(
                encoding=3, lang="fas", desc="", text=f"آرشیو مداحی — {album}"
            )

        # شمارهٔ نوا در آرشیو. در خانهٔ «Track number» می‌نشیند و
        # همان عددی است که با /delete و /sites و گزارش‌ها کار
        # می‌کند — پس از روی فایل هم می‌شود به آن رسید.
        if track_number:
            tags["TRCK"] = TRCK(encoding=3, text=str(track_number))

        if source_url:
            tags["WOAS"] = WOAS(url=source_url)
            tags["WOAF"] = WOAF(url=source_url)

        if lyrics:
            tags["USLT"] = USLT(
                encoding=3, lang="fas", desc="", text=fix_display(lyrics)
            )

        if cover and Path(cover).exists():
            tags["APIC"] = APIC(
                encoding=3,
                mime="image/jpeg",
                type=3,          # جلد رویین
                desc="Cover",
                data=Path(cover).read_bytes(),
            )

        tags.save(path, v2_version=3)
        return True

    except Exception as exc:  # noqa: BLE001
        logger.warning("برچسب‌گذاری «%s» شکست خورد: %s", path.name, exc)
        return False


def tag_with_cover(
    path: str | Path,
    madah: str | None = None,
    title: str | None = None,
    style: str | None = None,
    lyrics: str | None = None,
    logo_path: str | Path | None = None,
    source_label: str | None = None,
    source_url: str | None = None,
    track_number: int | None = None,
) -> bool:
    """
    جلد را می‌سازد و همراه برچسب در فایل می‌نشاند.

    درگاه آسانی برای هنگامی که نوایی تازه به گنجینه می‌آید.
    """
    from config import config

    cover = None
    try:
        cover = make_cover(
            madah=madah, title=title, lyrics=lyrics,
            logo_path=logo_path or _default_logo(),
            output=config.tmp_dir / f"cover_{Path(path).stem}.jpg",
        )
        return tag_audio(
            path, madah, title, style, lyrics, cover,
            source_label=source_label, source_url=source_url,
            track_number=track_number,
        )
    finally:
        if cover is not None:
            Path(cover).unlink(missing_ok=True)


# شناسهٔ ربات در سراسر یک اجرا ثابت است، پس پرسیدنش از پایگاه
# داده برای هر فایلی که برچسب می‌خورد، رفت‌وآمدی است که پاسخش را
# از پیش می‌دانیم.
_album_cache: str | None = None


def _album_name() -> str:
    """
    نامی که در خانهٔ «آلبوم» می‌نشیند: شناسهٔ خودِ ربات.

    شناسه هنگام برخاستن از تلگرام پرسیده و در تنظیمات نگه داشته
    می‌شود؛ پس اینجا بی هیچ رفت‌وآمد شبکه‌ای در دسترس است. اگر
    هنوز دانسته نشده باشد، نام برند جایش می‌نشیند تا خانه تهی
    نماند.
    """
    global _album_cache
    if _album_cache is not None:
        return _album_cache

    try:
        from core.db.database import get_setting

        username = (get_setting("bot_username", "") or "").lstrip("@")
    except Exception:  # noqa: BLE001
        username = ""

    name = f"@{username}" if username else "حدیث عشق"
    # تا وقتی شناسه دانسته نشده، در حافظه نمی‌ماند: پیش‌پرواز
    # اندکی پس از نخستین برچسب‌ها آن را می‌نشاند و نباید نامِ
    # جایگزین برای همیشه بچسبد.
    if username:
        _album_cache = name
    return name


def audio_labels(track, fallback_title: str | None = None) -> dict:
    """
    خانه‌های «هنرمند» و «نام» برای send_audio تلگرام.

    ## چرا یک جا، و چرا اصلاً

    پنج جای جدا `send_audio` می‌زدند و هر پنج همین دو خط را
    داشتند:

        title=track["title"] or track["madah"] or "نوا"
        performer=track["madah"] or "حدیث عشق"

    و هر دو خط غلط بودند.

    **خانهٔ هنرمند** جای نام مداح است. وقتی مداح دانسته نبود،
    نامِ برند آنجا می‌نشست — و کاربر روی فایل «حدیث عشق» را به
    جای نام مداح می‌دید. اکنون اگر مداح را ندانیم این خانه اصلاً
    فرستاده نمی‌شود؛ خالی ماندنش راست است و نامِ برند در آن،
    دروغ.

    **خانهٔ نام** جای اسم مداحی است. فرو افتادنش به نام مداح یعنی
    همان نام در هر دو خانه تکرار شود — همان که خواسته شد نشود.

    برند از فایل برداشته نشد: روی جلد، پایینِ تصویر، سر جایش
    می‌ماند. آنجا نشان است، نه نامِ هنرمند.
    """

    def _value(key: str) -> str | None:
        try:
            raw = track[key]
        except (KeyError, IndexError, TypeError):
            raw = None
        text = (raw or "").strip()
        return text or None

    madah = _value("madah")
    title = _value("title") or (fallback_title or "").strip() or None

    labels: dict = {"title": (title or "نوا")[:64]}
    if madah:
        labels["performer"] = madah[:64]
    return labels


def _default_logo() -> Path | None:
    """لوگوی کانال، اگر در پوشهٔ assets گذاشته شده باشد."""
    from config import config

    for name in ("logo.png", "logo.jpg", "logo.jpeg"):
        candidate = config.base_dir / "assets" / name
        if candidate.exists():
            return candidate
    return None
