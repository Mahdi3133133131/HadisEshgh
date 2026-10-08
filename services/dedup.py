"""
یافتن و ادغامِ نسخه‌های تکراری.

## چرا این هست

یک مداحی از چند راه به گنجینه می‌آید — کاربری می‌فرستد، گرداننده‌ای
می‌گذارد، کانالی منبع می‌شود. همان ضبط، با فشرده‌سازی دیگر یا
برش اندکی متفاوت، دو ردیف جدا می‌سازد.

`find_duplicate_track` تنها فایلِ **بایت‌به‌بایت یکسان** را می‌گیرد
(`file_unique_id` یا `sha256`)، پس دو کدگذاریِ گوناگون از یک صوت
بی‌مانع وارد می‌شوند.

## چرا زیان دارد، نه فقط جای بیشتر

تطبیق‌گر آزمونِ نسبت با نفر دوم دارد: اگر دو نوا نزدیک به هم
امتیاز بگیرند، هیچ‌کدام پذیرفته نمی‌شود. دو ردیف که **یک صوت**
باشند دقیقاً همین را می‌سازند — رأی یکدیگر را می‌شکنند و کاربر
پاسخی نمی‌گیرد که هر دو ردیف داشتندش.

## آستانه، و چرا این‌قدر گشاده

اندازه‌گیری روی گنجینهٔ راستین: نواهای **جدا** — حتی دو مداحی از
یک مداح با تمپوی یکسان — تنها ۰٫۱٪ تا ۰٫۲٪ عددِ هم‌راستا داشتند.
یک ضبطِ تکراری نزدیک ۱۰۰٪ می‌دهد.

میان ۰٫۲٪ و ۱۰۰٪ جا برای دودلی نیست، پس آستانه‌ای میانه‌رو
برگزیده شده. سخت‌گیرتر از جست‌وجو، چون ادغام یک ردیف را
**برمی‌دارد**: بهای اشتباه اینجا بیشتر است.
"""

from __future__ import annotations

import logging

import numpy as np

from core.audio import matcher
from core.audio.fingerprint import SAMPLE_RATE, fingerprint_query
from core.db import database

logger = logging.getLogger(__name__)

# پنجره‌ای از میانهٔ نوا که برای سنجش برداشته می‌شود.
#
# میانه، نه آغاز: آغازِ بسیاری از نواها خاموشی یا سخنِ آغازین
# است و میان دو نسخه فرق می‌کند.
PROBE_SECONDS = 45.0

# زیر این شمار عددِ هم‌راستا، سخنی از تکراری بودن نیست.
#
# پنجرهٔ ۴۵ ثانیه‌ای از یک ضبطِ همسان صدها عدد می‌دهد؛ نوای جدا
# در سنجش‌ها زیر بیست ماند. دویست، میانهٔ بازِ این دو است.
MIN_ALIGNED = 200

# و امتیاز هم باید بالا باشد — شمارِ تنها، با نوای بسیار دراز
# می‌تواند تصادفی بالا برود.
MIN_SCORE = 0.55


def _probe(samples: np.ndarray) -> np.ndarray:
    """پنجره‌ای از میانهٔ صوت."""
    limit = int(PROBE_SECONDS * SAMPLE_RATE)
    if samples.size <= limit:
        return samples
    start = (samples.size - limit) // 2
    return samples[start : start + limit]


def find_same_recording(track_id: int, samples: np.ndarray):
    """
    آیا این صوت، همان ضبطِ نوای دیگری در گنجینه است؟

    باید **پیش از** نشاندنِ اثر انگشتِ نوای تازه صدا زده شود،
    وگرنه خودش را می‌یابد.

    بازگشتی: (شناسهٔ نوای همسان، شمار عددِ هم‌راستا) یا None.
    `None` پاسخِ رایج و درست است.
    """
    try:
        query = fingerprint_query(_probe(samples))
    except Exception as exc:  # noqa: BLE001
        logger.debug("اثر انگشتِ سنجشِ تکراری ساخته نشد: %s", exc)
        return None

    found = matcher.match(query, min_aligned=MIN_ALIGNED)
    if found is None or int(found.track_id) == int(track_id):
        return None
    if found.score < MIN_SCORE:
        return None
    return int(found.track_id), int(found.aligned_hashes)


def _better(a, b) -> tuple[object, object]:
    """
    کدام بماند و کدام برود.

    درازتر می‌ماند — نسخهٔ کامل بر نسخهٔ بریده می‌چربد. در درازای
    برابر، پرحجم‌تر، که نشانهٔ نرخِ بیت بالاتر است.
    """
    a_dur = int(a["duration"] or 0)
    b_dur = int(b["duration"] or 0)
    if a_dur != b_dur:
        return (a, b) if a_dur > b_dur else (b, a)
    a_size = int(a["file_size"] or 0)
    b_size = int(b["file_size"] or 0)
    return (a, b) if a_size >= b_size else (b, a)


def merge(first_id: int, second_id: int) -> int | None:
    """
    دو ردیف را که یک ضبط‌اند یکی می‌کند.

    ردیفِ بازنده پاک **نمی‌شود**: `is_active = 0` می‌گیرد و
    `merged_into` نشانش می‌دهد کجا رفت. نشانی‌اش شاید جایی
    فرستاده شده باشد، و «چرا این نوا رفت» باید پاسخی داشته باشد.

    شناسنامه‌ها آمیخته می‌شوند: هر چه برنده ندارد و بازنده دارد،
    برداشته می‌شود. شمارِ فرستادن جمع می‌شود.

    بازگشتی: شناسهٔ برنده، یا None اگر نشد.
    """
    first = database.get_track(first_id)
    second = database.get_track(second_id)
    if first is None or second is None:
        return None

    winner, loser = _better(first, second)
    win_id = int(winner["id"])
    lose_id = int(loser["id"])
    if win_id == lose_id:
        return win_id

    # ── آمیختنِ شناسنامه ────────────────────────────────────
    fills: list[str] = []
    values: list[object] = []
    for column in ("madah", "title", "style", "lyrics_snippet", "transcript"):
        try:
            has = winner[column]
            other = loser[column]
        except (KeyError, IndexError):
            continue
        if not has and other:
            fills.append(f"{column} = ?")
            values.append(other)

    # هنجارهای جست‌وجو هم باید با آنچه نشست بخوانند.
    if "madah = ?" in fills or "title = ?" in fills:
        from core.normalize import normalize

        if "madah = ?" in fills:
            fills.append("madah_norm = ?")
            values.append(normalize(str(loser["madah"])))
        if "title = ?" in fills:
            fills.append("title_norm = ?")
            values.append(normalize(str(loser["title"])))

    fills.append("sent_count = sent_count + ?")
    values.append(int(loser["sent_count"] or 0))
    values.append(win_id)
    database.execute(
        f"UPDATE tracks SET {', '.join(fills)}, updated_at = datetime('now')"
        " WHERE id = ?",
        tuple(values),
    )

    # ── برداشتنِ بازنده ─────────────────────────────────────
    database.execute(
        """
        UPDATE tracks
           SET is_active = 0, merged_into = ?, updated_at = datetime('now')
         WHERE id = ?
        """,
        (win_id, lose_id),
    )
    # اثر انگشتش برداشته می‌شود، وگرنه همچنان رأیِ برنده را
    # می‌شکند — که همان ایرادی است که ادغام برای رفعش هست.
    database.execute("DELETE FROM fingerprints WHERE track_id = ?", (lose_id,))

    logger.info(
        "نوای %s در نوای %s ادغام شد (تکراری).", lose_id, win_id
    )
    return win_id

# ═════════════════════════════════════════════════════════════
#  همان نوحه، اجرای دیگر
# ═════════════════════════════════════════════════════════════

# زیر این همانندیِ خطِ آهنگ، سخنی از یکی بودن نیست.
#
# آستانهٔ خودِ لایه (MIN_SIMILARITY) پایه است؛ اینجا بالاتر
# گرفته می‌شود چون پیامدش هشدار به گرداننده است و هشدارِ بیهوده،
# اعتماد به هشدارهای راستین را می‌خورد.
TWIN_SIMILARITY = 0.74

# آستانهٔ سخت‌گیرانه‌تر، وقتی نامِ مداح نمی‌خواند.
#
# ## چرا دو آستانه، و نه یک صافیِ قطعی
#
# پیش‌تر مداحِ ناهم‌نام یکسره **کنار گذاشته** می‌شد. یعنی غربال
# تنها میانِ نواهای همان مداح می‌گشت و نوایی که از پیش داشتیم —
# ولی زیر نامی دیگر ثبت شده بود — دیده نمی‌شد. خواستهٔ روشن این
# بود که «کلِ مداحی‌ها را نگاه کند».
#
# ولی صافی بی‌دلیل هم نبود: یک نوحهٔ رایج را ده مداح خوانده‌اند و
# بی آن، ده هشدارِ بی‌جا می‌آمد. پس به‌جای بیرون انداختن، آستانه
# بالا می‌رود: هم‌نام از ۰٫۷۴، ناهم‌نام تنها از ۰٫۸۸ به بالا.
# تصمیمِ نهایی هم با گرداننده است، نه با ربات.
CROSS_MADAH_SIMILARITY = 0.88


def find_same_nowheh(samples, madah: str | None, exclude: int | None = None):
    """
    آیا همین نوحه از همین مداح از پیش در گنجینه هست؟

    ## چه چیزی می‌یابد که `find_same_recording` نمی‌یابد

    آن، همان **ضبط** را می‌یابد — همان فایل با فشرده‌سازی دیگر.
    این، همان **نوحه** را می‌یابد حتی اگر اجرای دیگری باشد: مجلس
    دیگر، سال دیگر، ضبط دیگر.

    ربات متنِ مداحی را نمی‌خواند، پس «متن یکی است» را نمی‌تواند
    مستقیم بسنجد. ولی خطِ آهنگ همان را از راه دیگر می‌گوید: دو
    اجرا از یک نوحه، خطِ آهنگِ یکسانی دارند حتی با گام و سرعت
    متفاوت.

    نامِ مداح هم باید بخواند. بی آن، نوحه‌ای که ده مداح خوانده‌اند
    ده هشدارِ بی‌جا می‌ساخت.

    بازگشتی: (شناسهٔ نوا، همانندی) یا None — و None پاسخِ رایج است.
    """
    from core.audio import melody as melody_mod
    from core.db import melody_store
    from core.normalize import normalize

    try:
        corpus = melody_store.corpus()
    except Exception as exc:  # noqa: BLE001
        logger.debug("گنجینهٔ خطِ آهنگ خوانده نشد: %s", exc)
        return None
    if not corpus:
        return None

    try:
        signature = melody_mod.signature(samples)
    except Exception as exc:  # noqa: BLE001
        # نوای کوتاه نشان نمی‌دهد؛ این ناکامی عادی است.
        logger.debug("نشانِ خطِ آهنگ ساخته نشد: %s", exc)
        return None

    try:
        # ۱۲ و نه ۵: بی صافیِ مداح، نامزدها بیشترند و سقفِ
        # تنگ، همانندِ راستین را از فهرست بیرون می‌انداخت.
        matches = melody_mod.search(signature, corpus, limit=12)
    except Exception as exc:  # noqa: BLE001
        logger.debug("جست‌وجوی خطِ آهنگ نشد: %s", exc)
        return None

    wanted = normalize(madah or "")
    for match in matches:
        track_id = int(match.track_id)
        if exclude is not None and track_id == int(exclude):
            continue
        if match.similarity < TWIN_SIMILARITY:
            continue
        track = database.get_track(track_id)
        if track is None or not int(track["is_active"] or 0):
            continue
        # نامِ مداح دیگر **صافی** نیست، آستانه را جابه‌جا می‌کند.
        same_madah = (
            not wanted or normalize(track["madah"] or "") == wanted
        )
        if not same_madah and match.similarity < CROSS_MADAH_SIMILARITY:
            continue
        logger.info(
            "نوحهٔ همانند یافت شد: نوای %s با همانندی %.2f",
            track_id, match.similarity,
        )
        return track_id, float(match.similarity)
    return None


# ═════════════════════════════════════════════════════════════
#  یک درگاه برای «آیا این را داریم؟»
# ═════════════════════════════════════════════════════════════

async def identify(bot, file_id: str, madah: str | None = None):
    """
    آیا این فایل از پیش در گنجینه هست؟

    ## چرا اینجا و نه در گردانندهٔ تلگرام

    سه جا همین پرسش را می‌پرسند — پذیرشِ گروهیِ گرداننده، پیشکشِ
    کاربر، و پیشکشِ کاربرِ مورد اعتماد — و پیش‌تر تنها یکی‌شان
    راستی می‌سنجید. دو تای دیگر تنها `file_unique_id` را
    می‌دیدند، یعنی **فایلِ بایت‌به‌بایت یکسان**؛ نسخهٔ بازفشرده یا
    بازآپلودشدهٔ همان ضبط بی‌مانع رد می‌شد.

    ## دو نشانه، به ترتیبِ استواری

    نخست اثر انگشت: «آیا این همان ضبط است؟» — قطعی.
    اگر نبود، خطِ آهنگ: «آیا این همان نوحه است، در اجرایی دیگر؟»
    — محتمل، و برای همین پاسخش با آدم است نه با ربات.

    بازگشتی: ‎(شناسهٔ نوای موجود، آیا همان ضبط است)‎ یا None.
    None پاسخِ رایج و درست است.

    ناکامی — شبکه، رمزگشایی، فایلِ خراب — هم None می‌دهد: نبودِ
    هشدار بهتر از ایستادنِ کار است.
    """
    import asyncio
    import time as _time

    from config import config
    from core.audio.decode import decode

    temp = config.tmp_dir / f"identify_{int(_time.time() * 1000)}.bin"
    try:
        from services.indexer import download

        await download(bot, file_id, temp)
        loop = asyncio.get_running_loop()
        samples = await loop.run_in_executor(None, decode, temp)

        # `-1` نگهبانی است که هرگز با شناسهٔ راستینی نمی‌خواند —
        # این فایل هنوز شناسه‌ای ندارد و تابع تنها برای کنار
        # گذاشتنِ خودش شناسه می‌خواهد.
        same = await loop.run_in_executor(
            None, find_same_recording, -1, samples
        )
        if same is not None:
            return int(same[0]), True

        twin = await loop.run_in_executor(
            None, find_same_nowheh, samples, madah, None
        )
        if twin is not None:
            return int(twin[0]), False
        return None
    except Exception as exc:  # noqa: BLE001
        logger.debug("سنجشِ «این را داریم؟» نشد: %s", exc)
        return None
    finally:
        temp.unlink(missing_ok=True)
