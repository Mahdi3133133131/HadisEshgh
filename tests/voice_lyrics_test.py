# -*- coding: utf-8 -*-
"""
سنجهٔ دو خواستهٔ تازه.

۱. **شناختِ مداح از آوا.** «اگر از اون شخص قبلاً گوش داده باشم،
   بدون اینکه بهم بگه این کیه، می‌گم فلانیه. ربات هم همین‌طوری
   باشه — اگر اسم مداح نبود، خودش بنویسه.»

۲. **یافتنِ نوا از روی تکه‌ای از شعر.** «طرف تیکه از مداحی نوشت،
   براش بفرستی» — و بی هیچ سرویسِ بیرونی.

هر دو موتور از پیش در پروژه بودند و صدا نمی‌شدند.
"""
import inspect
import io
import pathlib
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from core.db import database, features_store

ok = fail = 0


def check(label, cond, detail=""):
    global ok, fail
    if cond:
        ok += 1
        print(f"  ✓ {label}{detail}")
    else:
        fail += 1
        print(f"  ✗ {label}{detail}")


print("=" * 62)
print("  آوا و متن")
print("=" * 62)

database.init_db()
features_store.ensure_table()

# =============================================================
print()
print("▸ ۱. شناختِ مداح از آوا")
# =============================================================
from core.audio.classifier import get_classifier, retrain
from services import voice

madahs, styles, samples = retrain()
check("گمانه‌زن از نواهای برچسب‌خورده آموخت", samples > 0,
      f" — {madahs} مداح، {styles} سبک، {samples} نمونه")
check("و آموزش‌دیده شد", get_classifier().is_trained)

check("`identify_madah` هست", hasattr(voice, "identify_madah"))
src = inspect.getsource(voice.identify_madah)
check("پیش از فرو گرفتن، آموزش را می‌سنجد", "is_trained" in src)
check("فایلِ موقت را برمی‌دارد", "unlink" in src)

# و در جای درست صدا می‌شود: آنجا که نامِ مداح نیست
from bot.handlers import intake

nxt = inspect.getsource(intake._next)
check("در پذیرش، وقتی نام نیست، صدا می‌شود",
      "voice.identify_madah" in nxt)
check("و تنها در شاخهٔ «نام نبود»",
      nxt.index("else:") < nxt.index("voice.identify_madah"))
check("گمانه نشانه می‌خورد تا در کارت پیدا باشد",
      "madah_by_voice" in nxt)

# =============================================================
print()
print("▸ ۲. یافتنِ نوا از روی متن")
# =============================================================
from core.audio import transcribe as asr

check("موتورِ رونویسی در دسترس است", asr.available())

try:
    import faster_whisper  # noqa: F401
    check("faster-whisper نصب است", True)
except ImportError:
    check("faster-whisper نصب است", False)

# جست‌وجوی متنی باید متنِ نوا را هم ببیند
check("`search_tracks_by_lyrics` هست",
      hasattr(database, "search_tracks_by_lyrics"))
by_text = inspect.getsource(database.search_tracks_by_text)
check("جست‌وجوی متنی، `transcript` را هم می‌بیند", "transcript" in by_text)
check("و یافتهٔ نام/عنوان را نخست می‌آورد", "match_rank" in by_text)

# ── آزمونِ راستین، روی ردیفی ساختگی ─────────────────────────
#
# متنِ آزمایشی عمداً بی‌معناست: سنجه نباید به شعرِ راستینِ کسی
# بند باشد.
PROBE = "یاسینِ آزمایشیِ سنجه واژهٔ یکتا زیبق"
tid = database.add_track(
    file_id="VOICE_TEST", file_unique_id="UVOICE_TEST",
    source="test", title="نوای آزمایشی", madah="کربلایی آزماینده",
    style=None, duration=90,
)
try:
    database.set_transcript(tid, PROBE)
    hits = database.search_tracks_by_lyrics("زیبق")
    check("تکه‌ای از متن، نوا را می‌یابد",
          any(int(r["id"]) == tid for r in hits), f" — {len(hits)} یافته")

    both = database.search_tracks_by_text("زیبق")
    check("جست‌وجوی همگانی هم می‌یابدش",
          any(int(r["id"]) == tid for r in both))

    # و واژه‌ای که در هیچ متنی نیست، چیزی نمی‌دهد
    check("واژهٔ نبوده، یافته‌ای ندارد",
          not database.search_tracks_by_lyrics("قققق‌ناموجود"))
finally:
    database.execute("DELETE FROM tracks WHERE id = ?", (tid,))

check("سنجه ردِ پا نگذاشت",
      database.get_track(tid) is None)

# =============================================================
print()
print("▸ ۳. کارهای زمان‌بندی‌شده")
# =============================================================
main_src = pathlib.Path("main.py").read_text(encoding="utf-8")
check("رونویسی زمان‌بندی شده", "_transcribe_job" in main_src)
check("آموزشِ گمانه‌زن سرِ راه‌اندازی", "retrain()" in main_src)
check("و شبانه هم دوباره", "_retrain_job" in main_src)

print()
print("=" * 62)
if fail:
    print(f"  ✗ {fail} سنجه ناکام ماند ({ok} گذشت)")
    sys.exit(1)
print(f"  ✓ هر {ok} سنجه گذشت")
print("=" * 62)
