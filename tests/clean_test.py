# -*- coding: utf-8 -*-
"""
سنجهٔ پاک‌سازی.

خواستهٔ روشن: پس از پایانِ پذیرش، پیام‌های «به گنجینه افزوده شد»
و پرسش‌ها و صوت‌های بازفرستاده بروند و **تنها نسخهٔ آراسته**
بماند — و `/clean` همان کار را برای هر چه ثبت شده بکند، حتی
صوت‌هایی که خودِ گردانندگان فرستاده‌اند.

قاعدهٔ وارونه هم سنجیده می‌شود: چیزی که ثبت نشده، هرگز پاک
نمی‌شود. صوتِ آراسته هرگز ثبت نمی‌شود — و همین، نگهبانِ اوست.
"""
import asyncio
import io
import pathlib
import sys
import types

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from core.db import bot_messages, database

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
print("  پاک‌سازیِ گروه")
print("═" * 62)
print()

database.init_db()
CHAT = -100777111
deleted: list[int] = []


class FakeBot:
    async def send_message(self, chat_id, text, **kw):
        return types.SimpleNamespace(message_id=900 + len(deleted))

    async def send_audio(self, chat_id, audio, **kw):
        return types.SimpleNamespace(message_id=910 + len(deleted))

    async def delete_message(self, chat_id, message_id):
        deleted.append(int(message_id))
        return True


async def main():
    from bot.handlers import intake

    # زمینهٔ تمیز
    bot_messages.forget_all(CHAT)
    deleted.clear()

    # ── ثبت ────────────────────────────────────────────────
    print("▸ نشان‌کردنِ پیام‌های گذرا")
    ctx = types.SimpleNamespace(bot=FakeBot(), user_data={})
    intake._remember(CHAT, types.SimpleNamespace(message_id=11), "intake")
    intake._remember(CHAT, types.SimpleNamespace(message_id=12), "intake_audio")
    intake._remember(CHAT, types.SimpleNamespace(message_id=13), "intake")
    check("سه پیام نشان خورد", bot_messages.count(CHAT) == 3,
          f" → {bot_messages.count(CHAT)}")

    # صوتِ آراسته هرگز ثبت نمی‌شود — اینجا هم نمی‌کنیم، و همین
    # است که نگهش می‌دارد.
    ORNATE = 99
    check("صوتِ آراسته ثبت نشد",
          ORNATE not in [int(r["message_id"]) for r in bot_messages.pending(CHAT)])

    # ── رُفت‌وروب ──────────────────────────────────────────
    print()
    print("▸ رُفت‌وروبِ پایانِ پذیرش")
    gone = await intake._sweep(ctx, CHAT)
    check("هر سه برداشته شدند", gone == 3, f" → {gone}")
    check("و راستی حذف شدند", sorted(deleted) == [11, 12, 13], f" → {sorted(deleted)}")
    check("صوتِ آراسته دست‌نخورده ماند", ORNATE not in deleted)
    check("دفتر خالی شد", bot_messages.count(CHAT) == 0)

    # ── نشانِ کهنه، دوباره کوشیده نمی‌شود ──────────────────
    print()
    print("▸ پس از رُفت‌وروب")
    deleted.clear()
    again = await intake._sweep(ctx, CHAT)
    check("دور دوم چیزی برای بردن ندارد", again == 0, f" → {again}")
    check("و بیهوده به تلگرام نمی‌زند", deleted == [])

    # ── `_remember` در برابر ورودیِ پوچ ────────────────────
    print()
    print("▸ استواری")
    intake._remember(CHAT, None)
    check("پیامِ تهی، دفتر را کثیف نمی‌کند", bot_messages.count(CHAT) == 0)

    # ── صوتِ خودِ گرداننده هم ثبت می‌شود ───────────────────
    print()
    print("▸ صوتی که گرداننده فرستاده")
    from bot.handlers import curation

    curation._mark_transient(CHAT, 21, "bulk_audio")
    curation._mark_transient(CHAT, 22, "bulk")
    check("صوت و پیامِ گرداننده نشان خوردند",
          bot_messages.count(CHAT) == 2, f" → {bot_messages.count(CHAT)}")
    deleted.clear()
    await intake._sweep(ctx, CHAT)
    check("و با رُفت‌وروب رفتند", sorted(deleted) == [21, 22], f" → {sorted(deleted)}")

    curation._mark_transient(CHAT, None)
    curation._mark_transient(None, 5)
    check("ورودیِ پوچ نادیده گرفته می‌شود", bot_messages.count(CHAT) == 0)

    bot_messages.forget_all(CHAT)

    print()
    print("═" * 62)
    if fail:
        print(f"  ✗ {fail} سنجه ناکام ماند ({ok} گذشت)")
        return 1
    print(f"  ✓ هر {ok} سنجه گذشت")
    print("═" * 62)
    return 0


sys.exit(asyncio.run(main()))
