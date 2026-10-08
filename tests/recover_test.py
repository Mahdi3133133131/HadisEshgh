# -*- coding: utf-8 -*-
"""
سنجهٔ «ربات یادش نرود».

پنج ایرادی که کاربر گزارش کرد، هر کدام یک بخش:

  ۱. گردآوریِ انبوه با راه‌اندازیِ دوباره گم نشود
  ۲. `/clean` در گروهی باشد که شلوغی آنجا ساخته می‌شود
  ۳. غربال همهٔ گنجینه را ببیند، نه تنها نواهای همان مداح
  ۴. تکراری‌بودن پیش از پرسیدنِ مشخصات گفته شود
  ۵. همراهِ مورد اعتماد دسته‌ای بارگذارد و هر نوا یک سکه بگیرد
"""
import io
import inspect
import pathlib
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from core.db import database, intake_sessions as S

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
print("  ربات یادش نرود")
print("=" * 62)

database.init_db()
S.ensure_table()

CHAT = -100515151

# =============================================================
print()
print("▸ ۱. گردآوری، پس از راه‌اندازیِ دوباره")
# =============================================================
#
# شبیه‌سازیِ راستین: `_keep_bulk` می‌نویسد، آنگاه `user_data`
# یکسره دور ریخته می‌شود (همان که با ری‌استارت رخ می‌دهد)، و
# `_recover_bulk` باید همه را بازگرداند.
from bot.handlers import curation
from bot.states import AWAITING_BULK_AUDIO

S.clear(CHAT)
items = [
    {"file_id": f"F{i}", "file_unique_id": f"U{i}", "file_name": f"نوای {i}"}
    for i in range(1, 8)
]
curation._keep_bulk(None, CHAT, {"items": items, "madah": "محمود کریمی", "added": 7})

back = curation._recover_bulk(CHAT)
check("گردآوری بازگردانده شد", back is not None)
check("هر هفت نوا سرِ جایش", bool(back) and len(back.get("items", [])) == 7,
      f" → {len(back.get('items', [])) if back else 0}")
check("نامِ دسته نگه داشته شد", bool(back) and back.get("madah") == "محمود کریمی")
check("حالت درست نشانه خورده",
      bool(back) and back.get("_state") == AWAITING_BULK_AUDIO)

# جاروب نباید نشستِ نیمه‌گردآورده را بکُشد
from bot.handlers import intake

src = inspect.getsource(intake.sweep_locks)
check("جاروب، `items` را می‌شمارد", 'data.get("items")' in src)

S.clear(CHAT)
check("پس از پاک شدن، چیزی بازنمی‌گردد", curation._recover_bulk(CHAT) is None)

# مهلت
check("مهلت ده دقیقه شد", S.DEFAULT_TIMEOUT == 600,
      f" → {S.DEFAULT_TIMEOUT}")

# نوشتنِ متن هم مهلت را نو کند
mine = inspect.getsource(intake._mine)
check("`_mine` مهلت را نو می‌کند", "intake_sessions.touch" in mine)

# =============================================================
print()
print("▸ ۲. `/clean` همان‌جا که شلوغی ساخته می‌شود")
# =============================================================
from bot import commands

archive = {name for name, _ in commands.ARCHIVE_GROUP}
madahi = {name for name, _ in commands.MADAHI_GROUP}
check("در گروه بایگانی هست", "clean" in archive)
check("در گروه مداحی هم هست", "clean" in madahi)
check("`/bulk` هم همان‌جاست", "bulk" in archive)

# =============================================================
print()
print("▸ ۳. غربال، همهٔ گنجینه")
# =============================================================
from services import dedup

check("آستانهٔ ناهم‌نام هست", hasattr(dedup, "CROSS_MADAH_SIMILARITY"))
check("و سخت‌گیرانه‌تر از هم‌نام است",
      dedup.CROSS_MADAH_SIMILARITY > dedup.TWIN_SIMILARITY,
      f" → {dedup.TWIN_SIMILARITY} < {dedup.CROSS_MADAH_SIMILARITY}")

nowheh = inspect.getsource(dedup.find_same_nowheh)
check("مداحِ ناهم‌نام دیگر بیرون انداخته نمی‌شود",
      'if wanted and normalize(track["madah"] or "") != wanted:' not in nowheh)
check("به‌جایش آستانه جابه‌جا می‌شود", "same_madah" in nowheh)
check("سقفِ نامزدها باز شد", "limit=12" in nowheh)

# =============================================================
print()
print("▸ ۴. تکراری، پیش از پرسش")
# =============================================================
from bot.handlers import submission

on_audio = inspect.getsource(submission.on_audio)
ask = on_audio.find("submit_ask_style_tags")
twin = on_audio.find("dedup.identify")
check("سنجشِ اثر انگشت در `on_audio` هست", twin != -1)
check("و **پیش از** پرسشِ سبک است", twin != -1 and ask != -1 and twin < ask)

# =============================================================
print()
print("▸ ۵. بارگذاری دسته‌ایِ همراه")
# =============================================================
check("`accept_batch` هست", hasattr(submission, "accept_batch"))
check("`/upload` هست", hasattr(curation, "begin_upload"))
check("`/done` هست", hasattr(curation, "end_upload"))

batch = inspect.getsource(submission.accept_batch)
check("هر نوا سکه می‌گیرد", "adjust_tokens" in batch)
check("و سنجشِ تکراری برداشته نشده", "_already_have" in batch)
check("نامِ فارسی هم اعمال می‌شود",
      "resolve_madah" in batch and "clean_title" in batch)

begin = inspect.getsource(curation.begin_upload)
check("ناهمراه راه ندارد", "is_trusted" in begin)
check("تنها در گفتگوی خصوصی", 'chat.type != "private"' in begin)

# =============================================================
print()
print("=" * 62)
if fail:
    print(f"  ✗ {fail} سنجه ناکام ماند ({ok} گذشت)")
    sys.exit(1)
print(f"  ✓ هر {ok} سنجه گذشت")
print("=" * 62)
