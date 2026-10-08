# -*- coding: utf-8 -*-
"""
سنجهٔ قفلِ فایل تا تأیید.

بی شبکه و بی تلگرام: هر بخشِ بیرونی جایگزین می‌شود.

## آنچه سنجیده می‌شود

نوا **قفل‌شده** می‌رود؛ با «دریافت نسخهٔ قابل دانلود» نسخهٔ آزاد
فرستاده و قفل‌شده برداشته می‌شود؛ با «جست‌وجوی دوباره» قفل‌شده
برداشته می‌شود و سکه بازمی‌گردد.
"""
import asyncio
import io
import pathlib
import sys
import types

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from bot.keyboards import inline
from core.db import database, searches

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
print("  قفلِ فایل تا تأیید")
print("═" * 62)
print()

database.init_db()

UID = 777000111
sent: list[dict] = []
deleted: list[int] = []


class FakeAudio:
    file_id = "LOCKED_FILE"
    file_unique_id = "LOCKED_UNIQ"
    title = "نوای آزمون"
    performer = "مداح آزمون"
    duration = 100


class FakeMessage:
    """پیامِ قفل‌شده‌ای که دکمه‌اش نواخته می‌شود."""

    def __init__(self):
        self.chat_id = UID
        self.message_id = 55
        self.caption = "زیرنویس"
        self.audio = FakeAudio()

    async def delete(self):
        deleted.append(self.message_id)
        return True


class FakeBot:
    async def send_audio(self, chat_id, audio, **kw):
        sent.append({"chat": chat_id, "audio": audio,
                     "protected": kw.get("protect_content", False),
                     "caption": kw.get("caption", "")})
        return types.SimpleNamespace(message_id=len(sent))

    async def send_message(self, chat_id, text, **kw):
        sent.append({"chat": chat_id, "text": text[:40], "protected": None})
        return types.SimpleNamespace(message_id=len(sent))


class FakeQuery:
    def __init__(self, data):
        self.data = data
        self.from_user = types.SimpleNamespace(id=UID)
        self.message = FakeMessage()
        self.answers = []
        self.markup_cleared = False
        self.caption_edits = []

    async def answer(self, text=None, show_alert=False):
        self.answers.append(text)

    async def edit_message_caption(self, caption=None, **kw):
        self.caption_edits.append(caption)

    async def edit_message_reply_markup(self, reply_markup=None):
        self.markup_cleared = True


async def main():
    from bot.handlers import search as S

    # ── ۱. آیا نوا قفل‌شده می‌رود؟ ─────────────────────────
    print("▸ فرستادن")
    source = io.open(
        pathlib.Path(__file__).resolve().parent.parent / "bot" / "handlers" / "search.py",
        encoding="utf-8",
    ).read()
    body = source.split("async def _deliver")[1].split("\nasync def ")[0]
    check("‏`_deliver` با قفل می‌فرستد",
          body.count("protect_content=True") == 2,
          f" → {body.count('protect_content=True')} جا")

    # ── ۲. تأیید: نسخهٔ آزاد و برداشتنِ قفل‌شده ────────────
    print()
    print("▸ «دریافت نسخهٔ قابل دانلود»")
    database.upsert_user(UID, "tester", "آزماینده", None)
    sid = searches.create(user_id=UID, input_kind="audio")
    searches.mark_charged(sid)

    sent.clear(); deleted.clear()
    q = FakeQuery(f"{inline.SEARCH_CORRECT}:{sid}")
    upd = types.SimpleNamespace(callback_query=q,
                                effective_user=types.SimpleNamespace(id=UID))
    ctx = types.SimpleNamespace(bot=FakeBot())
    await S.on_feedback(upd, ctx)

    frees = [m for m in sent if m.get("audio")]
    check("نسخهٔ آزاد فرستاده شد", len(frees) == 1, f" → {len(frees)}")
    check("و راستی بی قفل بود",
          bool(frees) and frees[0]["protected"] is False)
    check("همان فایلِ پیامِ قفل‌شده بود",
          bool(frees) and frees[0]["audio"] == "LOCKED_FILE")
    check("پیامِ قفل‌شده برداشته شد", deleted == [55], f" → {deleted}")

    # ── ۳. رد: برداشتن و بازگشتِ سکه ───────────────────────
    print()
    print("▸ «جست‌وجوی دوباره»")
    before = database.get_tokens(UID)
    sid2 = searches.create(user_id=UID, input_kind="audio")
    searches.mark_charged(sid2)

    sent.clear(); deleted.clear()
    q2 = FakeQuery(f"{inline.SEARCH_WRONG}:{sid2}")
    upd2 = types.SimpleNamespace(callback_query=q2,
                                 effective_user=types.SimpleNamespace(id=UID))

    # آوای کلیپ پس از «نیست» فرستاده می‌شود؛ اینجا کاری‌اش نداریم.
    S._deliver_clip_after_wrong = lambda *a, **k: asyncio.sleep(0)
    await S.on_feedback(upd2, ctx)

    check("پیامِ قفل‌شده برداشته شد", deleted == [55], f" → {deleted}")
    check("نسخهٔ آزادی فرستاده نشد",
          not [m for m in sent if m.get("audio")])
    check("سکه بازگشت", database.get_tokens(UID) == before + 1,
          f" → {before} ← {database.get_tokens(UID)}")

    # ── ۴. نامِ دکمه‌ها ────────────────────────────────────
    print()
    print("▸ نامِ دکمه‌ها")
    from core import texts
    correct = texts.btn("result_correct")
    wrong = texts.btn("result_wrong")
    check("«این همان است» دیگر نیست", "همان" not in correct, f" → {correct}")
    check("«این نیست» دیگر نیست", wrong.strip() != "❌ این نیست", f" → {wrong}")

    # ── پاک‌سازی ───────────────────────────────────────────
    for s in (sid, sid2):
        database.execute("DELETE FROM searches WHERE id = ?", (s,))
    database.execute("DELETE FROM token_ledger WHERE user_id = ?", (UID,))
    database.execute("DELETE FROM users WHERE user_id = ?", (UID,))

    print()
    print("═" * 62)
    if fail:
        print(f"  ✗ {fail} سنجه ناکام ماند ({ok} گذشت)")
        return 1
    print(f"  ✓ هر {ok} سنجه گذشت")
    print("═" * 62)
    return 0


sys.exit(asyncio.run(main()))
