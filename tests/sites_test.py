# -*- coding: utf-8 -*-
"""
آزمون پلهٔ دوم — جست‌وجو در تارنماها.

هیچ‌جا به شبکه دست نمی‌زند: به جای گرفتن راستینِ برگه‌ها، پاسخ‌های
از پیش نوشته‌شده جای `_get_text` می‌نشینند. پس این آزمون هم بی
اینترنت اجرا می‌شود و هم بارِ بیهوده‌ای بر آن تارنماها نمی‌گذارد —
که اگر می‌گذاشت، خودش همان بی‌ادبی‌ای بود که ماژول از آن پرهیز
می‌کند.
"""

import asyncio
import io
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# پایانهٔ ویندوز با cp1252 هیچ نشانهٔ غیرلاتینی را نمی‌پذیرد و
# آزمون روی نخستین چاپ از پا می‌افتاد.
sys.stdout = io.TextIOWrapper(
    sys.stdout.buffer, encoding="utf-8", errors="replace", line_buffering=True
)

_tmp_db = Path(tempfile.gettempdir()) / f"hadis_sites_{os.getpid()}.db"
os.environ["DATABASE_PATH"] = str(_tmp_db)

from config import config  # noqa: E402

if config.database_path != _tmp_db:
    raise SystemExit("✗ آزمون به پایگاه دادهٔ راستین اشاره می‌کند؛ اجرا نشد.")

from core.db import database as db, site_index  # noqa: E402
from services import sites  # noqa: E402

db.init_db()
site_index.ensure_table()

OK = 0


def step(label):
    print(f"\n▸ {label}")


def check(condition, detail=""):
    global OK
    assert condition, detail or "ناکام"
    OK += 1
    print(f"   ✓ {detail}" if detail else "   ✓")


# ── برگه‌های ساختگی ─────────────────────────────────────────
SEARCH_HTML = """
<html><body>
  <a href="/person/karimi">صفحهٔ مداح</a>
  <a href="https://kashoob.com/audio/AB12/%D9%86%D9%88%D8%A7%DB%8C-%D8%A2%D8%B2%D9%85%D8%A7%DB%8C%D8%B4%DB%8C/">یک</a>
  <a href="https://kashoob.com/audio/CD34/%D9%86%D9%88%D8%A7%DB%8C-%D8%AF%D9%88%D9%85/">دو</a>
  <a href="https://kashoob.com/video/ZZ99/">نماهنگ</a>
</body></html>
"""

PAGE_HTML = """
<html><head>
  <title>نوای آزمایشی — حاج آزماینده | کشوب</title>
  <meta property="og:title" content="نوای آزمایشی — حاج آزماینده | کشوب">
</head><body>
  <audio src="https://cdn.kashoob.com/files/2026/test-track.mp3"></audio>
</body></html>
"""

SITEMAP_INDEX = """<?xml version="1.0"?>
<sitemapindex><sitemap><loc>https://kashoob.com/sitemap-1.xml</loc></sitemap></sitemapindex>
"""

SITEMAP_PAGE = """<?xml version="1.0"?>
<urlset>
  <url><loc>https://kashoob.com/audio/EF56/%D9%86%D9%88%D8%A7%DB%8C-%D8%B3%D9%88%D9%85/</loc></url>
  <url><loc>https://kashoob.com/about/</loc></url>
</urlset>
"""


async def fake_get_text(session, url):
    if "search?q=" in url:
        return SEARCH_HTML
    if url.endswith("sitemap.xml.gz"):
        return SITEMAP_INDEX
    if url.endswith("sitemap-1.xml"):
        return SITEMAP_PAGE
    if "/audio/" in url:
        return PAGE_HTML
    return None


class FakeSession:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


async def main():
    sites._get_text = fake_get_text
    sites._session = lambda: FakeSession()

    step("شناختن صفحهٔ نوا از دیگر نشانی‌ها")
    kashoob = sites.by_name("kashoob")
    check(kashoob.is_track_page("https://kashoob.com/audio/AB12/x/"), "صفحهٔ صوت شناخته شد")
    check(not kashoob.is_track_page("https://kashoob.com/video/ZZ99/"), "نماهنگ کنار گذاشته شد")
    check(not kashoob.is_track_page("https://kashoob.com/person/karimi"), "صفحهٔ مداح کنار گذاشته شد")

    step("جست‌وجوی زنده")
    hits = await sites.live_search("آزمایش", limit=5)
    urls = {hit.page_url for hit in hits}
    check(len(urls) == 2, f"{len(urls)} صفحهٔ نوا از برگهٔ نتیجه بیرون کشیده شد")
    check(
        all("/audio/" in url for url in urls),
        "تنها صفحه‌های صوت — نه نماهنگ و نه صفحهٔ مداح",
    )
    check(
        any("نوای" in hit.title for hit in hits),
        f"نام از خود نشانی خوانده شد: «{hits[0].title}»",
    )

    step("رسیدن از صفحه به فایل")
    hit = await sites.resolve(hits[0])
    check(
        hit.file_url == "https://cdn.kashoob.com/files/2026/test-track.mp3",
        "نشانی فایل یافت شد — حتی روی میزبانِ دیگر",
    )
    check("کشوب" not in hit.title, f"نام تارنما از سرنویس بریده شد: «{hit.title}»")

    step("نشستن در نمایه")
    row = site_index.get(hit.page_url)
    check(row is not None and row["file_url"] == hit.file_url, "نشانی فایل در نمایه ماند")

    step("جست‌وجوی نمایه — بی هیچ شبکه‌ای")
    found = sites.indexed_search("آزمایشی", limit=5)
    check(found, f"{len(found)} یافته از نمایهٔ محلی")
    check(found[0].file_url is not None, "یافتهٔ نمایه، نشانی فایل را هم با خود دارد")

    step("صفحهٔ بی‌نام در جست‌وجو نمی‌آید")
    site_index.remember("kashoob", "https://kashoob.com/audio/NONAME/", "")
    empty = site_index.get("https://kashoob.com/audio/NONAME/")
    check(empty is not None and empty["title_norm"] == "", "بی‌نام نشست")
    check(
        all("NONAME" not in hit.page_url for hit in sites.indexed_search("آزمایشی", 9)),
        "ولی در نتیجه‌ها نیامد — نامِ تهی با هر چیزی می‌خواند",
    )

    step("سیت‌مپ")
    before = site_index.total()
    added = await sites.refresh_index("kashoob")
    check(added.get("kashoob") == 1, "تنها صفحهٔ نوا از سیت‌مپ برداشته شد، نه /about/")
    check(site_index.total() == before + 1, "نمایه یک ردیف بزرگ‌تر شد")

    step("نام تهی، نامِ به‌دست‌آمده را پاک نمی‌کند")
    site_index.remember("kashoob", hit.page_url, "")
    again = site_index.get(hit.page_url)
    check(again["title"] == hit.title, "نام پیشین سر جایش ماند")

    step("robots.txt در کارِ زنده بدبینانه داوری می‌شود")
    sites._robots.clear()
    sites._robots["nowhere.example"] = None
    allowed = await sites._allowed(FakeSession(), "https://nowhere.example/x.mp3")
    check(not allowed, "خوانده‌نشدن robots.txt یعنی ناروا، نه روا")

    step("برچسب سرچشمه بر خودِ فایل")
    from services import tagger
    import inspect

    params = inspect.signature(tagger.tag_with_cover).parameters
    check("source_label" in params and "source_url" in params, "tagger سرچشمه می‌گیرد")
    src = inspect.getsource(tagger.tag_audio)
    check("WOAS" in src and "WOAF" in src, "فریم‌های استاندارد نشانی سرچشمه نوشته می‌شوند")

    print(f"\n{'═' * 58}\n  ✓ هر {OK} سنجه گذشت\n{'═' * 58}")


asyncio.run(main())
db.close_connection()
_tmp_db.unlink(missing_ok=True)
for suffix in ("-wal", "-shm"):
    Path(str(_tmp_db) + suffix).unlink(missing_ok=True)
