# -*- coding: utf-8 -*-
"""
سنجهٔ «چرا اصلا نمی‌گرده».

کاربر گفت جست‌وجوی سایت‌ها «اصلا نمی‌گرده». سه ریشه داشت و هر سه
اینجا بسته می‌شوند:

  ۱. برای کلیپِ بی‌نام، سایت‌ها **اصلاً صدا نمی‌شدند**
  ۲. دو سومِ نمایه بی‌نام بود و بی‌نام یعنی نامرئی
  ۳. `bootstrap` شمارِ ردیف را می‌سنجید نه شمارِ نام‌دار، پس
     هرگز تعمیر نمی‌کرد

به‌علاوهٔ سه ایرادِ ساختاری که همان‌جا پیدا شدند.
"""
import inspect
import io
import pathlib
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from core.db import database, site_index
from services import sites

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
print("  جست‌وجوی سایت‌ها")
print("=" * 62)

database.init_db()
site_index.ensure_table()


class _Audio:
    def __init__(self, performer=None, title=None, file_name=None):
        self.performer, self.title, self.file_name = performer, title, file_name


# =============================================================
print()
print("▸ ۱. عبارت از برچسبِ خودِ فایل ساخته می‌شود")
# =============================================================
from bot.handlers import search

check("برچسبِ لاتین عبارت می‌دهد",
      bool(search._term_from_tags(_Audio("Mahdi Rasoli", "Baz Dobare"), None)))
check("برچسبِ فارسی هم",
      search._term_from_tags(
          _Audio("کربلایی مرتضی یبرنژاد", "شور | ماهم حضرت رضا"), None
      ) == "کربلایی مرتضی یبرنژاد ماهم حضرت رضا")
check("کپشن، وقتی برچسب نیست",
      search._term_from_tags(_Audio(), "مداحی از حاج محمود کریمی")
      == "کربلایی محمود کریمی")
check("بی هیچ، None", search._term_from_tags(_Audio(), None) is None)
check("بی رسانه، None", search._term_from_tags(None, None) is None)

# و راستی صدا شود
src = inspect.getsource(search._after_failure)
check("`_after_failure` برچسب را می‌آزماید", "tag_term" in src)
check("و پیش از تسلیم", src.index("tag_term") < src.index("search_ask_hint_after_fail"))

# =============================================================
print()
print("▸ ۲. نشانهٔ «مداح» درونِ «مداحی» نگیرد")
# =============================================================
from services import captions

for cap, want in [
    ("مداحی از حاج محمود کریمی", "حاج محمود کریمی"),
    ("مداح: محمود کریمی", "محمود کریمی"),
    ("مداحی جدید از سید جواد ذاکر", "سید جواد ذاکر"),
    ("با صدای حسین طاهری", "حسین طاهری"),
]:
    got = captions.find_madah(cap)
    check(f"«{cap[:26]}»", got == want, f" → {got}")

# =============================================================
print()
print("▸ ۳. نمایه — دیدنی، و نوبتی")
# =============================================================
check("`titled()` هست", hasattr(site_index, "titled"))
check("و از `total()` بیشتر نیست", site_index.titled() <= site_index.total(),
      f" — {site_index.titled()}/{site_index.total()}")

boot = inspect.getsource(sites.bootstrap)
check("`bootstrap` نام‌دار را می‌سنجد، نه ردیف", "site_index.titled()" in boot)

untitled = inspect.getsource(site_index.untitled)
check("پرکردنِ نام نوبتی است", "PARTITION BY site" in untitled)

search_src = inspect.getsource(site_index.search)
check("جست‌وجو واژه‌به‌واژه است", "AND" in search_src and "title_norm LIKE ?" in search_src)

# ترتیبِ واژه‌ها نباید مهم باشد
a = len(site_index.search("محمود کریمی"))
b = len(site_index.search("کریمی محمود"))
check("ترتیبِ واژه مهم نیست", a == b, f" — {a} و {b}")

# =============================================================
print()
print("▸ ۴. سه ایرادِ ساختاری")
# =============================================================
check("مهلتِ درخواست زیرِ بودجه است",
      sites.REQUEST_TIMEOUT < sites.LIVE_BUDGET,
      f" — {sites.REQUEST_TIMEOUT} < {sites.LIVE_BUDGET}")
check("`robots` مهلت دارد", hasattr(sites, "_robots_fresh"))

# دنبالهٔ سرنویس: نامِ تارنما برود، نامِ آدم بماند
for text, should_change in [
    ("شور زیبا | کاشوب", True),
    ("شب اول محرم | kashoob.com", True),
    ("روضه — پلن سه", True),
    ("دلبر ابالفضل — حاج محمود کریمی", False),
    ("ماهم حضرت رضا | مرتضی یبرنژاد", False),
]:
    changed = sites._strip_site_tail(text) != text
    check(f"«{text[:30]}»", changed == should_change,
          " — برید" if changed else " — ماند")

# =============================================================
print()
print("▸ ۵. تشخیص برای `/sites`")
# =============================================================
rows = sites.diagnose()
check("برای هر تارنما یک ردیف", len(rows) == len(sites.SITES))
check("ردیف‌ها میدان‌های لازم را دارند",
      all({"label", "named", "total", "robots", "troubles"} <= set(r) for r in rows))
blind = [r for r in rows if r["total"] and not r["named"]]
check("تارنمای یکسره بی‌نام هشدار می‌گیرد",
      all(r["troubles"] for r in blind),
      f" — {len(blind)} تارنما")

print()
print("=" * 62)
if fail:
    print(f"  ✗ {fail} سنجه ناکام ماند ({ok} گذشت)")
    sys.exit(1)
print(f"  ✓ هر {ok} سنجه گذشت")
print("=" * 62)
