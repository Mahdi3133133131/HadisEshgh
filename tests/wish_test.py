# -*- coding: utf-8 -*-
"""آزمونِ چرخهٔ «خبرم کن»، بی تلگرام."""
import asyncio
import io
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent))

from core.db import database, searches
from bot.handlers import search as S

database.init_db()
ok = fail = 0


def check(label, cond):
    global ok, fail
    if cond:
        ok += 1
        print(f"  OK   {label}")
    else:
        fail += 1
        print(f"  FAIL {label}")


class FakeBot:
    def __init__(self):
        self.sent = []

    async def send_audio(self, chat_id, audio, caption=None, **kw):
        self.sent.append({"chat": chat_id, "audio": audio, "caption": caption})
        return True


class Ctx:
    def __init__(self):
        self.bot = FakeBot()


async def main():
    # ── زمینه: کاربر و نوایی که هنوز نیست ──────────────────
    uid = 99900001

    # پاک‌سازی **پیش از** آغاز، نه تنها پس از پایان.
    #
    # اگر اجرای پیشین نیمه‌کاره مانده باشد (خطا، Ctrl+C)، سفارشِ
    # بازش می‌ماند و نخستین سنجه — «بی سفارش، چیزی فرستاده
    # نمی‌شود» — دروغ می‌شد. آزمونی که به ترتیب اجرا وابسته باشد،
    # از نبودنش بدتر است.
    database.execute("DELETE FROM searches WHERE user_id = ?", (uid,))
    database.upsert_user(uid, "tester", "آزمونگر")

    sid = searches.create(
        user_id=uid, input_kind="video", query_text=None
    )
    searches.set_hint(sid, "پیام کیانی")
    searches.finish(sid, "not_found")

    # پیش از سفارش، گشت نباید چیزی بفرستد
    ctx = Ctx()
    n = await S.sweep_wishes(ctx)
    check("بی سفارش، چیزی فرستاده نمی‌شود", n == 0 and not ctx.bot.sent)

    # ── کاربر «خبرم کن» را می‌زند ──────────────────────────
    searches.want_notice(sid)
    wishes = searches.open_wishes()
    check("سفارش در فهرستِ باز می‌نشیند", any(w["id"] == sid for w in wishes))

    # ── گشت: نوای «پیام کیانی» در گنجینه هست ───────────────
    ctx = Ctx()
    n = await S.sweep_wishes(ctx)
    check("سفارش برآورده شد", n == 1)
    check("به همان کاربر رفت", ctx.bot.sent and ctx.bot.sent[0]["chat"] == uid)

    # ── دوباره نرود ────────────────────────────────────────
    ctx2 = Ctx()
    n2 = await S.sweep_wishes(ctx2)
    check("خبر دوباره فرستاده نمی‌شود", n2 == 0 and not ctx2.bot.sent)

    row = searches.get(sid)
    check("نشانِ خبر خورد", row["notified_at"] is not None)
    check("وضعیت fulfilled شد", row["status"] == "fulfilled")

    # ── سفارشی که در گنجینه نیست، برآورده نمی‌شود ──────────
    sid2 = searches.create(user_id=uid, input_kind="video")
    searches.set_hint(sid2, "نامی که هرگز نبوده زززز")
    searches.finish(sid2, "not_found")
    searches.want_notice(sid2)
    ctx3 = Ctx()
    n3 = await S.sweep_wishes(ctx3)
    check("سفارشِ ناموجود برآورده نمی‌شود", n3 == 0 and not ctx3.bot.sent)
    check("و باز می‌ماند", searches.get(sid2)["notified_at"] is None)

    # ── پاک‌سازی ───────────────────────────────────────────
    database.execute("DELETE FROM searches WHERE user_id = ?", (uid,))
    database.execute("DELETE FROM users WHERE user_id = ?", (uid,))

    print()
    print(f"  {ok} گذشت · {fail} ناکام")
    return 1 if fail else 0


sys.exit(asyncio.run(main()))
