# -*- coding: utf-8 -*-
"""
سنجهٔ گشت‌وگذار در مداحان.

بی شبکه و بی تلگرام: هر بخشِ بیرونی جایگزین می‌شود.
"""
import asyncio
import io
import pathlib
import sys
import types

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from bot.keyboards import inline
from core.db import database
from services import harvest  # noqa: F401  — تا جدول‌ها ساخته شوند

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
print("  گشت‌وگذار در مداحان")
print("═" * 62)
print()

database.init_db()

MADAH_A = "آزمون مداح الف"
MADAH_B = "آزمون مداح ب"
made: list[int] = []


def add(title, madah, active=1):
    tid = database.add_track(
        title=title, madah=madah, style="شور",
        file_id=f"F{title}", file_unique_id=f"U{title}",
        duration=120, source="test",
    )
    made.append(tid)
    if not active:
        database.execute("UPDATE tracks SET is_active = 0 WHERE id = ?", (tid,))
    return tid


async def main():
    # ── زمینه ───────────────────────────────────────────────
    # دو نگارش از یک نام، تا گروه‌بندی بر madah_norm سنجیده شود
    add("الف-۱", MADAH_A)
    add("الف-۲", "  " + MADAH_A + " ")
    add("الف-۳", MADAH_A)
    gone = add("الف-حذف‌شده", MADAH_A, active=0)
    add("ب-۱", MADAH_B)

    print("▸ شمارشِ مداحان")
    rows = database.madahs_with_counts(0, 100)
    by_name = {r["madah"].strip(): int(r["tracks"]) for r in rows if r["madah"]}
    check(
        "دو نگارشِ یک نام، یک ردیف شد",
        sum(1 for r in rows if MADAH_A in (r["madah"] or "")) == 1,
    )
    check("شمارِ نواها درست است (بی نوای حذف‌شده)",
          by_name.get(MADAH_A) == 3, f" → {by_name.get(MADAH_A)}")
    check("مداحِ دوم جدا شمرده شد", by_name.get(MADAH_B) == 1)

    # ── فهرستِ نواهای یک مداح ───────────────────────────────
    print()
    print("▸ نواهای یک مداح")
    norm = next(r["madah_norm"] for r in rows if MADAH_A in (r["madah"] or ""))
    tracks = database.tracks_of_madah(norm, 0, 100)
    titles = {t["title"] for t in tracks}
    check("همهٔ نواهای فعالش آمد", len(tracks) == 3, f" → {len(tracks)}")
    check("نوای حذف‌شده نیامد", "الف-حذف‌شده" not in titles)
    check("شمارشِ جدا هم می‌خواند",
          database.count_tracks_of_madah(norm) == 3)

    # ── صفحه‌بندی ───────────────────────────────────────────
    print()
    print("▸ صفحه‌بندی")
    first = database.tracks_of_madah(norm, 0, 2)
    second = database.tracks_of_madah(norm, 2, 2)
    ids1 = {int(t["id"]) for t in first}
    ids2 = {int(t["id"]) for t in second}
    check("برگهٔ نخست دو ردیف دارد", len(first) == 2)
    check("برگهٔ دوم بقیه را می‌دهد", len(second) == 1)
    check("برگه‌ها روی هم نمی‌افتند", not (ids1 & ids2))

    # ── صفحه‌کلیدها ─────────────────────────────────────────
    print()
    print("▸ صفحه‌کلید")
    # ── قراردادِ تازه ───────────────────────────────────────
    #
    # جفت‌ها اکنون (شمارهٔ نمایشی، شناسه) اند، نه (شناسه، برچسب):
    # نام‌ها در متنِ پیام‌اند و روی دکمه تنها شماره می‌نشیند، چون
    # چهار نامِ فارسی در یک ردیف جا نمی‌شود.
    kb = inline.madah_list([(1, 101), (2, 102)], page=0, pages=3)
    data = [b.callback_data for row in kb.inline_keyboard for b in row]
    labels = [b.text for row in kb.inline_keyboard for b in row]
    check("دکمهٔ گزینشِ مداح ساخته شد", f"{inline.MADAH_PICK}:101" in data)
    check("برچسب، شمارهٔ پارسی است", "۱" in labels and "۲" in labels)
    check("دکمهٔ برگهٔ پسین هست", f"{inline.MADAH_PAGE}:1" in data)
    check("در برگهٔ نخست، «پیشین» نیست",
          f"{inline.MADAH_PAGE}:-1" not in data)

    # ── شبکهٔ چهارستونی ────────────────────────────────────
    full = inline.madah_list([(n, 100 + n) for n in range(1, 33)], page=0, pages=2)
    grid = full.inline_keyboard[:-1]          # ردیفِ آخر، ورق‌زن است
    check("هشت ردیف ساخته شد", len(grid) == inline.ROWS, f" → {len(grid)}")
    check("هر ردیف چهار ستون دارد",
          all(len(r) == inline.COLUMNS for r in grid),
          f" → {[len(r) for r in grid]}")
    check("سی‌ودو دکمه در یک برگه",
          sum(len(r) for r in grid) == inline.PER_PAGE)

    # ردیفِ ناقصِ پایانی نباید بشکند
    partial = inline.madah_list([(n, 100 + n) for n in range(1, 7)], page=0, pages=1)
    check("ردیفِ ناقص هم درست می‌شود",
          [len(r) for r in partial.inline_keyboard] == [4, 2],
          f" → {[len(r) for r in partial.inline_keyboard]}")

    kb2 = inline.madah_tracks([(1, 7)], anchor_id=3, page=1, pages=2)
    data2 = [b.callback_data for row in kb2.inline_keyboard for b in row]
    check("دکمهٔ گزینشِ نوا ساخته شد", f"{inline.MADAH_TRACK}:7" in data2)
    check("برگهٔ پیشین، شناسهٔ لنگر را نگه می‌دارد",
          f"{inline.MADAH_TRACK_PAGE}:0:3" in data2)
    check("دکمهٔ بازگشت هست", any(d.startswith(inline.MADAH_BACK) for d in data2))

    # سقفِ ۶۴ بایتیِ تلگرام
    longest = max(len(d.encode("utf-8")) for d in data + data2)
    check("فراخوان‌ها زیر سقفِ ۶۴ بایت‌اند", longest <= 64, f" → {longest} بایت")

    # ── چینشِ الفبای فارسی ─────────────────────────────────
    print()
    print("▸ چینشِ الفبا")
    from core.normalize import persian_key
    probe = ["پیام", "بهار", "تقی", "گلزار", "کاظم", "ژاله", "چاوش", "یاسر", "حسین"]
    want = ["بهار", "پیام", "تقی", "چاوش", "حسین", "ژاله", "کاظم", "گلزار", "یاسر"]
    check("پ پس از ب و پیش از ت می‌نشیند",
          sorted(probe, key=persian_key) == want)
    check("اجرای مشترک ته فهرست می‌رود",
          sorted(["ی نفر", "الف ، ب"], key=persian_key) == ["ی نفر", "الف ، ب"])
    check("نامِ تهی از همه پس‌تر است",
          persian_key("") > persian_key("الف ، ب"))

    # ── تک‌برگه: دکمهٔ ورق نباید بیاید ──────────────────────
    kb3 = inline.madah_list([(1, "یک")], page=0, pages=1)
    rows3 = [b.callback_data for row in kb3.inline_keyboard for b in row]
    check("با یک برگه، دکمهٔ ورق ساخته نمی‌شود",
          not any("noop" in d or inline.MADAH_PAGE in d for d in rows3))

    # ── پاک‌سازی ────────────────────────────────────────────
    for tid in made:
        database.execute("DELETE FROM tracks WHERE id = ?", (tid,))

    print()
    print("═" * 62)
    if fail:
        print(f"  ✗ {fail} سنجه ناکام ماند ({ok} گذشت)")
        return 1
    print(f"  ✓ هر {ok} سنجه گذشت")
    print("═" * 62)
    return 0


sys.exit(asyncio.run(main()))
