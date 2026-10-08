# -*- coding: utf-8 -*-
"""
سنجهٔ نامِ فارسی.

## دو کارِ جدا، با دو انتظارِ جدا

**قاعده‌های غیرحدسی** — برداشتنِ لقب و جداکننده — باید **همیشه**
درست باشند. اینها سنجهٔ سخت‌گیرند.

**برگردانِ لاتین** حدسی است و ادعای دقت ندارد. آنچه اینجا سنجیده
می‌شود این است که زنجیرهٔ کامل — تطبیقِ آوایی با نامِ موجود، و
تنها پس از آن نگاشتِ حرفی — نامی را که در گنجینه هست **درست**
بدهد. برای نامِ تازه، تنها انتظار این است که خروجی فارسی باشد.
"""
import io
import pathlib
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from core.db import database
from services import persianize as P

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
print("  نامِ فارسی، همیشه")
print("═" * 62)
print()

database.init_db()

# ── قاعده‌های غیرحدسی ───────────────────────────────────────
print("▸ برداشتنِ واژه‌های اضافه — باید همیشه درست باشد")
for raw, field, want in [
    ("کربلایی مرتضی یبرنژاد", "madah", "مرتضی یبرنژاد"),
    ("حاج محمود کریمی", "madah", "محمود کریمی"),
    ("حاج آقا مجتبی رمضانی", "madah", "مجتبی رمضانی"),
    ("شور | ماهم حضرت رضا", "title", "ماهم حضرت رضا"),
    ("زمینه / دیوونه حسینم", "title", "دیوونه حسینم"),
    ("دلبر ابالفضل / احسان لطفی", "madah", "احسان لطفی"),
]:
    got = P.clean_name(raw, field)
    check(f"«{raw[:26]}»", got == want, f" → {got}")

print()
print("▸ نامی که تنها از لقب ساخته شده، تهی نمی‌شود")
check("«حاج» تنها", P.strip_honorifics("حاج") == "حاج")
check("نامِ تهی", P.clean_name("") == "")
check("نامِ فقط فاصله", P.clean_name("   ") == "")

print()
print("▸ زبالهٔ نامِ فایل")
check("UpMusic برداشته می‌شود", "UpMusic" not in P.to_persian("Borna ~ UpMusic"))
check("mp3 برداشته می‌شود", "mp3" not in P.to_persian("Borna mp3").lower())

# ── زنجیرهٔ کامل ───────────────────────────────────────────
print()
print("▸ زنجیرهٔ کامل — نامی که در گنجینه هست")
from services.captions import known_madahs, resolve_madah

known = known_madahs()
if len(known) < 5:
    print("  ⚠ گنجینه خُرد است؛ این بخش معنا ندارد و رد می‌شود.")
else:
    for probe, want in [
        ("Hosein Sotude", "کربلایی حسین ستوده"),
        ("Borna", "کربلایی رسول برنا"),
        ("Morteza Yebranezhad", "کربلایی مرتضی یبرنژاد"),
        ("Payam Kiani", "کربلایی پیام کیانی"),
    ]:
        got = resolve_madah(probe)
        check(f"«{probe}»", got == want, f" → {got}")

print()
print("▸ نامِ لاتین، مرجعِ دیگران نمی‌شود")
check("هیچ نامِ لاتینی در فهرستِ مرجع نیست",
      not [n for n in known.values() if P.is_latin(n)],
      f" → {[n for n in known.values() if P.is_latin(n)]}")

print()
print("▸ نامِ تازه — تنها انتظار: خروجی فارسی باشد")
for probe in ("Mahdi Rasoli", "Baz Dobare Tako Tanha ~ UpMusic", "Ali Fani"):
    got = resolve_madah(probe)
    check(f"«{probe[:28]}» فارسی شد",
          bool(got) and not P.is_latin(got), f" → {got}")

print()
print("▸ نامی که از پیش فارسی است، دست نمی‌خورد")
for name in ("سید جواد ذاکر", "رسول برنا"):
    check(f"«{name}»", P.to_persian(name) == name or P.clean_name(name) == name)

print()
print("▸ مسیرِ راستین — آنچه گنجینه واقعاً می‌گیرد")
#
# ## چرا این بخش هست
#
# `clean_name` از روز نخست درست کار می‌کرد، ولی هیچ‌جا صدا
# نمی‌شد: `captions.read` برچسبِ خامِ فایل را یکراست به گنجینه
# می‌سپرد. سنجه‌های بالا سبز بودند و ایراد سرِ جایش. پس از این
# پس، مسیر سنجیده می‌شود نه تنها ماژول.
from services.captions import clean_title, read as caption_read


class _Audio:
    def __init__(self, performer, title):
        self.performer, self.title, self.file_name = performer, title, None


for perf, tit, want_m, want_t in (
    ("کربلایی مرتضی یبرنژاد", "شور | ماهم حضرت رضا",
     "کربلایی مرتضی یبرنژاد", "ماهم حضرت رضا"),
    ("Borna", "دلبر ابالفضل / احسان لطفی", "کربلایی رسول برنا", "دلبر ابالفضل"),
):
    got_m, got_t = caption_read(_Audio(perf, tit), None)
    check(f"مداحِ «{perf[:20]}»", got_m == want_m, f" → {got_m}")
    check(f"اسمِ «{tit[:20]}»", got_t == want_t, f" → {got_t}")

check("نامِ لاتین در مسیر فارسی می‌شود",
      not P.is_latin(caption_read(_Audio("Mahdi Rasoli", "X"), None)[0]))

print()
print("▸ اسمِ نوا: لقب نمی‌افتد، جداکننده می‌شکند")
# «حاج» در اسمِ نوا می‌تواند خودِ واژه باشد، نه لقبِ کسی.
check("لقب در اسمِ نوا می‌ماند", clean_title("حاج آقا") == "حاج آقا",
      f" → {clean_title('حاج آقا')}")
check("اسمِ تهی نمی‌شکند", clean_title(None) is None)

print()
print("═" * 62)
if fail:
    print(f"  ✗ {fail} سنجه ناکام ماند ({ok} گذشت)")
    sys.exit(1)
print(f"  ✓ هر {ok} سنجه گذشت")
print("═" * 62)
