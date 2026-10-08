# -*- coding: utf-8 -*-
"""
سنجهٔ هشت ایرادِ گزارش‌شده.

کاربر فهرستی داد و گفت «یکم دقت کن». هر بخش زیر یکی از آن‌هاست،
و هر کدام پیش از این سنجه راستی خراب بود.
"""
import inspect
import io
import pathlib
import sys
import time

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from core.db import database
from services import persianize as P
from services.captions import clean_title, resolve_madah

ok = fail = 0
ZWNJ = "‌"


def check(label, cond, detail=""):
    global ok, fail
    if cond:
        ok += 1
        print(f"  ✓ {label}{detail}")
    else:
        fail += 1
        print(f"  ✗ {label}{detail}")


print("=" * 62)
print("  هشت ایرادِ گزارش‌شده")
print("=" * 62)

database.init_db()

# =============================================================
print()
print("▸ ۱. «کربلایی» — بر نامی که لقب ندارد")
# =============================================================
#
# تصمیمِ خودِ کاربر: نامِ دارای لقبِ دیگر دست نخورد.
for name, want in [
    ("حسین ستوده", "کربلایی حسین ستوده"),
    ("رسول برنا", "کربلایی رسول برنا"),
    ("کویتی پور", "کربلایی کویتی پور"),
    # لقبِ کوتاه‌شده، یکسان می‌شود
    ("کربلای وحید شکری", "کربلایی وحید شکری"),
    # نیم‌فاصله — همان که دو مداحِ جدا ساخته بود
    ("کربلایی" + ZWNJ + "وحید شکری", "کربلایی وحید شکری"),
    # از پیش «کربلایی» دارد
    ("کربلایی محمدرضا جدیدوند", "کربلایی محمدرضا جدیدوند"),
    # لقبِ خودش را دارد — دست نخورد
    ("سید جواد ذاکر", "سید جواد ذاکر"),
    ("حاج مهدی سلحشور", "حاج مهدی سلحشور"),
    ("استاد کویتی پور", "استاد کویتی پور"),
    # زباله و لاتین، لقب نمی‌گیرند
    (".", "."),
    ("Baz Dobare Tako Tanha", "Baz Dobare Tako Tanha"),
]:
    got = P.with_karbalaei(name)
    check(f"«{name[:26]}»", got == want, f" → {got}")

check("تهی نمی‌شکند", P.with_karbalaei("") == "" and P.with_karbalaei(None) is None)

# و از راهِ زنجیرهٔ کامل هم
check("زنجیره هم لقب می‌نشاند",
      resolve_madah("حسین ستوده") == "کربلایی حسین ستوده",
      f" → {resolve_madah('حسین ستوده')}")
check("و لقبِ خودش را نگه می‌دارد",
      resolve_madah("سید جواد ذاکر") == "سید جواد ذاکر")

# =============================================================
print()
print("▸ ۲. زباله — حتی وقتی به نشانه چسبیده")
# =============================================================
for token, want in [
    ("UpMusic", True), ("musicdel.ir", True), ("Nex1Music.com", True),
    ("[320]", True), ("(Official)", True), ("~", True),
    ("www.x.com", True), ("mp3", True), ("MusicDel", True),
    ("حسین", False), ("ستوده", False), ("کریمی", False),
]:
    check(f"«{token}»", P._is_junk(token) == want)

for raw, want in [
    ("دیوونه حسینم - musicdel.ir", "دیوونه حسینم"),
    ("نماهنگ ام البکا [320]", "نماهنگ ام البکا"),
    ("شور | ماهم حضرت رضا ~ UpMusic", "ماهم حضرت رضا"),
    ("زمینه زیبا (Official) [320] mp3", "زمینه زیبا"),
]:
    got = clean_title(raw)
    check(f"«{raw[:28]}»", got == want, f" → {got}")

# =============================================================
print()
print("▸ ۳. واژهٔ فارسی نباید نابود شود")
# =============================================================
#
# ایرادِ راستین: `to_persian` نخست `bare` (تنها حرفِ لاتین)
# می‌ساخت و اگر تهی بود `continue` — و برای هر واژهٔ فارسی تهی
# است. پس هر واژهٔ فارسی خاموش دور ریخته می‌شد.
for raw, want in [
    ("حسین ستوده Hosein", "حسین ستوده"),
    ("احسان لطفی musicdel", "احسان لطفی"),
    ("زمینه زیبا mp3", "زمینه زیبا"),
]:
    got = P.to_persian(raw)
    check(f"«{raw}»", got.startswith(want), f" → {got}")

# =============================================================
print()
print("▸ ۴. لغزشِ شبکه ≠ «فایلت بزرگ است»")
# =============================================================
from bot.handlers import search
from core import net, texts

src = inspect.getsource(search._run_media)
check("فرو گرفتن، کوششِ دوباره دارد", "net.retry" in src)
check("خطای حجم از لغزشِ شبکه جدا شده", '"too big" in str(exc).lower()' in src)
check("و پیامِ جداگانه دارد", "search_network_failed" in src)
check("نوشتارش هست", bool(texts.msg("search_network_failed")))
check("سقف ۲۰ مگابایت است — ۱۰ مگ نباید بخورد",
      search.MAX_INPUT_BYTES == 20 * 1024 * 1024,
      f" — {search.MAX_INPUT_BYTES}")

# سندِ MP4 باید ویدیو شمرده شود
begin = inspect.getsource(search.on_input)
check("سندِ ویدیویی، ویدیو شمرده می‌شود", 'doc_mime.startswith("video/")' in begin)

# =============================================================
print()
print("▸ ۵. لغزشِ گذرا نوا را نامرئی نکند")
# =============================================================
from services import indexer

idx = inspect.getsource(indexer)
check("ناکامیِ گذرا شناخته می‌شود", "isinstance(exc, net.TRANSIENT)" in idx)
check("و شمرده نمی‌شود", "if not transient:" in idx)
check("`TRANSIENT` همان شبکه است",
      {t.__name__ for t in net.TRANSIENT} == {"TimedOut", "NetworkError"})

from core.db import fingerprints as fp
check("هیچ نوایی کنار گذاشته نمانده", len(fp.broken_tracks()) == 0,
      f" — {len(fp.broken_tracks())}")

# =============================================================
print()
print("▸ ۶. حالتِ `/upload` نوای جست‌وجو را نبلعد")
# =============================================================
from bot import states
from bot.handlers import curation

ud = {}
states.set_state(ud, states.AWAITING_BULK_AUDIO, items=[], last_file=time.time())
check("تازه، کهنه نیست", not curation.bulk_is_stale(ud))
states.set_state(
    ud, states.AWAITING_BULK_AUDIO, items=[],
    last_file=time.time() - curation.UPLOAD_IDLE_LIMIT - 10,
)
check("بی‌کارِ دیرپا، کهنه است", curation.bulk_is_stale(ud))
check("بی‌حالت، کهنه نیست", not curation.bulk_is_stale({}))

from bot.handlers import router

rt = inspect.getsource(router)
check("مسیریاب کهنگی را می‌سنجد", "curation.bulk_is_stale" in rt)

print()
print("=" * 62)
if fail:
    print(f"  ✗ {fail} سنجه ناکام ماند ({ok} گذشت)")
    sys.exit(1)
print(f"  ✓ هر {ok} سنجه گذشت")
print("=" * 62)
