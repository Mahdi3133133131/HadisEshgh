# -*- coding: utf-8 -*-
"""
سنجهٔ لینکِ دعوت.

خواستهٔ کاربر، به بیان خودش: «هرکس از طریق لینک زیر کسی رو دعوت
کنه ۳ سکه می‌گیره… نکته اینجاست که اون کسی که عضو شد دوباره ربات
پاک کرد و دوباره عضو شد، دیگه به اون شخص دعوت‌کننده سکه‌ای تعلق
نمی‌گیره — یک بار از اون کاربر.»

پس مهم‌ترین سنجه، همان **یک‌بار بودن** است.
"""
import io
import pathlib
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from config import config
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


print("═" * 62)
print("  لینکِ دعوت")
print("═" * 62)
print()

database.init_db()

HOST, GUEST, OTHER = 900001, 900002, 900003


def wipe():
    for uid in (HOST, GUEST, OTHER):
        database.execute("DELETE FROM token_ledger WHERE user_id = ?", (uid,))
        database.execute("DELETE FROM users WHERE user_id = ?", (uid,))


wipe()
for uid, name in ((HOST, "میزبان"), (GUEST, "مهمان"), (OTHER, "دیگری")):
    database.upsert_user(uid, None, name, None)

# ── نشاندنِ دعوت‌کننده ──────────────────────────────────────
print("▸ نشاندنِ دعوت‌کننده")
check("دعوت ثبت شد", database.set_inviter(GUEST, HOST))
check("بارِ دوم ثبت نمی‌شود", not database.set_inviter(GUEST, OTHER))
check("و همان اولی مانده",
      int(database.get_user(GUEST)["invited_by"]) == HOST)
check("خودْدعوتی رد می‌شود", not database.set_inviter(OTHER, OTHER))

# ── پاداش ──────────────────────────────────────────────────
print()
print("▸ پاداش، یک بار")
before = database.get_tokens(HOST)
inviter = database.claim_invite_reward(GUEST)
check("دعوت‌کننده شناخته شد", inviter == HOST, f" → {inviter}")

database.adjust_tokens(HOST, config.invite_reward, reason="invite",
                       ref_type="user", ref_id=GUEST)
check("سکه رسید",
      database.get_tokens(HOST) == before + config.invite_reward,
      f" → {before} ← {database.get_tokens(HOST)}")

print()
print("▸ همان همراه، بارِ دوم")
again = database.claim_invite_reward(GUEST)
check("پاداشِ دوباره داده نمی‌شود", again is None, f" → {again}")

# ── و اگر ربات را پاک کند و برگردد؟ ───────────────────────
print()
print("▸ ربات را پاک کرد و دوباره آمد")
database.execute("UPDATE users SET is_blocked_bot = 1 WHERE user_id = ?", (GUEST,))
database.upsert_user(GUEST, None, "مهمان", None)     # /start دوباره
check("ردیفش از بین نرفت", database.get_user(GUEST) is not None)
check("نشانِ پاداش هم ماند",
      int(database.get_user(GUEST)["invite_rewarded"] or 0) == 1)
check("پس سکهٔ تازه‌ای در کار نیست",
      database.claim_invite_reward(GUEST) is None)

# ── شمارش ──────────────────────────────────────────────────
print()
print("▸ شمارشِ آورده‌ها")
check("یک نفر شمرده شد", database.count_invites(HOST) == 1,
      f" → {database.count_invites(HOST)}")
check("برای کسی که دعوتی نکرده، صفر", database.count_invites(OTHER) == 0)

# ── خواندنِ پارامترِ لینک ──────────────────────────────────
print()
print("▸ خواندنِ پارامترِ لینک")
from bot.handlers import start as S

database.execute("UPDATE users SET invited_by = NULL WHERE user_id = ?", (OTHER,))
S._note_inviter(OTHER, ["inv_%d" % HOST])
check("‏`inv_<شناسه>` خوانده شد",
      int(database.get_user(OTHER)["invited_by"] or 0) == HOST)

for junk in ([], ["hello"], ["inv_"], ["inv_abc"], ["inv_-5"], None):
    database.execute("UPDATE users SET invited_by = NULL WHERE user_id = ?", (OTHER,))
    S._note_inviter(OTHER, junk)
    if database.get_user(OTHER)["invited_by"] is not None:
        check(f"پارامترِ نامعتبر {junk!r}", False)
        break
else:
    check("پارامترِ نامعتبر چیزی نمی‌شکند", True)

# ── کارنامه ────────────────────────────────────────────────
print()
print("▸ کارنامهٔ سکه")
from bot.handlers.tokens import _REASONS

check("«دعوت» برچسب دارد", "invite" in _REASONS)
rows = database.token_history(HOST, 5)
check("در کارنامه نشست",
      any(r["reason"] == "invite" for r in rows))

wipe()

print()
print("═" * 62)
if fail:
    print(f"  ✗ {fail} سنجه ناکام ماند ({ok} گذشت)")
    sys.exit(1)
print(f"  ✓ هر {ok} سنجه گذشت")
print("═" * 62)
