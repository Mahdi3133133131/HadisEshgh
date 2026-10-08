"""
اثر انگشت صوتی — الگوریتم نشانه‌ای (landmark).

## چگونه کار می‌کند

۱. موج صوتی به طیف‌نگار دگرگون می‌شود: نمودار توان در هر بسامد،
   در هر لحظه.
۲. «قله‌ها» یافته می‌شوند — نقطه‌هایی که در همسایگی خود بلندترین‌اند.
   قله‌ها در برابر نویز، فشرده‌سازی و بلندی صدا پایدارند؛ همین است
   که این روش را کارآمد می‌کند.
۳. هر قله با چند قلهٔ پس از خود جفت می‌شود و از هر جفت یک عدد
   ساخته می‌گردد: (بسامد نخست، بسامد دوم، فاصلهٔ زمانی).
۴. همان عدد با زمانِ رخدادش در پایگاه داده می‌نشیند.

هنگام بازجویی، همین کار روی تکهٔ فرستاده‌شده انجام می‌شود و
عددهایش با گنجینه سنجیده می‌شود. اگر تکه براستی از نوایی بریده
شده باشد، ده‌ها عدد مشترک پیدا می‌شوند و — مهم‌تر از آن — همگی
با **فاصلهٔ زمانی یکسان** جور درمی‌آیند. همین یکسانی فاصله است که
تطبیق راستین را از هم‌آمدنِ تصادفی جدا می‌کند.

## آنچه این روش می‌تواند و آنچه نمی‌تواند

می‌تواند: تکه‌ای بریده از **همان ضبط** را بیابد، حتی با نویز،
فشرده‌سازی سنگین، یا صدای پس‌زمینه.

نمی‌تواند: اجرای دیگری از همان نوا را بیابد. اگر کاربر تکه‌ای از
اجرای زنده بفرستد و در گنجینه نسخهٔ دیگری باشد، هیچ عدد مشترکی
پدید نمی‌آید. این کاستی ذاتی روش است، نه ایراد پیاده‌سازی.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import numpy as np
from scipy import ndimage, signal

from core.audio.decode import SAMPLE_RATE

logger = logging.getLogger(__name__)

# ── پارامترهای طیف‌نگار ──────────────────────────────────────
WINDOW_SIZE = 1024                     # ≈ ۹۳ میلی‌ثانیه در نرخ ۱۱۰۲۵
HOP_SIZE = 512                         # نیم‌پوشانی → ≈ ۲۱٫۵ قاب در ثانیه
MS_PER_FRAME = 1000 * HOP_SIZE / SAMPLE_RATE   # ≈ ۴۶٫۴ میلی‌ثانیه

# ── نسخهٔ اثر انگشت ─────────────────────────────────────────
#
# با هر دگرگونیِ الگوریتم، این عدد بالا می‌رود و همهٔ نواها از نو
# نمایه می‌شوند. اثر انگشتِ نسخهٔ کهنه با نسخهٔ تازه هم‌خوان نیست و
# آمیختنشان یعنی هیچ‌کدام کار نکند.
FINGERPRINT_VERSION = 2

# ── یافتن قله ───────────────────────────────────────────────
# همسایگی‌ای که هر قله باید در آن بلندترین باشد.
#
# پهنای زمانی از ۲۰ قاب (۹۲۹ میلی‌ثانیه!) به ۸ آمد. آن پهنا در
# واحد فیزیکی به‌شدت نامتقارن بود — ±۱۰۷ هرتز ولی ±۴۶۴ میلی‌ثانیه —
# و چون در هر پنجرهٔ ۲۰ قابی تنها یک قاب برنده می‌شد، جابه‌جا شدنِ
# شبکه، **برندهٔ همه‌جا** را عوض می‌کرد. قله‌های چگال‌تر و
# پایدارتر، همان چیزی است که این موتور کم داشت.
# سنجیده شد: با (۱۲، ۸) چگالی به ۳۲۴ عدد در ثانیه می‌رسید —
# هفت برابرِ پیش — و نوای بیگانه ۲۲ عدد هم‌راستا می‌گرفت، یعنی
# بالاتر از آستانهٔ پذیرش. قله‌های انبوه، هش را بی‌معنا می‌کنند.
PEAK_NEIGHBORHOOD_FREQ = 24
PEAK_NEIGHBORHOOD_TIME = 16

# قله‌هایی که از این اندازه کم‌توان‌ترند دور ریخته می‌شوند.
# پس از سفیدسازی سنجیده می‌شود، پس دیگر به بلندی صدا و به درازای
# فایل وابسته نیست.
PEAK_PERCENTILE = 85.0

# پهنای پنجرهٔ سفیدسازی، بر حسب خانهٔ بسامد.
#
# میانهٔ متحرکِ هر باند از خودش کم می‌شود. این هم نویز پس‌زمینه را
# برمی‌دارد و هم آستانه را از محتوا مستقل می‌کند — پیش‌تر آستانهٔ
# نمایه (روی کل فایل) و آستانهٔ پرس‌وجو (روی ده ثانیه) با هم فرق
# داشتند و همان، بخشی از ناهم‌خوانی بود.
WHITEN_BAND = 33

# ── جفت‌سازی ────────────────────────────────────────────────
#
# چگالی نامتقارن — یکی از سودمندترین تصمیم‌های این موتور.
#
# قله‌ها در هر دو سو یکسانند، ولی شمار جفت‌ها نه: گنجینه با جفت‌های
# اندک ذخیره می‌شود و بازجویی با جفت‌های پرشمار پرسیده می‌گردد.
# چون تطبیق تنها می‌خواهد عددهای بازجویی به عددهای ذخیره‌شده
# بخورند، بازجویی پرجفت همان تطبیق‌ها را می‌یابد در حالی که گنجینه
# یک‌چهارم فضا می‌گیرد.
#
# سنجیده شده روی ۶۰ نوا: چگالی از ۱۶۸ به ۴۱ عدد در ثانیه افتاد
# (۴ گیگابایت به ۱ گیگابایت برای ۵۰۰۰ نوا) و دقت تکهٔ ده‌ثانیه‌ای
# حتی در نویز سنگین، ۵۸ از ۶۰ ماند.
FAN_OUT_INDEX = 3           # هنگام نشاندن در گنجینه
FAN_OUT_QUERY = 10          # هنگام بازجویی

MIN_TIME_DELTA = 1          # قاب
MAX_TIME_DELTA = 43         # قاب ≈ ۲ ثانیه

# بیشترین فاصلهٔ بسامدی میان دو قلهٔ یک جفت، بر حسب خانه.
#
# ناحیهٔ هدف باید **کران‌دار** باشد، وگرنه لنگر با قله‌ای در آن
# سرِ طیف جفت می‌شود و آن جفت هیچ معنای موسیقایی ندارد.
MAX_FREQ_DELTA = 96

# تا این اندازه در فهرست قله‌ها جلو می‌رویم تا هدف‌های ناحیه را
# بیابیم. کران‌دار است تا حلقه بر فایل بلند از پا درنیاید.
SEARCH_SPAN = 16

# جابه‌جایی‌های زیرقابی که پرس‌وجو در آن‌ها اثر انگشت می‌خورد.
#
# ## چرا این، مهم‌ترین تکهٔ این تعمیر است
#
# کلیپ کاربر از نمونهٔ دلخواهی آغاز می‌شود، پس شبکهٔ STFT او تا
# نیم گام (۲۵۶ نمونه) با شبکهٔ نمایه فرق دارد. اندازه‌گیری: همان
# صوت، هم‌تراز ۴۳۱ عدد هم‌راستا داد و با ۲۵۶ نمونه جابه‌جایی ۱۵ تا.
#
# با چهار جابه‌جایی، یکی از آن‌ها همیشه به شبکهٔ نمایه نزدیک است.
# بهایش تنها سمت پرس‌وجوست — کلیپ کوتاه است — نه سمت نمایه.
QUERY_OFFSETS = (0, 128, 256, 384)

# کلیپ کوتاه‌تر از این، با شبکهٔ چگال‌تری سنجیده می‌شود.
#
# پنج ثانیه عددهای کمی می‌دهد و هر عددی که به سبب ناهم‌ترازی گم
# شود، سهم بزرگ‌تری از کل است. هشت نقطهٔ شروع به جای چهار، همان
# جبران را می‌کند — و چون کلیپ کوتاه است، بهایش ناچیز.
SHORT_QUERY_SECONDS = 8.0
QUERY_OFFSETS_DENSE = (0, 64, 128, 192, 256, 320, 384, 448)

# نرخ‌هایی که پس از ناکامیِ نرخِ یک آزموده می‌شوند.
#
# ## چرا
#
# اثر انگشت بر بسامدِ قله‌ها استوار است، و تغییر سرعت هر دو بسامد
# و فاصلهٔ زمانی را جابه‌جا می‌کند. اندازه‌گیری، سختیِ کار را نشان
# می‌دهد — کلیپ ۱۵ ثانیه‌ای، آستانهٔ ۱۵:
#
#     ۰٪ سرعت  ۵۹۳ عدد هم‌راستا   ✓
#     ۱٪ سرعت    ۹ عدد            ✗ ناکام
#     ۲٪ سرعت    ۲ عدد            ✗ ناکام
#
# یعنی **یک درصد** بس است. ریلزهای اینستاگرام و ویدیوهای بازفشرده
# تقریباً همیشه چنین‌اند، پس این تنها یک حالتِ کناری نیست.
#
# ═══════════════════════════════════════════════════════════
#   گامِ ۱٪ سنجیده شده است، نه گمانه‌زده
# ═══════════════════════════════════════════════════════════
#
# نخستین گمانِ من گامِ ۳٪ بود. سنجش ردش کرد: کلیپِ ۳٪ تندشده با
# نرخِ ۰٫۹۷ یافته می‌شد، ولی ۲٪ و ۴٪ و ۵٪ همچنان ناکام می‌ماندند —
# نرخ‌ها سوراخ داشتند.
#
# پس پهنای پذیرش اندازه گرفته شد: کلیپِ ۳٪ تندشده، با جاروی ریزِ
# نرخِ جبران —
#
#     نرخ ۰٫۹۶۲۵ →  ۱۲ عدد
#     نرخ ۰٫۹۶۵۰ →  ۲۸ عدد   ✓ آغازِ پنجره
#     نرخ ۰٫۹۷۰۰ → ۲۸۰ عدد   ← نرخِ درست
#     نرخ ۰٫۹۷۷۵ →  ۱۹ عدد   ✓ پایانِ پنجره
#     نرخ ۰٫۹۸۰۰ →   ۸ عدد
#
# پنجره از ۰٫۹۶۵ تا ۰٫۹۷۸ باز است — نیم‌پهنای **۰٫۶٪**. پس گام
# باید کمتر از ۱٫۲٪ باشد تا پنجره‌ها هم‌پوشانی کنند و سوراخی
# نماند. گامِ ۱٪ با اندکی حاشیهٔ ایمنی برگزیده شد.
#
# **پله‌ای، و به ترتیبِ بخت:** این‌ها تنها آنگاه آزموده می‌شوند که
# نرخِ یک چیزی نیافته باشد، و از نزدیک‌ترین به دورترین — چون
# دگرگونیِ خُرد (بازفشردنِ ساده) بسیار رایج‌تر از ویرایشِ عمدی
# است. نخستین یافته کار را می‌بندد، پس بیشترِ کلیپ‌ها یکی دو نرخ
# بیشتر نمی‌روند.
QUERY_RATES = (
    0.99, 1.01, 0.98, 1.02, 0.97, 1.03,
    0.96, 1.04, 0.95, 1.05, 0.94, 1.06,
)

# ── بسته‌بندی عدد ───────────────────────────────────────────
# ۱۰ بیت بسامد نخست | ۱۰ بیت بسامد دوم | ۱۲ بیت فاصله = ۳۲ بیت
_FREQ_BITS = 10
_DELTA_BITS = 12
_FREQ_MASK = (1 << _FREQ_BITS) - 1
_DELTA_MASK = (1 << _DELTA_BITS) - 1

MIN_CLIP_SECONDS = 3.0


@dataclass(frozen=True)
class Fingerprint:
    """اثر انگشت یک قطعهٔ صوتی."""

    hashes: np.ndarray    # آرایهٔ int64 از عددهای بسته‌بندی‌شده
    offsets: np.ndarray   # آرایهٔ int32، زمان هر عدد بر حسب میلی‌ثانیه
    duration_ms: int
    peak_count: int

    def __len__(self) -> int:
        return int(self.hashes.size)

    @property
    def density(self) -> float:
        """شمار عدد در هر ثانیه — سنجه‌ای برای سلامت اثر انگشت."""
        if self.duration_ms <= 0:
            return 0.0
        return len(self) * 1000.0 / self.duration_ms


class FingerprintError(RuntimeError):
    """ساختن اثر انگشت شدنی نبود."""


def spectrogram(samples: np.ndarray) -> np.ndarray:
    """
    طیف‌نگار توان بر حسب دسی‌بل.

    پنجرهٔ هَن به کار رفته تا نشتِ بسامدی کاسته شود؛ بی آن، قله‌ها
    پخش می‌شوند و جایگاهشان میان اجراها ناپایدار می‌گردد.
    """
    if samples.size < WINDOW_SIZE:
        raise FingerprintError("قطعهٔ صوتی از یک پنجره هم کوتاه‌تر است.")

    _, _, stft = signal.stft(
        samples,
        fs=SAMPLE_RATE,
        window="hann",
        nperseg=WINDOW_SIZE,
        noverlap=WINDOW_SIZE - HOP_SIZE,
        boundary=None,
        padded=False,
    )
    magnitude = np.abs(stft)
    # کف کوچکی افزوده می‌شود تا لگاریتم صفر پدید نیاید
    return 20.0 * np.log10(magnitude + 1e-10)


def whiten(spec: np.ndarray) -> np.ndarray:
    """
    میانهٔ متحرکِ هر باند را از خودش کم می‌کند.

    ## چرا

    طیفِ خام دو مشکل دارد: نویزِ پس‌زمینه و کوبشِ بم، هر دو کفِ
    طیف را بالا می‌برند و آستانهٔ سراسری را با خود می‌کشند؛ و
    آستانه به **محتوا و درازای** فایل وابسته می‌شود، پس نمایه (کل
    فایل) و پرس‌وجو (ده ثانیه) با دو آستانهٔ متفاوت کار می‌کنند.

    کم کردن میانهٔ متحرک هر دو را می‌برد: آنچه می‌ماند «چقدر این
    خانه از همسایگانش بلندتر است»، و آن، مستقل از بلندی صداست.
    """
    if spec.shape[0] < 3:
        return spec
    background = ndimage.median_filter(
        spec, size=(WHITEN_BAND, 1), mode="nearest"
    )
    return spec - background


def find_peaks(spec: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """
    قله‌های طیف را می‌یابد.

    بازگشتی: (شمارهٔ بسامد، شمارهٔ قاب) — هر دو مرتب بر پایهٔ زمان.

    مرتب بودن بر پایهٔ زمان برای جفت‌سازی بایسته است؛ وگرنه «قلهٔ
    پسین» معنایی ندارد.
    """
    # طیف نخست سفید می‌شود؛ از آن پس «بلند» یعنی «بلندتر از
    # همسایگانش»، نه «بلندتر از کلِ فایل».
    spec = whiten(spec)

    neighborhood = (PEAK_NEIGHBORHOOD_FREQ, PEAK_NEIGHBORHOOD_TIME)
    local_max = ndimage.maximum_filter(spec, size=neighborhood, mode="constant", cval=-np.inf)

    threshold = np.percentile(spec, PEAK_PERCENTILE)
    peaks = (spec == local_max) & (spec > threshold)

    freq_idx, time_idx = np.nonzero(peaks)
    if freq_idx.size == 0:
        return freq_idx.astype(np.int32), time_idx.astype(np.int32)

    order = np.argsort(time_idx, kind="stable")
    return freq_idx[order].astype(np.int32), time_idx[order].astype(np.int32)


def _pack(freq1: np.ndarray, freq2: np.ndarray, delta: np.ndarray) -> np.ndarray:
    """سه مقدار را در یک عدد ۳۲ بیتی می‌فشارد."""
    return (
        ((freq1.astype(np.int64) & _FREQ_MASK) << (_FREQ_BITS + _DELTA_BITS))
        | ((freq2.astype(np.int64) & _FREQ_MASK) << _DELTA_BITS)
        | (delta.astype(np.int64) & _DELTA_MASK)
    )


def pair_peaks(
    freq_idx: np.ndarray, time_idx: np.ndarray, fan_out: int = FAN_OUT_QUERY
) -> tuple[np.ndarray, np.ndarray]:
    """
    هر لنگر را با قله‌هایی که در **ناحیهٔ هدفِ** او هستند جفت می‌کند.

    بازگشتی: (عددها، زمان قلهٔ لنگر بر حسب قاب)

    ## چرا ناحیه‌ای، و نه گامی

    پیش‌تر هر قله با قلهٔ `i+step` جفت می‌شد — یعنی بر پایهٔ
    **شمارهٔ اندیس** در فهرست قله‌ها. آن روش یک ضعف کشنده دارد: اگر
    یک قله بیفتد (که با اندکی نویز یا جابه‌جایی شبکه همیشه می‌افتد)،
    *همهٔ* جفت‌های پس از آن جابه‌جا می‌شوند و هیچ‌کدام دیگر با نمایه
    نمی‌خوانند.

    جفت‌سازی ناحیه‌ای بر پایهٔ **جای زمانی-بسامدی** است: لنگر با هر
    قله‌ای که در بازهٔ زمانی و بسامدی‌اش باشد جفت می‌شود. افتادن یک
    قله تنها همان چند جفت را می‌برد، نه همه را. اُفتِ دقت خطی
    می‌شود به جای فروپاشی.

    اندازه‌گیری، همان کلیپ با نیم‌قاب جابه‌جایی: ۱۵ عدد هم‌راستا با
    روش گامی، در برابر آنچه اکنون می‌بینید.

    ## چرا هنوز کران‌دار است

    `SEARCH_SPAN` جلوی حلقه را می‌گیرد و `fan_out` شمار جفت‌های هر
    لنگر را. بی این دو، فایل یک‌ساعته میلیون‌ها جفت می‌سازد.
    """
    count = freq_idx.size
    if count < 2:
        empty_hash = np.empty(0, dtype=np.int64)
        return empty_hash, np.empty(0, dtype=np.int32)

    freqs = freq_idx.astype(np.int32)
    times = time_idx.astype(np.int32)

    hash_chunks: list[np.ndarray] = []
    anchor_chunks: list[np.ndarray] = []
    rank_chunks: list[np.ndarray] = []
    index_chunks: list[np.ndarray] = []

    # قله‌ها بر زمان مرتب‌اند، پس هدف‌های یک لنگر همیشه پس از او
    # می‌آیند. جهش در اندیس تنها راهِ **رسیدن** به آن‌هاست؛ خودِ
    # پذیرش با بازهٔ زمانی و بسامدی سنجیده می‌شود، نه با شمارهٔ جهش.
    for step in range(1, SEARCH_SPAN + 1):
        if step >= count:
            break

        anchor_f = freqs[:-step]
        anchor_t = times[:-step]
        target_f = freqs[step:]
        target_t = times[step:]

        delta = target_t - anchor_t
        keep = (
            (delta >= MIN_TIME_DELTA)
            & (delta <= MAX_TIME_DELTA)
            & (np.abs(target_f - anchor_f) <= MAX_FREQ_DELTA)
        )
        if not keep.any():
            continue

        picked = np.flatnonzero(keep)
        hash_chunks.append(_pack(anchor_f[picked], target_f[picked], delta[picked]))
        anchor_chunks.append(anchor_t[picked])
        # برای گزینشِ نزدیک‌ترین‌ها به ازای هر لنگر
        rank_chunks.append(delta[picked])
        index_chunks.append(picked)

    if not hash_chunks:
        return np.empty(0, dtype=np.int64), np.empty(0, dtype=np.int32)

    hashes = np.concatenate(hash_chunks)
    anchors = np.concatenate(anchor_chunks).astype(np.int32)
    deltas = np.concatenate(rank_chunks)
    owners = np.concatenate(index_chunks)

    # ── نگه داشتن fan_out نزدیک‌ترین هدف به ازای هر لنگر ──────
    #
    # بی این، لنگری که در ناحیه‌اش سی قله دارد سی جفت می‌سازد و
    # لنگرِ تنها هیچ — و چگالی نمایه از دست می‌رود. نزدیک‌ترین‌ها
    # برگزیده می‌شوند چون پایدارترین‌اند.
    order = np.lexsort((deltas, owners))
    owners = owners[order]
    hashes = hashes[order]
    anchors = anchors[order]

    starts = np.zeros(owners.size, dtype=np.int64)
    if owners.size:
        boundaries = np.flatnonzero(owners[1:] != owners[:-1]) + 1
        starts[boundaries] = boundaries
        np.maximum.accumulate(starts, out=starts)
    rank = np.arange(owners.size, dtype=np.int64) - starts
    keep = rank < fan_out

    hashes = hashes[keep]
    anchors = anchors[keep]

    order = np.argsort(anchors, kind="stable")
    return hashes[order], anchors[order]


def fingerprint(samples: np.ndarray, fan_out: int = FAN_OUT_QUERY) -> Fingerprint:
    """
    از موج صوتی، اثر انگشت می‌سازد.

    این تنها درگاهی است که لایه‌های بالاتر باید بشناسند.

    fan_out را برای نشاندن در گنجینه FAN_OUT_INDEX و برای بازجویی
    FAN_OUT_QUERY بگذارید — شرحش در بالای همین پرونده آمده است.
    پیش‌فرض، حالت بازجویی است، چون فراموش کردنش آنجا تنها کندی
    می‌آورد نه نادرستی.
    """
    duration_ms = int(samples.size * 1000 / SAMPLE_RATE)

    if samples.size < MIN_CLIP_SECONDS * SAMPLE_RATE:
        raise FingerprintError(
            f"قطعهٔ صوتی کوتاه‌تر از {MIN_CLIP_SECONDS:.0f} ثانیه است "
            f"({duration_ms / 1000:.1f} ثانیه)."
        )

    spec = spectrogram(samples)
    freq_idx, time_idx = find_peaks(spec)

    if freq_idx.size < 2:
        raise FingerprintError(
            "قلهٔ بسنده‌ای یافت نشد؛ شاید صوت خاموش یا یکنواخت است."
        )

    hashes, anchors = pair_peaks(freq_idx, time_idx, fan_out)
    if hashes.size == 0:
        raise FingerprintError("هیچ جفتی از قله‌ها ساخته نشد.")

    offsets = np.round(anchors * MS_PER_FRAME).astype(np.int32)

    return Fingerprint(
        hashes=hashes,
        offsets=offsets,
        duration_ms=duration_ms,
        peak_count=int(freq_idx.size),
    )


def resample(samples: np.ndarray, rate: float) -> np.ndarray:
    """
    کلیپ را `rate` برابر تندتر می‌کند.

    `rate` بزرگ‌تر از یک، صوت را می‌فشرد (تندتر و زیرتر)؛ کوچک‌تر
    از یک، می‌کشدش. پس برای جبرانِ کلیپی که ۳٪ تند شده،
    `rate = 0.97` به کار می‌رود.

    درون‌یابیِ خطی است، نه بازنمونه‌برداریِ درست — و همین بس است:
    کتابخانهٔ تازه‌ای نمی‌خواهد (خواستهٔ صریح)، و در بازهٔ باریکِ
    ±۶٪ که اینجا به کار می‌رود، نقطه‌های نمونه نزدیکِ درست‌اند و
    ناهنجاریِ برهم‌نشینی ناچیز است. قله‌های طیفی — که تنها چیزِ
    مهم برای اثر انگشت‌اند — سر جای خود می‌مانند.
    """
    if rate == 1.0:
        return samples
    count = int(round(samples.size / rate))
    if count < 2:
        raise FingerprintError("کلیپ برای بازنمونه‌برداری کوتاه است.")
    return np.interp(
        np.linspace(0.0, samples.size - 1.0, count),
        np.arange(samples.size, dtype=np.float64),
        samples.astype(np.float64),
    ).astype(np.float32)


def fingerprint_query(
    samples: np.ndarray, fan_out: int = FAN_OUT_QUERY, rate: float = 1.0
) -> Fingerprint:
    """
    اثر انگشتِ **پرس‌وجو** — از چند جابه‌جایی زیرقابی، با هم.

    ## چرا این لازم است

    نمایه از آغازِ فایل قاب‌بندی می‌شود، ولی کلیپ کاربر از نمونهٔ
    دلخواهی بریده شده. پس دو شبکهٔ STFT تا نیم گام (۲۵۶ نمونه) با
    هم فرق دارند، و قله‌هایی که در یکی برنده‌اند در دیگری نیستند.

    اندازه‌گیریِ همان صوت، بی هیچ نویزی:

        هم‌تراز با قاب      ۴۳۱ عدد هم‌راستا
        ۲۵۶ نمونه جابه‌جا    ۱۵ عدد

    یعنی ۹۶٪ نابودی، تنها به خاطر جایی که کاربر برش زده.

    چاره: کلیپ در چند جابه‌جایی اثر انگشت می‌خورد و همه با هم
    جست‌وجو می‌شوند. یکی از آن‌ها همیشه به شبکهٔ نمایه نزدیک است.

    زمان‌ها به خط زمانیِ **خودِ کلیپ** بازگردانده می‌شوند، وگرنه
    بافهٔ هم‌ترازی چهار قلهٔ جدا می‌دید به جای یکی.

    این تنها برای پرس‌وجوست. نمایه یک بار و از نقطهٔ صفر ساخته
    می‌شود؛ چهار برابر کردنش، گنجینه را چهار برابر می‌کرد.
    """
    # درازای **راستینِ** کلیپ، پیش از هر کشیدنی. امتیاز بر این
    # سنجیده می‌شود، وگرنه کلیپی که ۶٪ کشیده شده، ۶٪ اطمینانِ
    # دروغ می‌گرفت.
    true_ms = int(round(samples.size * 1000.0 / SAMPLE_RATE))
    samples = resample(samples, rate)

    chunks: list[np.ndarray] = []
    offset_chunks: list[np.ndarray] = []
    duration_ms = 0
    peaks = 0
    last_error: Exception | None = None

    seconds = samples.size / SAMPLE_RATE
    shifts = (
        QUERY_OFFSETS_DENSE if seconds <= SHORT_QUERY_SECONDS else QUERY_OFFSETS
    )

    for shift in shifts:
        if shift >= samples.size:
            break
        try:
            piece = fingerprint(samples[shift:], fan_out)
        except FingerprintError as exc:
            last_error = exc
            continue

        shift_ms = int(round(shift * 1000.0 / SAMPLE_RATE))
        chunks.append(piece.hashes)
        offset_chunks.append(piece.offsets + shift_ms)
        duration_ms = max(duration_ms, piece.duration_ms + shift_ms)
        peaks = max(peaks, piece.peak_count)

    if not chunks:
        raise last_error or FingerprintError("اثر انگشتی ساخته نشد.")

    hashes = np.concatenate(chunks)
    offsets = np.concatenate(offset_chunks).astype(np.int32)

    # جفت‌های یکسان از دو جابه‌جایی، یک بار شمرده شوند — وگرنه
    # مخرجِ امتیاز باد می‌کند و اطمینان دروغ می‌گوید.
    #
    # ## چرا ۳۲ بیت و نه ۲۰
    #
    # کلیدِ پیشین `(hash << 20) ^ offset` بود و برای کلیپ‌های
    # کوتاه درست کار می‌کرد. ولی عدد اثر انگشت ۳۲ بیتی است و زمان
    # بر حسب میلی‌ثانیه: از ۲^۲۰ میلی‌ثانیه — یعنی ۱۷٫۵ دقیقه — به
    # بالا، زمان از خانهٔ خودش سرریز می‌کرد و روی بیت‌های عدد
    # می‌نشست. آنگاه دو جفتِ **جدا** یک کلید می‌گرفتند و یکی‌شان
    # خاموش دور ریخته می‌شد.
    #
    # با جابه‌جاییِ ۳۲ بیتی، دو خانه هیچ هم‌پوشانی ندارند و کلید
    # یک‌به‌یک است. `uint64` به کار می‌رود چون عدد ۳۲ بیتیِ
    # جابه‌جاشده از گنجایشِ int64 علامت‌دار بیرون می‌زند.
    pairs = (hashes.astype(np.uint64) << np.uint64(32)) | (
        offsets.astype(np.uint64) & np.uint64(0xFFFFFFFF)
    )
    _, unique = np.unique(pairs, return_index=True)
    unique.sort()

    return Fingerprint(
        hashes=hashes[unique],
        offsets=offsets[unique],
        duration_ms=true_ms,
        peak_count=peaks,
    )


def fingerprint_file(
    path,
    start: float | None = None,
    duration: float | None = None,
    fan_out: int = FAN_OUT_QUERY,
) -> Fingerprint:
    """فایل را رمزگشایی و اثر انگشتش را می‌سازد."""
    from core.audio.decode import decode

    samples = decode(path, start=start, duration=duration)
    return fingerprint(samples, fan_out)
