# -*- coding: utf-8 -*-
"""
سنجهٔ غربالِ پیش از داوری.

دو خواسته:
  ۱. پذیرشِ گروهی — نخست همه با گنجینه سنجیده شوند، سپس پرسش‌ها
  ۲. پیشکشِ کاربر — تکراری هرگز به گردانندگان نرود

بی شبکه: `dedup.identify` جایگزین می‌شود، چون خودش فایل فرو
می‌گیرد و رمزگشایی می‌کند.
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
print("  غربالِ پیش از داوری")
print("═" * 62)
print()

database.init_db()
CHAT = -100999
ADMIN = None
sent: list[str] = []
made: list[int] = []


class FakeBot:
    async def send_audio(self, chat_id, audio, **kw):
        sent.append("audio:" + str(kw.get("caption", "")))
        return types.SimpleNamespace(message_id=len(sent))

    async def send_message(self, chat_id, text, **kw):
        sent.append("text:" + str(text))
        return types.SimpleNamespace(message_id=len(sent))


class FakeQuery:
    def __init__(self, data):
        self.data = data
        self.message = types.SimpleNamespace(
            chat_id=CHAT, message_id=1, caption="c", text=None
        )

    async def answer(self, text=None, show_alert=False):
        pass

    async def edit_message_caption(self, **kw):
        pass

    async def edit_message_reply_markup(self, **kw):
        pass

    async def edit_message_text(self, *a, **kw):
        pass


def ctx(user_data):
    return types.SimpleNamespace(bot=FakeBot(), user_data=user_data)


async def main():
    global ADMIN
    from config import config
    from bot.handlers import intake
    from bot.states import AWAITING_INTAKE_SCREEN, get_state, get_data
    from services import dedup

    ADMIN = config.admin_ids[0]

    # اگر اجرای پیشین نیمه‌کاره مانده، ردش را برمی‌داریم — وگرنه
    # قیدِ یکتاییِ file_unique_id اجرای بعدی را زمین می‌زند.
    database.execute("DELETE FROM tracks WHERE file_unique_id = ?", ("TWIN_U",))

    # نوایی که «از پیش داریم»
    twin_id = database.add_track(
        title="نوای موجود", madah="مداح آزمون", style="شور",
        file_id="TWIN_F", file_unique_id="TWIN_U", duration=100, source="test",
    )
    made.append(twin_id)

    items = [
        {"file_id": "A", "file_unique_id": "UA", "madah": "مداح آزمون"},
        {"file_id": "B", "file_unique_id": "UB", "madah": "مداح آزمون"},
        {"file_id": "C", "file_unique_id": "UC", "madah": "مداح آزمون"},
    ]

    # ── فایلِ B همانند است، بقیه تازه ───────────────────────
    async def fake_identify(bot, file_id, madah=None):
        return (twin_id, True) if file_id == "B" else None

    dedup.identify = fake_identify

    print("▸ غربال، پیش از هر پرسشی")
    ud = {}
    sent.clear()
    await intake.start(ctx(ud), CHAT, list(items), batch_madah="مداح آزمون")

    check("در وضعیتِ غربال ایستاد",
          get_state(ud) == AWAITING_INTAKE_SCREEN, f" → {get_state(ud)}")
    data = get_data(ud)
    check("همانند برای داوری نگه داشته شد",
          (data.get("screening") or {}).get("file_id") == "B")
    check("تازه‌ها بی پرسش به صف رفتند",
          [i["file_id"] for i in data.get("queue", [])] == ["A"],
          f" → {[i['file_id'] for i in data.get('queue', [])]}")
    check("نوای موجود فرستاده شد تا شنیده شود",
          any(m.startswith("audio:") for m in sent))
    check("هنوز هیچ پرسشی از سبک نشده",
          not any("سبک" in m for m in sent))

    # ── «بله، همین است» → کنار می‌رود ──────────────────────
    print()
    print("▸ «بله، همین است»")
    sent.clear()
    seq = int(data["seq"])
    upd = types.SimpleNamespace(
        callback_query=FakeQuery(f"{inline.IN_DUP}:{seq}"),
        effective_user=types.SimpleNamespace(id=ADMIN),
    )
    await intake.on_screen_dup(upd, ctx(ud))
    data = get_data(ud)
    check("کنار گذاشته شد", int(data.get("dropped", 0)) == 1)
    check("و از صف بیرون ماند",
          "B" not in [i["file_id"] for i in data.get("queue", [])])
    survivors = [i["file_id"] for i in data.get("queue", [])]
    current = (data.get("current") or {}).get("file_id")
    check("بازماندگان A و C اند",
          sorted(survivors + ([current] if current else [])) == ["A", "C"],
          f" → صف {survivors} + جاری {current}")

    # ── «نه، تازه است» → می‌ماند ───────────────────────────
    print()
    print("▸ «نه، تازه است»")
    ud2 = {}
    sent.clear()
    await intake.start(ctx(ud2), CHAT, list(items), batch_madah="مداح آزمون")
    d2 = get_data(ud2)
    upd2 = types.SimpleNamespace(
        callback_query=FakeQuery(f"{inline.IN_NEW}:{int(d2['seq'])}"),
        effective_user=types.SimpleNamespace(id=ADMIN),
    )
    await intake.on_screen_new(upd2, ctx(ud2))
    d2 = get_data(ud2)
    check("در صف ماند",
          "B" in [i["file_id"] for i in d2.get("queue", [])],
          f" → {[i['file_id'] for i in d2.get('queue', [])]}")
    check("چیزی کنار گذاشته نشد", int(d2.get("dropped", 0)) == 0)

    # ── هیچ همانندی نبود → یک‌راست به پرسش‌ها ──────────────
    print()
    print("▸ وقتی هیچ‌کدام تکراری نیستند")

    async def none_identify(bot, file_id, madah=None):
        return None

    dedup.identify = none_identify
    ud3 = {}
    sent.clear()
    await intake.start(ctx(ud3), CHAT, list(items), batch_madah="مداح آزمون")
    d3 = get_data(ud3)
    check("غربال نایستاد", d3.get("screening") is None)
    check("همه به صف رفتند",
          len(d3.get("queue", [])) + (1 if d3.get("current") else 0) == 3,
          f" → صف {len(d3.get('queue', []))} + جاری {1 if d3.get('current') else 0}")
    check("پرسشِ سبک پرسیده شد", any("سبک" in m for m in sent))

    # ── نگهبانِ نواختِ کهنه ────────────────────────────────
    print()
    print("▸ نگهبان‌ها")
    ud4 = {}
    await intake.start(ctx(ud4), CHAT, list(items))
    stale = types.SimpleNamespace(
        callback_query=FakeQuery(f"{inline.IN_DUP}:999"),
        effective_user=types.SimpleNamespace(id=ADMIN),
    )
    before = dict(get_data(ud4))
    await intake.on_screen_dup(stale, ctx(ud4))
    check("نواختِ کهنه کاری نمی‌کند",
          int(get_data(ud4).get("dropped", 0)) == int(before.get("dropped", 0)))

    not_admin = types.SimpleNamespace(
        callback_query=FakeQuery(f"{inline.IN_DUP}:1"),
        effective_user=types.SimpleNamespace(id=1),
    )
    await intake.on_screen_dup(not_admin, ctx(ud4))
    check("ناگرداننده رد می‌شود",
          int(get_data(ud4).get("dropped", 0)) == int(before.get("dropped", 0)))

    # ── پاک‌سازی ───────────────────────────────────────────
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
