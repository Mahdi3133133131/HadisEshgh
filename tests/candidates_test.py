# -*- coding: utf-8 -*-
"""
سنجهٔ نامزدها، پلهٔ چهارم، و یادگیری.

خواستهٔ کاربر، به بیان خودش: «انگلیسی به فارسی خیلی راحت هم هست —
A=آ، B=ب، C=س یا ک، D=د …»

و همان «C = س یا ک» گرهِ کار بود: نگاشت یک‌به‌یک نیست. پس به‌جای
یک نگارش، همهٔ نگارش‌های شدنی ساخته می‌شود و آنکه در گنجینه هست
برنده است.

سه بخش:
  ۱. خودِ سازندهٔ نامزدها
  ۲. پلهٔ چهارم — رسیدن به نامِ گنجینه، بی‌پرسش
  ۳. یادگیری — تصحیحِ گرداننده دفعهٔ بعد بگیرد
"""
import io
import pathlib
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from core.db import database, madah_aliases
from services import persianize as P
from services import translit
from services.captions import known_madahs, resolve_madah

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
print("  نامزدها و یادگیری")
print("=" * 62)

database.init_db()

# =============================================================
print()
print("▸ ۱. سازندهٔ نامزدها")
# =============================================================

# هر نمونه باید نگارشِ درست را **میان** نامزدهایش داشته باشد.
WANT = [
    ("Hosein", "حسین"), ("Morteza", "مرتضی"), ("Ali", "علی"),
    ("Mahdi", "مهدی"), ("Rasoli", "رسولی"), ("Borna", "برنا"),
    ("Sotude", "ستوده"), ("Tanha", "تنها"), ("Tako", "تکو"),
    ("Baz", "باز"), ("Fani", "فانی"), ("Reza", "رضا"),
    ("Abbas", "عباس"), ("Dobare", "دوباره"), ("Taheri", "طاهری"),
]
hits = 0
worst = 0
for latin, want in WANT:
    forms = P.candidates(latin)
    got = forms is not None and want in forms
    hits += got
    worst = max(worst, len(forms) if forms else 0)
check(
    f"نگارشِ درست میانِ نامزدهاست ({hits} از {len(WANT)})",
    hits >= 14,
    f" — بیشترین شمارِ نامزد: {worst}",
)

check("همخوانِ دوتایی یکی می‌شود", "عباس" in (P.candidates("Abbas") or set()))
check("«C» هم س می‌دهد هم ک",
      {"سام", "کام"} <= (P.candidates("Cam") or set()))
check("«a»ی پایانی هم ا هم ی",
      {"رضا", "رضی"} <= (P.candidates("Reza") or set()))

check("انفجار None می‌دهد", P.candidates("Baz Dobare Tako Tanha") is None)
check("تهی، تهی می‌ماند", P.candidates("") == set())
check("واژهٔ فارسی دست نمی‌خورد",
      P.candidates("محمود کریمی") == {"محمود کریمی"})
check("زباله می‌افتد",
      all("upmusic" not in c.lower() for c in (P.candidates("Borna UpMusic") or [])))

# =============================================================
print()
print("▸ ۲. پلهٔ چهارم — بی‌پرسش به نامِ گنجینه")
# =============================================================
known = known_madahs()
if len(known) < 5:
    print("  ⚠ گنجینه کوچک است؛ این بخش رد شد.")
else:
    for latin, want in [
        ("Hosein Sotude", "کربلایی حسین ستوده"),
        ("Borna", "کربلایی رسول برنا"),
        ("Morteza Yebranezhad", "کربلایی مرتضی یبرنژاد"),
        ("Payam Kiani", "کربلایی پیام کیانی"),
        ("Hosein Taheri", "کربلایی حسین طاهری"),
        ("Javad Zaker", "سید جواد ذاکر"),
    ]:
        got = resolve_madah(latin)
        check(f"«{latin}»", got == want, f" → {got}")

    # نامی که در گنجینه نیست نباید به زور به چیزی چسبانده شود؛
    # حدس می‌خورد و به تأییدِ گرداننده می‌رسد.
    stranger = resolve_madah("Mahdi Rasoli")
    check("نامِ ناشناخته به زور تطبیق نمی‌شود",
          stranger not in known.values(), f" → {stranger}")
    check("ولی دست‌کم فارسی می‌شود",
          bool(stranger) and not P.is_latin(stranger))

# =============================================================
print()
print("▸ ۳. یادگیری — تصحیح دفعهٔ بعد بگیرد")
# =============================================================
#
# این تا امروز **هرگز** کار نکرده بود: نامِ مستعار با کلیدِ حدسِ
# فارسی ثبت می‌شد، نه نگارشِ لاتینِ خام، و آن دو کلید یکی نیستند.
RAW, FIXED = "Mahdi Rasoli", "مهدی رسولی"
had = madah_aliases.resolve(RAW)
try:
    before = resolve_madah(RAW)
    check("پیش از تصحیح، حدس است", before != FIXED, f" → {before}")

    stored = madah_aliases.remember(RAW, FIXED, added_by=None)
    check("نامِ مستعار با کلیدِ لاتین ثبت شد", bool(stored),
          f" — کلید: {translit.skeleton(RAW)}")

    after = resolve_madah(RAW)
    check("دفعهٔ بعد بی‌پرسش گرفت", after == "کربلایی " + FIXED, f" → {after}")
finally:
    # سنجه نباید گنجینهٔ راستین را آلوده بگذارد.
    madah_aliases.forget(RAW)
    if had:
        madah_aliases.remember(RAW, had, added_by=None)

check("سنجه ردِ پا نگذاشت", madah_aliases.resolve(RAW) == had)

# =============================================================
print()
print("=" * 62)
if fail:
    print(f"  ✗ {fail} سنجه ناکام ماند ({ok} گذشت)")
    sys.exit(1)
print(f"  ✓ هر {ok} سنجه گذشت")
print("=" * 62)
