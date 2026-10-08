"""
آزمون موتور اثر انگشت — از راه پایگاه دادهٔ راستین.

اجرا:  python tests/engine_test.py

جاروب‌های تنظیم پارامتر درون حافظه انجام شدند؛ این آزمون همان
مسیری را می‌پیماید که ربات در کار راستین می‌پیماید: نشاندن در
SQLite، بازجویی از همان‌جا، و تطبیق.

نواهای آزمایشی ساختگی‌اند و در پایان پاک می‌شوند. برای سنجش با
نواهای راستین خودتان، tests/accuracy_real.py را ببینید.
"""

from __future__ import annotations

import sys
import time
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.console import enable_utf8_console  # noqa: E402

enable_utf8_console()

import numpy as np  # noqa: E402

from core.audio.decode import SAMPLE_RATE  # noqa: E402
from core.audio.fingerprint import (  # noqa: E402
    FAN_OUT_INDEX,
    FAN_OUT_QUERY,
    fingerprint_query,
    fingerprint,
)
from core.audio import matcher  # noqa: E402
from core.db import database, fingerprints as fp_store  # noqa: E402

N_TRACKS = 25
TRACK_SECONDS = 150
TEST_SOURCE = "engine_test"


def make_audio(seconds: float, seed: int) -> np.ndarray:
    """آوایی ساختگی ولی پیچیده: هارمونیک‌ها با لرزش و پوش."""
    rng = np.random.default_rng(seed)
    t = np.linspace(0, seconds, int(seconds * SAMPLE_RATE), endpoint=False)
    x = np.zeros_like(t)

    base = rng.uniform(90, 260)
    for k in range(1, 9):
        f = base * k * rng.uniform(0.99, 1.01)
        if f > SAMPLE_RATE / 2 - 100:
            break
        env = 0.5 + 0.5 * np.sin(2 * np.pi * rng.uniform(0.15, 0.9) * t + rng.uniform(0, 6))
        vib = 1 + 0.015 * np.sin(2 * np.pi * rng.uniform(3, 7) * t)
        x += (rng.uniform(0.4, 1.0) / k) * env * np.sin(2 * np.pi * f * vib * t)

    for _ in range(6):
        f = rng.uniform(600, 4200)
        env = np.maximum(0, np.sin(2 * np.pi * rng.uniform(0.5, 2.5) * t)) ** 4
        x += rng.uniform(0.15, 0.5) * env * np.sin(2 * np.pi * f * t)

    x += 0.015 * rng.standard_normal(t.size)
    return (x / np.max(np.abs(x))).astype(np.float32)


def add_noise(clip: np.ndarray, rng, snr_db: float | None) -> np.ndarray:
    if snr_db is None:
        return clip
    power = float(np.mean(clip ** 2))
    noise_power = power / (10 ** (snr_db / 10))
    out = clip + np.sqrt(noise_power) * rng.standard_normal(clip.size).astype(np.float32)
    return (out / max(1e-9, float(np.max(np.abs(out))))).astype(np.float32)


def cleanup() -> None:
    rows = database.query_all(
        "SELECT id FROM tracks WHERE source = ?", (TEST_SOURCE,)
    )
    for row in rows:
        fp_store.delete_for_track(int(row["id"]))
    database.execute("DELETE FROM tracks WHERE source = ?", (TEST_SOURCE,))


def main() -> int:
    database.init_db()
    cleanup()

    print("═" * 62)
    print("  آزمون موتور اثر انگشت — از راه SQLite")
    print("═" * 62)
    print(f"\nچگالی: گنجینه fan={FAN_OUT_INDEX}، بازجویی fan={FAN_OUT_QUERY}")

    # ── نشاندن گنجینه ────────────────────────────────────────
    print(f"\n▸ نشاندن {N_TRACKS} نوای {TRACK_SECONDS} ثانیه‌ای")
    audios: list[np.ndarray] = []
    track_ids: list[int] = []
    total_rows = 0
    started = time.monotonic()

    for i in range(N_TRACKS):
        audio = make_audio(TRACK_SECONDS, 2000 + i)
        audios.append(audio)
        track_id = database.add_track(
            file_id=f"TEST_{i}", file_unique_id=f"TESTUQ_{i}",
            source=TEST_SOURCE, title=f"نوای آزمایشی {i}",
            madah="آزماینده", style="شور", duration=TRACK_SECONDS,
        )
        track_ids.append(track_id)
        print_result = fingerprint(audio, fan_out=FAN_OUT_INDEX)
        total_rows += fp_store.store(track_id, print_result.hashes, print_result.offsets)

    index_seconds = time.monotonic() - started
    audio_seconds = N_TRACKS * TRACK_SECONDS
    print(f"  ✓ {total_rows:,} عدد در {index_seconds:.1f} ثانیه")
    print(f"    چگالی گنجینه: {total_rows / audio_seconds:.0f} عدد در ثانیه")
    print(f"    شتاب: {audio_seconds / index_seconds:.0f}× زمان واقعی")

    # ── بازجویی ──────────────────────────────────────────────
    print(f"\n▸ بازجویی — {N_TRACKS} تکه در هر حالت")
    rng = np.random.default_rng(4242)
    failures: list[str] = []
    latencies: list[float] = []

    scenarios = [
        ("۵ ثانیه، پاک", 5, None),
        ("۵ ثانیه، نویز ۱۰dB", 5, 10),
        ("۱۰ ثانیه، پاک", 10, None),
        ("۱۰ ثانیه، نویز ۱۰dB", 10, 10),
        ("۱۰ ثانیه، نویز ۰dB", 10, 0),
        ("۲۰ ثانیه، نویز ۰dB", 20, 0),
    ]

    for label, clip_seconds, snr in scenarios:
        hits = wrong = missed = 0
        offset_errors: list[float] = []

        for index in range(N_TRACKS):
            start_sample = int(rng.integers(0, (TRACK_SECONDS - clip_seconds - 2) * SAMPLE_RATE))
            true_offset = start_sample / SAMPLE_RATE
            clip = audios[index][start_sample : start_sample + clip_seconds * SAMPLE_RATE]
            clip = add_noise(clip, rng, snr)

            query = fingerprint_query(clip)
            t0 = time.monotonic()
            found = matcher.match(query)
            latencies.append(time.monotonic() - t0)

            if found is None:
                missed += 1
            elif found.track_id == track_ids[index]:
                hits += 1
                offset_errors.append(abs(found.offset_seconds - true_offset))
            else:
                wrong += 1

        rate = 100 * hits / N_TRACKS
        offset_note = ""
        if offset_errors:
            offset_note = f"  خطای جایگاه: میانه {np.median(offset_errors):.2f}s"
        mark = "✓" if wrong == 0 else "✗"
        print(f"  {mark} {label:22s} یافت {hits:2d}/{N_TRACKS} ({rate:5.1f}٪)"
              f"  نیافت {missed:2d}  غلط {wrong}{offset_note}")

        if wrong:
            failures.append(f"{label}: {wrong} تطبیق غلط")
        if clip_seconds >= 10 and rate < 80:
            failures.append(f"{label}: نرخ یافتن {rate:.0f}٪ کمتر از ۸۰٪")

    print(f"\n  میانگین زمان بازجویی: {1000 * float(np.mean(latencies)):.0f} میلی‌ثانیه")

    # ── آزمون منفی ───────────────────────────────────────────
    print("\n▸ آزمون منفی — نواهایی که در گنجینه نیستند")
    false_positives = 0
    for i in range(20):
        stranger = make_audio(20, 900_000 + i)
        clip = stranger[3 * SAMPLE_RATE : 13 * SAMPLE_RATE]
        query = fingerprint_query(clip)
        if matcher.match(query) is not None:
            false_positives += 1

    mark = "✓" if false_positives == 0 else "✗"
    print(f"  {mark} مثبت کاذب: {false_positives}/20")
    if false_positives:
        failures.append(f"{false_positives} مثبت کاذب")

    # ── برآورد مقیاس ─────────────────────────────────────────
    density = total_rows / audio_seconds
    print("\n▸ برآورد مقیاس گنجینهٔ راستین")
    for count in (1_000, 5_000, 20_000):
        rows = count * 300 * density
        print(f"  {count:>6,} نوای پنج‌دقیقه‌ای -> {rows / 1e6:>5.0f} میلیون ردیف"
              f"  (~{rows * 16 / 1e9:.1f} گیگابایت)")

    cleanup()

    print("\n" + "═" * 62)
    if failures:
        print("  ✗ آزمون ناکام ماند:")
        for failure in failures:
            print(f"     • {failure}")
        print("═" * 62)
        return 1

    print("  ✓ موتور همهٔ سنجه‌ها را گذراند")
    print("═" * 62)
    return 0


if __name__ == "__main__":
    sys.exit(main())
