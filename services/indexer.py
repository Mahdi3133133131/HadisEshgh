"""
نمایه‌سازی نواها.

یک نوا از تلگرام فرو گرفته می‌شود، اثر انگشتش ساخته می‌گردد، و
تنها همان اثر انگشت در پایگاه داده می‌ماند — خودِ فایل پاک می‌شود.

این تصمیم، ستون فقرات معماری است: فایل صوتی در تلگرام می‌ماند و ما
تنها file_id را نگه می‌داریم. پس نگهداری هزاران نوا هیچ فضایی از
دیسک ما نمی‌گیرد، و فرستادن دوباره‌شان بی‌درنگ است چون بارگذاری
تازه‌ای در کار نیست.

سقف فرو گرفتن: ربات معمولی تنها تا ۲۰ مگابایت می‌تواند فایل بگیرد.
نوای درازتر از آن، بی سرور محلی Bot API نمایه نمی‌شود؛ این کاستی
اینجا گرفته و گزارش می‌شود، نه آنکه خاموش بگذرد.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
from pathlib import Path

import numpy as np
from telegram import Bot
from telegram.error import TelegramError

from config import config
from core.audio.decode import DecodeError, decode
from core.audio.fingerprint import (
    FAN_OUT_INDEX,
    Fingerprint,
    FingerprintError,
    fingerprint,
)
from core import net
from core.db import (
    database,
    features_store,
    fingerprints as fp_store,
    melody_store,
)

logger = logging.getLogger(__name__)

# سقف فرو گرفتن ربات معمولی
PLAIN_BOT_DOWNLOAD_LIMIT = 20 * 1024 * 1024


class IndexError_(RuntimeError):
    """نمایه‌سازی یک نوا شکست خورد."""


async def download(bot: Bot, file_id: str, destination: Path) -> Path:
    """
    فایل را از تلگرام فرو می‌گیرد، با کوشش دوباره.

    گسستِ گذرا بر این پیوند وضعِ عادی است، نه خطا. بی کوشش دوباره،
    یک قطعی یک‌ثانیه‌ای نوایی را نمایه‌نشده می‌گذاشت.
    """
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        handle = await net.retry(
            lambda: bot.get_file(file_id),
            attempts=config.network_retries,
            label=f"گرفتن نشانی فایل {file_id[:12]}…",
        )
    except TelegramError as exc:
        message = str(exc)
        if "too big" in message.lower():
            raise IndexError_(
                "فایل از سقف فرو گرفتن ربات (۲۰ مگابایت) بزرگ‌تر است.\n"
                "برای نواهای بزرگ‌تر، سرور محلی Bot API بایسته است."
            ) from exc
        raise IndexError_(f"گرفتن فایل شکست خورد: {exc}") from exc

    try:
        await net.retry(
            lambda: handle.download_to_drive(custom_path=destination),
            attempts=config.network_retries,
            label="فرو گرفتن فایل",
        )
    except TelegramError as exc:
        raise IndexError_(f"فرو گرفتن فایل شکست خورد: {exc}") from exc
    return destination


def fingerprint_path(
    path: Path,
) -> tuple[Fingerprint, str, object | None, object | None, np.ndarray]:
    """
    اثر انگشت، درهم‌سازی محتوا و ویژگی‌های صوتی را می‌سازد.

    درهم‌سازی برای یافتن تکراری دقیق به کار می‌آید؛ اثر انگشت برای
    یافتن تکه در نوا؛ ویژگی‌ها برای گمانه‌زنی سبک و مداح.

    اینجا FAN_OUT_INDEX به کار می‌رود نه پیش‌فرض بازجویی: گنجینه
    کم‌جفت می‌ماند و یک‌چهارم فضا می‌گیرد، حال آنکه بازجویی پرجفت
    همان تطبیق‌ها را می‌یابد.

    هر سه کار در یک بار رمزگشایی انجام می‌شود؛ رمزگشایی گران‌ترین
    گام است و دوباره کردنش هدر رفتن آشکار.
    """
    from core.audio import melody as melody_mod
    from core.audio.features import FeatureError, extract

    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    samples = decode(path)
    print_result = fingerprint(samples, fan_out=FAN_OUT_INDEX)

    # ویژگی‌ها اختیاری‌اند: نوای کوتاه یا ناهنجار ویژگی نمی‌دهد،
    # ولی این نباید نمایه‌سازی را که کار اصلی است بشکند.
    try:
        features = extract(samples)
    except FeatureError as exc:
        logger.debug("برداشت ویژگی از «%s» شدنی نبود: %s", path.name, exc)
        features = None

    # نشان خطِ آهنگ — همان که اجرای دیگرِ یک نوحه را می‌یابد. آن هم
    # اختیاری است و به همان دلیل: نوای کوتاه نشان نمی‌دهد.
    try:
        melody_sig = melody_mod.signature(samples)
    except Exception as exc:  # noqa: BLE001
        logger.debug("نشان خطِ آهنگ از «%s» ساخته نشد: %s", path.name, exc)
        melody_sig = None

    # صوتِ رمزگشایی‌شده هم برمی‌گردد: سنجشِ تکراری به آن نیاز
    # دارد و رمزگشاییِ دوباره، گران‌ترین گام را دو بار می‌کرد.
    return print_result, digest, features, melody_sig, samples


async def index_track(bot: Bot, track_id: int) -> int:
    """
    یک نوای گنجینه را نمایه می‌کند.

    بازگشتی: شمار عددهای نشانده‌شده.
    """
    record = database.get_track(track_id)
    if record is None:
        raise IndexError_(f"نوای {track_id} در دفتر نیست.")
    if not record["file_id"]:
        raise IndexError_(f"نوای {track_id} شناسهٔ فایل ندارد.")

    temp_path = config.tmp_dir / f"index_{track_id}.bin"
    try:
        await download(bot, record["file_id"], temp_path)

        loop = asyncio.get_running_loop()
        # اثر انگشت‌گیری کاری پردازنده‌بر است؛ در ریسه‌ای جدا انجام
        # می‌شود تا حلقهٔ رویداد و پاسخ‌گویی ربات نایستد.
        (
            print_result, digest, features, melody_sig, decoded
        ) = await loop.run_in_executor(None, fingerprint_path, temp_path)

        # ── تکراری؟ ─────────────────────────────────────────
        #
        # پیش از نشاندنِ اثر انگشت سنجیده می‌شود، وگرنه نوا خودش
        # را می‌یافت. اگر همان ضبط از پیش هست، این ردیف در آن
        # ادغام می‌شود و کار همین‌جا تمام است.
        from services import dedup

        twin = dedup.find_same_recording(track_id, decoded)
        if twin is not None:
            other_id, aligned = twin
            logger.info(
                "نوای %s همان ضبطِ نوای %s است (%s عدد هم‌راستا).",
                track_id, other_id, aligned,
            )
            winner = dedup.merge(other_id, track_id)
            if winner is not None and winner != track_id:
                # بازنده همین ردیف بود؛ نمایه‌سازی‌اش بی‌معناست.
                return 0

        rows = fp_store.store(track_id, print_result.hashes, print_result.offsets)
        database.execute(
            """
            UPDATE tracks
               SET sha256 = ?, duration = COALESCE(duration, ?), updated_at = datetime('now')
             WHERE id = ?
            """,
            (digest, print_result.duration_ms // 1000, track_id),
        )

        if features is not None:
            features_store.ensure_table()
            features_store.store(track_id, features)

        if melody_sig is not None:
            melody_store.ensure_table()
            melody_store.store(track_id, melody_sig)

        logger.info(
            "نوای %s نمایه شد: %s عدد، %s ثانیه، چگالی %.0f%s",
            track_id, rows, print_result.duration_ms // 1000, print_result.density,
            f"، تمپو {features.tempo:.0f}" if features is not None else "",
        )
        return rows

    except (DecodeError, FingerprintError) as exc:
        raise IndexError_(f"پردازش صوت نوای {track_id} شکست خورد: {exc}") from exc
    finally:
        temp_path.unlink(missing_ok=True)


async def index_pending(bot: Bot, limit: int = 20) -> tuple[int, int]:
    """
    نواهای نمایه‌نشده را یکی‌یکی نمایه می‌کند.

    بازگشتی: (شمار کامیاب، شمار ناکام)

    ناکامی یک نوا، کار را نمی‌ایستاند؛ تنها به گزارش می‌رود. یک
    فایل خراب نباید همهٔ نمایه‌سازی را زمین بزند.
    """
    # دو گروه در صف‌اند: نواهایی که هرگز نمایه نشده‌اند، و نواهایی
    # که ویژگی‌شان با ساختار کهنه ساخته شده. گروه دوم اثر انگشت
    # درستی دارند ولی گمانه‌زن نمی‌تواند بخواندشان؛ رمزگشایی دوباره
    # هر دو را با هم نو می‌کند.
    features_store.ensure_table()
    melody_store.ensure_table()
    pending = fp_store.pending_tracks(limit)
    seen = set(pending)
    for source in (features_store.pending(limit), melody_store.pending(limit)):
        for track_id in source:
            if track_id not in seen and len(pending) < limit:
                pending.append(track_id)
                seen.add(track_id)

    if not pending:
        return 0, 0

    logger.info("نمایه‌سازی %s نوای در انتظار آغاز شد.", len(pending))
    succeeded = failed = 0

    for track_id in pending:
        try:
            await index_track(bot, track_id)
            succeeded += 1
        except (IndexError_, TelegramError) as exc:
            # ── چرا هر ناکامی شمرده نمی‌شود ──────────────────
            #
            # پس از `MAX_INDEX_ATTEMPTS` ناکامی، نوا برای همیشه
            # کنار گذاشته می‌شود: نه در جست‌وجو یافت می‌شود و — که
            # بدتر است — نه در **سنجشِ تکراری** دیده می‌شود، پس
            # نسخهٔ دومش بی‌مانع ثبت می‌شود.
            #
            # ولی پیش‌تر لغزشِ شبکه هم شمرده می‌شد، و این پیوند
            # (به گفتهٔ `core/net.py`) شب‌ها ده‌ها بار می‌شکند. سه
            # قطعیِ گذرا کافی بود تا نوایی سالم برای همیشه نامرئی
            # شود. در گنجینهٔ راستین پنج نوا چنین از دست رفته
            # بودند — و دو تاشان همان نوای تکراری بودند که چون
            # اثر انگشت نداشتند، هر دو ثبت شدند.
            #
            # اکنون تنها ناکامیِ **ماندگار** شمرده می‌شود؛ لغزشِ
            # گذرا دور بعد دوباره آزموده می‌شود.
            transient = isinstance(exc, net.TRANSIENT)
            logger.warning(
                "نمایه‌سازی نوای %s شکست خورد%s: %s",
                track_id, " (گذرا)" if transient else "", exc,
            )
            if not transient:
                fp_store.note_attempt(track_id)
            failed += 1
        except Exception:  # noqa: BLE001
            logger.exception("خطای نابیوسیده در نمایه‌سازی نوای %s", track_id)
            fp_store.note_attempt(track_id)
            failed += 1

    logger.info("نمایه‌سازی پایان یافت: %s کامیاب، %s ناکام.", succeeded, failed)

    # نواهایی که از کوشش افتاده‌اند، بی‌صدا کنار نمانند: بی این
    # خط، نوایی که هرگز نمایه نشد در گنجینه می‌ماند و **نامرئی**
    # است — کاربر مداحی‌اش را می‌فرستد و پاسخی نمی‌گیرد، و هیچ‌کس
    # نمی‌داند چرا.
    broken = fp_store.broken_tracks()
    if broken:
        logger.warning(
            "%s نوا پس از %s کوشش نمایه نشدند و کنار گذاشته شدند: %s",
            len(broken), fp_store.MAX_INDEX_ATTEMPTS,
            ", ".join(str(row["id"]) for row in broken),
        )

    return succeeded, failed


# ═════════════════════════════════════════════════════════════
#  برچسب‌گذاری و جلد
# ═════════════════════════════════════════════════════════════

async def tag_and_republish(bot: Bot, track_id: int, chat_id: int | None = None) -> bool:
    """
    نوا را برچسب می‌زند، جلد می‌نشاند و نسخهٔ آراسته را جایگزین
    می‌کند.

    ## چرا اینجا و نه هنگام فرستادن

    فرستادن نوا با file_id بی‌درنگ است، چون فایل از پیش در تلگرام
    است. اگر می‌خواستیم هنگام هر فرستادن برچسب بزنیم، ناگزیر بودیم
    هر بار فرو بگیریم، برچسب بزنیم و دوباره بارگذاری کنیم — و
    بزرگ‌ترین برد معماری را از دست می‌دادیم.

    پس یک بار، هنگام ورود نوا به گنجینه، این کار انجام می‌شود و
    file_id تازه جای کهنه را می‌گیرد. از آن پس هر فرستادن، هم
    بی‌درنگ است هم آراسته.

    ## کجا می‌نشیند

    در گروه «نسخهٔ آراسته و بایگانی‌شده». آن گروه دو کار می‌کند:
    فایل را برای همیشه در تلگرام نگه می‌دارد (پس file_id ما هرگز
    نمی‌پوسد)، و بایگانی‌ای دیدنی از هر چه به گنجینه افزوده‌ایم
    می‌سازد. اگر پیکربندی نشده باشد، به گروه مداحی فرو می‌افتد —
    نبودِ یک کلید اختیاری نباید کاری درست را بشکند.

    بازگشتی: آیا کامیاب بود. ناکامی زیانی نمی‌رساند — نوای
    بی‌برچسب همچنان یافته و فرستاده می‌شود.
    """
    from bot.keyboards import inline
    from services import tagger

    record = database.get_track(track_id)
    if record is None or not record["file_id"]:
        return False

    target_chat = chat_id or config.ornate_target
    if not target_chat:
        return False

    # ── مدارشکن ─────────────────────────────────────────────
    # این سنجش **پیش از** فرو گرفتن است، و همین‌جا جانِ کار است.
    # پیش‌تر ترتیب وارونه بود: فایل چندمگابایتی فرو گرفته می‌شد،
    # برچسب می‌خورد، و آنگاه بارگذاری با «گفتگو یافت نشد» شکست
    # می‌خورد. در یک شب، هفده بار. اکنون یک بار سنجیده می‌شود و
    # از آن پس بی هیچ رفت‌وآمدی رد می‌شود.
    #
    # بازگشتیِ resolve_chat همان شناسه‌ای است که باید به آن فرستاد —
    # و شاید با آنچه در .env نوشته شده فرق کند؛ شناسهٔ ابرگروه دو
    # نمایش دارد و رونویسیِ شکل درونی، «Chat not found» می‌دهد.
    target_chat = await net.resolve_chat(bot, target_chat, "گروه نسخهٔ آراسته")
    if target_chat is None:
        # گروه بایگانی در دسترس نیست. اگر گروه مداحی هست، نسخهٔ
        # آراسته همان‌جا بنشیند — پیش‌تر این وعده در پیام پیش‌پرواز
        # داده می‌شد ولی هرگز انجام نمی‌گرفت.
        fallback = config.madahi_group_id
        if not fallback or fallback == (chat_id or config.ornate_target):
            return False
        target_chat = await net.resolve_chat(bot, fallback, "گروه مداحی")
        if target_chat is None:
            return False
        logger.info("گروه بایگانی در دسترس نبود؛ نسخهٔ آراسته به گروه مداحی می‌رود.")

    temp_path = config.tmp_dir / f"tag_{track_id}.mp3"
    try:
        await download(bot, record["file_id"], temp_path)

        loop = asyncio.get_running_loop()
        tagged = await loop.run_in_executor(
            None,
            lambda: tagger.tag_with_cover(
                temp_path,
                madah=record["madah"],
                title=record["title"],
                style=record["style"],
                lyrics=record["lyrics_snippet"],
                track_number=track_id,
            ),
        )
        if not tagged:
            return False

        async def _upload():
            # پرونده در هر کوشش از نو گشوده می‌شود؛ نشانگرِ خواندنِ
            # پروندهٔ نیمه‌خوانده به آغازش بازنمی‌گردد و کوشش دوم
            # فایلی تهی می‌فرستاد.
            with temp_path.open("rb") as handle:
                return await bot.send_audio(
                    chat_id=target_chat,
                    audio=handle,
                    caption=_ornate_caption(record),
                    # سرنویس با برچسب HTML نوشته می‌شود؛ بی این،
                    # تلگرام «<b>مداح:</b>» را همان‌گونه که هست
                    # چاپ می‌کرد و گروه بایگانی پر از برچسب خام بود.
                    parse_mode="HTML",
                    **tagger.audio_labels(record),
                    reply_markup=inline.ornate_actions(track_id),
                    disable_notification=True,
                    read_timeout=config.read_timeout,
                    write_timeout=config.write_timeout,
                    connect_timeout=config.connect_timeout,
                )

        sent = await net.retry(
            _upload,
            attempts=config.network_retries,
            label=f"بارگذاری نسخهٔ آراستهٔ نوای {track_id}",
        )

        if sent.audio is None:
            return False

        database.execute(
            """
            UPDATE tracks
               SET file_id = ?, file_unique_id = ?,
                   ornate_at = datetime('now'), updated_at = datetime('now')
             WHERE id = ?
            """,
            (sent.audio.file_id, sent.audio.file_unique_id, track_id),
        )
        logger.info("نوای %s برچسب خورد و جایگزین شد.", track_id)
        return True

    except (IndexError_, TelegramError) as exc:
        logger.warning("برچسب‌گذاری نوای %s شکست خورد: %s", track_id, exc)
        return False
    except Exception:  # noqa: BLE001
        logger.exception("خطای نابیوسیده در برچسب‌گذاری نوای %s", track_id)
        return False
    finally:
        temp_path.unlink(missing_ok=True)


def _ornate_caption(record) -> str:
    """
    سرنویس نسخهٔ آراسته.

    شناسنامه هم روی خودِ فایل می‌نشیند (نام و مداح در برچسب ID3) و
    هم اینجا در سرنویس. دوباره‌کاری نیست: برچسب را تنها کسی می‌بیند
    که فایل را دانلود کند، و سرنویس را هرکه گروه بایگانی را ورق
    بزند.
    """
    from core import texts

    # ایمن‌سازی بایسته است: این مقدارها از برچسب ID3 فایل‌ها
    # می‌آیند و برچسب‌زن‌ها گاه چیزی مانند «<unknown>» می‌گذارند —
    # که تلگرام آن را برچسب HTML می‌خواند و کل پیام را رد می‌کند.
    lines = ["🌿 <b>نسخهٔ آراسته و بایگانی‌شده</b>", ""]
    if record["madah"]:
        lines.append(f"<b>مداح:</b> {texts.escape(record['madah'])}")
    if record["style"]:
        lines.append(f"<b>سبک:</b> {texts.escape(record['style'])}")
    if record["title"]:
        lines.append(f"<b>نام نوا:</b> {texts.escape(record['title'])}")
    lines.append(f"<b>شمارهٔ نوا:</b> <code>{record['id']}</code>")
    return "\n".join(lines)


async def transcribe_pending(bot: Bot, limit: int = 3) -> tuple[int, int]:
    """
    نواهایی که هنوز متنشان درنیامده.

    ## چرا کارِ جدا و نه در دلِ نمایه‌سازی

    رونویسی گران است — چند ده ثانیه برای هر نوا روی CPU. اگر در
    دلِ `index_pending` می‌نشست، هر دسته چند دقیقه طول می‌کشید و
    نمایه‌سازی — که کارِ اصلی و فوری‌تر است — پشتش می‌ماند.

    پس جدا، و با دستهٔ کوچک (پیش‌فرض سه‌تا)، تا هر بار اندکی جلو
    برود بی‌آنکه چیزی را گروگان بگیرد.

    اگر مدل نصب نباشد، همان بار نخست بازمی‌گردد و دیگر نمی‌کوشد.

    بازگشتی: (شمار کامیاب، شمار ناکام)
    """
    from core.audio import transcribe as asr

    if not asr.available():
        return 0, 0

    rows = database.query_all(
        """
        SELECT id, file_id FROM tracks
         WHERE is_active = 1
           AND is_indexed = 1
           AND transcript IS NULL
           AND file_id IS NOT NULL
         ORDER BY sent_count DESC, id DESC
         LIMIT ?
        """,
        (limit,),
    )
    if not rows:
        return 0, 0

    done = failed = 0
    loop = asyncio.get_running_loop()
    for row in rows:
        track_id = int(row["id"])
        temp_path = config.tmp_dir / f"asr_{track_id}.bin"
        try:
            await download(bot, row["file_id"], temp_path)
            text = await loop.run_in_executor(
                None,
                lambda p=temp_path: asr.transcribe_file(
                    p,
                    model_size=config.whisper_model,
                    device=config.whisper_device,
                    compute_type=config.whisper_compute,
                ),
            )
            if text:
                database.set_transcript(track_id, text)
                done += 1
                logger.info(
                    "متنِ نوای %s درآمد (%s واژه).", track_id, len(text.split())
                )
            else:
                # رشتهٔ تهی می‌نشیند، نه NULL — وگرنه هر بار از نو
                # کوشیده می‌شد برای نوایی که متن ندارد (نوای بی‌کلام).
                database.set_transcript(track_id, "")
                failed += 1
        except Exception as exc:  # noqa: BLE001
            logger.warning("رونویسی نوای %s نشد: %s", track_id, exc)
            failed += 1
        finally:
            temp_path.unlink(missing_ok=True)

    return done, failed


async def republish_pending(bot: Bot, limit: int = 10) -> tuple[int, int]:
    """
    نواهایی که نسخهٔ آراسته‌شان هرگز در گروه بایگانی ننشست.

    ## چرا این کار بایسته شد

    برچسب‌گذاری، ناکامی‌اش را می‌بخشید و می‌گذشت — و همین درست بود،
    چون نوای بی‌برچسب هم یافته می‌شود. ولی «می‌بخشد و می‌گذرد» یعنی
    اگر گروه بایگانی یک شب در دسترس نبود، آن نواها **برای همیشه**
    از بایگانی بیرون می‌ماندند و هیچ‌کس نمی‌فهمید.

    اکنون ستون ornate_at می‌گوید کدام‌ها ننشسته‌اند، و این کار هر
    ربع ساعت چند تایی را دوباره می‌آزماید.
    """
    if not config.ornate_target:
        return 0, 0

    rows = database.query_all(
        """
        SELECT id FROM tracks
         WHERE is_active = 1 AND ornate_at IS NULL AND file_id IS NOT NULL
         ORDER BY created_at
         LIMIT ?
        """,
        (limit,),
    )
    ok = failed = 0
    for row in rows:
        if await tag_and_republish(bot, int(row["id"])):
            ok += 1
        else:
            # گروه در دسترس نیست یا فرو گرفتن نشد؛ آزمودن بقیه در
            # همین دور، تنها زمان هدر دادن است.
            failed += 1
            break
    return ok, failed


def ornate_pending_count() -> int:
    row = database.query_one(
        """
        SELECT COUNT(*) AS c FROM tracks
         WHERE is_active = 1 AND ornate_at IS NULL AND file_id IS NOT NULL
        """
    )
    return int(row["c"]) if row else 0


async def finalize_track(bot: Bot, track_id: int) -> bool:
    """
    کارِ پایانیِ هر نوای تازه: برچسب و جلد، سپس نمایه.

    ترتیبش سرنوشت‌ساز است — برچسب‌گذاری file_id را دگرگون می‌کند و
    نمایه باید به نسخهٔ پایانی بچسبد، وگرنه اثر انگشت به فایلی
    اشاره می‌کند که دیگر فرستاده نمی‌شود.

    ناکامی کار را نمی‌ایستاند: نوا با is_indexed=0 می‌ماند و کار
    دوره‌ای هر ربع ساعت دوباره می‌آزمایدش. بازگشتی می‌گوید نمایه
    شد یا نه.
    """
    from worker.queue import get_queue

    if database.get_setting("auto_tag", "1") == "1":
        try:
            await tag_and_republish(bot, track_id)
        except Exception as exc:  # noqa: BLE001
            logger.warning("برچسب‌گذاری نوای %s شکست خورد: %s", track_id, exc)

    try:
        await get_queue().run_async(index_track(bot, track_id))
        return True
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "نمایه‌سازی نوای %s شکست خورد؛ کار دوره‌ای دوباره می‌آزماید: %s",
            track_id, exc,
        )
        return False
