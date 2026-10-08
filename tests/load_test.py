"""
آزمون بار — بیست بازجویی هم‌زمان.

اجرا:  python tests/load_test.py

سنگین‌ترین ایراد پنهانی که می‌توانست این ربات را زمین بزند این بود:
اگر ده نفر با هم آوا بفرستند و پردازش درون خودِ گرداننده انجام شود،
حلقهٔ رویداد بند می‌آید و **همهٔ** ربات — حتی پاسخ به یک «سلام» —
می‌ایستد. صف پردازش برای همین ساخته شد؛ این آزمون می‌سنجد که براستی
کار می‌کند.

پنج چیز سنجیده می‌شود:

  ۱. هم‌زمانی از سقف رد نمی‌شود
  ۲. حلقهٔ رویداد در سراسر بار پاسخ‌گو می‌ماند
  ۳. شمارندهٔ صف پس از کارهای **ناکام** درست می‌ماند
     — و این همان جایی است که باگ بود
  ۴. لغو شدن در میانهٔ صف، شمارنده را خراب نمی‌کند
  ۵. نوشتن هم‌زمان بر SQLite از چند ریسه، رکوردی گم نمی‌کند

هیچ پیوندی با تلگرام گرفته نمی‌شود.
"""

import asyncio
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from core.console import enable_utf8_console  # noqa: E402

enable_utf8_console()

from worker.queue import JobQueue  # noqa: E402

MAX_CONCURRENT = 3
REQUESTS = 20

# بیشترین درنگی که حلقهٔ رویداد می‌تواند داشته باشد تا هنوز
# «پاسخ‌گو» شمرده شود. کاربر درنگ زیر یک دهم ثانیه را حس نمی‌کند.
#
# بر صدکِ ۹۵ داوری می‌شود نه بر بیشینه: یک درنگ تکی هنگام برپا
# شدن استخر ریسه یا زباله‌روبیِ پایتون، «قفل شدن ربات» نیست و
# داوری بر آن، آزمونی می‌سازد که با بخت می‌گذرد و با بخت می‌افتد.
RESPONSIVE_MS = 60


def step(n, label):
    print(f"\n{n}. {label}")


# ═════════════════════════════════════════════════════════════
#  کارهای ساختگی
# ═════════════════════════════════════════════════════════════

_peak = 0
_now = 0
_lock = threading.Lock()


def busy(seconds: float = 0.12) -> str:
    """
    حلقهٔ پایتونیِ خالص — **بدترین حالت**، نه کار راستین.

    قفل مفسر را در سراسر کار نگه می‌دارد. هیچ‌کدام از کارهای
    راستینِ این صف چنین نیستند (بنگرید به real_work)، ولی نگه
    داشتنش ارزش دارد: اگر روزی کسی کار پایتونیِ سنگینی به صف
    افزود، عددش همین‌جا پیدا می‌شود.
    """
    global _peak, _now
    with _lock:
        _now += 1
        _peak = max(_peak, _now)
    try:
        # چرخش راستین، نه sleep — تا اگر روزی کسی run را از استخر
        # ریسه بیرون بیاورد، این آزمون بی‌درنگ بگیردش.
        end = time.monotonic() + seconds
        total = 0
        while time.monotonic() < end:
            total += 1
        return f"ok:{total}"
    finally:
        with _lock:
            _now -= 1


def real_work(_seconds: float = 0.0) -> str:
    """
    همان کاری که صف براستی می‌راند: اثر انگشت‌گیری.

    numpy و scipy قفل مفسر را هنگام کار عددی رها می‌کنند، و
    رمزگشایی که ffmpeg است اصلاً زیرفرایند جداست. پس حلقهٔ رویداد
    گرسنه نمی‌ماند — و داوریِ «آیا ربات زیر بار پاسخ‌گو می‌ماند»
    باید بر همین باشد، نه بر حلقهٔ ساختگی.
    """
    global _peak, _now
    import numpy as np

    from core.audio.decode import SAMPLE_RATE
    from core.audio.fingerprint import fingerprint

    with _lock:
        _now += 1
        _peak = max(_peak, _now)
    try:
        rng = np.random.default_rng(7)
        seconds = 25
        t = np.arange(SAMPLE_RATE * seconds) / SAMPLE_RATE
        # چند آهنگ روی هم، تا قله‌های راستین پدید آیند
        wave = sum(
            np.sin(2 * np.pi * f * t) * (0.6 ** i)
            for i, f in enumerate((180.0, 360.0, 545.0, 720.0))
        )
        wave += 0.05 * rng.standard_normal(t.size)
        return f"ok:{fingerprint(wave.astype(np.float32)).hashes.size}"
    finally:
        with _lock:
            _now -= 1


class Boom(RuntimeError):
    """همان گونه خطایی که DecodeError و FingerprintError‌اند."""


def failing(seconds: float = 0.05):
    busy(seconds)
    raise Boom("رمزگشایی شکست خورد")


# ═════════════════════════════════════════════════════════════

async def main() -> int:
    global _peak, _now
    problems: list[str] = []

    # ── ۱ و ۲ — بار هم‌زمان ─────────────────────────────────
    step(1, f"{REQUESTS} بازجویی هم‌زمان، با سقف {MAX_CONCURRENT} کارگر")
    print("   (کار راستین: اثر انگشت‌گیری از ۲۵ ثانیه آوا، برای هر بازجویی)")
    queue = JobQueue(max_concurrent=MAX_CONCURRENT)
    _peak = _now = 0

    # ضربان‌سنج: هر ۱۰ میلی‌ثانیه بیدار می‌شود. اگر حلقهٔ رویداد
    # بند بیاید، فاصلهٔ بیداری‌ها بالا می‌رود — و همان، دقیقاً همان
    # چیزی است که کاربر به شکل «ربات جواب نمی‌دهد» می‌بیند.
    gaps: list[float] = []
    beating = True

    async def heartbeat():
        last = time.monotonic()
        while beating:
            await asyncio.sleep(0.01)
            now = time.monotonic()
            gaps.append((now - last) * 1000)
            last = now

    pulse = asyncio.create_task(heartbeat())
    started = time.monotonic()
    results = await asyncio.gather(*(queue.run(real_work) for _ in range(REQUESTS)))
    elapsed = time.monotonic() - started
    beating = False
    await pulse

    ordered = sorted(gaps)
    worst = ordered[-1] if ordered else 0.0
    p95 = ordered[int(len(ordered) * 0.95)] if ordered else 0.0
    middle = ordered[len(ordered) // 2] if ordered else 0.0
    print(f"   {REQUESTS} کار در {elapsed:.1f} ثانیه؛ بیشینهٔ هم‌زمانی {_peak}")

    if _peak > MAX_CONCURRENT:
        problems.append(f"هم‌زمانی از سقف رد شد: {_peak} > {MAX_CONCURRENT}")
    else:
        print(f"   ✓ هم‌زمانی هرگز از {MAX_CONCURRENT} رد نشد")

    if len(results) != REQUESTS or not all(r.startswith("ok:") for r in results):
        problems.append("همهٔ کارها به سرانجام نرسیدند")
    else:
        print(f"   ✓ هر {REQUESTS} کار به سرانجام رسید")

    print(
        f"   درنگ حلقهٔ رویداد: میانه {middle:.0f} · صدک۹۵ {p95:.0f} "
        f"· بیشینه {worst:.0f} میلی‌ثانیه"
    )
    if p95 > RESPONSIVE_MS:
        problems.append(
            f"حلقهٔ رویداد در صدک ۹۵ به {p95:.0f} م.ث رسید — ربات زیر بار "
            f"به پیام‌ها دیر پاسخ می‌دهد"
        )
    else:
        print(f"   ✓ ربات در سراسر بار پاسخ‌گو ماند (صدک۹۵ زیر {RESPONSIVE_MS} م.ث)")

    if queue.waiting != 0 or queue.running != 0:
        problems.append(f"شمارنده پس از بار: صف {queue.waiting}، در دست {queue.running}")
    else:
        print("   ✓ شمارنده به صفر بازگشت")

    # ── ۲ — بدترین حالت، تنها به گزارش ──────────────────────
    step(2, "بدترین حالت: کار پایتونیِ خالص که قفل مفسر را رها نمی‌کند")
    queue2 = JobQueue(max_concurrent=MAX_CONCURRENT)
    gaps2: list[float] = []
    beating = True

    async def heartbeat2():
        last = time.monotonic()
        while beating:
            await asyncio.sleep(0.01)
            now = time.monotonic()
            gaps2.append((now - last) * 1000)
            last = now

    pulse2 = asyncio.create_task(heartbeat2())
    await asyncio.gather(*(queue2.run(busy) for _ in range(REQUESTS)))
    beating = False
    await pulse2
    queue2.shutdown()

    o2 = sorted(gaps2)
    print(
        f"   درنگ: میانه {o2[len(o2)//2]:.0f} · صدک۹۵ {o2[int(len(o2)*0.95)]:.0f} "
        f"· بیشینه {o2[-1]:.0f} میلی‌ثانیه"
    )
    print("   ⓘ این عدد داوری نمی‌شود. هیچ‌یک از کارهای امروزِ صف پایتونیِ")
    print("     خالص نیست؛ ولی اگر روزی شد، اندازه‌اش اینجاست.")

    # ── ۳ — کارهای ناکام ────────────────────────────────────
    step(3, "کارهای ناکام، در میانهٔ صفِ شلوغ")
    print("   (خطای رمزگشایی در کار روزمره پیش می‌آید؛ نباید شمارنده را بشکند)")
    queue = JobQueue(max_concurrent=MAX_CONCURRENT)

    async def guarded(fn):
        try:
            return await queue.run(fn)
        except Boom:
            return "boom"

    # آمیخته، تا هنگام شکستِ یکی، دیگران در صف باشند
    jobs = [failing if i % 2 else busy for i in range(REQUESTS)]
    out = await asyncio.gather(*(guarded(fn) for fn in jobs))

    booms = sum(1 for o in out if o == "boom")
    print(f"   {booms} ناکام، {len(out) - booms} کامیاب")
    print(f"   شمارندهٔ صف پس از همه: {queue.waiting}")

    if queue.waiting != 0:
        problems.append(
            f"شمارندهٔ صف پس از کارهای ناکام {queue.waiting} است، نه صفر — "
            f"با گذر زمان یا منفی می‌شود یا صف را برای همیشه پر نشان می‌دهد"
        )
    else:
        print("   ✓ شمارنده درست ماند")

    if queue.stats.failed != booms:
        problems.append(f"آمار ناکامی {queue.stats.failed} است، نه {booms}")
    else:
        print(f"   ✓ آمار ناکامی درست شمرده شد: {queue.stats.failed}")

    # ── ۴ — لغو در میانهٔ صف ────────────────────────────────
    step(4, "لغو شدن پیش از رسیدن نوبت")
    queue = JobQueue(max_concurrent=1)

    slow = [asyncio.create_task(queue.run(busy, 0.3)) for _ in range(2)]
    await asyncio.sleep(0.05)
    doomed = [asyncio.create_task(queue.run(busy, 0.1)) for _ in range(3)]
    await asyncio.sleep(0.02)
    for task in doomed:
        task.cancel()
    await asyncio.gather(*doomed, return_exceptions=True)
    await asyncio.gather(*slow, return_exceptions=True)
    await asyncio.sleep(0.05)

    print(f"   شمارنده پس از ۳ لغو: صف {queue.waiting}، در دست {queue.running}")
    if queue.waiting != 0 or queue.running != 0:
        problems.append(
            f"لغو شدن شمارنده را خراب کرد: صف {queue.waiting}، در دست {queue.running}"
        )
    else:
        print("   ✓ لغو، شمارنده را خراب نکرد")

    # ── ۵ — نوشتن هم‌زمان بر SQLite ─────────────────────────
    step(5, "نوشتن هم‌زمان بر SQLite از چند ریسه")
    from core.db import database as db

    db.init_db()
    db.execute("CREATE TABLE IF NOT EXISTS _load_probe (id INTEGER PRIMARY KEY, who TEXT)")
    db.execute("DELETE FROM _load_probe")

    ROWS = 40

    def write_row(index: int) -> None:
        # هر ریسه اتصال خودش را می‌گیرد؛ همان کاری که صف می‌کند
        db.execute("INSERT INTO _load_probe (who) VALUES (?)", (f"t{index}",))

    q2 = JobQueue(max_concurrent=MAX_CONCURRENT)
    await asyncio.gather(*(q2.run(write_row, i) for i in range(ROWS)))

    count = db.query_one("SELECT COUNT(*) AS c FROM _load_probe")["c"]
    print(f"   {count} از {ROWS} رکورد نشست")
    if count != ROWS:
        problems.append(f"{ROWS - count} رکورد در نوشتن هم‌زمان گم شد")
    else:
        print("   ✓ هیچ رکوردی گم نشد (WAL کار می‌کند)")
    db.execute("DROP TABLE _load_probe")

    for q in (queue, q2):
        q.shutdown()

    # ── داوری ───────────────────────────────────────────────
    print("\n" + "═" * 62)
    if problems:
        print("  ✗ آزمون بار ایراد یافت")
        print("═" * 62)
        for p in problems:
            print(f"\n  • {p}")
        return 1
    print("  ✓ ربات زیر بار قفل نشد و شمارنده‌ها درست ماندند")
    print("═" * 62)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
