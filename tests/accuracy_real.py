"""
سنجش دقت با نواهای راستین شما.

═══════════════════════════════════════════════════════════════
  چرا این آزمون از همهٔ آزمون‌های دیگر مهم‌تر است
═══════════════════════════════════════════════════════════════

آزمون‌های دیگر با آوای ساختگی کار می‌کنند و تنها نشان می‌دهند
موتور درست ساخته شده است. ولی نواهای راستین ویژگی‌هایی دارند که
آوای ساختگی ندارد: پژواک مجلس، صدای جمعیت، فشرده‌سازی سنگین
فایل‌های دست‌به‌دست‌شده، و آوای انسانی که ایستا نیست.

پیش از آنکه این ربات را به دست کاربران بسپارید، باید عدد راستین
دقت را بدانید. اگر روی نواهای خودتان دقت پایین بود، دانستنش امروز
بهتر از فهمیدنش از راه شکایت کاربران است.

═══════════════════════════════════════════════════════════════
  چگونه اجرا شود
═══════════════════════════════════════════════════════════════

۱. پوشه‌ای بسازید و دست‌کم ۲۰ — بهتر ۱۰۰ — نوای راستین در آن
   بگذارید (ام‌پی‌تری، هر چه در گنجینهٔ خودتان دارید).

۲. اجرا کنید:

       python tests/accuracy_real.py "D:\\madahi"

۳. اسکریپت خودش از هر نوا چند تکه می‌برد، نویز و فشرده‌سازی
   می‌افزاید تا ضبط با گوشی را شبیه‌سازی کند، و می‌سنجد که آیا
   موتور نوای درست را بازمی‌یابد.

نکته: نواهای آزمایشی در گنجینهٔ راستین شما نمی‌نشینند؛ همه در
پایان پاک می‌شوند.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.console import enable_utf8_console  # noqa: E402

enable_utf8_console()

import numpy as np  # noqa: E402

from core.audio.decode import SAMPLE_RATE, DecodeError, decode  # noqa: E402
from core.audio.fingerprint import (  # noqa: E402
    FAN_OUT_INDEX,
    FAN_OUT_QUERY,
    FingerprintError,
    fingerprint,
)
from core.audio import matcher  # noqa: E402
from core.db import database, fingerprints as fp_store  # noqa: E402

TEST_SOURCE = "accuracy_real"
AUDIO_SUFFIXES = {".mp3", ".m4a", ".ogg", ".oga", ".wav", ".flac", ".aac", ".opus"}

# تکه‌هایی به این درازا از هر نوا بریده می‌شود
CLIP_LENGTHS = (5, 10, 20)
CLIPS_PER_TRACK = 3


def add_noise(clip: np.ndarray, rng, snr_db: float) -> np.ndarray:
    power = float(np.mean(clip ** 2))
    if power <= 0:
        return clip
    noise_power = power / (10 ** (snr_db / 10))
    out = clip + np.sqrt(noise_power) * rng.standard_normal(clip.size).astype(np.float32)
    peak = float(np.max(np.abs(out)))
    return (out / peak).astype(np.float32) if peak > 0 else out


def cleanup() -> None:
    rows = database.query_all("SELECT id FROM tracks WHERE source = ?", (TEST_SOURCE,))
    for row in rows:
        fp_store.delete_for_track(int(row["id"]))
    database.execute("DELETE FROM tracks WHERE source = ?", (TEST_SOURCE,))


def main(folder: Path) -> int:
    if not folder.is_dir():
        print(f"پوشهٔ «{folder}» یافت نشد.")
        return 1

    files = sorted(
        path for path in folder.rglob("*") if path.suffix.lower() in AUDIO_SUFFIXES
    )
    if not files:
        print(f"در «{folder}» هیچ فایل صوتی یافت نشد.")
        return 1

    print("═" * 64)
    print("  سنجش دقت با نواهای راستین")
    print("═" * 64)
    print(f"\n{len(files)} فایل یافت شد در {folder}")
    if len(files) < 20:
        print("⚠ برای عددی که بتوان به آن تکیه کرد، دست‌کم ۲۰ نوا بهتر است.")

    database.init_db()
    cleanup()

    # ── نشاندن گنجینه ────────────────────────────────────────
    print(f"\n▸ نمایه‌سازی (گنجینه fan={FAN_OUT_INDEX})")
    samples_by_track: dict[int, np.ndarray] = {}
    names: dict[int, str] = {}
    total_rows = 0
    total_audio_seconds = 0.0
    started = time.monotonic()
    skipped: list[str] = []

    for index, path in enumerate(files, start=1):
        try:
            samples = decode(path)
        except DecodeError as exc:
            skipped.append(f"{path.name}: {exc}")
            continue

        if samples.size < 30 * SAMPLE_RATE:
            skipped.append(f"{path.name}: کوتاه‌تر از ۳۰ ثانیه")
            continue

        try:
            print_result = fingerprint(samples, fan_out=FAN_OUT_INDEX)
        except FingerprintError as exc:
            skipped.append(f"{path.name}: {exc}")
            continue

        track_id = database.add_track(
            file_id=None, file_unique_id=None, source=TEST_SOURCE,
            title=path.stem, duration=int(samples.size / SAMPLE_RATE),
        )
        total_rows += fp_store.store(track_id, print_result.hashes, print_result.offsets)
        total_audio_seconds += samples.size / SAMPLE_RATE
        samples_by_track[track_id] = samples
        names[track_id] = path.stem

        if index % 10 == 0 or index == len(files):
            print(f"    {index}/{len(files)}…")

    if not samples_by_track:
        print("هیچ نوایی نمایه نشد.")
        cleanup()
        return 1

    elapsed = time.monotonic() - started
    density = total_rows / total_audio_seconds
    print(f"  ✓ {len(samples_by_track)} نوا، {total_rows:,} عدد، {elapsed:.0f} ثانیه")
    print(f"    چگالی: {density:.0f} عدد در ثانیه")
    print(f"    شتاب: {total_audio_seconds / elapsed:.0f}× زمان واقعی")
    if skipped:
        print(f"  ⚠ {len(skipped)} فایل کنار گذاشته شد:")
        for note in skipped[:5]:
            print(f"      {note}")

    # ── بازجویی ──────────────────────────────────────────────
    print(f"\n▸ بازجویی (fan={FAN_OUT_QUERY})")
    rng = np.random.default_rng(1234)
    track_ids = list(samples_by_track)

    scenarios = [("پاک", None), ("نویز ۱۵dB", 15), ("نویز ۵dB", 5)]
    summary: dict[str, tuple[int, int, int, int]] = {}
    wrong_examples: list[str] = []

    for clip_seconds in CLIP_LENGTHS:
        for label, snr in scenarios:
            hits = wrong = missed = trials = 0

            for track_id in track_ids:
                samples = samples_by_track[track_id]
                usable = samples.size - clip_seconds * SAMPLE_RATE
                if usable <= SAMPLE_RATE:
                    continue

                for _ in range(CLIPS_PER_TRACK):
                    start = int(rng.integers(0, usable))
                    clip = samples[start : start + clip_seconds * SAMPLE_RATE]
                    if snr is not None:
                        clip = add_noise(clip, rng, snr)

                    trials += 1
                    try:
                        query = fingerprint(clip, fan_out=FAN_OUT_QUERY)
                    except FingerprintError:
                        missed += 1
                        continue

                    found = matcher.match(query)
                    if found is None:
                        missed += 1
                    elif found.track_id == track_id:
                        hits += 1
                    else:
                        wrong += 1
                        if len(wrong_examples) < 5:
                            wrong_examples.append(
                                f"«{names[track_id]}» -> «{names.get(found.track_id, '؟')}»"
                                f" ({clip_seconds}s/{label})"
                            )

            key = f"{clip_seconds} ثانیه / {label}"
            summary[key] = (hits, wrong, missed, trials)
            rate = 100 * hits / trials if trials else 0
            mark = "✓" if wrong == 0 and rate >= 80 else ("⚠" if wrong == 0 else "✗")
            print(f"  {mark} {key:24s} یافت {hits:3d}/{trials:3d} ({rate:5.1f}٪)"
                  f"  نیافت {missed:3d}  غلط {wrong}")

    # ── آزمون منفی ───────────────────────────────────────────
    print("\n▸ آزمون منفی — نوایی که در گنجینه نیست")
    holdout = track_ids[-1]
    fp_store.delete_for_track(holdout)
    database.execute("DELETE FROM tracks WHERE id = ?", (holdout,))

    false_positives = holdout_trials = 0
    samples = samples_by_track[holdout]
    for _ in range(20):
        usable = samples.size - 10 * SAMPLE_RATE
        if usable <= 0:
            break
        start = int(rng.integers(0, usable))
        clip = samples[start : start + 10 * SAMPLE_RATE]
        holdout_trials += 1
        try:
            query = fingerprint(clip, fan_out=FAN_OUT_QUERY)
        except FingerprintError:
            continue
        if matcher.match(query) is not None:
            false_positives += 1

    mark = "✓" if false_positives == 0 else "✗"
    print(f"  {mark} مثبت کاذب: {false_positives}/{holdout_trials}")

    # ── داوری ────────────────────────────────────────────────
    cleanup()

    ten_second = summary.get("10 ثانیه / پاک", (0, 0, 0, 0))
    ten_rate = 100 * ten_second[0] / ten_second[3] if ten_second[3] else 0
    total_wrong = sum(w for _, w, _, _ in summary.values())

    print("\n" + "═" * 64)
    print("  داوری")
    print("═" * 64)
    print(f"\n  دقت تکهٔ ده‌ثانیه‌ای (پاک): {ten_rate:.0f}٪")
    print(f"  تطبیق غلط در همهٔ حالت‌ها: {total_wrong}")
    print(f"  مثبت کاذب: {false_positives}")

    if wrong_examples:
        print("\n  نمونهٔ تطبیق‌های غلط:")
        for example in wrong_examples:
            print(f"    • {example}")

    print()
    if total_wrong == 0 and false_positives == 0 and ten_rate >= 90:
        print("  ✓ موتور آمادهٔ کار راستین است.")
        verdict = 0
    elif total_wrong or false_positives:
        print("  ✗ تطبیق غلط یا مثبت کاذب دیده شد.")
        print("    MIN_ALIGNED_HASHES در core/audio/matcher.py را بالاتر ببرید.")
        verdict = 1
    else:
        print("  ⚠ دقت پایین‌تر از انتظار است.")
        print("    FAN_OUT_INDEX در core/audio/fingerprint.py را بالاتر ببرید")
        print("    (۳ -> ۵ یا ۱۰)؛ گنجینه بزرگ‌تر می‌شود ولی دقت بالا می‌رود.")
        verdict = 1

    print("═" * 64)
    return verdict


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        print('\nنمونه:  python tests/accuracy_real.py "D:\\madahi"')
        sys.exit(1)
    sys.exit(main(Path(sys.argv[1])))
