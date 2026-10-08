# -*- coding: utf-8 -*-
"""
شناختنِ مداح از **آوایش**.

## خواستهٔ کاربر، به بیان خودش

«اگر از اون شخص قبلا گوش داده باشم، طرف بدون اینکه بهم بگه این
کیه، بهش می‌گم فلانیه. ربات هم همین‌طوری باشه — اگر قبلاً صداش
شنیده باشه و اسم مداح نبود، خودش بنویسه.»

## آنچه از پیش بود

`core/audio/features.py` نشانِ آوا را درمی‌آورد (MFCC، تقابل
طیفی، کروما، گام) و `core/audio/classifier.py` مرکزِ آوایی هر
مداح را نگه می‌دارد و نزدیک‌ترین را می‌گوید. هر دو نوشته شده
بودند و کار می‌کردند.

آنچه نبود، **صدا زدنشان در جای درست**: گمانهٔ آوایی تنها در
«نواهای همانند» پس از یک جست‌وجوی ناکام به کار می‌رفت، نه آنجا
که نامِ مداح جا افتاده بود.

## مرزِ راستین

این گمانه است نه یقین. `guess_madah` خودش زیر آستانهٔ اطمینان
`None` می‌دهد، و آنچه از اینجا بیرون می‌آید در کارتِ شناسنامه به
تأییدِ گرداننده می‌رسد. هرچه نواهای برچسب‌خوردهٔ یک مداح بیشتر
شوند، گمانه استوارتر می‌شود — و `/train` همان را می‌کند.
"""
from __future__ import annotations

import asyncio
import logging
import time

logger = logging.getLogger(__name__)


async def identify_madah(bot, file_id: str):
    """
    مداحِ این فایل را از روی آوایش حدس می‌زند.

    بازگشتی: ‎(نامِ مداح، اطمینان)‎ یا None.

    None پاسخِ رایج و درستی است: گنجینهٔ کوچک، آوای ناشناخته، یا
    نوایی کوتاه‌تر از کفِ لازم. ناکامی — شبکه، رمزگشایی — هم
    None می‌دهد؛ نبودِ گمانه بهتر از گمانهٔ غلط است.
    """
    from config import config
    from core.audio.classifier import get_classifier
    from core.audio.decode import decode
    from core.audio.features import extract

    classifier = get_classifier()
    if not classifier.is_trained:
        # هنوز چیزی نیاموخته؛ فرو گرفتنِ فایل بیهوده است.
        return None

    temp = config.tmp_dir / f"voice_{int(time.time() * 1000)}.bin"
    try:
        from services.indexer import download

        await download(bot, file_id, temp)
        loop = asyncio.get_running_loop()
        features = await loop.run_in_executor(
            None, lambda: extract(decode(temp))
        )
        guess = await loop.run_in_executor(
            None, classifier.guess_madah, features
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug("شناختنِ مداح از آوا نشد: %s", exc)
        return None
    finally:
        try:
            temp.unlink(missing_ok=True)
        except OSError:
            pass

    if guess is None:
        return None
    logger.info(
        "آوای این نوا به «%s» می‌مانَد (اطمینان %.0f٪).",
        guess.label, guess.confidence * 100,
    )
    return guess.label, float(guess.confidence)
