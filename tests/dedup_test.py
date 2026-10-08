# -*- coding: utf-8 -*-
"""
سنجهٔ یافتن و ادغامِ نسخه‌های تکراری.

با فایل mp3 **راستین** کار می‌کند، نه آرایهٔ درون حافظه: تکراری
در جهانِ واقعی از راه فشرده‌سازیِ دیگر می‌آید، و همان است که باید
سنجیده شود.

نیازمند ffmpeg در PATH.
"""
import io
import pathlib
import shutil
import subprocess
import sys
import tempfile

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import numpy as np

from core.audio.decode import decode
from core.audio.fingerprint import FAN_OUT_INDEX, SAMPLE_RATE, fingerprint
from core.db import database, fingerprints as fp_store
from services import dedup

ok = fail = 0


def check(label, cond, detail=""):
    global ok, fail
    if cond:
        ok += 1
        print(f"  ✓ {label}{detail}")
    else:
        fail += 1
        print(f"  ✗ {label}{detail}")


def make_audio(seconds, seed):
    r = np.random.default_rng(seed)
    t = np.linspace(0, seconds, int(seconds * SAMPLE_RATE), endpoint=False)
    x = np.zeros_like(t)
    base = r.uniform(90, 260)
    for k in range(1, 9):
        f = base * k * r.uniform(0.99, 1.01)
        if f > SAMPLE_RATE / 2 - 100:
            break
        env = 0.5 + 0.5 * np.sin(2 * np.pi * r.uniform(0.15, 0.9) * t + r.uniform(0, 6))
        vib = 1 + 0.015 * np.sin(2 * np.pi * r.uniform(3, 7) * t)
        x += (r.uniform(0.4, 1.0) / k) * env * np.sin(2 * np.pi * f * vib * t)
    for _ in range(6):
        f = r.uniform(600, 4200)
        env = np.maximum(0, np.sin(2 * np.pi * r.uniform(0.5, 2.5) * t)) ** 4
        x += r.uniform(0.15, 0.5) * env * np.sin(2 * np.pi * f * t)
    x += 0.015 * r.standard_normal(t.size)
    return (x / np.max(np.abs(x))).astype(np.float32)


def write_mp3(samples, path, bitrate):
    raw = (np.clip(samples, -1, 1) * 32767).astype("<i2").tobytes()
    subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
         "-f", "s16le", "-ar", str(SAMPLE_RATE), "-ac", "1", "-i", "pipe:0",
         "-b:a", bitrate, str(path)],
        input=raw, check=True,
    )


if shutil.which("ffmpeg") is None:
    print("ffmpeg نیست؛ این سنجه رد شد.")
    sys.exit(0)

print("═" * 62)
print("  یافتن و ادغامِ نسخه‌های تکراری")
print("═" * 62)
print()

database.init_db()
work = pathlib.Path(tempfile.mkdtemp(prefix="dedup_"))
made: list[int] = []

try:
    # ── دو نسخه از یک ضبط، با دو نرخِ بیت ──────────────────
    source = make_audio(90.0, seed=4242)
    a_path, b_path = work / "a.mp3", work / "b.mp3"
    write_mp3(source, a_path, "128k")
    write_mp3(source, b_path, "64k")

    # و یک نوای یکسره جدا
    other = make_audio(90.0, seed=777)
    c_path = work / "c.mp3"
    write_mp3(other, c_path, "128k")

    def add(name, path, duration):
        tid = database.add_track(
            title=name, madah="آزمون", style="آزمون",
            file_id=f"test_{name}", file_unique_id=f"uniq_{name}",
            duration=duration, file_size=path.stat().st_size,
            source="test",
        )
        made.append(tid)
        return tid

    a_id = add("dedup_a", a_path, 90)
    c_id = add("dedup_c", c_path, 90)

    # نسخهٔ الف و نوای جدا نمایه می‌شوند
    for tid, path in ((a_id, a_path), (c_id, c_path)):
        samples = decode(path)
        pr = fingerprint(samples, fan_out=FAN_OUT_INDEX)
        fp_store.store(tid, pr.hashes, pr.offsets)
        database.execute("UPDATE tracks SET is_indexed = 1 WHERE id = ?", (tid,))

    print("▸ تشخیص")

    # نسخهٔ ب — همان ضبط، نرخِ بیتِ دیگر
    b_id = add("dedup_b", b_path, 90)
    twin = dedup.find_same_recording(b_id, decode(b_path))
    check(
        "نسخهٔ دوم از همان ضبط، تکراری شناخته شد",
        twin is not None and twin[0] == a_id,
        f" — {twin}",
    )

    # نوای جدا نباید تکراری شمرده شود
    stranger = make_audio(90.0, seed=999)
    d_path = work / "d.mp3"
    write_mp3(stranger, d_path, "128k")
    d_id = add("dedup_d", d_path, 90)
    check(
        "نوای بیگانه تکراری شمرده نمی‌شود",
        dedup.find_same_recording(d_id, decode(d_path)) is None,
    )

    print()
    print("▸ ادغام")

    # ب کوتاه‌تر نیست ولی کم‌حجم‌تر است، پس الف باید بماند
    database.bump_sent_count(b_id)
    database.bump_sent_count(b_id)
    before = int(database.get_track(a_id)["sent_count"] or 0)

    winner = dedup.merge(a_id, b_id)
    check("برندهٔ ادغام، نسخهٔ پرحجم‌تر است", winner == a_id, f" — برنده {winner}")

    loser = database.get_track(b_id)
    check("بازنده غیرفعال شد", int(loser["is_active"]) == 0)
    check("بازنده به برنده گره خورد", int(loser["merged_into"]) == a_id)
    check(
        "اثر انگشتِ بازنده برداشته شد",
        fp_store.count_for_track(b_id) == 0,
    )
    check(
        "شمارِ فرستادن جمع شد",
        int(database.get_track(a_id)["sent_count"] or 0) == before + 2,
    )
    check(
        "برنده همچنان در گنجینه است",
        int(database.get_track(a_id)["is_active"]) == 1,
    )

finally:
    for tid in made:
        database.execute("DELETE FROM fingerprints WHERE track_id = ?", (tid,))
        database.execute("DELETE FROM tracks WHERE id = ?", (tid,))
    shutil.rmtree(work, ignore_errors=True)

print()
print("═" * 62)
if fail:
    print(f"  ✗ {fail} سنجه ناکام ماند ({ok} گذشت)")
    sys.exit(1)
print(f"  ✓ هر {ok} سنجه گذشت")
print("═" * 62)
