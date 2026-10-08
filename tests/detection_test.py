# -*- coding: utf-8 -*-
"""
سنجهٔ «چیزِ بی‌ربط دستِ کاربر داده نشود».

دو نگهبان:
  ۱. داوریِ گمانه‌ای (رنگ آوا) هرگز به کاربر نمی‌رود
  ۲. یافتهٔ نامربوطِ تارنما از کفِ ربط رد نمی‌شود
"""
import io
import pathlib
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

ok = fail = 0


def check(label, cond, detail=""):
    global ok, fail
    if cond:
        ok += 1
        print(f"  ✓ {label}{detail}")
    else:
        fail += 1
        print(f"  ✗ {label}{detail}")


print("═" * 62)
print("  چیزِ بی‌ربط دستِ کاربر داده نشود")
print("═" * 62)
print()

# ── ۱. گمانه ────────────────────────────────────────────────
print("▸ داوریِ گمانه‌ای")
from core.audio import verdict as V

guess = V.decide(None, [], [], [(7, 0.9)])
check("موتور خودش گمانه را می‌سازد",
      guess is not None and guess.kind is V.Kind.GUESS)

source = io.open(
    pathlib.Path(__file__).resolve().parent.parent / "bot" / "handlers" / "search.py",
    encoding="utf-8",
).read()
body = source.split("def _fingerprint_and_match")[1].split("\nasync def ")[0]
check("ولی مسیرِ کاربر آن را می‌بندد",
      "Kind.GUESS" in body and "return None" in body)

# نگهبان باید **پس از** ساختنِ پاسخ باشد، نه پیش از آن — وگرنه
# داوری‌های استوار را هم می‌بلعد.
check("و تنها گمانه را می‌بندد، نه بقیه را",
      body.count("return answer") == 1)

# ── ۲. کفِ ربط تارنما ──────────────────────────────────────
print()
print("▸ کفِ ربطِ یافته‌های تارنما")
from services.sites import MIN_RELEVANCE, relevance

cases = [
    ("محمود کریمی", "دانلود مداحی شور از حاج محمود کریمی", True),
    ("محمود کریمی", "مداحی محمود کریمی - شب اول محرم", True),
    ("محمود کریمی", "دانلود مداحی مهدی رسولی", False),
    ("محمود کریمی", "نوحه جدید سال ۱۴۰۳", False),
    ("دیوونه حسینم", "دانلود مداحی دیوونه حسینم", True),
    ("دیوونه حسینم", "دانلود مداحی حسین جان", False),
    ("رسول برنا", "مخلوق خالق علی از رسول برنا", True),
    ("رسول برنا", "دانلود آهنگ جدید", False),
]
for term, title, want in cases:
    score = relevance(term, title)
    passed = score >= MIN_RELEVANCE
    check(f"«{term[:14]}» ← «{title[:30]}»", passed == want,
          f" → {score:.2f}")

# جداییِ دو توزیع باید پهن بماند؛ اگر روزی نزدیک شدند، کف باید
# دوباره سنجیده شود.
yes = min(relevance(t, x) for t, x, w in cases if w)
no = max(relevance(t, x) for t, x, w in cases if not w)
check("جدایی پهن است", yes - no > 0.3, f" → درست≥{yes:.2f} · نادرست≤{no:.2f}")

print()
print("═" * 62)
if fail:
    print(f"  ✗ {fail} سنجه ناکام ماند ({ok} گذشت)")
    sys.exit(1)
print(f"  ✓ هر {ok} سنجه گذشت")
print("═" * 62)
