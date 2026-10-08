# -*- coding: utf-8 -*-
"""
سنجهٔ لایهٔ متن.

## چرا واژه‌ها ساختگی‌اند

آزمون نباید به محتوای هیچ نوای راستینی وابسته باشد؛ آنچه سنجیده
می‌شود رفتارِ **تطبیق** است در برابر خطای رونویسی، نه شناختِ
متنی ویژه.

## چرا این ژنراتور، و نه ساده‌ترش

کوششِ نخستِ من همهٔ نواها را از یک انبانِ سیصدواژه‌ای می‌ساخت.
نتیجه‌اش سنجه‌ای گمراه‌کننده بود: هر دو نوا حدود ۸۵٪ واژگان
مشترک داشتند و امتیازِ «نوای بیگانه» تا ۰٫۹۱ می‌رفت — که در
جهانِ راستین چنین نیست.

اکنون هر نوا واژگانِ **ویژهٔ خودش** دارد و تنها ۳۰٪ از واژگانِ
مشترک (حروف ربط و واژه‌های پرتکرار) برمی‌دارد. و خطای رونویسی
هم آوایی است نه تصادفی: واژه کمی دگرگون می‌شود، نه اینکه واژهٔ
یکسره دیگری شود — که همان‌گونه است که رونویسِ ماشینی می‌لغزد.
"""
import io
import pathlib
import random
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from core import lyrics

ok = fail = 0


def check(label, cond, detail=""):
    global ok, fail
    if cond:
        ok += 1
        print(f"  ✓ {label}{detail}")
    else:
        fail += 1
        print(f"  ✗ {label}{detail}")


COMMON = [f"مشترک{i}" for i in range(25)]


def make_track(seed, length=120):
    """نوایی با واژگانِ ویژهٔ خودش، و اندکی واژهٔ مشترک."""
    r = random.Random(seed)
    own = [f"س{seed}و{i}" for i in range(60)]
    return " ".join(
        r.choice(COMMON) if r.random() < 0.30 else r.choice(own)
        for _ in range(length)
    )


def take_clip(text, words=12, seed=0):
    parts = text.split()
    r = random.Random(seed)
    start = r.randrange(0, max(1, len(parts) - words))
    return " ".join(parts[start : start + words])


def damage(text, rate, seed=0):
    """خطای آوایی: شنیدهٔ نادرستِ شبیه، یا واژهٔ جاافتاده."""
    r = random.Random(seed)
    out = []
    for w in text.split():
        roll = r.random()
        if roll < rate * 0.7:
            out.append(w[:-1] + "ه" if len(w) > 2 else w)
        elif roll < rate:
            continue
        else:
            out.append(w)
    return " ".join(out)


print("═" * 62)
print("  لایهٔ متن — تطبیق در برابر خطای رونویسی")
print("═" * 62)
print()

TRACKS = [(i, make_track(i)) for i in range(1, 26)]

print("▸ کلیپِ درست، با خطای فزایندهٔ رونویسی")
for rate, floor in ((0.0, 25), (0.2, 20), (0.3, 18), (0.4, 12)):
    hits = sum(
        1
        for tid, text in TRACKS
        if (got := lyrics.best_match(
            damage(take_clip(text, seed=tid), rate, seed=tid), TRACKS
        ))
        and got[0] == tid
    )
    check(
        f"خطای {int(rate * 100):>2}٪ رونویسی",
        hits >= floor,
        f" — {hits}/25 درست (کف {floor})",
    )

print()
print("▸ نوایی که در گنجینه نیست — سخت‌گیرترین سنجه")
false_hits = sum(
    1
    for seed in range(900, 940)
    if lyrics.best_match(
        take_clip(make_track(seed), seed=seed), TRACKS
    )
    is not None
)
check("مثبت کاذب", false_hits == 0, f" — {false_hits}/40")

print()
print("▸ نگهبان‌ها")
check("متنِ خیلی کوتاه رد می‌شود", lyrics.best_match("یک دو", TRACKS) is None)
check("متنِ تهی رد می‌شود", lyrics.best_match("", TRACKS) is None)
check("گنجینهٔ تهی رد می‌شود", lyrics.best_match(take_clip(TRACKS[0][1]), []) is None)

twin = make_track(1)
check(
    "دو نوای همسان، هیچ‌کدام برنده نمی‌شود",
    lyrics.best_match(take_clip(twin), [(1, twin), (2, twin)]) is None,
)

print()
print("═" * 62)
if fail:
    print(f"  ✗ {fail} سنجه ناکام ماند ({ok} گذشت)")
    sys.exit(1)
print(f"  ✓ هر {ok} سنجه گذشت")
print("═" * 62)
