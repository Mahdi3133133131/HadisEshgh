# -*- coding: utf-8 -*-
"""
سنجهٔ رساندنِ سخن به گروه نقد.

بی شبکه: تلگرام جایگزین می‌شود و تنها فراخوان‌ها شمرده می‌شوند.
"""
import asyncio
import io
import pathlib
import sys
import types

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

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
print("  سخن در گروه نقد")
print("═" * 62)
print()

calls: list[dict] = []


class FakeBot:
    async def send_message(self, chat_id, text, **kw):
        calls.append({"how": "send_message", "text": text, **kw})
        return types.SimpleNamespace(message_id=100 + len(calls))

    async def copy_message(self, chat_id, from_chat_id, message_id, **kw):
        calls.append({"how": "copy_message", **kw})
        return types.SimpleNamespace(message_id=200 + len(calls))


def fake(kind, text=None, caption=None):
    m = types.SimpleNamespace(
        chat_id=5, message_id=9, text=text, caption=caption,
        photo=None, audio=None, voice=None, video=None,
        video_note=None, animation=None, document=None, sticker=None,
    )
    if kind != "text":
        setattr(m, kind, object())
    return m


USER = types.SimpleNamespace(id=42, full_name="کاربر <آزمون>", username="tester")


def ctx():
    """`_post` بافتار می‌گیرد نه ربات — همان که گرداننده می‌بیند."""
    return types.SimpleNamespace(bot=FakeBot())


async def main():
    from bot.handlers import feedback as F

    header = F._header_for(USER, 7)

    print("▸ گریزِ HTML در نام")
    check("نامِ دارای «<» گریز خورد", "&lt;آزمون&gt;" in header)
    check("و برچسب‌های خودمان سالم ماندند", "<b>فرستنده:</b>" in header)

    print()
    print("▸ رسانهٔ زیرنویس‌پذیر — یک پیام")
    for kind in ("photo", "video", "audio", "voice", "animation", "document"):
        calls.clear()
        await F._post(ctx(), fake(kind, caption="سلام"), kind, header, 7)
        one = len(calls) == 1 and calls[0]["how"] == "copy_message"
        has_cap = bool(calls) and header[:20] in (calls[0].get("caption") or "")
        has_btn = bool(calls) and calls[0].get("reply_markup") is not None
        check(f"{kind}", one and has_cap and has_btn,
              f" → {len(calls)} پیام، زیرنویس={has_cap}، دکمه={has_btn}")

    print()
    print("▸ متنِ ساده — یک پیام")
    calls.clear()
    await F._post(ctx(), fake("text", text="نقد من"), "text", header, 7)
    check("یک پیام رفت", len(calls) == 1 and calls[0]["how"] == "send_message")
    check("سرنویس و متن با هم‌اند",
          bool(calls) and "نقد من" in calls[0]["text"] and "فرستنده" in calls[0]["text"])

    print()
    print("▸ برچسب و یادداشت ویدیویی — ناچار دو پیام")
    for kind in ("sticker", "video_note"):
        calls.clear()
        await F._post(ctx(), fake(kind), kind, header, 7)
        check(f"{kind}", len(calls) == 2, f" → {len(calls)} پیام")

    print()
    print("▸ زیرنویسِ درازتر از سقف — بازگشت به دو پیام")
    calls.clear()
    await F._post(ctx(), fake("photo", caption="ن" * 1200), "photo", header, 7)
    check("دو پیام رفت", len(calls) == 2, f" → {len(calls)}")
    check("هیچ واژه‌ای بریده نشد",
          all(len(c.get("caption") or "") <= 1024 for c in calls))

    print()
    print("▸ شناسهٔ بازگشتی، همانِ پیامِ دکمه‌دار است")
    calls.clear()
    got = await F._post(ctx(), fake("photo", caption="آ"), "photo", header, 7)
    check("شناسهٔ رونوشت برگشت", got == 201, f" → {got}")

    print()
    print("═" * 62)
    if fail:
        print(f"  ✗ {fail} سنجه ناکام ماند ({ok} گذشت)")
        return 1
    print(f"  ✓ هر {ok} سنجه گذشت")
    print("═" * 62)
    return 0


sys.exit(asyncio.run(main()))
