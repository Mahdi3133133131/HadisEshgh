"""
خواندن نام مداح و اسم مداحی از کپشنِ کانال.

## چرا این پرونده هست

فایلی که در کانال‌های مداحی گذاشته می‌شود، اغلب برچسب ID3 ندارد یا
برچسبش چیزی مانند `voice_0032` است. ولی نامِ مداح تقریباً همیشه در
**کپشن** نوشته شده — بالای فایل یا زیرش. تا امروز ربات آن را
نمی‌خواند و نوا بی نام مداح در آرشیو می‌نشست.

## سه لایه، به همین ترتیب

۱. **برچسب خودِ فایل** — اگر بود، همان و تمام. خواستهٔ صریح این
   بود که آنچه روی فایل است دست نخورد.
۲. **الگوی صریح در کپشن** — «مداح:»، «با نوای»، «صدای» و مانند
   آن‌ها.
۳. **نام‌های شناخته‌شده** — هر مداحی که از پیش در آرشیو هست، در
   کپشن جست‌وجو می‌شود.

لایهٔ سوم **خودش را می‌سازد**: هر مداحی که یک بار دستی ثبت شود، از
آن پس در کپشن‌های آینده شناخته می‌شود. با گذشت زمان و پر شدن
آرشیو، این لایه از لایهٔ دوم هم کارآمدتر می‌شود.

## چرا القاب جدا نگه داشته می‌شوند

«حاج»، «کربلایی»، «سید» و مانندشان بخشی از نام نیستند ولی در
کپشن‌ها همیشه کنارش می‌آیند. اگر در نام بمانند، «حاج محمود کریمی»
و «محمود کریمی» دو مداحِ جدا شمرده می‌شوند. پس هنگام سنجش برداشته
می‌شوند، ولی در نامی که ذخیره می‌شود می‌مانند — چون مردم مداح را
با لقبش می‌شناسند.
"""

from __future__ import annotations

import logging
import re

from core.normalize import clean_tag, fix_characters, normalize

logger = logging.getLogger(__name__)

# القابی که پیش از نام می‌آیند و بخشی از نام نیستند.
TITLES = (
    "حاج",
    "حاجی",
    "کربلایی",
    "کربلائی",
    "سید",
    "سيد",
    "شادروان",
    "مرحوم",
    "استاد",
    "آقای",
)

# نشانه‌هایی که پس از آن‌ها نام مداح می‌آید.
#
# ترتیب مهم است: صریح‌ترین‌ها نخست. «از» را عمداً پایین گذاشته‌ایم
# چون در فارسی هزار کاربرد دیگر دارد و به‌تنهایی نشانهٔ ضعیفی است.
_LEAD = (
    r"مداح",
    r"مداحی از",
    r"با نوای",
    r"با صدای",
    r"صدای",
    r"نوای",
    r"خواننده",
    r"🎤",
    r"🎙",
)

# ── دو نکتهٔ ریز که یک باگِ راستین می‌ساختند ────────────────
#
# ۱. **ترتیب.** موتورِ regex در `a|b` نخستین گزینهٔ خوانا را
#    برمی‌دارد، نه بلندترین را. «مداح» پیش از «مداحی از» بود، پس
#    «مداحی از حاج محمود کریمی» چنین شکسته می‌شد:
#    نشانه = «مداح»، نام = «ی از حاج محمود کریمی».
#    اکنون بلندترین‌ها نخست چیده می‌شوند، هرچه در `_LEAD` نوشته
#    شده باشد.
#
# ۲. **مرز.** «مداح» نباید درونِ واژهٔ بلندتر بگیرد. پس از
#    نشانه‌های فارسی یک نگاهِ منفی می‌آید تا حرفِ فارسیِ دیگری
#    پس از آن نباشد. نشانه‌های تصویری (🎤) این مرز را نمی‌گیرند،
#    چون گاه نام بی‌فاصله پس از آن‌ها می‌آید.
_PERSIAN_LETTER = "[" + chr(92) + "u0600-" + chr(92) + "u06FF]"


def _lead_pattern() -> str:
    parts = []
    for marker in sorted(_LEAD, key=len, reverse=True):
        if re.search(_PERSIAN_LETTER, marker):
            parts.append(marker + "(?!" + _PERSIAN_LETTER + ")")
        else:
            parts.append(marker)
    return "|".join(parts)


_LEAD_RE = re.compile(
    r"(?:^|\n)\s*(?:" + _lead_pattern() + r")\s*[:：\-—]?\s*(?P<name>[^\n]{2,60})",
    re.MULTILINE,
)

# خطی که تنها لقب و نام است: «حاج محمود کریمی»
_TITLED_RE = re.compile(
    r"(?:^|\n)\s*(?P<name>(?:" + "|".join(TITLES) + r")\s+[^\n]{2,50})",
    re.MULTILINE,
)

# چیزهایی که در کپشن هستند ولی نام نیستند
_NOISE = re.compile(
    r"(?:https?://\S+|@[\w_]+|[#][^\s#]+|\|+|·|•|\d{2,4}[/-]\d{1,2}[/-]\d{1,2})"
)

# خط‌هایی که یکسره تبلیغ‌اند
_ADVERT = re.compile(
    r"(عضو|کانال|لینک|دنبال|فالو|اشتراک|join|channel|@)", re.IGNORECASE
)

# ایموجی و نشانه‌های تزئینی که سرِ خط می‌آیند. در نام مداحی جایی
# ندارند و اگر بمانند، دو نامِ یکسان با دو ایموجی متفاوت، دو چیز
# جدا شمرده می‌شوند.
_LEADING_ORNAMENT = re.compile(r"^[^\w؀-ۿ]+")


def _strip_noise(text: str) -> str:
    text = _NOISE.sub(" ", text or "")
    text = _LEADING_ORNAMENT.sub("", text)
    return re.sub(r"\s+", " ", text).strip(" \t:،-—_*")


def strip_title(name: str) -> str:
    """لقب را از سرِ نام برمی‌دارد — تنها برای سنجش، نه برای ذخیره."""
    out = (name or "").strip()
    changed = True
    while changed:
        changed = False
        for title in TITLES:
            if out.startswith(title + " "):
                out = out[len(title) + 1 :].strip()
                changed = True
    return out


def known_madahs() -> dict[str, str]:
    """
    نام مداحانی که از پیش در آرشیو هستند: هنجارشده ← نامِ نمایشی.

    همین است که لایهٔ سوم را خودآموز می‌کند.
    """
    from core.db.database import query_all

    out: dict[str, str] = {}
    try:
        rows = query_all(
            "SELECT DISTINCT madah FROM tracks"
            " WHERE madah IS NOT NULL AND madah != '' AND is_active = 1"
        )
    except Exception:  # noqa: BLE001
        logger.debug("خواندن فهرست مداحان نشد.")
        return out

    for row in rows:
        name = (row["madah"] or "").strip()
        if not name:
            continue

        # ── نامِ لاتین، مرجع نمی‌شود ─────────────────────────
        #
        # ## چرا این نگهبان بایسته شد
        #
        # در گنجینهٔ راستین، اسمِ فایلی مانند
        # «Baz Dobare Tako Tanha ~ UpMusic» به‌عنوان نامِ مداح
        # نشسته بود. لایهٔ سوم آن را با **خودش** تطبیق می‌داد و
        # امتیازِ ۱٫۰۰ می‌گرفت — یعنی زباله، خودش را قانونی
        # می‌کرد و جلوِ برگردانِ فارسی را هم می‌گرفت.
        #
        # اکنون که نامِ مداح همیشه فارسی است، نامِ لاتین دیگر
        # مرجعِ کسی نمی‌شود. از گنجینه پاک نمی‌شود — آن تصمیمِ
        # آدم است — تنها دیگر الگو نمی‌شود.
        try:
            from services.persianize import is_latin

            if is_latin(name):
                continue
        except Exception:  # noqa: BLE001
            pass

        key = normalize(strip_title(name))
        if len(key) >= 3:
            out[key] = name
    return out


def _by_candidates(name: str, known: dict[str, str]) -> str | None:
    """
    نامِ لاتین را با ساختنِ همهٔ نگارش‌های شدنی به گنجینه می‌رساند.

    بازگشتی نامِ نمایشیِ گنجینه است، یا None اگر هیچ نگارشی
    نخواند — که آنگاه کار به حدسِ تک‌مقداری می‌افتد.

    چند نگارش که خواندند، آنکه به نگارشِ لاتین نزدیک‌تر است
    برنده می‌شود؛ سنجهٔ نزدیکی همان اسکلتِ آواییِ `translit` است
    که برای همین کار ساخته شده.
    """
    if not known:
        return None

    from services import persianize

    if not persianize.is_latin(name):
        return None

    try:
        forms = persianize.candidates(name)
    except Exception:  # noqa: BLE001
        logger.debug("ساختنِ نامزدها نشد.", exc_info=True)
        return None

    if not forms:
        # None یعنی «نشماردنی بود»، تهی یعنی «هیچ نشد» — هر دو
        # به پلهٔ بعد می‌روند.
        return None

    hits = {}
    for form in forms:
        key = normalize(strip_title(form))
        if key and key in known:
            hits[key] = known[key]

    if not hits:
        return None

    if len(hits) == 1:
        display = next(iter(hits.values()))
        logger.info("نامِ «%s» با نامزدها به «%s» رسید.", name, display)
        return display

    # بیش از یکی: نزدیک‌ترین به نگارشِ لاتین
    try:
        from services.translit import similarity, skeleton

        probe = skeleton(name)
        best = max(hits.values(), key=lambda d: similarity(probe, skeleton(d)))
    except Exception:  # noqa: BLE001
        logger.debug("گزینشِ میانِ نامزدها نشد.", exc_info=True)
        best = sorted(hits.values())[0]

    logger.info(
        "نامِ «%s» میانِ %s نامزدِ خوانا به «%s» رسید.",
        name, len(hits), best,
    )
    return best


def resolve_madah(name: str | None) -> str | None:
    """
    نامِ درستِ مداح، با لقبِ «کربلایی».

    زنجیرهٔ رساندنِ نام در `_resolve_madah` است؛ اینجا تنها لقب
    نشانده می‌شود — خواستهٔ کاربر: «اگر کلمه کربلایی داشت که
    داشت، اگر نداشت بهش اضافه کن».

    نامی که لقبِ **خودش** را دارد («سید جواد ذاکر»، «حاج مهدی
    سلحشور») دست نمی‌خورد؛ همان که کاربر تأیید کرد.
    """
    resolved = _resolve_madah(name)
    if not resolved:
        return resolved
    try:
        from services import persianize

        return persianize.with_karbalaei(resolved) or resolved
    except Exception:  # noqa: BLE001
        logger.debug("نشاندنِ لقب نشد.", exc_info=True)
        return resolved


def _resolve_madah(name: str | None) -> str | None:
    """
    نگارشی از نامِ مداح را به نامِ درستش می‌رساند.

    سه پله، به همین ترتیب — از استوارترین گواه به سست‌ترین:

    ۱. **نامِ مستعارِ آموخته.** گرداننده‌ای پیش‌تر همین نگارش را
       اصلاح کرده؛ هیچ گمانه‌ای استوارتر از تصحیحِ آدم نیست.
    ۲. **همان‌گویی با نامی که داریم.** اگر پس از هنجارسازی عیناً
       یکی از مداحانِ گنجینه باشد، همان است.
    ۳. **نزدیکیِ آوایی.** فینگلیش یا نامِ ناقص را به نزدیک‌ترین
       مداحِ شناخته‌شده می‌رساند — `morteza yebovkzhad` به
       «مرتضی یبرنژاد»، و `Borna` به «رسول برنا».

    اگر هیچ‌کدام نگرفت، همان نگارشِ ورودی برمی‌گردد: نامی که
    نمی‌شناسیم شاید مداحِ تازه‌ای باشد، و دور ریختنش بدتر از
    نگه داشتنِ نگارشِ خام است.
    """
    name = (name or "").strip()
    if not name:
        return None

    # ── پلهٔ ۱: آنچه آموخته‌ایم ──────────────────────────────
    try:
        from core.db import madah_aliases

        learned = madah_aliases.resolve(name)
        if learned:
            return learned
    except Exception:  # noqa: BLE001
        logger.debug("خواندن نام‌های مستعار نشد.", exc_info=True)

    known = known_madahs()
    if not known:
        return name

    # ── پلهٔ ۲: همان‌گویی ────────────────────────────────────
    key = normalize(strip_title(name))
    if key in known:
        return known[key]

    # ── پلهٔ ۳: نزدیکیِ آوایی ────────────────────────────────
    try:
        from services.translit import match_name

        found = match_name(name, known)
        if found is not None:
            display, score = found
            logger.info(
                "نامِ «%s» به «%s» رسانده شد (شباهت %.2f).", name, display, score
            )
            return display
    except Exception:  # noqa: BLE001
        logger.debug("تطبیقِ آواییِ نام نشد.", exc_info=True)

    # ── پلهٔ ۴: نامزدها، با تکیه بر گنجینه ──────────────────
    #
    # ## چرا نامزد، و نه یک نگاشت
    #
    # نگاشتِ حرف‌به‌حرف تک‌مقداری است: `s`→س و بس. ولی فارسی برای
    # یک حرفِ لاتین چند حرف دارد — همان که کاربر نوشت: «C = س یا
    # ک». پس همهٔ نگارش‌های شدنی ساخته می‌شود و آنکه در گنجینه
    # هست برنده است.
    #
    # سنجیده شد: نگاشتِ تک‌مقداری ۶/۱۲، این ۱۵/۱۶.
    #
    # یافتهٔ اینجا **گمانه نیست، یقین است** — نگارشِ ساخته‌شده
    # عیناً با نامی که در گنجینه داریم می‌خواند. پس بی‌پرسش
    # می‌نشیند؛ همان که کاربر خواست.
    found = _by_candidates(name, known)
    if found is not None:
        return found

    # ── پلهٔ ۵: یک حدس، برای نامی که راستی تازه است ─────────
    # ── پلهٔ ۵ ادامه ───────────────────────────────
    #
    # تنها وقتی سه پلهٔ بالا چیزی نگفته‌اند — یعنی این نام در
    # گنجینه نیست. آنگاه دست‌کم نگارشش فارسی می‌شود.
    #
    # ## چرا آخر، و نه اول
    #
    # سنجش روشن بود: پلهٔ سوم «Hosein Sotude» را «حسین ستوده»
    # می‌کند و «Morteza Yebranezhad» را «مرتضی یبرنژاد» — کاری که
    # نگاشتِ حرفی هرگز نمی‌تواند، چون لاتین یک «s» دارد و فارسی
    # سه تا (س ص ث) و یک «h» دارد و فارسی دو تا (ح ه). پس نگاشتِ
    # حرفی تنها آنجا به کار می‌آید که هیچ نامی برای تطبیق نباشد.
    #
    # نتیجه‌اش حدس است، پس در کارتِ شناسنامه به گرداننده نشان
    # داده می‌شود؛ ویرایشش به حافظهٔ نام‌های مستعار می‌رود و
    # دفعهٔ بعد پلهٔ یکم همان را می‌دهد — بی هیچ پرسشی.
    try:
        from services import persianize

        guess = persianize.clean_name(name, "madah", known)
        if guess and guess != name:
            logger.info("نامِ «%s» به «%s» پاک شد.", name, guess)
            return guess
    except Exception:  # noqa: BLE001
        logger.debug("پاک‌سازیِ نام نشد.", exc_info=True)

    return name


def clean_title(title: str | None) -> str | None:
    """
    اسمِ مداحی را می‌پیراید.

    دو کار: جداکننده را می‌شکند («شور | ماهم حضرت رضا» →
    «ماهم حضرت رضا»)، و اگر لاتین بود فارسی‌اش می‌کند.

    برخلافِ نامِ مداح، اینجا لقب برداشته **نمی‌شود** — «حاج» در
    اسمِ یک نوا می‌تواند خودِ واژه باشد، نه لقبِ کسی.
    """
    if not title or not title.strip():
        return title

    try:
        from services import persianize

        out = persianize.clean_name(title, "title", known_madahs())
        if out and out != title:
            logger.info("اسمِ «%s» به «%s» پاک شد.", title, out)
            return out
    except Exception:  # noqa: BLE001
        logger.debug("پاک‌سازیِ اسمِ نوا نشد.", exc_info=True)

    return title


def find_madah(caption: str | None) -> str | None:
    """نام مداح را از کپشن بیرون می‌کشد؛ None اگر نیافت."""
    text = fix_characters(caption or "")
    if not text.strip():
        return None

    # ── لایهٔ ۲: نشانهٔ صریح ─────────────────────────────────
    for match in _LEAD_RE.finditer(text):
        name = _strip_noise(match.group("name"))
        # نشانه گاهی سرِ خط است و نام، خطِ پس از آن
        if not name or _ADVERT.search(name):
            continue
        cleaned = clean_tag(name, 120)
        if cleaned and len(strip_title(cleaned)) >= 3:
            return cleaned

    # ── لایهٔ ۳: نامی که از پیش می‌شناسیم ───────────────────
    known = known_madahs()
    if known:
        haystack = normalize(text)
        # بلندترین نخست، تا «محمود کریمی» بر «محمود» بچربد
        for key in sorted(known, key=len, reverse=True):
            if key and key in haystack:
                return known[key]

    # ── لایهٔ ۲ب: خطی که با لقب آغاز می‌شود ─────────────────
    for match in _TITLED_RE.finditer(text):
        name = _strip_noise(match.group("name"))
        if not name or _ADVERT.search(name):
            continue
        cleaned = clean_tag(name, 120)
        if cleaned and len(strip_title(cleaned)) >= 3:
            return cleaned

    return None


def find_title(caption: str | None, madah: str | None = None) -> str | None:
    """
    اسم مداحی را از کپشن بیرون می‌کشد.

    نخستین خطِ معناداری که نام مداح و تبلیغ نیست. کپشن کانال‌ها
    معمولاً با نام خودِ مداحی آغاز می‌شود.
    """
    text = fix_characters(caption or "")
    if not text.strip():
        return None

    madah_key = normalize(strip_title(madah or "")) if madah else ""

    for raw in text.split("\n"):
        line = _strip_noise(raw)
        if len(line) < 3 or _ADVERT.search(line):
            continue
        # خطی که خودش نام مداح است، اسم مداحی نیست
        if madah_key and normalize(strip_title(line)) == madah_key:
            continue
        # خطی که با نشانهٔ مداح آغاز می‌شود هم نه
        if _LEAD_RE.match("\n" + raw):
            continue
        cleaned = clean_tag(line, 200)
        if cleaned:
            return cleaned
    return None


def read(audio, caption: str | None) -> tuple[str | None, str | None]:
    """
    شناسنامهٔ یک فایل کانال: (نام مداح، اسم مداحی).

    برچسب خودِ فایل همیشه می‌چربد — همان که خواسته شده بود: آنچه
    روی فایل هست دست نخورد. کپشن تنها جای خالی را پر می‌کند.
    """
    madah = clean_tag(getattr(audio, "performer", None), 120)
    title = clean_tag(getattr(audio, "title", None), 200)

    if madah is None:
        madah = find_madah(caption)
    if title is None:
        title = find_title(caption, madah) or clean_tag(
            getattr(audio, "file_name", None), 200
        )

    # ── پیرایش، پیش از سپردن به گنجینه ──────────────────────
    #
    # برچسبِ خودِ فایل همچنان می‌چربد — ولی «چربیدن» یعنی این
    # برچسب *سرچشمه* است، نه اینکه دست‌نخورده بماند. نامِ لاتین
    # و واژهٔ اضافه در گنجینه ماندگار می‌شوند و هر جست‌وجویی را
    # پس از آن خراب می‌کنند.
    if madah:
        madah = resolve_madah(madah) or madah
    title = clean_title(title)

    return madah, title
