"""
لایهٔ متن — آنچه خوانده می‌شود.

## چرا این لایه هست

سه نشانه‌ای که شنوندهٔ آشنا به کار می‌برد این‌هاست: **متن**، رنگ
صدا، و ریتم. ربات تا امروز دو تای دوم را داشت و مهم‌ترین را نه.

و متن، مهم‌ترین است چون **از ضبط مستقل است**: همان نوحه با کیفیت
دیگر، از اجرای دیگر، با گام دیگر — کلماتش یکی است. اثر انگشت با
تغییر یک درصدِ سرعت می‌شکند؛ متن نمی‌شکند.

## چرا محلی

هیچ API بیرونی. مدل روی خودِ دستگاه اجرا می‌شود و صوت از سرور
بیرون نمی‌رود — همان قیدی که از آغاز این پروژه داشت.

## فروپاشی نرم — مهم‌ترین ویژگی این ماژول

اگر کتابخانه نصب نباشد، مدل دانلود نشده باشد، یا رونویسی بشکند،
این ماژول `None` می‌دهد و **هیچ‌چیز نمی‌شکند**. ربات بی این لایه
همان‌قدر کار می‌کند که پیش از آن می‌کرد.

این عمدی است: مدل نیم‌گیگابایتی روی سروری که تازه راه افتاده
شاید نباشد، و ربات نباید به این سبب بالا نیاید.

## پالودهٔ سکوت — آنچه سنجیده شد و آنچه از سنجش بیرون آمد

گزارش‌های خودِ ربات یک بار این را نشان دادند:

    Processing audio with duration 03:08.000
    VAD filter removed 02:02.880 of audio

۶۵٪ یک نوا پیش از رونویسی دور ریخته شده بود، و گمانِ نخستِ من
این بود که آستانهٔ VAD برای **گفتار** میزان شده و آوازِ کشیده را
سکوت می‌شمارد. پس آستانه را از ۰٫۵ به ۰٫۳ آوردم.

**سنجش ردش کرد.** روی نوای راستینِ گنجینه، با سه بلندیِ گوناگون:

    بلندی        آستانهٔ ۰٫۵        آستانهٔ ۰٫۳
    ۰ دسی‌بل      ۳٪ دور ریخت       ۳٪
    ۲۰− دسی‌بل    ۳٪                ۳٪
    ۳۰− دسی‌بل    ۳٪                ۴٪

هیچ تفاوتی نکرد — silero پیش از داوری خودش بلندی را هنجار
می‌کند، پس پایین آوردن آستانه کارِ ضبطِ آهسته را درست نمی‌کند. و
در یکی از سنجش‌ها خروجی را اندکی **بدتر** کرد.

پس آستانه دست‌نخورده ماند و به‌جایش `_log_vad` نشست: هرگاه
دورریز از ۴۰٪ گذشت، خودش را در گزارش می‌نویسد. آن ۶۵٪ علتِ
دیگری داشت — شاید همان نوا براستی دو دقیقه خاموشی یا سازِ بی‌کلام
داشت — و تا وقتی داده نداریم، میزان کردنِ آستانه گمانه‌زنی است نه
تعمیر.
"""

from __future__ import annotations

import logging
import threading
import time
from pathlib import Path

import numpy as np

logger = logging.getLogger(__name__)

# نرخ نمونه‌برداری که مدل می‌خواهد. صوت ما ۱۱۰۲۵ است و باید
# بالا برده شود.
WHISPER_RATE = 16000

# کوتاه‌تر از این، رونویسی چیزی به دست نمی‌دهد جز نویز.
MIN_SECONDS = 4.0

# پالودهٔ سکوت با تنظیمِ خودِ کتابخانه می‌رود. کوششِ میزان کردنش
# سنجیده و رد شد — شرحش در سرآیندِ همین پرونده. اگر روزی داده‌ای
# به دست آمد که خلافش را بگوید، همین‌جا جایش هست:
#     VAD_PARAMETERS = {"threshold": ..., ...}
# و `transcribe` خودش آرگومانِ `vad_parameters` را می‌پذیرد.
VAD_PARAMETERS = None

# راهنمای آغازین — رمزگشا را به املای این حوزه می‌کشاند.
#
# بی این، نام‌ها و اصطلاحات مداحی به نزدیک‌ترین واژهٔ روزمره
# رونویسی می‌شوند و هم‌پوشانیِ واژگانی می‌شکند. متن کوتاه است
# چون راهنمای دراز، خودش خروجی را به سوی خود می‌کشد.
INITIAL_PROMPT = (
    "مداحی و نوحهٔ فارسی: یا حسین، یا اباالفضل، کربلا، عاشورا، "
    "زینب، سیدالشهدا، روضه، شور، واحد، زمینه."
)

# پس از ناکامیِ بار کردن، این‌قدر درنگ پیش از کوشش دوباره.
#
# ناکامیِ گذرا — دیسک پر، دانلودِ نیمه‌کاره — نباید لایهٔ متن را
# تا پایان عمرِ پروسه بکشد. ولی کوشش در هر بازجویی هم درست
# نیست: بار کردن چند ثانیه می‌برد و کاربر پشتش می‌ماند.
RETRY_AFTER_SECONDS = 600.0

# ── وضعیت مدل ───────────────────────────────────────────────
# بارگذاری گران است (چند ثانیه) و یک بار انجام می‌شود. قفل
# می‌گذارد که دو ریسه هم‌زمان بارش نکنند.
_model = None
_unavailable = False          # کتابخانه نیست — قفلِ دائم
_failed_at: float | None = None   # ناکامیِ گذرا — با درنگ، دوباره
_lock = threading.Lock()

# قفلِ خودِ رونویسی، جدا از قفلِ بار کردن.
#
# ## چرا این بایسته است
#
# `WhisperModel` برای فراخوانِ هم‌زمان ساخته نشده. صفِ پردازش سه
# ریسهٔ کارگر دارد (`worker/queue.py`) و کارِ دوره‌ایِ رونویسی هم
# جداگانه می‌رود — پس چهار ریسه می‌توانند با هم روی یک نمونهٔ مدل
# بیفتند. پیش‌تر تنها بار کردن قفل داشت، نه خودِ رونویسی.
_infer_lock = threading.Lock()


def _load(model_size: str, device: str, compute_type: str):
    """
    مدل را یک بار بار می‌کند؛ None اگر نشد.

    دو گونه ناکامی از هم جدا شده‌اند، چون سرنوشتشان یکی نیست:

    • **کتابخانه نیست** — در زمان اجرا نصب نمی‌شود، پس قفلِ دائم.
    • **بار کردن نشد** — دیسک پر بود، دانلود نیمه ماند، یا مدل با
      این CPU نساخت. این‌ها گذرایند و پس از درنگی دوباره آزموده
      می‌شوند. پیش‌تر یک پرچمِ `_tried` هر دو را یکی می‌گرفت و
      **یک خطای گذرا، لایهٔ متن را تا پایان عمرِ پروسه می‌کشت**.
    """
    global _model, _unavailable, _failed_at
    with _lock:
        if _model is not None:
            return _model
        if _unavailable:
            return None
        if _failed_at is not None and (
            time.monotonic() - _failed_at
        ) < RETRY_AFTER_SECONDS:
            return None

        try:
            from faster_whisper import WhisperModel
        except ImportError:
            _unavailable = True
            logger.info(
                "faster-whisper نصب نیست؛ لایهٔ متن خاموش می‌ماند. "
                "نصب: pip install faster-whisper"
            )
            return None

        try:
            _model = WhisperModel(
                model_size, device=device, compute_type=compute_type
            )
            _failed_at = None
            logger.info("مدل رونویسی «%s» بار شد.", model_size)
        except Exception as exc:  # noqa: BLE001
            # دانلود نشده، فضای دیسک، یا ناسازگاریِ CPU.
            _failed_at = time.monotonic()
            _model = None
            logger.warning(
                "بار کردن مدل رونویسی نشد: %s — پس از %.0f ثانیه "
                "دوباره کوشیده می‌شود.",
                exc, RETRY_AFTER_SECONDS,
            )
        return _model


def available() -> bool:
    """آیا لایهٔ متن در دسترس است — بی آنکه مدل را بار کند."""
    if _unavailable:
        return False
    try:
        import faster_whisper  # noqa: F401
    except ImportError:
        return False
    return True


def _to_whisper(samples: np.ndarray, source_rate: int) -> np.ndarray:
    """
    نرخ نمونه‌برداری را به آنچه مدل می‌خواهد می‌برد.

    درون‌یابی خطی بس است: گفتار در باندِ پایین است و مدل خودش
    طیف‌نگار می‌سازد؛ ظرافتِ بازنمونه‌برداری اینجا دیده نمی‌شود.
    """
    if source_rate == WHISPER_RATE:
        return samples.astype(np.float32)
    count = int(round(samples.size * WHISPER_RATE / source_rate))
    if count < 2:
        return samples.astype(np.float32)
    return np.interp(
        np.linspace(0.0, samples.size - 1.0, count),
        np.arange(samples.size, dtype=np.float64),
        samples.astype(np.float64),
    ).astype(np.float32)


def transcribe(
    samples: np.ndarray,
    source_rate: int,
    *,
    model_size: str = "small",
    device: str = "cpu",
    compute_type: str = "int8",
    beam_size: int = 1,
    vad_parameters: dict | None = None,
) -> str | None:
    """
    آنچه در این صوت خوانده می‌شود، به نوشتار.

    بازگشتی: متن، یا `None` اگر لایه در دسترس نبود یا چیزی شنیده
    نشد. `None` پاسخِ درست و رایج است، نه نشانهٔ خرابی.

    `beam_size=1` (جست‌وجوی حریصانه) برگزیده شده چون اینجا متن
    برای **تطبیق** است نه برای خواندن؛ دقتِ واژه‌به‌واژه لازم نیست
    و حریصانه چند برابر تندتر است.

    ## چرا `condition_on_previous_text=False`

    مداحی ذاتاً تکرارشونده است — یک مصرع، ده بار. با حافظهٔ متنِ
    پیشین، رمزگشا در همان تکرار **حلقه می‌زند** و یک بند را ده‌ها
    بار می‌نویسد. آن متنِ باد کرده، هم‌پوشانیِ واژگانیِ
    `core/lyrics.py` را می‌شکند: مجموعهٔ واژه‌هایش همان مجموعهٔ
    کوچک می‌ماند ولی نوا را دیگر نمی‌شناساند.
    """
    seconds = samples.size / max(source_rate, 1)
    if seconds < MIN_SECONDS:
        logger.debug("برای رونویسی کوتاه است: %.1f ثانیه", seconds)
        return None

    model = _load(model_size, device, compute_type)
    if model is None:
        return None

    try:
        audio = _to_whisper(samples, source_rate)
        # مدل برای فراخوانِ هم‌زمان ساخته نشده؛ شرحش کنار
        # `_infer_lock`.
        with _infer_lock:
            segments, info = model.transcribe(
                audio,
                language="fa",
                beam_size=beam_size,
                vad_filter=True,
                vad_parameters=vad_parameters or VAD_PARAMETERS,
                # ↑ None یعنی پیش‌فرضِ کتابخانه؛ عمدی است.
                condition_on_previous_text=False,
                initial_prompt=INITIAL_PROMPT,
            )
            # `segments` زایاست و کارِ راستین هنگام پیمودنش انجام
            # می‌شود — پس پیمودن هم باید درون قفل باشد، نه بیرونش.
            text = " ".join(segment.text.strip() for segment in segments)

        _log_vad(info, seconds)
        return text.strip() or None
    except Exception as exc:  # noqa: BLE001
        logger.warning("رونویسی شکست خورد: %s", exc)
        return None


def _log_vad(info, seconds: float) -> None:
    """
    چقدر از صوت را پالودهٔ سکوت خورد.

    همین عدد بود که کاستیِ پیشین را آشکار کرد، پس همان‌جا می‌ماند
    تا اگر روزی دوباره بالا رفت، دیده شود. نبودِ این خانه‌ها در
    نسخه‌های کهنه‌ترِ کتابخانه، خطا نیست.
    """
    kept = getattr(info, "duration_after_vad", None)
    total = getattr(info, "duration", None) or seconds
    if not kept or not total:
        return
    dropped = 1.0 - (kept / total)
    if dropped > 0.40:
        logger.info(
            "پالودهٔ سکوت %.0f٪ از %.0f ثانیه را برداشت — اگر ماند، "
            "VAD_PARAMETERS باید نرم‌تر شود.",
            dropped * 100, total,
        )
    else:
        logger.debug(
            "پالودهٔ سکوت %.0f٪ از %.0f ثانیه را برداشت.", dropped * 100, total
        )


def transcribe_file(
    path: str | Path, **kwargs
) -> str | None:
    """رونویسی از روی پرونده — خودش رمزگشایی می‌کند."""
    from core.audio.decode import DecodeError, decode
    from core.audio.fingerprint import SAMPLE_RATE

    try:
        samples = decode(path)
    except DecodeError as exc:
        logger.debug("رمزگشایی برای رونویسی نشد: %s", exc)
        return None
    return transcribe(samples, SAMPLE_RATE, **kwargs)


def reset() -> None:
    """وضعیت بارگذاری را از نو می‌کند — برای آزمون."""
    global _model, _unavailable, _failed_at
    with _lock:
        _model = None
        _unavailable = False
        _failed_at = None
