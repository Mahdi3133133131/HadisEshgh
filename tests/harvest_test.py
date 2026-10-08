# -*- coding: utf-8 -*-
"""
سنجهٔ رشدِ خودکارِ گنجینه.

بی شبکه کار می‌کند: هر بخشِ بیرونی جایگزین می‌شود، تا این سنجه
هم تند باشد و هم به بالا بودنِ تارنمایی وابسته نباشد.
"""
import asyncio
import io
import pathlib
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from core.db import database
from services import crawler, harvest

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
print("  رشدِ خودکارِ گنجینه")
print("═" * 62)
print()

database.init_db()
crawler._ensure_table()

PAGE = "https://example.test/nowheh-1"
made_tracks: list[int] = []


class FakeBot:
    def __init__(self):
        self.sent = []

    async def send_audio(self, chat_id, audio, **kw):
        self.sent.append({"chat": chat_id, "caption": kw.get("caption")})

        class A:
            file_id = "HARVEST_FILE"
            file_unique_id = "HARVEST_UNIQ"

        class M:
            message_id = 4242
            audio = A()

        return M()


async def main():
    # ── شکستنِ تیتر ─────────────────────────────────────────
    print("▸ خواندنِ عنوان و مداح از تیتر")
    cases = [
        ("دانلود مداحی ای وارث دلتنگی آدم از حاج میثم مطیعی",
         "ای وارث دلتنگی آدم", "حاج میثم مطیعی"),
        ("مداحی نحن أبناء از حاج محمود", "نحن أبناء", "حاج محمود"),
        ("عنوانی بی مداح", "عنوانی بی مداح", None),
    ]
    for raw, want_title, want_madah in cases:
        title, madah = harvest.split_title(raw)
        check(
            f"«{raw[:34]}…»",
            title == want_title and madah == want_madah,
            f" → {title} / {madah}",
        )

    # ── نشانیِ درصدنویسی‌شده ────────────────────────────────
    print()
    print("▸ آماده‌سازیِ نشانیِ فایل")
    dirty = "https://dl.example.test/05/04/Ay Vars Deltangi.mp3"
    clean = harvest._clean_url(dirty)
    check("فاصله درصدنویسی شد", "%20" in clean and " " not in clean, f" → …{clean[-28:]}")

    # ── صف ──────────────────────────────────────────────────
    print()
    print("▸ صفِ داوری")
    database.execute("DELETE FROM harvest_queue WHERE page_url = ?", (PAGE,))
    database.execute("DELETE FROM crawled_urls WHERE url = ?", (PAGE,))

    qid = harvest._enqueue(
        site="example", page_url=PAGE, file_url="https://dl.example.test/a.mp3",
        title="نوای آزمون", madah="مداح آزمون", duration=200,
    )
    check("پرونده در صف نشست", qid is not None)
    check("در فهرستِ در انتظار می‌آید", any(r["id"] == qid for r in harvest.pending()))

    # همان نشانی دوباره — نباید ردیف تازه بسازد
    again = harvest._enqueue(
        site="example", page_url=PAGE, file_url="x", title="y", madah="z", duration=1
    )
    check("نشانیِ تکراری ردیف تازه نمی‌سازد", again == qid)

    # ── پذیرش ───────────────────────────────────────────────
    print()
    print("▸ پذیرش")
    database.execute(
        "UPDATE harvest_queue SET file_id = ?, file_unique_id = ? WHERE id = ?",
        ("HARVEST_FILE", "HARVEST_UNIQ", qid),
    )
    record = harvest.get(qid)
    track_id = database.add_track(
        file_id=record["file_id"], file_unique_id=record["file_unique_id"],
        source="site", title=record["title"], madah=record["madah"],
        duration=record["duration"], source_url=record["page_url"],
    )
    made_tracks.append(track_id)
    harvest.mark(qid, "approved", track_id=track_id)

    row = harvest.get(qid)
    check("وضعیت approved شد", row["status"] == "approved")
    check("شمارهٔ نوا نشست", int(row["track_id"]) == track_id)
    track = database.get_track(track_id)
    check("نوا در گنجینه است", track is not None and track["madah"] == "مداح آزمون")
    check("سرچشمه‌اش نشان دارد", track["source_url"] == PAGE)
    check("از فهرستِ در انتظار بیرون رفت",
          not any(r["id"] == qid for r in harvest.pending()))

    # ── رد ──────────────────────────────────────────────────
    print()
    print("▸ رد کردن")
    other = "https://example.test/nowheh-2"
    database.execute("DELETE FROM harvest_queue WHERE page_url = ?", (other,))
    database.execute("DELETE FROM crawled_urls WHERE url = ?", (other,))
    qid2 = harvest._enqueue(
        site="example", page_url=other, file_url="u", title="t", madah="m", duration=9
    )
    before = database.query_one("SELECT COUNT(*) AS c FROM tracks")["c"]
    harvest.mark(qid2, "rejected")
    crawler._remember(other, "example", "rejected", note="آزمون")

    check("وضعیت rejected شد", harvest.get(qid2)["status"] == "rejected")
    check("نشانی نشان خورد تا دوباره نیاید", crawler._seen(other))
    after = database.query_one("SELECT COUNT(*) AS c FROM tracks")["c"]
    check("گنجینه دست‌نخورده ماند", before == after)

    # ── پاک‌سازی ────────────────────────────────────────────
    for tid in made_tracks:
        database.execute("DELETE FROM tracks WHERE id = ?", (tid,))
    database.execute("DELETE FROM harvest_queue WHERE page_url IN (?, ?)", (PAGE, other))
    database.execute("DELETE FROM crawled_urls WHERE url IN (?, ?)", (PAGE, other))

    print()
    print("═" * 62)
    if fail:
        print(f"  ✗ {fail} سنجه ناکام ماند ({ok} گذشت)")
        return 1
    print(f"  ✓ هر {ok} سنجه گذشت")
    print("═" * 62)
    return 0


sys.exit(asyncio.run(main()))
