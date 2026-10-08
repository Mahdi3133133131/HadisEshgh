"""
نامِ فینگلیش را به مداحِ شناخته‌شده می‌رساند.

## چرا «رساندن»، نه «برگرداندن»

برگرداندنِ فینگلیشِ دلخواه به فارسیِ درست شدنی نیست: «morteza»
می‌تواند «مرتضی» یا «مرتضا» باشد، و املای فینگلیش هیچ قاعدهٔ
ثابتی ندارد — همان نام را ده نفر ده جور می‌نویسند.

ولی کارِ ما آسان‌تر است: نمی‌خواهیم فارسیِ درست **بسازیم**،
می‌خواهیم بفهمیم کدام مداحِ **شناخته‌شده** مقصود بوده. و برای
این، تنها باید دو نگارش را به یک کلیدِ مشترک برسانیم و
نزدیک‌ترین را بگیریم.

## کلید آوایی

واکه‌ها ناپایدارترین بخشِ هر دو نگارش‌اند (کریمی/karimi/kareemi)،
پس دور ریخته می‌شوند و تنها اسکلتِ همخوان‌ها می‌ماند:

    مرتضی یبرنژاد   →  mrtzybrnzhd
    morteza yebovkzhad →  mrtzybvkzhd

که به‌قدر کافی نزدیک‌اند تا با سنجهٔ شباهت یکی شمرده شوند.

## چرا واژه‌به‌واژه هم سنجیده می‌شود

«Borna» تنها نامِ خانوادگی است، و با «رسول برنا» در کل رشته
شباهتِ کمی دارد. ولی واژه‌اش با واژهٔ «برنا» دقیقاً یکی است. پس
هر دو سنجه گرفته می‌شود و بهترین برنده است.
"""

from __future__ import annotations

import logging
import re
from difflib import SequenceMatcher

logger = logging.getLogger(__name__)

# ── نگاشت فارسی به اسکلتِ همخوان ─────────────────────────────
#
# حرف‌هایی که یک آوا دارند به یک نشانه می‌روند: ت و ط هر دو t،
# س و ص و ث هر سه s. چون فینگلیش‌نویس هم همین را می‌شنود و
# می‌نویسد.
_PERSIAN_MAP = {
    "ا": "", "آ": "", "أ": "", "إ": "", "ء": "", "ع": "", "ئ": "", "ؤ": "",
    "ب": "b", "پ": "p",
    "ت": "t", "ط": "t",
    "ث": "s", "س": "s", "ص": "s",
    "ج": "j", "چ": "c",
    "ح": "h", "ه": "h",
    "خ": "x",
    "د": "d",
    "ذ": "z", "ز": "z", "ض": "z", "ظ": "z",
    "ر": "r",
    "ژ": "g",
    "ش": "$",
    "غ": "q", "ق": "q",
    "ف": "f",
    "ک": "k", "ك": "k",
    "گ": "g",
    "ل": "l",
    "م": "m",
    "ن": "n",
    "و": "v",
    "ی": "y", "ي": "y",
    "ة": "h",
}

# ── نگاشت لاتین ─────────────────────────────────────────────
#
# دونویسه‌ها نخست، وگرنه «kh» دو حرفِ جدا خوانده می‌شد.
_LATIN_DIGRAPHS = (
    ("kh", "x"), ("gh", "q"), ("ch", "c"), ("sh", "$"), ("zh", "g"),
    ("ph", "f"), ("th", "s"), ("aa", ""), ("ee", ""), ("oo", "v"),
    ("ou", "v"), ("ei", ""), ("ai", ""), ("ay", ""),
)
_LATIN_MAP = {
    # ── چرا i به y می‌رود و نه به هیچ ──────────────────────
    #
    # در فارسی «ی» هم همخوان است هم واکهٔ بلند، و در اسکلت
    # می‌ماند. اگر لاتینِ همتایش (i) دور ریخته شود، دو نگارشِ یک
    # نام از هم می‌پاشند:
    #
    #     کیانی  -> kyny      ولی  kiani -> kn      ✗
    #
    # با این نگاشت، هر دو «kyny» می‌شوند.
    "a": "", "e": "", "i": "y", "o": "", "u": "",
    "b": "b", "c": "k", "d": "d", "f": "f", "g": "g", "h": "h",
    "j": "j", "k": "k", "l": "l", "m": "m", "n": "n", "p": "p",
    "q": "q", "r": "r", "s": "s", "t": "t", "v": "v", "w": "v",
    "x": "x", "y": "y", "z": "z",
}

_NOISE = re.compile(r"[^\w\s؀-ۿ]+", re.UNICODE)
_SPACES = re.compile(r"\s+")

# نویسه‌هایی که در نام مداح معنا ندارند و از نام فایل می‌آیند.
_JUNK_WORDS = {
    "upmusic", "music", "mp3", "download", "ir", "com", "www",
    "official", "new", "full", "hq", "128", "320",
}


def is_latin(text: str) -> bool:
    """آیا این نوشته بیشتر لاتین است."""
    letters = [ch for ch in text if ch.isalpha()]
    if not letters:
        return False
    latin = sum(1 for ch in letters if ch.isascii())
    return latin > len(letters) / 2


def skeleton(text: str) -> str:
    """
    اسکلتِ آوایی — کلیدی که دو نگارش را به هم می‌رساند.

    فارسی و لاتین هر دو به یک فضا می‌روند، پس مستقیم قابل
    سنجش‌اند.
    """
    if not text:
        return ""
    text = _NOISE.sub(" ", text.lower())
    text = _SPACES.sub(" ", text).strip()

    out: list[str] = []
    for word in text.split():
        if word in _JUNK_WORDS:
            continue
        if word.isascii():
            piece = word
            for digraph, replacement in _LATIN_DIGRAPHS:
                piece = piece.replace(digraph, replacement)
            out.append("".join(_LATIN_MAP.get(ch, "") for ch in piece))
        else:
            # ── «ی» پایانی، واکه است نه همخوان ─────────────
            #
            # «مرتضی» را morteza می‌نویسند، نه mortezay — آن ی
            # صدای «ا» می‌دهد. نگه داشتنش، اسکلتِ فارسی را از
            # فینگلیشش دور می‌کرد.
            plain = word[:-1] if len(word) > 2 and word[-1] in "یي" else word
            out.append("".join(_PERSIAN_MAP.get(ch, "") for ch in plain))
    return "".join(out)


def word_skeletons(text: str) -> list[str]:
    """اسکلتِ هر واژه، جدا — برای تطبیقِ نامِ خانوادگیِ تنها."""
    if not text:
        return []
    text = _NOISE.sub(" ", text.lower())
    out: list[str] = []
    for word in _SPACES.sub(" ", text).strip().split():
        if word in _JUNK_WORDS:
            continue
        key = skeleton(word)
        if len(key) >= 2:
            out.append(key)
    return out


def similarity(first: str, second: str) -> float:
    """شباهتِ دو اسکلت، میان ۰ و ۱."""
    if not first or not second:
        return 0.0
    return SequenceMatcher(None, first, second).ratio()


# زیر این شباهت، سخنی از یکی بودن نیست.
#
# سنجیده بر روی نام‌های راستینِ گنجینه: نگارش‌های گوناگونِ یک نام
# بالای ۰٫۸ می‌مانند و نام‌های جدا زیر ۰٫۶ می‌افتند.
MIN_WHOLE = 0.80

# برای تطبیقِ یک واژه (نامِ خانوادگیِ تنها) سخت‌گیرتر، چون یک
# واژه آگاهیِ کمتری دارد و آسان‌تر تصادفی می‌خواند.
MIN_WORD = 0.90


def match_name(text: str, candidates: dict[str, str]) -> tuple[str, float] | None:
    """
    نزدیک‌ترین مداحِ شناخته‌شده به این نوشته.

    آرگومان‌ها:
        text: نگارشی که یافته‌ایم — فینگلیش، ناقص، یا بدنوشته.
        candidates: نامِ نمایشی ← همان (از `known_madahs`).

    بازگشتی: (نامِ درست، شباهت) یا None.
    """
    if not text or not candidates:
        return None

    probe = skeleton(text)
    probe_words = word_skeletons(text)
    if len(probe) < 3:
        return None

    best: tuple[str, float] | None = None
    for display in candidates.values():
        target = skeleton(display)
        if len(target) < 3:
            continue

        score = similarity(probe, target)

        # ── واژه‌به‌واژه، ولی تنها برای نامِ تک‌واژه‌ای ──────
        #
        # «Borna» تنها نامِ خانوادگی است و در سنجشِ کلِ رشته با
        # «رسول برنا» گم می‌شود؛ واژه‌اش ولی دقیق می‌خواند.
        #
        # ═══════════════════════════════════════════════════
        #   چرا تنها تک‌واژه — این یک باگِ راستین بود
        # ═══════════════════════════════════════════════════
        #
        # نخست این پله برای هر ورودی‌ای اجرا می‌شد، و آزمونِ دود
        # گرفتش: «مهدی رسولی» به «رسول برنا» رسانده می‌شد!
        #
        #     رسولی -> rsvl        رسول -> rsvl        یکی
        #
        # یک واژهٔ مشترک، دو نامِ یکسره جدا را یکی می‌کرد. با
        # نامِ چندواژه‌ای، کلِ رشته آگاهیِ بس دارد و نیازی به این
        # پله نیست؛ تنها آنجا که ورودی یک واژه بیشتر نیست —
        # یعنی راستی نامِ خانوادگیِ تنها — به کارش می‌آید.
        if len(probe_words) == 1:
            probe_word = probe_words[0]
            for target_word in word_skeletons(display):
                if len(probe_word) < 3 or len(target_word) < 3:
                    continue
                if similarity(probe_word, target_word) >= MIN_WORD:
                    score = max(score, MIN_WHOLE + 0.01)

        if best is None or score > best[1]:
            best = (display, score)

    if best is None or best[1] < MIN_WHOLE:
        return None
    return best
