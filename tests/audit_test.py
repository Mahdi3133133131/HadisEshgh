# -*- coding: utf-8 -*-
"""
سنجهٔ بازرسیِ کامل.

کاربر خواست ربات بی‌ایراد شود. یک بازرسیِ سامان‌مند شد و آنچه
پیدا شد اینجا قفل می‌شود تا برنگردد.

الگوی غالبِ ایرادهای این پروژه یکی بوده: **کد نوشته شده و
صدا نمی‌شود.** پس بخشِ نخست همان را می‌پاید.
"""

import inspect
import io

import pathlib
import re
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core.db import database

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
print("  بازرسیِ کامل")
print("=" * 62)

database.init_db()

# =============================================================
print()
print("▸ ۱. قفلِ پرکردن، آزاد می‌شود")
# =============================================================
#
# `searches.release_fill` نوشته شده بود و هیچ‌جا صدا نمی‌شد؛
# قفل تنها با سر آمدنِ مهلت باز می‌شد.
from bot.handlers import intake
from core.db import searches

src = inspect.getsource(intake)
check("پس از پر شدن، آزاد می‌شود", src.count("release_fill") >= 1)
check("و با `/cancel` هم", "release_fill" in inspect.getsource(intake.cancel))

# و راستی کار می‌کند
SID_USER = 999_000_111
# `searches` کلیدِ بیگانه به `users` دارد؛ بی کاربر ساخته نمی‌شود.
database.upsert_user(SID_USER, first_name="سنجهٔ بازرسی")
sid = searches.create(user_id=SID_USER, input_kind="audio")
try:
    got, _ = searches.try_acquire_fill(sid, 1, 600)
    check("قفل گرفته می‌شود", got)
    check("دارنده‌اش شناخته می‌شود",
          searches.current_fill_holder(sid) == 1)
    check("و آزاد می‌شود", searches.release_fill(sid))
    check("پس از آزادی، دارنده‌ای نیست",
          searches.current_fill_holder(sid) is None)
finally:
    database.execute("DELETE FROM searches WHERE id = ?", (sid,))
    database.execute("DELETE FROM users WHERE user_id = ?", (SID_USER,))

# =============================================================
print()
print("▸ ۲. جست‌وجوی متنِ نوا — هنجارشده")
# =============================================================
#
# ایرادِ راستین: عبارتِ کاربر هنجار می‌شد («آ» به «ا») ولی متن
# خام ذخیره می‌شد، پس هیچ واژه‌ای که «آ» داشت پیدا نمی‌شد.
cols = {
    row["name"] for row in database.query_all("PRAGMA table_info(tracks)")
}
check("ستونِ `transcript_norm` هست", "transcript_norm" in cols)

by_lyr = inspect.getsource(database.search_tracks_by_lyrics)
check("جست‌وجو روی ستونِ هنجارشده است", "transcript_norm" in by_lyr)
check("و واژه‌به‌واژه، نه عبارتِ یکپارچه",
      'join(["transcript_norm LIKE ?"]' in by_lyr)

tid = database.add_track(
    file_id="AUDIT_T", file_unique_id="AUDIT_U", source="test",
    title="نوای آزمایشی", madah="کربلایی آزماینده", style=None, duration=90,
)
try:
    database.set_transcript(tid, "واژهٔ یکتا زیبق و پژواک آزمایشی برای سنجه")
    row = database.get_track(tid)
    check("هر دو ستون با هم نوشته می‌شوند",
          bool(row["transcript"]) and bool(row["transcript_norm"]))

    for q, want, lbl in [
        ("زیبق", True, "یک واژه"),
        ("پژواک زیبق", True, "ترتیبِ جابه‌جا"),
        ("زیبق آزمایشی پژواک", True, "سه واژه با «آ»"),
        ("آزمایشی", True, "واژهٔ «آ»دار"),
        ("قققق‌ناموجود", False, "واژهٔ نبوده"),
    ]:
        hits = database.search_tracks_by_lyrics(q)
        found = any(int(r["id"]) == tid for r in hits)
        check(f"{lbl}", found == want, f" — «{q}»")
finally:
    database.execute("DELETE FROM tracks WHERE id = ?", (tid,))
check("سنجه ردِ پا نگذاشت", database.get_track(tid) is None)

# =============================================================
print()
print("▸ ۳. بازگشتِ متنی در جست‌وجوی کاربر")
# =============================================================
from bot.handlers import inline_query

rw = inspect.getsource(inline_query.reply_with_matches)
check("وقتی نام و عنوان چیزی ندادند، متن سنجیده می‌شود",
      "search_tracks_by_lyrics" in rw)
check("تنها برای عبارتِ چندواژه‌ای", "len(term.split()) >= 2" in rw)

# =============================================================
print()
print("▸ ۴. هر دکمه گرداننده‌ای دارد")
# =============================================================
inline_src = (ROOT / "bot/keyboards/inline.py").read_text(encoding="utf-8")
router_src = (ROOT / "bot/handlers/router.py").read_text(encoding="utf-8")
consts = dict(re.findall(r'^([A-Z][A-Z0-9_]*)\s*=\s*"([^"]+)"',
                         inline_src, re.M))
orphan = [
    n for n, v in consts.items()
    if not re.search(r"\b" + re.escape(n) + r"\b", router_src)
    and v not in router_src
]
check(f"هر {len(consts)} ثابتِ بازخوردی گرداننده دارد",
      not orphan, f" — بی‌گرداننده: {orphan}")

# =============================================================
print()
print("▸ ۵. هر حالت مسیر دارد")
# =============================================================
from bot import states

names = re.findall(r"^(AWAITING_[A-Z_]+)\s*=",
                   (ROOT / "bot/states.py").read_text(encoding="utf-8"), re.M)
loose = [
    n for n in names
    if n not in router_src and getattr(states, n) not in states.INTAKE_STATES
]
check(f"هر {len(names)} حالت مسیریابی می‌شود",
      not loose, f" — بی‌مسیر: {loose}")

# =============================================================
print()
print("▸ ۶. گنجینه پاکیزه است")
# =============================================================
rows = database.query_all(
    "SELECT DISTINCT madah FROM tracks"
    " WHERE is_active = 1 AND madah IS NOT NULL"
)
names_db = [r["madah"] for r in rows]
check("هیچ نامِ لاتینی نمانده",
      not [n for n in names_db if any("a" <= c.lower() <= "z" for c in n)])
check("هیچ نامِ یک‌دو حرفی نمانده",
      not [n for n in names_db if len(n.strip()) < 3])
check("هیچ زبالهٔ نشانی‌دار نمانده",
      not [n for n in names_db if "~" in n or "http" in n.lower()])

print()
print("=" * 62)
if fail:
    print(f"  ✗ {fail} سنجه ناکام ماند ({ok} گذشت)")
    sys.exit(1)
print(f"  ✓ هر {ok} سنجه گذشت")
print("=" * 62)
