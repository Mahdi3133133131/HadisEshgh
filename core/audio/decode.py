"""
رمزگشایی صوت به موج خام.

هر گونه‌ای که کاربر بفرستد — ام‌پی‌تری، نماهنگ، پیام صوتی، اوگ —
از یک درگاه می‌گذرد و به آرایه‌ای از اعداد اعشاری تک‌کاناله
دگرگون می‌شود. لایه‌های بالاتر دیگر نمی‌دانند گونهٔ اصلی چه بوده و
نباید هم بدانند.

چرا ffmpeg و نه pydub: pydub خودش بر ffmpeg سوار است و تنها لایه‌ای
نازک بر آن می‌افزاید. صدا زدن مستقیم ffmpeg، هم یک وابستگی کمتر
دارد، هم مهلت‌گذاری و مهار خطا را در دست ما می‌گذارد.

نرخ نمونه‌برداری ۱۱۰۲۵ برگزیده شده است: برای آوای انسان و ساز
بسنده است و در سنجش با ۴۴۱۰۰، یک‌چهارم داده می‌سازد — که در
اثرانگشت‌گیری، یک‌چهارم زمان و یک‌چهارم فضا معنی می‌دهد.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
import threading
from collections import OrderedDict
from pathlib import Path

import numpy as np

logger = logging.getLogger(__name__)

SAMPLE_RATE = 11025
_MAX_SECONDS = 60 * 60  # یک ساعت؛ فراتر از آن نشانهٔ فایل نادرست است

# ── بردباری در برابر جریانِ اندکی ناقص ───────────────────────
#
# ## چرا این بایسته شد
#
# پنج نوای گنجینه هرگز نمایه نشدند، و هر پنج یک نوع خطا داشتند:
#
#     Number of bands (24) exceeds limit (12)
#     channel element 3.10 is not allocated
#     Reserved bit set.
#
# این‌ها خطای جزئیِ بیت‌استریمِ AAC اند، نه فایلِ خراب. بیشترِ
# پخش‌کننده‌ها از رویشان می‌گذرند؛ رمزگشای سخت‌گیرِ ffmpeg
# نمی‌گذرد. نتیجه: نوا در گنجینه بود ولی **نامرئی** — چون
# اثر انگشتی نداشت. کاربر مداحی‌اش را می‌فرستاد و پاسخی
# نمی‌گرفت، و می‌پنداشت موتور ضعیف است.
_TOLERANT = ("-err_detect", "ignore_err", "-fflags", "+discardcorrupt")

# کمترین صوتی که ارزشِ نگه داشتن دارد.
#
# ffmpeg در خطای جزئی کدِ غیرصفر می‌دهد **ولی صوتِ سالم را هم
# بیرون می‌دهد**. پس کدِ خروج به‌تنهایی داورِ درستی نیست: آنچه
# مهم است این است که چقدر صوت به دست آمده. زیر یک ثانیه، راستی
# ناکامی است؛ بالاتر، چیزی است که می‌شود با آن کار کرد.
_MIN_SALVAGE_SECONDS = 1.0

# کوششِ دوم: ffmpeg را وادار می‌کند بیشتر بکاود پیش از آنکه
# بگوید این فایل جریانی ندارد. گران است، پس تنها وقتی کوششِ
# نخست دست‌خالی برگشت.
_PATIENT = ("-analyzeduration", "100M", "-probesize", "100M")


class DecodeError(RuntimeError):
    """رمزگشایی صوت شکست خورد."""


def ffmpeg_path() -> str:
    path = shutil.which("ffmpeg")
    if path is None:
        raise DecodeError(
            "ffmpeg در PATH یافت نشد.\n"
            "بی آن، استخراج صوت شدنی نیست.\n"
            "دریافت: https://www.gyan.dev/ffmpeg/builds/"
        )
    return path


def decode(
    source: str | Path,
    sample_rate: int = SAMPLE_RATE,
    start: float | None = None,
    duration: float | None = None,
) -> np.ndarray:
    """
    فایل را به موج تک‌کانالهٔ اعشاری در بازهٔ ‎[-1, 1]‎ برمی‌گرداند.

    آرگومان‌های start و duration پیش از ورودی نهاده می‌شوند تا ffmpeg
    به جای رمزگشایی همهٔ فایل و دور ریختن بیشترش، از همان آغاز بجهد.
    """
    source = str(source)
    samples, message = _run(source, sample_rate, start, duration, patient=False)

    # ── کوششِ دوم، شکیباتر ──────────────────────────────────
    #
    # اگر هیچ نیامد، شاید ffmpeg در **شناساییِ جریان** مانده
    # باشد، نه در رمزگشایی‌اش. پیش‌فرضِ probesize و analyzeduration
    # کوتاه است؛ فایلی که سرآیندش نامرتب یا بارِ آغازینش ناقص
    # است، در همان پله رد می‌شود و چیزی بیرون نمی‌دهد.
    #
    # کوششِ دوم گران‌تر است (تا صد مگابایت را می‌کاود) پس تنها
    # آنگاه می‌رود که کوششِ نخست دست‌خالی برگشته باشد.
    if samples.size < _MIN_SALVAGE_SECONDS * sample_rate:
        patient, patient_message = _run(
            source, sample_rate, start, duration, patient=True
        )
        if patient.size > samples.size:
            logger.info(
                "کوششِ نخست چیزی نداد؛ کوششِ شکیبا %.1f ثانیه یافت.",
                patient.size / sample_rate,
            )
            samples, message = patient, patient_message

    # ── داوری ───────────────────────────────────────────────
    if samples.size < _MIN_SALVAGE_SECONDS * sample_rate:
        low = message.lower()
        if "does not contain any stream" in low or "invalid data" in low:
            raise DecodeError("فایل هیچ جریان صوتی نداشت.")
        if message:
            raise DecodeError(f"ffmpeg نتوانست فایل را بگشاید: {message[:300]}")
        raise DecodeError("جریان صوتی تهی بود.")

    limit = _MAX_SECONDS * sample_rate
    if samples.size > limit:
        logger.warning(
            "صوت %s ثانیه‌ای به %s ثانیه کوتاه شد.",
            samples.size // sample_rate, _MAX_SECONDS,
        )
        samples = samples[:limit]

    return samples.astype(np.float32) / 32768.0


# ═════════════════════════════════════════════════════════════
#  کش کوتاه‌عمر
# ═════════════════════════════════════════════════════════════
#
# ## چرا
#
# یک بازجویی ناکام، همان فایل را دو بار رمزگشایی می‌کرد: یک بار در
# `_fingerprint_and_match` و یک بار در `_guess_similar` که پس از
# ناکامی می‌آید. رمزگشایی گران‌ترین گامِ مسیر است — یک پروسهٔ
# ffmpeg برای هر بار.
#
# ## چرا کران‌دار، و این‌قدر تنگ
#
# صوتِ رمزگشایی‌شده در حافظه بزرگ است: یک ساعت در نرخ ۱۱۰۲۵ و
# float32 نزدیک ۱۶۰ مگابایت. پس تنها **کلیپِ کاربر** کش می‌شود
# که همیشه کوتاه است؛ نوای کامل هرگز. با سه ورودیِ سه‌دقیقه‌ای،
# سقفِ حافظه حدود ۲۴ مگابایت می‌ماند.
#
# کلید، دگرگون شدنِ فایل را می‌بیند (اندازه و زمانِ ویرایش)، پس
# فایلی که جایش را به فایلِ دیگری داده، پاسخِ کهنه نمی‌گیرد.

_CACHE_MAX_ENTRIES = 3
_CACHE_MAX_SECONDS = 180.0

_cache: "OrderedDict[tuple, np.ndarray]" = OrderedDict()
_cache_lock = threading.Lock()


def decode_cached(
    source: str | Path, sample_rate: int = SAMPLE_RATE
) -> np.ndarray:
    """
    مانند `decode`، ولی پاسخِ همین فایل را کوتاه‌مدت نگه می‌دارد.

    تنها برای بازهٔ کامل یک فایل است؛ برای `start`/`duration` از
    خودِ `decode` بهره ببرید.

    **آرایهٔ بازگشتی مشترک است — دگرگونش نکنید.** همهٔ لایه‌های این
    پروژه تنها می‌خوانندش (اثر انگشت، ویژگی، خطِ آهنگ، رونویسی) و
    هر کدام که بخواهد دست ببرد، خودش رونوشت می‌گیرد.
    """
    path = Path(source)
    try:
        stat = path.stat()
        key = (str(path.resolve()), stat.st_size, stat.st_mtime_ns, sample_rate)
    except OSError:
        # نشد بشناسیمش؛ بی کش پیش می‌رویم.
        return decode(source, sample_rate)

    with _cache_lock:
        hit = _cache.get(key)
        if hit is not None:
            _cache.move_to_end(key)
            logger.debug("رمزگشاییِ «%s» از کش آمد.", path.name)
            return hit

    samples = decode(source, sample_rate)

    if samples.size <= _CACHE_MAX_SECONDS * sample_rate:
        with _cache_lock:
            _cache[key] = samples
            _cache.move_to_end(key)
            while len(_cache) > _CACHE_MAX_ENTRIES:
                _cache.popitem(last=False)

    return samples


def clear_cache() -> None:
    """کش را تهی می‌کند — برای آزمون و برای پس از پاک‌سازیِ tmp."""
    with _cache_lock:
        _cache.clear()


def _run(
    source: str,
    sample_rate: int,
    start: float | None,
    duration: float | None,
    patient: bool,
) -> tuple[np.ndarray, str]:
    """
    یک کوششِ ffmpeg. آنچه به دست آمد و آنچه گفت را برمی‌گرداند.

    خطا بالا نمی‌رود: داوری با فراخوان است، که هر دو کوشش را
    می‌بیند.
    """
    command = [ffmpeg_path(), "-hide_banner", "-loglevel", "error", "-nostdin"]
    command += list(_TOLERANT)
    if patient:
        command += list(_PATIENT)

    if start is not None:
        command += ["-ss", f"{start:.3f}"]
    command += ["-i", source]
    if duration is not None:
        command += ["-t", f"{duration:.3f}"]

    command += [
        "-vn",                 # هر جریان تصویری نادیده گرفته شود
        "-ac", "1",            # تک‌کاناله
        "-ar", str(sample_rate),
        "-f", "s16le",         # اعداد صحیح ۱۶ بیتی، بی سرآیند
        "-acodec", "pcm_s16le",
        "-",
    ]

    try:
        result = subprocess.run(
            command, capture_output=True, timeout=300, check=False
        )
    except subprocess.TimeoutExpired as exc:
        raise DecodeError("رمزگشایی صوت بیش از اندازه به درازا کشید.") from exc
    except OSError as exc:
        raise DecodeError(f"اجرای ffmpeg شکست خورد: {exc}") from exc

    message = result.stderr.decode("utf-8", errors="replace").strip()
    samples = np.frombuffer(result.stdout, dtype=np.int16)

    # ── کدِ خروج، به‌تنهایی داور نیست ───────────────────────
    #
    # ffmpeg در خطای جزئیِ بیت‌استریم کدِ غیرصفر می‌دهد **ولی
    # صوتِ سالم را هم بیرون می‌دهد**. کدِ پیشین همان‌جا خطا
    # می‌داد و آن صوت را دور می‌ریخت — حتی اگر نود درصدِ فایل
    # درست خوانده شده بود.
    if samples.size and (result.returncode != 0 or message):
        logger.debug(
            "ffmpeg با گلایه خواند (%.1f ثانیه): %s",
            samples.size / sample_rate, message[:200] or "کد خروج غیرصفر",
        )
    return samples, message


def probe_duration(source: str | Path) -> float | None:
    """
    درازای فایل به ثانیه، بی‌آنکه رمزگشایی شود.

    برای تصمیم‌های سبک — مانند «آیا این نماهنگ از یک دقیقه درازتر
    است؟» که سند خواسته بود — رمزگشایی همهٔ فایل هدر رفتن است.
    """
    ffprobe = shutil.which("ffprobe")
    if ffprobe is None:
        return None

    try:
        result = subprocess.run(
            [
                ffprobe, "-v", "error",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                str(source),
            ],
            capture_output=True,
            timeout=30,
            check=False,
        )
        if result.returncode != 0:
            return None
        return float(result.stdout.decode().strip())
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return None


def has_audio_stream(source: str | Path) -> bool:
    """آیا این فایل اصلاً جریان صوتی دارد."""
    ffprobe = shutil.which("ffprobe")
    if ffprobe is None:
        return True  # نمی‌دانیم؛ بگذار رمزگشایی خودش داوری کند

    try:
        result = subprocess.run(
            [
                ffprobe, "-v", "error",
                "-select_streams", "a",
                "-show_entries", "stream=index",
                "-of", "csv=p=0",
                str(source),
            ],
            capture_output=True,
            timeout=30,
            check=False,
        )
        return bool(result.stdout.strip())
    except (OSError, subprocess.TimeoutExpired):
        return True


def extract_audio(source: str | Path, destination: str | Path) -> Path:
    """
    جریان صوتی نماهنگ را به ام‌پی‌تری بیرون می‌کشد.

    سند خواسته بود هرگاه نسخهٔ کامل یافت نشد، دست‌کم صوتِ همان
    نماهنگ برای کاربر فرستاده شود. این تابع همان کار را می‌کند.
    """
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)

    command = [
        ffmpeg_path(), "-hide_banner", "-loglevel", "error", "-nostdin",
        "-i", str(source),
        "-vn",
        "-acodec", "libmp3lame",
        "-b:a", "128k",
        "-y",
        str(destination),
    ]

    try:
        result = subprocess.run(command, capture_output=True, timeout=300, check=False)
    except subprocess.TimeoutExpired as exc:
        raise DecodeError("استخراج صوت بیش از اندازه به درازا کشید.") from exc

    if result.returncode != 0 or not destination.exists():
        message = result.stderr.decode("utf-8", errors="replace").strip()
        raise DecodeError(f"استخراج صوت شکست خورد: {message[:300]}")

    return destination


def extract_preview(
    source: str | Path,
    destination: str | Path,
    seconds: float = 30.0,
    start: float = 0.0,
) -> Path:
    """
    تکه‌ای کوتاه از یک فایل صوتی می‌سازد.

    ## چرا پیش‌نمایش، و نه خودِ فایل

    وقتی چیزی در آرشیو نبود و از سایت‌ها چند گمانه آوردیم، نباید
    هر سه را کامل برای کاربر بفرستیم: هم کند است، هم اگر هیچ‌کدام
    آنی نباشد که می‌خواست، بیهوده بوده. سی ثانیه بس است تا بشناسد،
    و نسخهٔ کامل تنها پس از تأییدش می‌رود.

    ورودیِ ناقص هم پذیرفته است: چون تنها سرِ فایل را از سایت
    می‌گیریم، ffmpeg به انتهای بریده می‌رسد و آنجا می‌ایستد. پس
    کدِ بازگشتِ ناصفر به تنهایی شکست نیست — اگر فایلی با اندازهٔ
    معنادار ساخته شده باشد، کار انجام شده است.
    """
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)

    command = [ffmpeg_path(), "-hide_banner", "-loglevel", "error", "-nostdin"]
    if start > 0:
        command += ["-ss", f"{start:.3f}"]
    command += [
        "-i", str(source),
        "-t", f"{seconds:.3f}",
        "-vn",
        "-acodec", "libmp3lame",
        "-b:a", "128k",
        "-y",
        str(destination),
    ]

    try:
        result = subprocess.run(command, capture_output=True, timeout=120, check=False)
    except subprocess.TimeoutExpired as exc:
        destination.unlink(missing_ok=True)
        raise DecodeError("ساختن پیش‌نمایش بیش از اندازه به درازا کشید.") from exc

    # چهار کیلوبایت یعنی چند ثانیه صدای راستین؛ کمتر از آن، فایلِ
    # پوچی است که ffmpeg پیش از رسیدن به داده ساخته.
    if destination.exists() and destination.stat().st_size > 4096:
        return destination

    destination.unlink(missing_ok=True)
    message = result.stderr.decode("utf-8", errors="replace").strip()
    raise DecodeError(f"ساختن پیش‌نمایش شکست خورد: {message[:300]}")
