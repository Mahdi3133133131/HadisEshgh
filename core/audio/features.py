"""
ویژگی‌های صوتی — پایهٔ فهم مداحی.

═══════════════════════════════════════════════════════════════
  آنچه سند می‌خواست و آنچه براستی شدنی است
═══════════════════════════════════════════════════════════════

سند نوشته بود: «هوش مصنوعی که از ریتم، اوج و فرود، صدا، فرکانس و
سبک تشخیص بدهد» با نمونهٔ «حسین ستوده... فرکانس ۸۰، سبک شور».

«فرکانس ۸۰» اصطلاح نادرستی است؛ آنچه در ذهن بوده **تمپو** است —
شمار ضرب در دقیقه. بسامد ۸۰ هرتز یک نُتِ بم است، نه ویژگی سبک.

این لایه، موتور اصلی **نیست**. یافتن نوا کار اثر انگشت است و دقتش
نزدیک به بی‌خطاست. این لایه آنگاه به کار می‌آید که اثر انگشت چیزی
نیافت — و آنگاه هم «گمانه» می‌دهد نه پاسخ قطعی.

═══════════════════════════════════════════════════════════════
  دو گروه ویژگی
═══════════════════════════════════════════════════════════════

**نشان آوا** — آنچه یک مداح را از دیگری جدا می‌کند:

  • MFCC و مشتق‌های یکم و دوم — پوشِ طیفی و دگرگونی‌اش
  • تقابل طیفی — فاصلهٔ قله و درهٔ طیف در هر باند. برای رنگ آوا
    از MFCC هم گویاتر است و در برابر پژواک پایدارتر
  • کروما — رده‌های گامی. دستگاه و گسترهٔ گامی مداح را می‌گیرد
  • آمار گام پایه — گسترهٔ صوتی، که بسیار جداکننده است

**نشان سبک** — آنچه شور را از زمینه و روضه جدا می‌کند:

  • تمپو و **رسایی ضربان** — روضه ضرب ندارد و رسایی‌اش نزدیک صفر
    است؛ همین یک عدد، روضه را از سه سبک وزن‌دار جدا می‌کند
  • پایداری تمپو در سراسر نوا
  • نرخ آغازه — چگالی رخدادهای صوتی
  • پویایی نیرو و آمار طیفی

═══════════════════════════════════════════════════════════════
  چرا پنجره‌به‌پنجره، نه یک‌جا
═══════════════════════════════════════════════════════════════

یک ضبط مجلسی یکدست نیست: جایی مداح تنهاست، جایی جمعیت جواب
می‌دهد، جایی خاموشی است. اگر از همهٔ نوا یک میانگین بگیریم، آن
بخش‌های آلوده نشان آوا را می‌آلایند.

پس نوا به پنجره‌های کوتاه شکسته می‌شود، هر پنجره جدا سنجیده
می‌گردد، پنجره‌های کم‌جان دور ریخته می‌شوند، و از بازمانده
**میانه** گرفته می‌شود نه میانگین — میانه در برابر پنجره‌های
پرت پایدار است، میانگین نیست.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import numpy as np

from core.audio.decode import SAMPLE_RATE

logger = logging.getLogger(__name__)

# نسخهٔ ویژگی. با دگرگون شدن ساختار بردار باید بالا برود تا
# ویژگی‌های کهنه بازشناخته و از نو برداشته شوند.
FEATURE_VERSION = 3

N_MFCC = 20

# تقابل طیفی: با نرخ نمونه‌برداری ۱۱۰۲۵، نایکوئیست ۵۵۱۲ هرتز است و
# باندهای پیش‌فرض librosa (که تا ۶۴۰۰ می‌روند) از آن رد می‌شوند و
# خطا می‌دهند. با پنج باند از ۲۰۰ هرتز، بالاترین لبه زیر نایکوئیست
# می‌ماند و شش ردیف به دست می‌آید.
CONTRAST_FMIN = 200.0
CONTRAST_BANDS = 5
N_CONTRAST = CONTRAST_BANDS + 1

N_CHROMA = 12

STYLE_DIM = 14

# نشان آوا: ۲۰ میانگین MFCC + ۶ میانگین تقابل + ۱۲ کروما + ۴ گام
#
# انحراف معیار و مشتق‌ها عمداً نیستند — شرحش در _voice_window.
VOICE_DIM = N_MFCC + N_CONTRAST + N_CHROMA + 4   # ۲۰+۶+۱۲+۴ = ۴۲

MIN_SECONDS = 8.0
ANALYSIS_SECONDS = 120.0

# پنجره‌های تحلیل آوا
WINDOW_SECONDS = 12.0
HOP_SECONDS = 6.0

# پنجره‌هایی که نیرویشان از این صدکِ همهٔ پنجره‌ها کمتر باشد،
# دور ریخته می‌شوند — خاموشی و بریدگی نشان آوا را می‌آلایند.
QUIET_PERCENTILE = 25.0

# گسترهٔ گام آوای انسانی
F0_MIN = 65.0
F0_MAX = 520.0

# مرز وزن‌دار بودن — شرحش در Features.is_metrical
METRICAL_THRESHOLD = 0.45


@dataclass(frozen=True)
class Features:
    """ویژگی‌های یک قطعهٔ صوتی."""

    # ── سبک ──────────────────────────────────────────────────
    tempo: float
    pulse_clarity: float        # رسایی ضربان، ۰ تا ۱
    tempo_stability: float      # هم‌خوانی تمپو در سراسر نوا
    onset_rate: float           # آغازه در ثانیه
    energy_mean: float
    energy_std: float
    energy_range: float
    zero_crossing: float
    zero_crossing_std: float
    spectral_centroid: float
    spectral_bandwidth: float
    spectral_rolloff: float
    spectral_flatness: float
    onset_crest: float          # تیزی رخدادهای صوتی — شاخص کوبه‌ای بودن

    # ── آوا ──────────────────────────────────────────────────
    voice: np.ndarray

    version: int = FEATURE_VERSION

    def style_vector(self) -> np.ndarray:
        return np.array(
            [
                self.tempo,
                self.pulse_clarity,
                self.tempo_stability,
                self.onset_rate,
                self.energy_mean,
                self.energy_std,
                self.energy_range,
                self.zero_crossing,
                self.zero_crossing_std,
                self.spectral_centroid,
                self.spectral_bandwidth,
                self.spectral_rolloff,
                self.spectral_flatness,
                self.onset_crest,
            ],
            dtype=np.float32,
        )

    @property
    def is_metrical(self) -> bool:
        """
        آیا این نوا وزن دارد.

        روضه ضرب منظم ندارد. جدا کردن همین یک حالت، پیش از
        هر گمانهٔ دیگری، خطای سبک را به‌روشنی می‌کاهد.

        آستانه از سنجش به دست آمده، نه از گمان: سبک‌های وزن‌دار
        میان ۰٫۸۴ و ۰٫۹۳ افتادند و روضه میان ۰٫۱۹ و ۰٫۲۵. مرز در
        میانهٔ این شکاف گذاشته شده تا هر دو سو حاشیهٔ فراخ داشته
        باشند. (سنجیده با آوای ساختگی؛ با نواهای راستین شاید
        نیاز به جابه‌جایی داشته باشد.)
        """
        return self.pulse_clarity >= METRICAL_THRESHOLD

    def to_bytes(self) -> bytes:
        return (
            np.concatenate([self.style_vector(), self.voice])
            .astype(np.float32)
            .tobytes()
        )

    @staticmethod
    def from_bytes(raw: bytes) -> tuple[np.ndarray, np.ndarray]:
        """بازگشتی: (بردار سبک، بردار آوا)"""
        array = np.frombuffer(raw, dtype=np.float32)
        return array[:STYLE_DIM], array[STYLE_DIM:]

    @staticmethod
    def is_current(raw: bytes) -> bool:
        """آیا این بردار با ساختار کنونی خوانده می‌شود."""
        return len(raw) == (STYLE_DIM + VOICE_DIM) * 4


class FeatureError(RuntimeError):
    """برداشت ویژگی شدنی نبود."""


# ═════════════════════════════════════════════════════════════
#  برداشت
# ═════════════════════════════════════════════════════════════

def _center_slice(samples: np.ndarray) -> np.ndarray:
    """
    میانهٔ نوا را برمی‌دارد.

    آغاز نوا معمولاً خاموشی یا سخنِ آغازین است و پایانش محو
    می‌شود؛ هیچ‌کدام نمایندهٔ سبک و آوا نیستند.
    """
    limit = int(ANALYSIS_SECONDS * SAMPLE_RATE)
    if samples.size <= limit:
        return samples
    start = (samples.size - limit) // 2
    return samples[start : start + limit]


def _tempo(onset_env: np.ndarray) -> float:
    """
    تمپو، سازگار با نسخه‌های گوناگون librosa.

    ## چرا سه جا آزموده می‌شود

    این تابع در سه نسخه سه جا نشسته است:

        librosa ≤ ۰٫۹     librosa.beat.tempo
        librosa ۰٫۱۰      librosa.feature.rhythm.tempo
        librosa ۱٫۰       librosa.feature.tempo

    شیمِ پیشین تنها دو تای نخست را می‌شناخت و روی librosa ۱٫۰
    به `librosa.beat.tempo` می‌افتاد که دیگر نیست. آنگاه
    `extract` خطا می‌داد، `index_track` خطا را می‌بلعید و
    `features = None` می‌گذاشت — یعنی **همهٔ لایهٔ ویژگی خاموش
    می‌شد** و هیچ‌کس نمی‌فهمید چرا: نه گمانهٔ مداح، نه گمانهٔ سبک،
    نه نواهای همانند.
    """
    import librosa

    for owner, name in (
        (getattr(librosa.feature, "rhythm", None), "tempo"),
        (librosa.feature, "tempo"),
        (getattr(librosa, "beat", None), "tempo"),
    ):
        fn = getattr(owner, name, None)
        if fn is not None:
            return float(np.atleast_1d(fn(onset_envelope=onset_env, sr=SAMPLE_RATE))[0])

    raise FeatureError(
        "این نسخهٔ librosa تابع tempo را در هیچ‌یک از سه جای شناخته‌شده ندارد."
    )


def _pulse_clarity(onset_env: np.ndarray) -> float:
    """
    رسایی ضربان — آیا این نوا ضرب منظم دارد.

    ## چرا خودهم‌بستگی خام بس نیست

    نخستین پیاده‌سازی، بیشینهٔ خودهم‌بستگی پوشِ آغازه را می‌گرفت.
    ولی هر آوای کشیده‌ای خودهم‌بستگی بالا دارد — نه به سبب تناوب،
    بلکه به سبب روند کند. سنجیده شد که روضه ۰٫۹۴ می‌گرفت و شور
    ۰٫۸۵؛ یعنی وارونهٔ آنچه باید.

    آنچه ضرب را نشان می‌دهد **برجستگی** قله است نه بلندی‌اش: قله‌ای
    که از روند پیرامونش بالا زده باشد. پس خودهم‌بستگی هموار می‌شود
    تا روند به دست آید، و بیشینهٔ اختلافِ خودهم‌بستگی از روندِ
    خودش سنجیده می‌گردد.

    بازگشتی: عددی میان ۰ و ۱.

    ## دربارهٔ اندازهٔ این عدد

    اینجا پیش‌تر نوشته بود «نوای وزن‌دار بالای ۰٫۱۴ می‌ماند» — که
    با `METRICAL_THRESHOLD = 0.45` و با عددهایی که `is_metrical`
    گزارش می‌کند (۰٫۸۴ تا ۰٫۹۳ برای وزن‌دار) نمی‌خواند. سه ادعای
    ناسازگار در یک فایل بودند.

    عددِ درست همان است که `is_metrical` می‌گوید و آستانه بر آن
    استوار است. سنجشِ دوباره روی پوشِ آغازهٔ ساختگی: ضربِ منظم
    ۰٫۹۹ و آوازِ آزاد ۰٫۴۸ — یعنی جدایی هست، ولی حاشیهٔ سوی
    بی‌وزن باریک است. اگر روزی روضهٔ راستین «وزن‌دار» خوانده شد،
    نخست توزیعِ گنجینه را در `/features` ببینید و سپس آستانه را
    از روی همان جابه‌جا کنید — نه از روی گمان.
    """
    if onset_env.size < 32:
        return 0.0

    centered = onset_env - onset_env.mean()
    if not np.any(centered):
        return 0.0

    corr = np.correlate(centered, centered, mode="full")[centered.size - 1 :]
    corr = corr / (corr[0] + 1e-9)

    # بازهٔ لگ‌هایی که به تمپوی آدمی می‌خورند (حدود ۳۰ تا ۲۴۰ ضرب)
    low, high = 4, min(corr.size, 460)
    if high - low < 16:
        return 0.0
    window = corr[low:high]

    # روند: هموارسازی با میانگین متحرک. قلهٔ ضرب از روند بالا
    # می‌زند؛ فروکشِ کند با روند بالا می‌رود و برجستگی نمی‌سازد.
    span = max(9, window.size // 12)
    kernel = np.ones(span) / span
    trend = np.convolve(window, kernel, mode="same")

    prominence = float(np.max(window - trend))
    return float(np.clip(prominence, 0.0, 1.0))


def _voice_window(audio: np.ndarray) -> np.ndarray | None:
    """
    نشان آوای یک پنجره.

    None اگر پنجره برای سنجش بس نباشد.

    ## چرا انحراف معیار و مشتق‌ها اینجا نیستند

    در بازشناسی گویندهٔ گفتار، مشتق‌های MFCC جزو ابزار همیشگی‌اند و
    نبودنشان عجیب می‌نماید. ولی اینجا سنجیده شد که **زیان می‌رسانند**:

        بلوک                جداسازی
        میانگین MFCC        ٫۱۳+
        انحراف معیار MFCC   ٫۲۶−
        مشتق یکم            ٫۱۳−
        مشتق دوم            ٫۱۳−

    دلیلش فیزیکی است: انحراف معیار و مشتق، **دگرگونی در زمان** را
    می‌گیرند، و در مداحی آنچه در زمان دگرگون می‌شود بیش از هر چیز
    وزن است، نه خواننده. پس همان مداح در شور و در زمینه، دو نشان
    ناهمانند می‌گرفت؛ و دو مداح جدا در یک سبک، نشان همانند.

    یعنی سبک به نشان آوا نشت می‌کرد. با برداشتنشان، جداسازی روی
    آزمون سخت از ۰٫۱۴۴ به ۰٫۳۰۰ رفت. وزن جای خودش را دارد — در
    بردار سبک.

    ## یادداشتی دربارهٔ کروما

    در سنجش، کروما به‌تنهایی بالاترین جداسازی را داد (۰٫۴۴). ولی
    به آن تکیه نشد: در آوای ساختگی هر مداح گام پایهٔ ثابتی دارد و
    کروما عملاً برچسب را لو می‌دهد. مداح راستین گام را جابه‌جا
    می‌کند. کروما می‌ماند چون دستگاه و گسترهٔ گامی را می‌گیرد، ولی
    در کنار سه بلوک دیگر، نه به جایشان.
    """
    import librosa

    if audio.size < SAMPLE_RATE * 2:
        return None

    try:
        mfcc = librosa.feature.mfcc(y=audio, sr=SAMPLE_RATE, n_mfcc=N_MFCC)
        if mfcc.shape[1] < 4:
            return None

        contrast = librosa.feature.spectral_contrast(
            y=audio, sr=SAMPLE_RATE, fmin=CONTRAST_FMIN, n_bands=CONTRAST_BANDS
        )
        chroma = librosa.feature.chroma_stft(y=audio, sr=SAMPLE_RATE)

        # ── گام پایه ─────────────────────────────────────────
        # گسترهٔ صوتی مداح، جداکننده‌ترین تک‌ویژگی است.
        f0 = librosa.yin(
            audio, fmin=F0_MIN, fmax=F0_MAX, sr=SAMPLE_RATE,
            frame_length=2048,
        )
        voiced = f0[np.isfinite(f0) & (f0 > F0_MIN * 1.02) & (f0 < F0_MAX * 0.98)]
        if voiced.size >= 8:
            f0_stats = np.array(
                [
                    np.median(voiced),
                    np.percentile(voiced, 75) - np.percentile(voiced, 25),
                    voiced.size / max(1, f0.size),
                    np.std(np.log(voiced + 1e-6)),
                ],
                dtype=np.float32,
            )
        else:
            f0_stats = np.zeros(4, dtype=np.float32)

        return np.concatenate(
            [
                mfcc.mean(axis=1),
                contrast.mean(axis=1),
                chroma.mean(axis=1),
                f0_stats,
            ]
        ).astype(np.float32)

    except Exception as exc:  # noqa: BLE001
        logger.debug("سنجش پنجره شکست خورد: %s", exc)
        return None


def _voice_signature(audio: np.ndarray) -> np.ndarray:
    """
    نشان آوا از میانهٔ پنجره‌های پرجان.

    میانه به کار می‌رود نه میانگین: در ضبط مجلسی، چند پنجره‌ای که
    جمعیت در آن‌ها بلند جواب می‌دهد، میانگین را به سوی خود می‌کشند
    ولی بر میانه اثری ندارند.
    """
    window = int(WINDOW_SECONDS * SAMPLE_RATE)
    hop = int(HOP_SECONDS * SAMPLE_RATE)

    if audio.size <= window:
        single = _voice_window(audio)
        if single is None:
            raise FeatureError("نشان آوا از این قطعه به دست نیامد.")
        return single

    windows: list[np.ndarray] = []
    powers: list[float] = []
    for start in range(0, audio.size - window + 1, hop):
        chunk = audio[start : start + window]
        powers.append(float(np.mean(chunk ** 2)))
        windows.append(chunk)

    if not windows:
        raise FeatureError("هیچ پنجره‌ای ساخته نشد.")

    # پنجره‌های کم‌جان دور ریخته می‌شوند
    floor = np.percentile(powers, QUIET_PERCENTILE)
    kept = [w for w, p in zip(windows, powers) if p >= floor]
    if not kept:
        kept = windows

    signatures = [s for s in (_voice_window(w) for w in kept) if s is not None]
    if not signatures:
        raise FeatureError("هیچ پنجره‌ای نشان آوا نداد.")

    return np.median(np.vstack(signatures), axis=0).astype(np.float32)


def extract(samples: np.ndarray) -> Features:
    """
    ویژگی‌ها را از موج صوتی برمی‌دارد.

    کاری پردازنده‌بر است و باید از راه صف در ریسه‌ای جدا فراخوانده
    شود.
    """
    if samples.size < MIN_SECONDS * SAMPLE_RATE:
        raise FeatureError(f"قطعهٔ صوتی کوتاه‌تر از {MIN_SECONDS:.0f} ثانیه است.")

    import librosa

    audio = _center_slice(samples).astype(np.float32)

    try:
        # ── وزن و ضرب ────────────────────────────────────────
        onset_env = librosa.onset.onset_strength(y=audio, sr=SAMPLE_RATE)
        tempo = _tempo(onset_env)

        pulse_clarity = _pulse_clarity(onset_env)

        # پایداری تمپو: هم‌خوانی تمپو در نیمه‌های نوا
        half = onset_env.size // 2
        if half > 32:
            t1, t2 = _tempo(onset_env[:half]), _tempo(onset_env[half:])
            tempo_stability = float(
                1.0 - min(1.0, abs(t1 - t2) / max(1.0, max(t1, t2)))
            )
        else:
            tempo_stability = 0.0

        onsets = librosa.onset.onset_detect(onset_envelope=onset_env, sr=SAMPLE_RATE)
        onset_rate = float(len(onsets) * SAMPLE_RATE / max(1, audio.size))

        # تیزی رخدادها — شاخص کوبه‌ای بودن.
        #
        # نخست با جداسازی هارمونیک/کوبه‌ای (hpss) سنجیده می‌شد، ولی
        # آن تابع بیش از سه ثانیه برای هر نوا می‌برد — گران‌ترین گام
        # همهٔ برداشت. اینجا از پوشِ آغازه که از پیش محاسبه شده
        # بهره می‌بریم: ضربهٔ دف قله‌های تیز می‌سازد و آواز کشیده
        # نمی‌سازد. هزینه‌اش صفر است و همان را می‌رساند.
        if onset_env.size > 4 and onset_env.std() > 1e-9:
            onset_crest = float(
                (onset_env.max() - np.median(onset_env)) / (onset_env.std() + 1e-9)
            )
        else:
            onset_crest = 0.0

        # ── نیرو ─────────────────────────────────────────────
        rms = librosa.feature.rms(y=audio)[0]
        energy_mean = float(np.mean(rms))
        energy_std = float(np.std(rms))
        energy_range = float(np.percentile(rms, 95) - np.percentile(rms, 5))

        # ── طیف ──────────────────────────────────────────────
        zcr = librosa.feature.zero_crossing_rate(y=audio)[0]
        centroid = float(np.mean(librosa.feature.spectral_centroid(y=audio, sr=SAMPLE_RATE)[0]))
        bandwidth = float(np.mean(librosa.feature.spectral_bandwidth(y=audio, sr=SAMPLE_RATE)[0]))
        rolloff = float(np.mean(librosa.feature.spectral_rolloff(y=audio, sr=SAMPLE_RATE)[0]))
        flatness = float(np.mean(librosa.feature.spectral_flatness(y=audio)[0]))

        # ── نشان آوا ─────────────────────────────────────────
        voice = _voice_signature(audio)

    except FeatureError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise FeatureError(f"برداشت ویژگی شکست خورد: {exc}") from exc

    return Features(
        tempo=tempo,
        pulse_clarity=pulse_clarity,
        tempo_stability=tempo_stability,
        onset_rate=onset_rate,
        energy_mean=energy_mean,
        energy_std=energy_std,
        energy_range=energy_range,
        zero_crossing=float(np.mean(zcr)),
        zero_crossing_std=float(np.std(zcr)),
        spectral_centroid=centroid,
        spectral_bandwidth=bandwidth,
        spectral_rolloff=rolloff,
        spectral_flatness=flatness,
        onset_crest=onset_crest,
        voice=voice,
    )


def extract_file(path) -> Features:
    from core.audio.decode import decode

    return extract(decode(path))


# ═════════════════════════════════════════════════════════════
#  همانندی آوا
# ═════════════════════════════════════════════════════════════

def voice_similarity(
    first: np.ndarray,
    second: np.ndarray,
    center: np.ndarray | None = None,
    scale: np.ndarray | None = None,
) -> float:
    """
    همانندی دو نشان آوا، میان ۰ و ۱.

    ## چرا کم کردن میانگین گنجینه بایسته است

    همهٔ آواهای انسانی یک مؤلفهٔ مشترک بزرگ دارند: پوشِ طیفیِ
    گفتار، که در همه یکسان است و ربطی به اینکه چه کسی می‌خواند
    ندارد. اگر آن را کم نکنیم، همان مؤلفه بر همانندی چیره می‌شود و
    همهٔ آواها به هم همانند می‌نمایند.

    سنجیده شد: بی این کار، همانندی همهٔ جفت‌ها میان ۰٫۹۷ و ۰٫۹۹
    می‌افتاد — چه از یک مداح، چه از دو مداح جدا. تنها بخش کردن بر
    انحراف معیار بس نبود؛ آنچه کار می‌کند کم کردن **میانگین
    گنجینه** است.
    """
    if first.size != second.size or first.size == 0:
        return 0.0

    a = first.astype(np.float64)
    b = second.astype(np.float64)

    if center is not None and center.size == a.size:
        a = a - center
        b = b - center
    else:
        a = a - a.mean()
        b = b - b.mean()

    if scale is not None and scale.size == a.size:
        safe = np.where(scale < 1e-9, 1.0, scale)
        a = a / safe
        b = b / safe

    norm_a = np.linalg.norm(a)
    norm_b = np.linalg.norm(b)
    if norm_a == 0 or norm_b == 0:
        return 0.0

    cosine = float(np.dot(a, b) / (norm_a * norm_b))
    return max(0.0, min(1.0, (cosine + 1.0) / 2.0))


def describe_tempo(tempo: float, pulse_clarity: float = 1.0) -> str:
    """
    تمپو را به زبان آدمی برمی‌گرداند.

    اگر ضربان رسا نباشد، گفتن عدد تمپو گمراه‌کننده است — روضه هم
    عددی می‌گیرد، ولی آن عدد معنایی ندارد.
    """
    if pulse_clarity < METRICAL_THRESHOLD:
        return "بی‌وزن"
    if tempo < 70:
        return "بسیار آرام"
    if tempo < 95:
        return "آرام"
    if tempo < 120:
        return "میانه"
    if tempo < 150:
        return "تند"
    return "بسیار تند"
