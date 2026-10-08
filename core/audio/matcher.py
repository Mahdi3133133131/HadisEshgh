"""
تطبیق تکهٔ صوتی با گنجینه.

## چرا شمردن عددهای مشترک بس نیست

اگر تنها بشماریم «این تکه با کدام نوا بیشترین عدد مشترک را دارد»،
نواهای دراز همیشه برنده می‌شوند؛ چون عدد بیشتری دارند و از سرِ
بخت هم که شده، همانندی بیشتری می‌آورند.

نشانهٔ راستین چیز دیگری است: اگر تکه براستی از نوایی بریده شده
باشد، **همهٔ** عددهای مشترک با فاصلهٔ زمانی یکسان جور درمی‌آیند.
تکه‌ای از دقیقهٔ سوم، همهٔ عددهایش دقیقاً ۱۸۰ ثانیه جلوتر از
جای خودشان در تکه‌اند.

پس به جای شمردن، بافه‌ای (هیستوگرام) از فاصله‌ها می‌سازیم و بلندی
بلندترین ستونش را می‌سنجیم. هم‌آمدن تصادفی، فاصله‌هایش پراکنده
است و ستون بلندی نمی‌سازد.

## مدارا با ناهم‌ترازی

تکه‌ای که کاربر می‌فرستد، از هر جای موج بریده شده است و شبکهٔ
قاب‌هایش با شبکهٔ نوای گنجینه یکی نیست. پس فاصله‌ها دقیقاً یکسان
درنمی‌آیند، بلکه در بازه‌ای به پهنای یکی دو قاب می‌نشینند. از این
رو فاصله‌ها پیش از شمردن، در خانه‌هایی دسته می‌شوند و هر خانه با
همسایه‌اش هم جمع می‌گردد.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import numpy as np

from core.audio.fingerprint import MS_PER_FRAME, Fingerprint
from core.db import fingerprints as fp_store

logger = logging.getLogger(__name__)

# پهنای هر خانهٔ بافه، بر حسب میلی‌ثانیه.
# نزدیک به دو قاب گرفته شده تا ناهم‌ترازی برش را برتابد.
DELTA_BIN_MS = 100

# کمترین شمار عدد هم‌راستا برای آنکه تطبیق پذیرفته شود.
#
# از ۱۲ به ۱۵ آمد. اثر انگشت چگال‌تر شد، ولی نه آن‌قدر که
# آستانه را بتوان تا ۲۵ برد: آزمون زنده نشان داد ۲۵، کلیپ‌های
# پرنویز را می‌پراند. بیشترین امتیازِ نوای **بیگانه** در سنجش
# ۶۶ جفتی، ۶ عدد بود — پس ۱۵ همچنان دو و نیم برابرِ نویز است.
MIN_ALIGNED_HASHES = 15

# چند عدد هم‌راستا در هر ثانیه یعنی «یقین».
#
# ## چرا امتیاز از نو نوشته شد
#
# پیش‌تر `aligned / len(query)` بود. هر دو با درازای کلیپ خطی
# بزرگ می‌شوند، پس نسبتشان ثابت می‌ماند — اندازه‌گیری نشان داد
# حدود ۰٫۰۳ برای هر درازایی. یعنی `CONFIDENCE_STRONG = 0.30`
# دست‌نیافتنی بود و **تطبیق‌های درست با «۳٪» به کاربر نشان داده
# می‌شدند**.
#
# اکنون بر پایهٔ نرخ در ثانیه سنجیده می‌شود: کلیپ پاک به ۱۰۰٪
# می‌رسد و کلیپ در نویز سنگین حدود ۴۰٪ — همان چیزی که کاربر
# باید ببیند.
CONFIDENCE_RATE = 20.0

# بهترین نوا باید دست‌کم این‌قدر از نفر دوم جلوتر باشد.
#
# لایهٔ اثر انگشت تنها لایه‌ای بود که هیچ سنجش نسبی نداشت — حال
# آنکه «قطعی» خوانده می‌شد. خطِ آهنگ و رنگ آوا هر دو آزمون حاشیه
# دارند.
# سنجیده شد: با ۲٫۰ تطبیق‌های درست رد می‌شدند. نوای درست ۱۶۹ عدد
# می‌گرفت و نفر دوم ۹۰ — که با آرشیوی از نواهای هم‌سبک، عادی است —
# و ۱۶۹ < ۱۸۰ یعنی رد. ۱٫۲۵ تنها «دو نامزدِ سرشانه‌به‌شانه» را
# می‌گیرد، نه برندهٔ روشن را.
MIN_LEAD_OVER_RUNNER_UP = 1.25

# آستانه‌های اطمینان — همان‌ها که در پیام به کاربر نشان داده می‌شود
CONFIDENCE_STRONG = 0.30
CONFIDENCE_WEAK = 0.08


@dataclass(frozen=True)
class Match:
    """یک تطبیق یافته‌شده."""

    track_id: int
    aligned_hashes: int      # شمار عددهای هم‌راستا
    total_query_hashes: int
    offset_ms: int           # جای تکه در نوا
    score: float             # نسبت هم‌راستایی، بین ۰ و ۱

    @property
    def confidence(self) -> float:
        """
        اطمینان میان ۰ و ۱، برای نمایش به کاربر.

        نسبت خام هم‌راستایی هرگز به یک نمی‌رسد — حتی در تطبیق
        بی‌نقص، بخشی از عددهای تکه به سبب برش لبه‌ها گم می‌شوند.
        پس نسبت را بر آستانهٔ «تطبیق نیرومند» می‌سنجیم تا عددی که
        به کاربر نشان داده می‌شود با دریافت او از «چقدر مطمئن»
        هم‌خوان باشد.
        """
        # امتیاز از پیش میان ۰ و ۱ است و معنای «چقدر پرمایه»
        # را دارد؛ تقسیم دوباره‌اش بر آستانه، عددی می‌ساخت که
        # همیشه یا صفر بود یا یک.
        return float(min(1.0, max(0.0, self.score)))

    @property
    def is_strong(self) -> bool:
        return self.score >= CONFIDENCE_STRONG

    @property
    def offset_seconds(self) -> float:
        return self.offset_ms / 1000.0


def _score(aligned: int, query: Fingerprint) -> float:
    """
    امتیاز هم‌راستایی، میان ۰ و ۱.

    ## چرا نه `aligned / len(query)`

    آن فرمول پیشین بود و غلط: هم صورت و هم مخرج با درازای کلیپ
    خطی بزرگ می‌شوند، پس نسبتشان با هر درازایی ثابت می‌ماند.
    اندازه‌گیری روی کلیپ‌های ۱۰ تا ۸۰ ثانیه‌ای، همگی حدود ۰٫۰۳
    دادند — یعنی آستانهٔ «نیرومند» (۰٫۳۰) دست‌نیافتنی بود و
    **کاربر برای پاسخ درست «۳٪» می‌دید**.

    اکنون نرخ در ثانیه سنجیده می‌شود، که راستی می‌گوید این تکه
    چقدر پرمایه با نمایه خوانده است.
    """
    seconds = max(query.duration_ms / 1000.0, 1.0)
    return float(min(1.0, aligned / (seconds * CONFIDENCE_RATE)))


def match(query: Fingerprint, min_aligned: int = MIN_ALIGNED_HASHES) -> Match | None:
    """
    بهترین تطبیق را در گنجینه می‌جوید.

    None یعنی هیچ نوایی به اندازهٔ بسنده هم‌راستا نبود.
    """
    found, _weak = match_and_weak(query, min_aligned=min_aligned, weak_limit=0)
    return found


def match_and_weak(
    query: Fingerprint,
    min_aligned: int = MIN_ALIGNED_HASHES,
    weak_limit: int = 5,
    weak_min_aligned: int = 1,
) -> tuple[Match | None, list[Match]]:
    """
    هم بهترین تطبیق، هم تطبیق‌های نازک — با **یک** بار پرسیدن از گنجینه.

    بازگشتی: ‎(بهترین تطبیق یا None، فهرست تطبیق‌های نازک)‎

    ## چرا این تابع هست

    مسیر جست‌وجو هر دو را می‌خواست و هر کدام را جدا می‌پرسید: یک بار
    `match()` و یک بار `match_many()`. هر فراخوان یک `lookup_matches`
    است — پرس‌وجوی SQLite روی هزاران عدد اثر انگشت، و گران‌ترین گامِ
    دیتابیس در کل بازجویی. یعنی همان کار، دو بار.

    بافهٔ هم‌ترازی هم دو بار ساخته می‌شد. اکنون یک بار ساخته و دو بار
    خوانده می‌شود.
    """
    if len(query) == 0:
        return None, []

    track_ids, deltas = fp_store.lookup_matches(query.hashes, query.offsets)
    if track_ids.size == 0:
        logger.debug("هیچ عدد مشترکی با گنجینه یافت نشد.")
        return None, []

    table = _alignment_table(track_ids, deltas)

    weak: list[Match] = []
    if weak_limit > 0:
        weak = [
            Match(
                track_id=track_id,
                aligned_hashes=aligned,
                total_query_hashes=len(query),
                offset_ms=offset_ms,
                score=_score(aligned, query),
            )
            for track_id, aligned, offset_ms in _top_alignments(
                table, weak_limit, weak_min_aligned
            )
        ]

    ranked = _top_alignments(table, limit=2, min_aligned=min_aligned)
    if not ranked:
        return None, weak

    track_id, aligned, offset_ms = ranked[0]
    score = _score(aligned, query)

    # ── آزمون نسبت با نفر دوم ───────────────────────────────
    #
    # لایهٔ اثر انگشت تنها لایه‌ای بود که هیچ سنجش نسبی نداشت،
    # حال آنکه «قطعی» خوانده می‌شود و بر همه می‌چربد. اگر دو نوا
    # نزدیک به هم امتیاز بگیرند، هیچ‌کدام قطعی نیست.
    #
    # نفر دوم از همان بافه برداشته می‌شود. برداشتن ردیف‌های نوای
    # برنده، بافهٔ نواهای دیگر را دگرگون نمی‌کند — چون ستون‌ها
    # درون هر نوا جدا شمرده و تنها با همسایهٔ **همان نوا** جمع
    # می‌شوند. پس این، همان پاسخِ پیشین است با یک مرتب‌سازی کمتر.
    #
    # تنها نامزدِ **راستین** به شمار می‌آید. اگر نفر دوم خودش زیر
    # آستانهٔ پذیرش باشد، نویز است نه رقیب — و سنجیدن فاصله با
    # نویز، تطبیق‌های درستِ پرنویز را رد می‌کرد. آزمون زنده: با
    # سنجشِ نفر دومِ زیرآستانه، نرخ یافتن در نویز ۰dB از ۹۶٪ به
    # ۵۶٪ افتاد. پس `min_aligned` در همان فراخوان بالا به کار
    # رفته و نفر دومِ زیرآستانه اصلاً بیرون نمی‌آید.
    if len(ranked) > 1:
        second_track, second, _second_offset = ranked[1]
        if aligned < second * MIN_LEAD_OVER_RUNNER_UP:
            logger.info(
                "تطبیق رد شد: نوای %s با %s عدد، ولی نوای %s با %s — "
                "فاصله بس نیست.",
                track_id, aligned, second_track, second,
            )
            return None, weak

    logger.debug(
        "بهترین تطبیق: نوای %s با %s عدد هم‌راستا از %s (امتیاز %.3f)",
        track_id, aligned, len(query), score,
    )

    return (
        Match(
            track_id=track_id,
            aligned_hashes=aligned,
            total_query_hashes=len(query),
            offset_ms=offset_ms,
            score=score,
        ),
        weak,
    )


def _alignment_table(
    track_ids: np.ndarray, deltas: np.ndarray
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """
    بافهٔ هم‌ترازی: برای هر جفتِ (نوا، خانهٔ زمانی)، بلندی ستون.

    بازگشتی: (نواها، بلندی ستون‌ها، خانه‌ها) — سه آرایهٔ هم‌درازا.

    گران‌ترین گامِ این ماژول همین `lexsort` است، و پیش‌تر برای هر
    پرسش از نو انجام می‌شد. اکنون یک بار ساخته و چند بار خوانده
    می‌شود.
    """
    bins = np.floor_divide(deltas, DELTA_BIN_MS)

    # جفتِ (نوا، خانه) را به یک کلید یکتا می‌فشاریم تا با یک بار
    # مرتب‌سازی، شمارش هر دو با هم انجام شود.
    order = np.lexsort((bins, track_ids))
    sorted_tracks = track_ids[order]
    sorted_bins = bins[order]

    # مرز جایی است که نوا یا خانه دگرگون می‌شود
    boundaries = np.flatnonzero(
        (sorted_tracks[1:] != sorted_tracks[:-1]) | (sorted_bins[1:] != sorted_bins[:-1])
    )
    starts = np.concatenate(([0], boundaries + 1))
    ends = np.concatenate((boundaries + 1, [sorted_tracks.size]))
    counts = ends - starts

    group_tracks = sorted_tracks[starts]
    group_bins = sorted_bins[starts]

    # هر ستون با همسایهٔ راستش جمع می‌شود، چون برشِ ناهم‌تراز
    # می‌تواند یک خوشه را میان دو خانهٔ کنار هم بشکند.
    merged = counts.copy()
    same_track = group_tracks[1:] == group_tracks[:-1]
    adjacent = group_bins[1:] == group_bins[:-1] + 1
    pairable = same_track & adjacent
    merged[:-1][pairable] = counts[:-1][pairable] + counts[1:][pairable]

    return group_tracks, merged, group_bins


def _top_alignments(
    table: tuple[np.ndarray, np.ndarray, np.ndarray],
    limit: int,
    min_aligned: int,
) -> list[tuple[int, int, int]]:
    """
    برترین ستون‌های بافه، هر نوا تنها یک بار.

    بازگشتی: فهرست (شناسهٔ نوا، بلندی ستون، فاصله بر حسب میلی‌ثانیه)،
    از بلند به کوتاه.

    ## چرا برداشتنِ نوای برنده لازم نیست

    روشِ پیشین پس از هر برداشت، ردیف‌های نوای برنده را از آرایه
    بیرون می‌کشید و بافه را از نو می‌ساخت. کارِ بیهوده بود: ستون‌ها
    درون هر نوا جدا شمرده می‌شوند و تنها با همسایهٔ **همان نوا**
    جمع می‌گردند، پس برداشتن یک نوا بلندی ستون‌های نواهای دیگر را
    ذره‌ای تکان نمی‌دهد. همان پاسخ، با یک مرتب‌سازی به جای چند تا.
    """
    group_tracks, merged, group_bins = table
    if limit <= 0 or merged.size == 0:
        return []

    # `-merged` با مرتب‌سازیِ پایدار، یعنی نزولی و در برابری،
    # نخستین ستون برنده — همان رفتارِ `argmax` پیشین. وارونه کردنِ
    # مرتب‌سازیِ صعودی، در برابری **آخرین** را برمی‌گرداند و
    # می‌توانست خاموش جای برنده را عوض کند.
    order = np.argsort(-merged, kind="stable")

    out: list[tuple[int, int, int]] = []
    seen: set[int] = set()
    for index in order:
        aligned = int(merged[index])
        if aligned < min_aligned:
            break  # مرتب است؛ از اینجا به بعد همه کوتاه‌ترند
        track_id = int(group_tracks[index])
        if track_id in seen:
            continue
        seen.add(track_id)
        out.append((track_id, aligned, int(group_bins[index] * DELTA_BIN_MS)))
        if len(out) >= limit:
            break

    if not out:
        logger.debug(
            "بلندترین ستون تنها %s بود؛ کمتر از کمینهٔ %s.",
            int(merged.max()), min_aligned,
        )
    return out


def match_many(
    query: Fingerprint, limit: int = 3, min_aligned: int = MIN_ALIGNED_HASHES
) -> list[Match]:
    """
    چند تطبیق برتر را برمی‌گرداند، هر نوا تنها یک بار.

    برای هنگامی که اطمینان کم است و به جای یک پاسخ قطعی، چند
    گزینه پیش روی کاربر گذاشته می‌شود.
    """
    if len(query) == 0:
        return []

    track_ids, deltas = fp_store.lookup_matches(query.hashes, query.offsets)
    if track_ids.size == 0:
        return []

    table = _alignment_table(track_ids, deltas)
    return [
        Match(
            track_id=track_id,
            aligned_hashes=aligned,
            total_query_hashes=len(query),
            offset_ms=offset_ms,
            score=_score(aligned, query),
        )
        for track_id, aligned, offset_ms in _top_alignments(table, limit, min_aligned)
    ]
