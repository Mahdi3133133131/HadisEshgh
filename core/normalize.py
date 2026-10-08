"""
هنجارسازی متن پارسی.

بدون این لایه، جست‌وجوی متنی روی نام مداح از کار می‌افتد؛ چون یک نام
به چند شکل نوشته می‌شود: «حاج محمود کریمي» و «حاج محمود کریمی» و
«حاج‌محمود کریمی» از دید پایگاه داده سه رشتهٔ جداگانه‌اند.

قاعده: هر چیزی که پیش از ذخیره یا جست‌وجو در ستون‌های *_norm می‌رود،
باید از normalize() گذشته باشد. متن اصلی دست‌نخورده در ستون خودش
می‌ماند و همان به کاربر نشان داده می‌شود.

نکته: نویسه‌های نامرئی و اعراب در سراسر این پرونده با کد صریح
(\\uXXXX) نوشته شده‌اند، نه با شکل خام؛ چون شکل خام در ویرایشگر
دیده نمی‌شود و ویرایش بعدی را خطاخیز می‌کند.
"""

from __future__ import annotations

import re
import unicodedata

# ── نویسه‌های عربی که همتای پارسی دارند ──────────────────────
_CHAR_MAP = {
    "ي": "ی",  # ي عربی    → ی پارسی
    "ى": "ی",  # ى مقصوره  → ی پارسی
    "ك": "ک",  # ك عربی    → ک پارسی
    "ة": "ه",  # ة تاء مربوطه → ه
    "أ": "ا",  # أ → ا
    "إ": "ا",  # إ → ا
    "آ": "ا",  # آ → ا
    "ٱ": "ا",  # ٱ → ا
    "ؤ": "و",  # ؤ → و
    "ئ": "ی",  # ئ → ی
}

# ── ارقام پارسی و عربی → ارقام لاتین ─────────────────────────
_DIGIT_MAP = {
    **{chr(0x06F0 + i): str(i) for i in range(10)},  # ۰-۹ پارسی
    **{chr(0x0660 + i): str(i) for i in range(10)},  # ٠-٩ عربی
}

# ── اعراب، کشیدگی و نشانه‌های نامرئی که باید حذف شوند ────────
_STRIP_CHARS = (
    "ًٌٍ"  # تنوین: ً ٌ ٍ
    "َُِ"  # فتحه، ضمه، کسره
    "ّْ"        # تشدید، سکون
    "ٕٓٔ"  # مد، همزهٔ بالا، همزهٔ پایین
    "ٰ"              # الف کوتاه
    "ـ"              # کشیدگی (تطویل)
    "​"              # فاصلهٔ بی‌پهنا
    "‍"              # پیوندگر بی‌پهنا
    "‎‏"        # نشانگر جهت چپ‌به‌راست و راست‌به‌چپ
    "﻿"              # نشانگر ترتیب بایت
)
_STRIP_RE = re.compile(f"[{re.escape(_STRIP_CHARS)}]")

_TRANSLATION = str.maketrans({**_CHAR_MAP, **_DIGIT_MAP})

# نگاشت نمایش: تنها نویسه‌های عربی که همتای پارسی‌شان هم‌معناست.
# «آ» و «ة» و همزه‌ها اینجا نیستند، چون یکسان‌سازی‌شان معنا را
# دگرگون می‌کند و در نمایش به چشم می‌آید.
_DISPLAY_CHAR_MAP = {
    "ي": "ی",
    "ى": "ی",
    "ك": "ک",
}
_DISPLAY_TRANSLATION = str.maketrans({**_DISPLAY_CHAR_MAP, **_DIGIT_MAP})

# هر چیزی جز حرف، رقم، فاصله و محدودهٔ نویسه‌های عربی/پارسی
_PUNCT_RE = re.compile(r"[^\w؀-ۿ\s]", re.UNICODE)
_SPACE_RE = re.compile(r"\s+")

ZWNJ = "‌"  # نیم‌فاصله


def fix_characters(text: str) -> str:
    """
    نویسه‌های عربی را به همتای پارسی و ارقام را به لاتین برمی‌گرداند،
    ولی نیم‌فاصله و نشانه‌گذاری را نگه می‌دارد.

    این تابع برای متنی است که قرار است **به کاربر نشان داده شود**
    یا در برچسب فایل نوشته شود — نه برای کلید جست‌وجو.
    """
    if not text:
        return ""
    text = unicodedata.normalize("NFC", text)
    text = _STRIP_RE.sub("", text)
    return text.translate(_TRANSLATION)


# نام‌هایی که در خانهٔ «هنرمند» یا «نام» می‌نشینند ولی چیزی
# نمی‌گویند.
#
# ## چرا این فهرست هست
#
# فایلی که خودِ ما برچسب زده‌ایم، اگر روزی به ربات بازگردد، همان
# نامی را با خود می‌آورد که ما رویش نوشته‌ایم — و نامِ برند به
# جای نام مداح در پایگاه داده می‌نشیند؛ حلقه‌ای که خودش را
# می‌خوراند. برچسب‌زن‌های خودکار هم جای خالی را با
# «Unknown Artist» و مانند آن پر می‌کنند.
_EMPTY_TAGS = frozenset(
    {
        "حدیث عشق",
        "نامعلوم",
        "نامشخص",
        "بی‌نام",
        "بی نام",
        "unknown",
        "unknown artist",
        "unknown album",
        "<unknown>",
        "various artists",
        "va",
        "track",
        "audio",
        "untitled",
        "new recording",
    }
)

# نامی که پیداست نامِ پرونده است نه نامِ مداحی: voice_0032،
# audio1404، track 07، AUD-20240110-WA0001 و مانند آن.
_FILENAME_LIKE = re.compile(
    r"^(?:voice|audio|aud|rec|record(?:ing)?|track|file|video|vid|new)"
    r"[\s_\-]*\d*$",
    re.IGNORECASE,
)


def clean_tag(value: str | None, limit: int = 200) -> str | None:
    """
    مقدارِ یک خانهٔ برچسب، اگر راستی چیزی بگوید.

    تهی، یا یکی از نام‌های پوچِ بالا، یا نامی که تنها شکلِ نامِ
    پرونده است — همه None می‌دهند. پس فراخوان می‌داند که این خانه
    را نمی‌داند، به جای آنکه زباله را به چشمِ داده ببیند.
    """
    name = (fix_characters(value or "") or "").strip()
    if not name:
        return None

    folded = name.casefold()
    if folded in _EMPTY_TAGS or _FILENAME_LIKE.match(name):
        return None

    # نامی که هیچ حرفی ندارد (تنها عدد و نشانه) نام نیست.
    if not re.search(r"[^\W\d_]", name, re.UNICODE):
        return None

    return name[:limit]


def fix_display(text: str) -> str:
    """
    نویسه‌های عربی را به همتای پارسی برمی‌گرداند، ولی تنها آنجا که
    معنا را دگرگون نمی‌کند.

    تفاوتش با fix_characters این است که «آ» را به «ا» نمی‌نگارد و
    «ة» را به «ه» برنمی‌گرداند. آن نگاشت‌ها برای تطبیق سودمندند —
    تا «كريمي» و «کریمی» یکی شمرده شوند — ولی برای نمایش نادرستند:
    «آب» نباید «اب» نوشته شود.

    هر جا که نوشتار قرار است به چشم کاربر برسد (جلد نوا، برچسب
    فایل)، همین تابع باید به کار رود، نه fix_characters.
    """
    if not text:
        return ""
    text = unicodedata.normalize("NFC", text)
    text = _STRIP_RE.sub("", text)
    return text.translate(_DISPLAY_TRANSLATION)


def normalize(text: str) -> str:
    """
    شکل هنجارِ جست‌وجو می‌سازد: بی‌اعراب، بی‌نشانه‌گذاری،
    نیم‌فاصله تبدیل به فاصله، فاصله‌های پیاپی یکی شده، کوچک‌شده.

    خروجی این تابع تنها برای تطبیق است و هرگز به کاربر نشان داده نمی‌شود.

    >>> normalize("حاج‌محمود  كريمي")
    'حاج محمود کریمی'
    """
    if not text:
        return ""
    text = fix_characters(text)
    text = text.replace(ZWNJ, " ")
    text = _PUNCT_RE.sub(" ", text)
    text = _SPACE_RE.sub(" ", text)
    return text.strip().lower()


def to_persian_digits(text: str) -> str:
    """ارقام لاتین را به پارسی برمی‌گرداند — برای نمایش به کاربر."""
    return text.translate(str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹"))


def format_duration(seconds: int | None) -> str:
    """مدت زمان را به شکل خوانا و با ارقام پارسی برمی‌گرداند."""
    if not seconds or seconds < 0:
        return "نامعلوم"
    minutes, secs = divmod(int(seconds), 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        raw = f"{hours}:{minutes:02d}:{secs:02d}"
    else:
        raw = f"{minutes}:{secs:02d}"
    return to_persian_digits(raw)


def format_size(num_bytes: int | None) -> str:
    """اندازهٔ فایل را به شکل خوانا و با ارقام پارسی برمی‌گرداند."""
    if not num_bytes or num_bytes < 0:
        return "نامعلوم"
    units = ("بایت", "کیلوبایت", "مگابایت", "گیگابایت")
    size = float(num_bytes)
    index = 0
    while size >= 1024 and index < len(units) - 1:
        size /= 1024
        index += 1
    raw = f"{size:.0f}" if index == 0 else f"{size:.1f}"
    return f"{to_persian_digits(raw)} {units[index]}"


# ═════════════════════════════════════════════════════════════
#  چینش الفبایی فارسی
# ═════════════════════════════════════════════════════════════

# ── چرا این بایسته شد ────────────────────────────────────────
#
# مرتب‌سازی پیش‌فرضِ پایتون بر کدِ یونیکد است، و آن برای فارسی
# غلط درمی‌آید. روی مداحانِ راستینِ گنجینه آزمودم:
#
#     انتظار : الف، بهار، پیام، تقی، چاوش، حسین، ژاله، …
#     پایتون : الف، بهار، تقی، حسین، پیام، چاوش، ژاله، …
#
# ریشه‌اش این است که حرف‌های ویژهٔ فارسی (پ چ ژ گ ک ی) در بلوکِ
# دیگری از یونیکد نشسته‌اند — پ در U+067E و ح در U+062D — پس
# «پیام» پس از «حسین» می‌افتد. چاره، نگاشتنِ هر حرف به جایگاهِ
# راستینش در الفباست.
_ALPHABET = "ابپتثجچحخدذرزژسشصضطظعغفقکگلمنوهی"
_ALPHA_RANK = {letter: index for index, letter in enumerate(_ALPHABET)}

# حرف‌هایی که `normalize` یکسانشان نمی‌کند ولی در چینش باید کنارِ
# خویشاوندشان بنشینند.
_ALPHA_RANK.update({
    "آ": _ALPHA_RANK["ا"],
    "أ": _ALPHA_RANK["ا"],
    "إ": _ALPHA_RANK["ا"],
    "ئ": _ALPHA_RANK["ی"],
    "ؤ": _ALPHA_RANK["و"],
    "ء": _ALPHA_RANK["ا"],
    "ة": _ALPHA_RANK["ه"],
    "ك": _ALPHA_RANK["ک"],
    "ي": _ALPHA_RANK["ی"],
})

# ناشناخته‌ها — رقم، حرف لاتین، نشانه — پس از همهٔ حرف‌های فارسی.
_UNKNOWN_RANK = len(_ALPHABET) + 1


def persian_key(name: str | None) -> tuple:
    """
    کلیدِ چینشِ الفبایی فارسی.

    ## اجرای مشترک، در آخر

    نامی که با «،» یا «و» چند مداح را کنار هم آورده — مانند
    «حسین طاهری ، محمد حسین حدادیان» — یک نفر نیست. چنین نام‌هایی
    ته فهرست می‌روند، و آنجا خودشان الفبایی چیده می‌شوند.

    گروهِ ۰ تک‌مداح، گروهِ ۱ اجرای مشترک، گروهِ ۲ نامِ تهی.

    >>> persian_key("پیام") < persian_key("تقی")
    True
    """
    if not name or not name.strip():
        return (2, ())

    text = fix_characters(name).strip()
    group = 1 if ("،" in text or "," in text) else 0

    ranks = []
    for char in text:
        if char.isspace():
            continue
        rank = _ALPHA_RANK.get(char)
        ranks.append(_UNKNOWN_RANK if rank is None else rank)
    return (group, tuple(ranks))
