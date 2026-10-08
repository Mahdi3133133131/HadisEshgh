"""
آزمون سخت فهم مداحی.

اجرا:  python tests/comprehension_test.py

## چرا آزمون سخت‌تری لازم بود

آزمون پیشین سه «مداح» با آوای بسیار متمایز داشت (پایهٔ ۱۱۰، ۱۶۵ و
۲۲۰ هرتز) و صوتشان پاک بود. مداحان راستین چنین نیستند: آواهاشان به
هم نزدیک است، در مجلس پژواک دارد، و صدای جواب جمعیت هم رویش
می‌نشیند.

این آزمون همان دشواری‌ها را می‌سازد:

  • **شش مداح با پایهٔ بسامدی هم‌پوشان** (۱۱۰ تا ۲۲۰، با گام‌های
    نزدیک) — نه سه صدای دور از هم
  • **پژواک مجلس** — هم‌آمیزی با دنبالهٔ فروکش
  • **جواب جمعیت** — انفجارهای نویز روی ضرب
  • **بلندی ناهمسان** — هر ضبط با بهرهٔ دیگری
  • **چهار سبک، یکی بی‌وزن** — روضه ضرب ندارد و باید از سه سبک
    وزن‌دار جدا شود

عددی که این آزمون می‌دهد، به عدد راستین نزدیک‌تر است. ولی همچنان
ساختگی است؛ جای `accuracy_real.py` را نمی‌گیرد.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from core.console import enable_utf8_console  # noqa: E402

enable_utf8_console()

import numpy as np  # noqa: E402

from core.audio.decode import SAMPLE_RATE  # noqa: E402
from core.audio.classifier import Classifier  # noqa: E402
from core.audio.features import FeatureError, extract  # noqa: E402
from core.db import database as db, features_store  # noqa: E402
from core.normalize import normalize  # noqa: E402

TEST_SOURCE = "comptest"

# شش مداح با پایهٔ بسامدی نزدیک به هم — دشوارترین حالت برای
# جداسازی آوا. ساختار هارمونیک و روشنی‌شان هم کمی فرق دارد،
# همان‌گونه که در آوای راستین.
VOICES = {
    "مداح یکم": {"f0": 112.0, "harm": (1.00, 0.62, 0.44, 0.30, 0.19, 0.12), "bright": 0.22, "rasp": 0.10},
    "مداح دوم": {"f0": 128.0, "harm": (1.00, 0.48, 0.55, 0.22, 0.31, 0.15), "bright": 0.34, "rasp": 0.22},
    "مداح سوم": {"f0": 147.0, "harm": (1.00, 0.71, 0.28, 0.41, 0.16, 0.24), "bright": 0.28, "rasp": 0.15},
    "مداح چهارم": {"f0": 168.0, "harm": (1.00, 0.35, 0.62, 0.27, 0.38, 0.11), "bright": 0.46, "rasp": 0.30},
    "مداح پنجم": {"f0": 192.0, "harm": (1.00, 0.58, 0.36, 0.49, 0.21, 0.18), "bright": 0.39, "rasp": 0.18},
    "مداح ششم": {"f0": 218.0, "harm": (1.00, 0.44, 0.51, 0.33, 0.27, 0.26), "bright": 0.52, "rasp": 0.25},
}

# روضه ضرب ندارد؛ با تمپوی صفر نشان داده می‌شود
STYLES = {"زمینه": 62.0, "واحد": 98.0, "شور": 146.0, "روضه": 0.0}


def _reverb(signal: np.ndarray, rng, seconds: float = 0.35) -> np.ndarray:
    """
    پژواک مجلس — هم‌آمیزی با دنبالهٔ فروکش نمایی.

    این همان چیزی است که در ضبط راستین، نشان آوا را می‌آلاید و
    جداسازی مداحان را دشوار می‌کند.
    """
    n = int(seconds * SAMPLE_RATE)
    tail = rng.standard_normal(n) * np.exp(-np.linspace(0, 6, n))
    tail[0] = 1.0
    wet = np.convolve(signal, tail, mode="same")
    return 0.72 * signal + 0.28 * wet / (np.max(np.abs(wet)) + 1e-9)


def _crowd(t: np.ndarray, bpm: float, rng) -> np.ndarray:
    """جواب جمعیت — انفجارهای نویز پهن‌باند روی ضرب."""
    out = np.zeros_like(t)
    if bpm <= 0:
        return out
    period = int(SAMPLE_RATE * 60.0 / bpm)
    width = int(0.28 * SAMPLE_RATE)
    for start in range(period // 2, out.size - width, period * 2):
        env = np.hanning(width)
        out[start : start + width] += env * rng.standard_normal(width) * 0.9
    return out


def synth(voice: str, style: str, seconds: float, seed: int) -> np.ndarray:
    """یک ضبط مجلسی ساختگی می‌سازد."""
    rng = np.random.default_rng(seed)
    spec = VOICES[voice]
    bpm = STYLES[style]

    t = np.linspace(0, seconds, int(seconds * SAMPLE_RATE), endpoint=False)
    sig = np.zeros_like(t)

    # ── آوا: هارمونیک‌ها با ساختار ویژهٔ هر مداح ─────────────
    f0 = spec["f0"] * rng.uniform(0.96, 1.04)
    vib = 1 + 0.022 * np.sin(2 * np.pi * rng.uniform(4.0, 6.5) * t)
    # سُر خوردن گام، مانند آواز راستین
    glide = 1 + 0.05 * np.sin(2 * np.pi * 0.13 * t + rng.uniform(0, 6))
    for k, w in enumerate(spec["harm"], start=1):
        f = f0 * k * vib * glide
        if np.max(f) > SAMPLE_RATE / 2 - 200:
            break
        sig += w * np.sin(2 * np.pi * np.cumsum(f) / SAMPLE_RATE)

    # ── خشونت صدا: نویز باریک‌باند گرد هارمونیک‌ها ───────────
    if spec["rasp"] > 0:
        noise = rng.standard_normal(t.size)
        kernel = np.hanning(64) / 32
        sig += spec["rasp"] * 0.35 * np.convolve(noise, kernel, mode="same")

    # ── روشنی ────────────────────────────────────────────────
    for _ in range(3):
        sig += spec["bright"] * 0.30 * np.sin(
            2 * np.pi * rng.uniform(1800, 5000) * t
        )

    # ── وزن سبک ──────────────────────────────────────────────
    if bpm > 0:
        beat = bpm / 60.0
        env = 0.40 + 0.60 * np.maximum(0, np.sin(2 * np.pi * beat * t)) ** 2
        sig *= env
        click = np.zeros_like(t)
        period = int(SAMPLE_RATE / beat)
        for s in range(0, click.size - 500, period):
            click[s : s + 500] += np.exp(-np.linspace(0, 9, 500)) * rng.uniform(0.6, 1.0)
        sig += 0.42 * click * rng.standard_normal(t.size) * 0.5
        sig += 0.30 * _crowd(t, bpm, rng)
    else:
        # روضه: پوشِ گفتارگونه، بی ضرب منظم
        env = np.ones_like(t) * 0.35
        pos = 0
        while pos < t.size:
            ln = int(rng.uniform(0.7, 2.4) * SAMPLE_RATE)
            gap = int(rng.uniform(0.15, 0.6) * SAMPLE_RATE)
            end = min(pos + ln, t.size)
            env[pos:end] = 0.55 + 0.45 * np.hanning(max(2, end - pos))[: end - pos]
            pos = end + gap
        sig *= env

    sig += 0.012 * rng.standard_normal(t.size)
    sig = _reverb(sig, rng)
    sig *= rng.uniform(0.45, 1.0)          # بلندی ناهمسان
    return (sig / (np.max(np.abs(sig)) + 1e-9)).astype(np.float32)


def cleanup() -> None:
    for row in db.query_all("SELECT id FROM tracks WHERE source = ?", (TEST_SOURCE,)):
        features_store.delete_for_track(int(row["id"]))
    db.execute("DELETE FROM tracks WHERE source = ?", (TEST_SOURCE,))


def main() -> int:
    db.init_db()
    features_store.ensure_table()
    cleanup()

    print("═" * 64)
    print("  آزمون سخت فهم مداحی")
    print("═" * 64)
    print(f"\n{len(VOICES)} مداح با پایهٔ هم‌پوشان · {len(STYLES)} سبک (یکی بی‌وزن)")
    print("پژواک مجلس + جواب جمعیت + بلندی ناهمسان\n")

    # ── گنجینهٔ آموزشی ──────────────────────────────────────
    print("▸ ساخت گنجینهٔ آموزشی")
    started = time.time()
    seed = 0
    built = 0
    for voice in VOICES:
        for style in STYLES:
            for _ in range(3):
                seed += 1
                audio = synth(voice, style, 45, 5000 + seed)
                try:
                    features = extract(audio)
                except FeatureError as exc:
                    print(f"  ⚠ برداشت ویژگی شکست خورد: {exc}")
                    continue
                track_id = db.add_track(
                    file_id=f"CMP_{seed}", file_unique_id=f"cmpuq_{seed}",
                    source=TEST_SOURCE, title=f"{voice} · {style}",
                    madah=voice, style=style, duration=45,
                )
                features_store.store(track_id, features)
                built += 1
    elapsed = time.time() - started
    print(f"  ✓ {built} نوا در {elapsed:.0f} ثانیه "
          f"({elapsed / max(1, built):.1f} ثانیه برای هر نوا)")

    # ── آموزش ───────────────────────────────────────────────
    print("\n▸ آموزش")
    classifier = Classifier()
    madah_count, style_count, samples = classifier.train()
    print(f"  ✓ {madah_count} مداح، {style_count} سبک، از {samples} نمونه")

    # ── سنجش روی نمونه‌های تازه ─────────────────────────────
    print("\n▸ گمانه روی ضبط‌های تازه")
    madah_hit = madah_total = 0
    style_hit = style_total = 0
    per_style_hit: dict[str, list[int]] = {s: [0, 0] for s in STYLES}
    confusions: dict[str, str] = {}

    for voice in VOICES:
        for style in STYLES:
            for _ in range(2):
                seed += 1
                audio = synth(voice, style, 45, 400000 + seed)
                try:
                    features = extract(audio)
                except FeatureError:
                    continue

                madah_total += 1
                guess = classifier.guess_madah(features)
                if guess and guess.label == normalize(voice):
                    madah_hit += 1
                elif guess:
                    confusions[f"{voice} → {guess.label}"] = ""

                style_total += 1
                per_style_hit[style][1] += 1
                sg = classifier.guess_style(features)
                if sg and sg.label == style:
                    style_hit += 1
                    per_style_hit[style][0] += 1

    madah_rate = 100 * madah_hit / madah_total if madah_total else 0
    style_rate = 100 * style_hit / style_total if style_total else 0

    print(f"  مداح: {madah_hit}/{madah_total}  ({madah_rate:.0f}٪)")
    print(f"  سبک:  {style_hit}/{style_total}  ({style_rate:.0f}٪)")
    print("\n  تفکیک سبک:")
    for style, (hit, total) in per_style_hit.items():
        pct = 100 * hit / total if total else 0
        print(f"     {style:8s} {hit:>2}/{total:<2}  ({pct:3.0f}٪)")

    if confusions:
        print("\n  درهم‌آمیختگی‌های مداح:")
        for pair in list(confusions)[:6]:
            print(f"     {pair}")

    # ── جداسازی نشان آوا ────────────────────────────────────
    print("\n▸ جداسازی نشان آوا")
    from core.audio.features import voice_similarity

    center = getattr(classifier, "_voice_center", None)
    scale = getattr(classifier, "_voice_scale", None)

    names = list(VOICES)
    ref = {n: extract(synth(n, "واحد", 45, 600000 + i)).voice
           for i, n in enumerate(names)}
    same, other = [], []
    for i, n in enumerate(names):
        again = extract(synth(n, "شور", 45, 610000 + i)).voice
        same.append(voice_similarity(ref[n], again, center, scale))
        for m in names:
            if m != n:
                other.append(voice_similarity(ref[n], ref[m], center, scale))

    gap = float(np.mean(same) - np.mean(other))
    print(f"  همان مداح:  {np.mean(same):.3f}")
    print(f"  مداح دیگر:  {np.mean(other):.3f}")
    print(f"  جداسازی:    {gap:.3f}")

    cleanup()

    print("\n" + "═" * 64)
    print(f"  مداح {madah_rate:.0f}٪ · سبک {style_rate:.0f}٪ · جداسازی {gap:.3f}")
    print("═" * 64)
    print("\n  این عددها با آوای ساختگیِ سخت‌شده‌اند. عدد راستین را")
    print("  تنها accuracy_real.py روی نواهای خودتان می‌دهد.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
