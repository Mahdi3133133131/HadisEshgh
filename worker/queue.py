"""
صف پردازش سنگین.

سنگین‌ترین ایراد پنهانی که می‌توانست این ربات را زمین بزند این بود:
اگر ده نفر با هم صوت بفرستند و پردازش درون خودِ گرداننده انجام شود،
حلقهٔ رویداد بند می‌آید و **همهٔ** ربات — حتی پاسخ به یک «سلام» —
می‌ایستد.

چاره: شمار کارهای هم‌زمان مهار می‌شود و بقیه در صف می‌مانند. کاربرِ
در صف، جایگاهش را می‌بیند؛ خاموشی بی‌شرح، بدترین گونهٔ چشم‌به‌راهی
است.

اثر انگشت‌گیری کاری پردازنده‌بر است، نه چشم‌به‌راهِ شبکه؛ پس در
استخر ریسه انجام می‌شود تا قفل مفسر پایتون حلقهٔ رویداد را نبندد.
"""

from __future__ import annotations

import asyncio
import logging
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

logger = logging.getLogger(__name__)


@dataclass
class JobStats:
    """آمار زنده، برای پنل گردانندگان و تخمین زمان."""

    completed: int = 0
    failed: int = 0
    total_seconds: float = 0.0
    recent: list[float] = field(default_factory=list)

    def record(self, seconds: float, ok: bool) -> None:
        if ok:
            self.completed += 1
        else:
            self.failed += 1
        self.total_seconds += seconds
        self.recent.append(seconds)
        if len(self.recent) > 50:
            self.recent.pop(0)

    @property
    def average_seconds(self) -> float:
        """
        میانگین زمان کارهای اخیر.

        از همین برای گفتن «زمان تقریبی» به کاربر بهره می‌بریم — که
        سند خواسته بود. عددی سنجیده، نه گمانی دلبخواه.
        """
        if not self.recent:
            return 0.0
        return sum(self.recent) / len(self.recent)


class JobQueue:
    """صفی با مهار هم‌زمانی."""

    def __init__(self, max_concurrent: int = 3, max_waiting: int = 40) -> None:
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._max_concurrent = max_concurrent
        self._max_waiting = max_waiting
        self._waiting = 0
        self._running = 0
        self._executor = ThreadPoolExecutor(
            max_workers=max_concurrent, thread_name_prefix="hadis-audio"
        )
        self.stats = JobStats()

    # ── وضعیت ────────────────────────────────────────────────
    @property
    def running(self) -> int:
        return self._running

    @property
    def waiting(self) -> int:
        return self._waiting

    @property
    def is_full(self) -> bool:
        return self._waiting >= self._max_waiting

    def position_estimate(self) -> int:
        """جایگاه تقریبی کسی که هم‌اکنون در صف بنشیند."""
        return self._waiting + 1

    def wait_estimate_seconds(self) -> float:
        """
        تخمین زمان چشم‌به‌راهی، بر پایهٔ میانگین کارهای اخیر.

        تا هنگامی که هیچ کاری انجام نشده، تخمینی در کار نیست و
        صفر برمی‌گردد؛ گفتن عددی ساختگی، بدتر از نگفتن است.
        """
        average = self.stats.average_seconds
        if average <= 0:
            return 0.0
        ahead = self._waiting + self._running
        return average * (ahead / self._max_concurrent + 1)

    # ── اجرا ─────────────────────────────────────────────────
    def _blame(self, entered: bool) -> None:
        """
        اگر نوبت هرگز نرسید، از شمار چشم‌به‌راهان کم می‌کند.

        ═══════════════════════════════════════════════════════
          چرا این تابع هست، و چرا پیش‌تر نبود
        ═══════════════════════════════════════════════════════

        پیش‌تر اینجا یک `except BaseException` بود که با **حدس**
        داوری می‌کرد:

            if self._waiting > 0 and self._running == 0:
                self._waiting -= 1

        آن شرط، پرسشی را می‌پرسید که پاسخش را نمی‌دانست. هر دو
        سویش نادرست بود:

        **کم کردنِ نابجا.** اگر خودِ کار خطا می‌داد — و خطای
        رمزگشایی در کار روزمره پیش می‌آید؛ چهار جای search.py
        همین را می‌گیرند — این شاخه هم اجرا می‌شد، حال آنکه از
        شمار چشم‌به‌راهان پیش‌تر کم شده بود. پس دو بار کم می‌شد و
        شمارنده به منفی می‌رفت.

        **کم نکردنِ نابجا.** اگر کاربر در میانهٔ صف لغو می‌شد
        ولی کاری در دست انجام بود، `_running == 0` برقرار نبود و
        هیچ کم نمی‌شد. آن یک واحد **برای همیشه** می‌ماند. با
        چهل بار تکرار، `is_full` صف را برای همیشه پر نشان می‌داد
        و ربات هیچ بازجویی تازه‌ای نمی‌پذیرفت — بی‌آنکه کسی
        بفهمد چرا.

        چارهٔ درست حدس زدن نیست، دانستن است: تنها کسی که نوبتش
        نرسیده هنوز چشم‌به‌راه است.
        """
        if not entered:
            self._waiting -= 1

    async def run(self, func: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        """
        کاری پردازنده‌بر را در استخر ریسه و زیر مهار هم‌زمانی
        می‌راند.
        """
        self._waiting += 1
        entered = False
        try:
            async with self._semaphore:
                # میان گرفتن نوبت و این سطر هیچ await ای نیست، پس
                # پنجره‌ای برای لغو شدن در این میان وجود ندارد.
                entered = True
                self._waiting -= 1
                self._running += 1
                started = time.monotonic()
                ok = False
                try:
                    loop = asyncio.get_running_loop()
                    if kwargs:
                        from functools import partial

                        result = await loop.run_in_executor(
                            self._executor, partial(func, *args, **kwargs)
                        )
                    else:
                        result = await loop.run_in_executor(self._executor, func, *args)
                    ok = True
                    return result
                finally:
                    self._running -= 1
                    self.stats.record(time.monotonic() - started, ok)
        finally:
            self._blame(entered)

    async def run_async(self, coro: Awaitable[Any]) -> Any:
        """کاری ناهم‌گام (مانند فرو گرفتن) را زیر همان مهار می‌راند."""
        self._waiting += 1
        entered = False
        try:
            async with self._semaphore:
                entered = True
                self._waiting -= 1
                self._running += 1
                started = time.monotonic()
                ok = False
                try:
                    result = await coro
                    ok = True
                    return result
                finally:
                    self._running -= 1
                    self.stats.record(time.monotonic() - started, ok)
        finally:
            self._blame(entered)

    def shutdown(self) -> None:
        self._executor.shutdown(wait=False)


_queue: JobQueue | None = None


def get_queue() -> JobQueue:
    """صف یگانهٔ برنامه."""
    global _queue
    if _queue is None:
        from config import config

        _queue = JobQueue(max_concurrent=config.max_concurrent_jobs)
        logger.info(
            "صف پردازش با %s کارگر هم‌زمان آماده شد.", config.max_concurrent_jobs
        )
    return _queue
