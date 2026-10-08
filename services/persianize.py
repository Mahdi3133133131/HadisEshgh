# -*- coding: utf-8 -*-
"""
نامِ فارسی، همیشه.

═══════════════════════════════════════════════════════════════
  چرا این هست
═══════════════════════════════════════════════════════════════

برچسبِ فایل‌های مداحی، هرچه باشد جز نامِ تمیز است. در گنجینهٔ
راستین این‌ها دیده شد:

    Baz Dobare Tako Tanha ~ UpMusic   ← اسمِ فایلِ لاتین
    کربلایی مرتضی یبرنژاد              ← لقب چسبیده به نام
    شور | ماهم حضرت رضا               ← سبک چسبیده به عنوان
    دلبر ابالفضل / احسان لطفی          ← عنوان و مداح، جدانشده

همین‌ها بودند که در `/madahs` به‌عنوان «مداح» فهرست می‌شدند.

═══════════════════════════════════════════════════════════════
  دو کارِ جدا
═══════════════════════════════════════════════════════════════

**`to_persian`** نگارشِ لاتین را به فارسی برمی‌گرداند. این کار
ذاتاً حدسی است — «a» می‌تواند «ا» یا «آ» باشد و از املای لاتین
درنمی‌آید. پس نتیجه‌اش هرگز خاموش ثبت نمی‌شود؛ در کارتِ شناسنامه
به گرداننده نشان داده می‌شود و ویرایشش همان‌جا ممکن است — و آن
ویرایش، به حافظهٔ نام‌های مستعار می‌رود تا دفعهٔ بعد پرسیده نشود.

**`clean_name`** واژه‌های اضافه را برمی‌دارد. این حدسی نیست:
قاعده‌هایش روشن‌اند و روی همان نمونه‌های بالا سنجیده شده‌اند.

`services/translit.py` کارِ **دیگری** می‌کند و جایش را نمی‌گیرد:
آن نگارشِ ناشناخته را به نامی که **از پیش در گنجینه هست**
می‌رساند. اینجا جایی است که چنین نامی نباشد.
"""

from __future__ import annotations

import itertools
import logging
import re

logger = logging.getLogger(__name__)

# ── دونویسه‌ها، پیش از تک‌حرف‌ها ─────────────────────────────
#
# ترتیب مهم است: اگر «kh» پس از «k» بیاید، «خ» هرگز ساخته نمی‌شود
# و «kh» به «که» بدل می‌شود.
_DIGRAPHS: tuple[tuple[str, str], ...] = (
    ("kh", "خ"), ("gh", "ق"), ("ch", "چ"), ("sh", "ش"), ("zh", "ژ"),
    ("ph", "ف"), ("th", "ت"), ("aa", "ا"), ("ee", "ی"), ("oo", "و"),
    ("ou", "و"), ("ei", "ی"),
)
# «ay» و «ya» و «ie» عمداً نیستند: درونِ واژه هم شلیک می‌کردند و
# «Payam» را «پایم» می‌ساختند. سنجش گفت زیانشان بیش از سودشان است.

# ── همخوان‌ها ───────────────────────────────────────────────
_CONSONANTS: dict[str, str] = {
    "b": "ب", "c": "ک", "d": "د", "f": "ف", "g": "گ", "h": "ه",
    "j": "ج", "k": "ک", "l": "ل", "m": "م", "n": "ن", "p": "پ",
    "q": "ق", "r": "ر", "s": "س", "t": "ت", "v": "و", "w": "و",
    "x": "خ", "y": "ی", "z": "ز",
}

_VOWELS = frozenset("aeiou")

# ── واکه‌ها، و چرا این قاعده‌ها ──────────────────────────────
#
# فارسی واکهٔ کوتاه را نمی‌نویسد و بلند را می‌نویسد؛ ولی فینگلیش
# هر دو را یک‌جور می‌نویسد. پس هر قاعده‌ای اینجا گمانه است، و
# سنجش تنها راهِ برگزیدنشان بود.
#
# روی نمونه‌های راستین (Borna، Morteza، Hosein، Sotude، Mahdi،
# Rasoli، Baz، Tanha) سه گمانه آزموده شد:
#
#   «o همیشه و»  → بورنا، مورتزا، هوسین  ← ۲ از ۶
#   «o هرگز و»   → برنا، مرتضی، حسین     ← ۴ از ۶
#
# پس «o» کوتاه گرفته می‌شود. آنکه راستی بلند است، در فینگلیش
# معمولاً «oo» یا «ou» نوشته می‌شود و دونویسه‌ها می‌گیرندش.
#
# «i» و «u» برعکس: در نامِ فارسی کمابیش همیشه بلندند (ی و و).
_LONG_MID: dict[str, str] = {"i": "ی", "u": "و"}

# واکهٔ پایانی، همیشه نوشته می‌شود.
_FINAL: dict[str, str] = {"a": "ا", "e": "ه", "o": "و", "i": "ی", "u": "و"}

# واکه‌ای که در آغازِ واژه می‌آید، تکیه‌گاه می‌خواهد.
_INITIAL: dict[str, str] = {"a": "ا", "e": "ا", "o": "ا", "i": "ای", "u": "او"}

# زباله‌های نامِ فایل — نه لقب‌اند نه نام.
_JUNK = frozenset({
    "upmusic", "music", "mp3", "mp4", "download", "dl", "ir", "com", "net",
    "org", "www", "official", "new", "full", "hq", "128", "192", "256",
    "320", "kbps", "audio", "song", "track", "final", "original", "remix",
    "nex1music", "beeptunes", "musicdel", "kashoob", "pelan3", "madahi",
    "neynava", "neynavaplus", "radiojavan", "rj", "iranseda", "telegram",
    "channel", "ch", "join", "link", "bot", "exclusive", "single", "album",
})

# نشانه‌گذاری‌هایی که به زباله می‌چسبند و جدا نوشته نمی‌شوند.
_EDGE_PUNCT = " ~-\u2013\u2014_|/\\\u060c,.:;()[]{}<>\"'!?\u061f*#@\u2022"


def _is_junk(token: str) -> bool:
    """
    آیا این پاره زباله است.

    ## چرا سنجهٔ جدا، و نه `token in _JUNK`

    سنجشِ پیشین عضویتِ خام بود، پس تنها زبالهٔ **تنها و بی‌نشانه**
    را می‌گرفت. اینها می‌ماندند:

        musicdel.ir   Nex1Music.com   [320]   ~   (Official)

    و کاربر همین‌ها را می‌دید. اکنون سه چیز سنجیده می‌شود:
    نشانه‌گذاریِ کناری برداشته می‌شود، پارهٔ تهی خودش زباله است
    (همان `~`ی که تنها می‌ماند)، و نشانیِ اینترنتی از روی نقطه
    شکسته می‌شود تا `musicdel.ir` هم گرفته شود.
    """
    bare = (token or "").strip().strip(_EDGE_PUNCT).lower()
    if not bare:
        # نشانه‌گذاریِ تنها — «~» یا «-» که از زباله جا مانده.
        return True
    if bare in _JUNK:
        return True

    # نشانیِ اینترنتی: اگر پاره‌ای از آن زباله باشد، همه‌اش زباله است.
    if "." in bare:
        parts = [x for x in bare.split(".") if x]
        if parts and any(x in _JUNK for x in parts):
            return True

    # «mp3» گاهی «mp۳» یا «MP3_» می‌آید؛ بی رقم هم سنجیده شود.
    stripped = "".join(c for c in bare if not c.isdigit())
    return bool(stripped) and stripped != bare and stripped in _JUNK

# ── لقب‌ها ──────────────────────────────────────────────────
#
# برخلاف `captions.TITLES` که تنها پیشوند را و تنها برای **سنجش**
# می‌گیرد، اینجا برای **ذخیره** برداشته می‌شوند و از هر جای نام.
# «حاج آقا» پیش از «حاج» می‌آید، وگرنه «آقا» جا می‌ماند.
_HONORIFICS: tuple[str, ...] = (
    "حاج آقای", "حاج آقا", "حاج", "حاجی", "کربلایی", "کربلائی",
    "مشهدی", "استاد", "مرحوم", "شادروان", "آقای", "سرکار خانم",
    "حاجیه خانم", "دکتر", "مهندس",
)

# سبک‌های شناخته‌شده — وقتی یک سوی جداکننده اینهاست، آن سو رفتنی است.
_STYLES = frozenset({
    "شور", "واحد", "زمینه", "روضه", "نوحه", "مولودی", "مدح", "تک",
    "دم", "شعرخوانی", "سنگین", "تند", "مناجات", "سینه زنی", "سینه‌زنی",
})

_SEPARATORS = re.compile(r"\s*[|/\\]\s*")
_SPACES = re.compile(r"\s+")
_LATIN_WORD = re.compile(r"[A-Za-z]{2,}")


def is_latin(text: str) -> bool:
    """آیا بیشترِ حرف‌های این نوشته لاتین است."""
    letters = [c for c in (text or "") if c.isalpha()]
    if not letters:
        return False
    latin = sum(1 for c in letters if c.isascii())
    return latin * 2 > len(letters)


def to_persian(text: str) -> str:
    """
    نگارشِ لاتین را حرف‌به‌حرف به فارسی برمی‌گرداند.

    >>> to_persian("Baz Dobare Tako Tanha")
    'باز دوباره تکو تنها'

    حدسی است و ادعای دقت ندارد: از «Rasoli» نمی‌شود فهمید
    «رسولی» درست است یا «رصولی». برای همین نتیجه‌اش همیشه به
    تأییدِ گرداننده می‌رسد.
    """
    if not text:
        return ""

    out: list[str] = []
    for word in _SPACES.split(text.strip()):
        # ── ترتیب، و چرا وارونه بود ─────────────────────────
        #
        # پیش‌تر نخست `bare` ساخته می‌شد (تنها حرفِ لاتین) و اگر
        # تهی بود `continue`. ولی برای **هر واژهٔ فارسی** `bare`
        # تهی است — پس هر واژهٔ فارسی خاموش دور ریخته می‌شد و
        # خطِ «از پیش فارسی است» هرگز اجرا نمی‌شد:
        #
        #     to_persian("حسین ستوده Hosein")  ->  "هسین"
        #
        # اکنون فارسی‌بودن **نخست** سنجیده می‌شود.
        if _is_junk(word):
            continue
        if not word.isascii():
            out.append(word)          # از پیش فارسی است
            continue

        bare = re.sub(r"[^A-Za-z]", "", word).lower()
        if not bare:
            continue
        out.append(_word_to_persian(bare))
    return _SPACES.sub(" ", " ".join(p for p in out if p)).strip()


def _word_to_persian(bare: str) -> str:
    """
    یک واژهٔ لاتینِ کوچک‌شده را برمی‌گرداند.

    واکهٔ «a» در واژهٔ **تک‌واکه‌ای** بلند است («Baz» → «باز») و
    در واژهٔ چندواکه‌ای کوتاه («Tanha» → «تنها»). این تنها قاعده‌ای
    بود که هر دو نمونه را با هم درست می‌داد.
    """
    vowel_count = sum(1 for c in bare if c in _VOWELS)
    result: list[str] = []
    i = 0
    while i < len(bare):
        pair = bare[i : i + 2]
        for src, dst in _DIGRAPHS:
            if pair == src:
                result.append(dst)
                i += 2
                break
        else:
            ch = bare[i]
            first = i == 0
            last = i == len(bare) - 1
            if ch in _VOWELS:
                if first:
                    result.append(_INITIAL[ch])
                elif last:
                    result.append(_FINAL[ch])
                elif ch in _LONG_MID:
                    result.append(_LONG_MID[ch])
                elif vowel_count == 1:
                    result.append("ا")
                # وگرنه واکهٔ کوتاه است و نوشته نمی‌شود
            else:
                result.append(_CONSONANTS.get(ch, ""))
            i += 1
    return "".join(result)

# ═════════════════════════════════════════════════════════════
#  نامزدها — چون نگاشت یک‌به‌یک نیست
# ═════════════════════════════════════════════════════════════
#
# ## چرا این هست
#
# نگاشتِ `_CONSONANTS` تک‌مقداری است: `s`→س و بس. ولی فارسی برای
# یک حرفِ لاتین چند حرف دارد — همان که کاربر خودش نوشت:
# **«C = س یا ک»**.
#
# پس به‌جای یک نگارش، **همهٔ نگارش‌های شدنی** ساخته می‌شود و آنکه
# در گنجینه هست برنده است. سنجیده شد:
#
#     نگاشتِ تک‌مقداری .................... ۶/۱۲
#     نوشتنِ هر واکه ...................... ۳/۱۲
#     نامزدها + تکیه بر گنجینه ............ ۱۵/۱۶
#
# بهایش ناچیز است: بیشترین شمارِ نامزد در سنجش ۱۹۲ بود، و کار
# تنها یک اشتراکِ مجموعه است.
#
# **این جای `to_persian` را نمی‌گیرد.** وقتی هیچ نامزدی در گنجینه
# نباشد — یعنی نامِ راستی تازه — همان یک حدسِ `to_persian`
# می‌مانَد و به تأییدِ گرداننده می‌رسد.

# هر حرف، به همهٔ گونه‌هایش. «» یعنی می‌تواند اصلاً نوشته نشود
# (واکهٔ کوتاه).
_AMBIGUOUS: dict[str, tuple[str, ...]] = {
    "a": ("ا", "", "آ", "ع"),
    "e": ("ه", "", "ا"),
    "i": ("ی", "ای"),
    "o": ("و", ""),
    "u": ("و", "او"),
    "h": ("ه", "ح"),
    "s": ("س", "ص", "ث"),
    "z": ("ز", "ض", "ظ", "ذ"),
    "t": ("ت", "ط"),
    "q": ("ق", "غ"),
    "c": ("س", "ک"),
    "g": ("گ", "غ"),
    "b": ("ب",), "d": ("د",), "f": ("ف",), "j": ("ج",),
    "k": ("ک",), "l": ("ل",), "m": ("م",), "n": ("ن",),
    "p": ("پ",), "r": ("ر",), "v": ("و",), "w": ("و",),
    "x": ("خ",), "y": ("ی",),
}

# «a»ی پایانی در نامِ فارسی هم «ا» می‌شود هم «ی»: رضا، مرتضی.
_FINAL_A: tuple[str, ...] = ("ا", "ی", "")

# دونویسه‌ها پیش از تک‌حرف‌ها آزموده می‌شوند.
_CAND_DIGRAPHS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("kh", ("خ",)), ("sh", ("ش",)), ("ch", ("چ",)),
    ("gh", ("ق", "غ")), ("zh", ("ژ",)), ("ph", ("ف",)),
    ("aa", ("ا", "آ")), ("ee", ("ی",)),
    ("oo", ("و",)), ("ou", ("و",)),
)

# همخوانِ دوتایی در لاتین، در فارسی یکی است: Abbas ← عباس
_DOUBLED = re.compile(r"([bcdfgjklmnprstvxz])\1+")

# سقفِ شمارِ نامزد. از این که گذشت، کار به راهِ تک‌حدسی می‌افتد.
CANDIDATE_CAP = 20000


def _word_candidates(bare: str) -> list[tuple[str, ...]]:
    """هر جایگاهِ واژه، و گونه‌هایش."""
    bare = _DOUBLED.sub(r"\1", bare)
    slots: list[tuple[str, ...]] = []
    i = 0
    while i < len(bare):
        pair = bare[i : i + 2]
        for src, forms in _CAND_DIGRAPHS:
            if pair == src:
                slots.append(forms)
                i += 2
                break
        else:
            ch = bare[i]
            if ch == "a" and i == len(bare) - 1:
                slots.append(_FINAL_A)
            else:
                slots.append(_AMBIGUOUS.get(ch, ("",)))
            i += 1
    return slots


def candidates(text: str, cap: int = CANDIDATE_CAP) -> set[str] | None:
    """
    همهٔ نگارش‌های فارسیِ شدنی برای یک نامِ لاتین.

    بازگشتی `None` است اگر شمارِ نامزدها از `cap` بگذرد — آنگاه
    فراخوان باید به راهِ تک‌حدسیِ `to_persian` برگردد. `None` و
    مجموعهٔ تهی دو چیزند: تهی یعنی «هیچ نگارشی نشد»، `None` یعنی
    «نشماردنی بود».
    """
    if not text or not text.strip():
        return set()

    words = [w for w in _SPACES.split(text.strip()) if w]
    per_word: list[list[str]] = []
    total = 1

    for word in words:
        bare = "".join(c for c in word.lower() if c.isalpha())
        if not bare:
            continue
        if _is_junk(word):
            continue
        if not is_latin(word):
            # واژهٔ فارسی همان‌طور می‌مانَد.
            per_word.append([word])
            continue

        slots = _word_candidates(bare)
        count = 1
        for slot in slots:
            count *= len(slot)
        total *= count
        if total > cap:
            return None
        per_word.append(["".join(c) for c in itertools.product(*slots)])

    if not per_word:
        return set()

    out = {
        _SPACES.sub(" ", " ".join(combo)).strip()
        for combo in itertools.product(*per_word)
    }
    out.discard("")
    return out


def strip_honorifics(name: str) -> str:
    """
    لقب‌ها را از هر جای نام برمی‌دارد.

    >>> strip_honorifics("کربلایی مرتضی یبرنژاد")
    'مرتضی یبرنژاد'

    اگر پس از برداشتن چیزی نماند، **نامِ اصلی برمی‌گردد**: نامی
    که تنها از لقب ساخته شده، بهتر است بماند تا تهی شود.
    """
    if not name:
        return ""
    out = name
    for title in _HONORIFICS:
        out = re.sub(rf"(?:(?<=\s)|^){re.escape(title)}(?=\s|$)", " ", out)
    out = _SPACES.sub(" ", out).strip(" ـ-،,")
    return out or name.strip()


# ═════════════════════════════════════════════════════════════
#  «کربلایی» — لقبِ پیش‌فرض
# ═════════════════════════════════════════════════════════════
#
# خواستهٔ کاربر: «هر مداحی ذخیره کرد اگر کلمه کربلایی داشت که
# داشت، اگر نداشت بهش اضافه کن.»
#
# و در پاسخ به پرسشم روشن کرد که نامِ دارای **لقبِ دیگر** دست
# نخورد: «سید جواد ذاکر» و «حاج مهدی سلحشور» همان می‌مانند،
# چون «سید» و «حاج» لقبِ راستینِ آن اشخاص‌اند.

KARBALAEI = "کربلایی"

# نیم‌فاصله (U+200C) — در گنجینه به‌جای فاصله دیده شد.
ZWNJ = "‌"

# نگارش‌های دیگرِ همین لقب که باید به نگارشِ یکسان برسند.
# «کربلای» (بی ی پایانی) نگارشِ کوتاه‌شده‌ای است که کاربر خودش
# نمونه‌اش را داد.
_KARBALAEI_FORMS = ("کربلایی", "کربلائی", "کربلای", "کربلاء", "کربلا")

# هر لقبی که اگر باشد، «کربلایی» افزوده نمی‌شود. اجتماعِ دو
# فهرستِ پروژه است به‌علاوهٔ «سید» — که در `_HONORIFICS` نبود و
# نبودنش همان چیزی بود که «کربلایی سید جواد ذاکر» می‌ساخت.
_ANY_HONORIFIC: tuple[str, ...] = _HONORIFICS + (
    "سید", "سيد", "سیده", "میرزا", "ملا", "شیخ",
)


def unify_zwnj(name: str) -> str:
    """
    نیم‌فاصله را به فاصله بدل می‌کند.

    ## چرا لازم شد

    در گنجینهٔ راستین «کربلایی» و «وحید شکری» با **نیم‌فاصله**
    (U+200C) به هم چسبیده بودند، نه با فاصله. هیچ‌کدام از دو
    لقب‌بردار این را نمی‌دیدند — هر دو مرزِ `\s` می‌خواهند — پس
    «وحید شکری» و «کربلایی‌وحید شکری» دو مداحِ جدا شمرده می‌شدند.
    """
    return _SPACES.sub(" ", (name or "").replace(ZWNJ, " ")).strip()


def has_honorific(name: str) -> bool:
    """آیا این نام لقبی — هر لقبی — دارد."""
    words = unify_zwnj(name).split()
    if not words:
        return False
    joined = " ".join(words)
    for title in _ANY_HONORIFIC:
        if joined.startswith(title + " ") or joined == title:
            return True
    return any(w in _KARBALAEI_FORMS for w in words)


def with_karbalaei(name: str | None) -> str | None:
    """
    «کربلایی» را بر نام می‌نشاند، اگر لقبی نداشته باشد.

    سه کار، به همین ترتیب:
      ۱. نیم‌فاصله به فاصله («کربلایی‌وحید شکری» ← «کربلایی وحید شکری»)
      ۲. نگارشِ کوتاه یکسان می‌شود («کربلای وحید» ← «کربلایی وحید»)
      ۳. اگر هیچ لقبی نبود، «کربلایی» پیش می‌آید

    نامِ تهی، تک‌واژه‌ای‌های بی‌معنا و نامِ لاتین دست نمی‌خورند —
    «کربلایی .» یا «کربلایی UpMusic» بدتر از نبودنش است.
    """
    if not name or not name.strip():
        return name

    cleaned = unify_zwnj(name)
    if not cleaned or is_latin(cleaned):
        return cleaned or name

    words = cleaned.split()

    # نگارشِ کوتاه، یکسان شود — و تنها در جایگاهِ لقب (واژهٔ نخست)،
    # وگرنه نامِ شهرِ «کربلا» در اسمِ نوا هم عوض می‌شد.
    if words and words[0] in _KARBALAEI_FORMS:
        words[0] = KARBALAEI
        return " ".join(words)

    if has_honorific(cleaned):
        return cleaned

    # نامی که هیچ حرفِ فارسی ندارد، نام نیست.
    if not any("\u0600" <= ch <= "\u06ff" for ch in cleaned):
        return cleaned

    return KARBALAEI + " " + cleaned


def clean_name(raw: str, field: str = "madah", known_madahs=None) -> str:
    """
    نامِ تمیز، از برچسبِ خامِ فایل.

    `field` یکی از «madah» یا «title» است و کار را عوض می‌کند:
    در جداکننده‌ای مانند «دلبر ابالفضل / احسان لطفی»، برای مداح
    باید سویی را برداشت که نامِ آدم است، و برای عنوان سویِ دیگر.

    `known_madahs` مجموعه‌ای از نام‌های هنجارشدهٔ گنجینه است؛ اگر
    داده شود، تصمیمِ جداکننده بر پایهٔ آن گرفته می‌شود نه بر
    حدس.
    """
    if not raw or not raw.strip():
        return ""

    text = _pick_side(raw, field, known_madahs)

    if is_latin(text):
        converted = to_persian(text)
        if converted:
            logger.info("نامِ لاتینِ «%s» به «%s» برگردانده شد.", text, converted)
            text = converted

    if field == "madah":
        text = strip_honorifics(text)

    # زباله‌های نامِ فایل، حتی در نگارشِ فارسی‌شده
    words = [w for w in _SPACES.split(text) if not _is_junk(w)]
    return _SPACES.sub(" ", " ".join(words)).strip(_EDGE_PUNCT + "\u0640")


def _pick_side(raw: str, field: str, known_madahs) -> str:
    """
    از «الف | ب» یا «الف / ب»، سویِ درست را برمی‌دارد.

    سه قاعده، به ترتیبِ استواری:
      ۱. سویی که سبکِ شناخته‌شده است، رفتنی است
      ۲. سویی که مداحِ شناخته‌شده است، همان مداح است
      ۳. وگرنه دست نمی‌خورد — حدسِ نادرست بدتر از دست‌نزدن است
    """
    parts = [p.strip() for p in _SEPARATORS.split(raw) if p.strip()]
    if len(parts) < 2:
        return raw.strip()

    # قاعدهٔ ۱ — سبک را بینداز
    kept = [p for p in parts if p not in _STYLES]
    if len(kept) == 1:
        return kept[0]
    if not kept:
        return parts[-1]
    parts = kept

    # قاعدهٔ ۲ — مداحِ شناخته‌شده
    if known_madahs:
        from core.normalize import normalize

        for part in parts:
            if normalize(strip_honorifics(part)) in known_madahs:
                return part if field == "madah" else _other(parts, part)

    # قاعدهٔ ۳ — دست نمی‌زنیم، ولی جداکننده را به فاصله بدل می‌کنیم
    # تا دست‌کم «شور | ماهم» به «شور ماهم» بدل نشود بلکه هر دو
    # بمانند و گرداننده در کارت ببیندشان.
    return parts[-1] if field == "madah" else parts[0]


def _other(parts: list[str], chosen: str) -> str:
    """آن یکی سو."""
    rest = [p for p in parts if p != chosen]
    return rest[0] if rest else chosen
