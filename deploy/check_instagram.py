# -*- coding: utf-8 -*-
"""
سنجشِ اینستاگرام — پیش از راه‌اندازی ربات.

می‌گوید کوکی درست است یا نه، و اگر نه، دقیقاً چه ایرادی دارد.

    python deploy/check_instagram.py
    python deploy/check_instagram.py https://www.instagram.com/reel/XXXX/

بی نشانی، تنها پیکربندی سنجیده می‌شود (ارزان و آفلاین). با نشانی،
یک فروگرفتنِ راستین هم آزموده می‌شود.
"""
import io
import pathlib
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

problems: list[str] = []
notes: list[str] = []


def ok(text):
    print(f"  ✓ {text}")


def bad(text, fix=""):
    print(f"  ✗ {text}")
    problems.append(text + (f"\n      ← {fix}" if fix else ""))


print("=" * 62)
print("  سنجشِ اینستاگرام")
print("=" * 62)
print()

# ── ۱) yt-dlp ───────────────────────────────────────────────
print("▸ ابزار فروگرفتن")
try:
    import yt_dlp

    version = yt_dlp.version.__version__
    ok(f"yt-dlp نصب است: {version}")
    # نسخهٔ کهنه، شایع‌ترین سببِ ناکامیِ اینستاگرام است.
    year = int(version.split(".")[0])
    month = int(version.split(".")[1])
    if (year, month) < (2025, 6):
        bad(
            f"نسخهٔ {version} کهنه است",
            "pip install -U yt-dlp",
        )
    else:
        ok("نسخه به‌روز است")
except ImportError:
    bad("yt-dlp نصب نیست", "pip install -r requirements.txt")

# ── ۲) پیکربندی ─────────────────────────────────────────────
print()
print("▸ پیکربندی")
try:
    from config import config

    raw = getattr(config, "instagram_cookies_file", "")
    if not raw:
        bad(
            "INSTAGRAM_COOKIES_FILE در .env تهی است",
            "راهنما: deploy/INSTAGRAM.md",
        )
        cookie_path = None
    else:
        cookie_path = pathlib.Path(raw)
        if not cookie_path.is_absolute():
            cookie_path = config.base_dir / cookie_path
        ok(f"نشانیِ کوکی: {cookie_path}")
except Exception as exc:  # noqa: BLE001
    bad(f"خواندن پیکربندی نشد: {exc}")
    cookie_path = None

# ── ۳) خودِ پروندهٔ کوکی ────────────────────────────────────
print()
print("▸ پروندهٔ کوکی")
if cookie_path is None:
    print("  — (نشانی نداریم؛ رد شد)")
elif not cookie_path.exists():
    bad(
        "پرونده در آن نشانی نیست",
        "کوکی را از مرورگر بیرون بدهید و همان‌جا بگذارید",
    )
else:
    size = cookie_path.stat().st_size
    ok(f"پرونده هست ({size:,} بایت)")
    if size == 0:
        bad("پرونده تهی است")
    else:
        text = cookie_path.read_text(encoding="utf-8", errors="replace")
        lines = [ln for ln in text.splitlines() if ln.strip() and not ln.startswith("#")]

        # قالبِ Netscape: هفت ستون، جدا با tab
        tabbed = [ln for ln in lines if ln.count("\t") >= 6]
        if not tabbed:
            bad(
                "قالبش Netscape cookies.txt نیست",
                "افزونه باید خروجیِ cookies.txt بدهد، نه JSON",
            )
        else:
            ok(f"قالب درست است ({len(tabbed)} کوکی)")

        if "instagram.com" not in text:
            bad(
                "کوکیِ instagram.com در آن نیست",
                "هنگام بیرون‌دادن، باید در برگهٔ اینستاگرام باشید",
            )
        else:
            ok("کوکیِ instagram.com هست")

        # sessionid کلیدِ اصلی است؛ بی آن، ورود شمرده نمی‌شود.
        if "sessionid" in text:
            ok("کلیدِ sessionid هست")
        else:
            bad(
                "کلیدِ sessionid نیست",
                "یعنی هنگام بیرون‌دادن وارد حساب نبوده‌اید",
            )

        # هشدارِ ادب، نه ایراد
        import stat as _stat

        mode = cookie_path.stat().st_mode
        if mode & (_stat.S_IRGRP | _stat.S_IROTH):
            notes.append(
                "پرونده برای دیگران هم خواندنی است. روی سرور: "
                f"chmod 600 {cookie_path}"
            )

# ── ۴) آزمونِ راستین ────────────────────────────────────────
url = sys.argv[1] if len(sys.argv) > 1 else None
print()
print("▸ آزمونِ راستین")
if not url:
    print("  — نشانی ندادید؛ رد شد.")
    print("     برای آزمودن:  python deploy/check_instagram.py <نشانیِ پست>")
elif problems:
    print("  — اول ایرادهای بالا را درست کنید.")
else:
    import shutil
    import tempfile

    work = pathlib.Path(tempfile.mkdtemp(prefix="igcheck_"))
    try:
        from services import instagram

        print(f"  در حال فروگرفتن…  {url[:60]}")
        video = instagram.download(url, work)
        ok(f"گرفته شد: {video.path.name} ({video.path.stat().st_size:,} بایت)")
        if getattr(video, "duration", None):
            ok(f"درازا: {video.duration} ثانیه")
    except Exception as exc:  # noqa: BLE001
        key = getattr(exc, "message_key", "")
        bad(f"نشد: {key or type(exc).__name__} — {str(exc)[:120]}")
        if key == "instagram_needs_login":
            print("      ← کوکی یا نیست یا باطل شده. از نو بگذاریدش.")
    finally:
        shutil.rmtree(work, ignore_errors=True)

# ── داوری ───────────────────────────────────────────────────
print()
print("=" * 62)
if problems:
    print(f"  {len(problems)} ایراد:")
    for item in problems:
        print(f"    • {item}")
else:
    print("  ✓ همه‌چیز آماده است.")
for note in notes:
    print(f"  ⚠ {note}")
print("=" * 62)
sys.exit(1 if problems else 0)
