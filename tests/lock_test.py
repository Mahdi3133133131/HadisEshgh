# -*- coding: utf-8 -*-
"""
سنجهٔ قفلِ گروه.

خواستهٔ کاربر، به بیان خودش: «هر دو ادمین دیگه می‌تونه کار منو
ادامه بده یا کار خودش پیش بگیره؛ من خودم اومدم کارم ادامه می‌دم.»

پس سه چیز سنجیده می‌شود:
  ۱. تا مهلت نگذشته، گردانندهٔ دیگر نمی‌تواند دست بزند
  ۲. پس از مهلت، صف **دست‌نخورده** به دیگری می‌رسد
  ۳. آغازگرِ نخست هم می‌تواند برگردد و ادامه دهد
"""
import asyncio
import io
import pathlib
import sys
import types

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


print("═" * 62)
print("  قفلِ گروه میان گردانندگان")
print("═" * 62)
print()

database.init_db()
S.ensure_table()

CHAT = -100424242
A, B = 111111, 222222
said: list[str] = []


class FakeBot:
    async def send_message(self, chat_id, text, **kw):
        said.append(str(text))
        return types.SimpleNamespace(message_id=len(said))

    async def send_audio(self, chat_id, audio, **kw):
        said.append("audio")
        return types.SimpleNamespace(message_id=len(said))


async def main():
    S.clear(CHAT)

    # ── لایهٔ داده ──────────────────────────────────────────
    print("▸ گرفتن و نگه داشتن")
    check("A قفل را می‌گیرد", S.try_take(CHAT, A, 120))
    check("B نمی‌تواند", not S.try_take(CHAT, B, 120))
    check("A دنبالهٔ کار خودش را می‌گیرد", S.try_take(CHAT, A, 120))
    check("دارنده A است", S.holder(CHAT) == A, f" → {S.holder(CHAT)}")

    print()
    print("▸ صف، مالِ گروه است نه مالِ یک نفر")
    S.save(CHAT, {"chat_id": CHAT, "queue": [{"file_id": "X"}, {"file_id": "Y"}],
                  "seq": 4, "_state": "awaiting_intake_style"})
    check("ذخیره و بازخوانی می‌خواند",
          (S.load(CHAT) or {}).get("seq") == 4)

    print()
    print("▸ پس از سرآمدنِ مهلت")
    S.try_take(CHAT, A, -5)          # مهلت را به گذشته می‌بریم
    check("قفل آزاد شمرده می‌شود", S.holder(CHAT) is None)
    check("B می‌تواند به دست بگیرد", S.try_take(CHAT, B, 120))
    left = S.load(CHAT) or {}
    check("و صف دست‌نخورده است",
          [i["file_id"] for i in left.get("queue", [])] == ["X", "Y"],
          f" → {[i['file_id'] for i in left.get('queue', [])]}")
    check("اکنون دارنده B است", S.holder(CHAT) == B, f" → {S.holder(CHAT)}")
    check("و A دیگر نمی‌تواند", not S.try_take(CHAT, A, 120))

    print()
    print("▸ بازگشتِ آغازگر پس از آزاد شدن")
    S.try_take(CHAT, B, -5)
    check("A می‌تواند کارِ خودش را از سر بگیرد", S.try_take(CHAT, A, 120))
    back = S.load(CHAT) or {}
    check("و همان صف را می‌بیند", back.get("seq") == 4)

    # ── اعلامِ آزاد شدن ────────────────────────────────────
    print()
    print("▸ اعلامِ آزاد شدنِ قفل")
    from bot.handlers import intake

    S.try_take(CHAT, A, -5)
    said.clear()
    ctx = types.SimpleNamespace(bot=FakeBot())
    await intake.sweep_locks(ctx)
    check("خبر داده شد", any("آزاد" in m for m in said),
          f" → {len(said)} پیام")
    check("قفل راستی آزاد شد", S.holder(CHAT) is None)
    check("ولی صف نگه داشته شد",
          [i["file_id"] for i in (S.load(CHAT) or {}).get("queue", [])] == ["X", "Y"])

    # ── نشستِ بی‌کار، بیهوده نماند ─────────────────────────
    print()
    print("▸ نشستِ تهی")
    S.clear(CHAT)
    S.try_take(CHAT, A, -5)
    S.save(CHAT, {"chat_id": CHAT, "queue": [], "screen": []})
    said.clear()
    await intake.sweep_locks(ctx)
    check("نشستِ بی‌کار بسته شد", S.load(CHAT) is None)
    check("و پیامِ بیهوده نداد", not said, f" → {said}")

    # ── یاورهای خودِ پذیرش ─────────────────────────────────
    print()
    print("▸ تحویلِ کار به گردانندهٔ دیگر")
    S.clear(CHAT)
    S.try_take(CHAT, A, 120)
    S.save(CHAT, {"chat_id": CHAT, "queue": [{"file_id": "Z"}],
                  "current": {"file_id": "W"}, "seq": 7,
                  "_state": "awaiting_intake_style"})
    ud_b = {}
    ctx_b = types.SimpleNamespace(bot=FakeBot(), user_data=ud_b)
    adopted = intake._adopt(ctx_b, CHAT)
    check("گردانندهٔ دیگر صف را به ارث می‌برد",
          adopted is not None and adopted.get("seq") == 7,
          f" → {(adopted or {}).get('seq')}")
    from bot.states import get_state
    check("و وضعیت هم درست بازسازی شد",
          get_state(ud_b) == "awaiting_intake_style", f" → {get_state(ud_b)}")

    S.clear(CHAT)

    print()
    print("═" * 62)
    if fail:
        print(f"  ✗ {fail} سنجه ناکام ماند ({ok} گذشت)")
        return 1
    print(f"  ✓ هر {ok} سنجه گذشت")
    print("═" * 62)
    return 0


sys.exit(asyncio.run(main()))
