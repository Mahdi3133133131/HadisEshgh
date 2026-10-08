"""
آزمون لایهٔ خطِ آهنگ — یافتنِ اجرای دیگرِ همان نوحه.

اجرا:  python tests/melody_test.py

═══════════════════════════════════════════════════════════════
  این آزمون چه چیزی را می‌سنجد
═══════════════════════════════════════════════════════════════

تا پیش از این لایه، مستند پروژه می‌گفت موتور «نمی‌تواند اجرای
دیگری از همان نوا را بیابد» و آن را کاستیِ ذاتیِ روش می‌خواند.
درست هم بود: اثر انگشت تنها همان ضبط را می‌یابد.

این آزمون می‌سنجد که آیا لایهٔ تازه همان شکاف را می‌بندد —
و مهم‌تر، آیا **بی‌جا** نمی‌بندد: نوحهٔ دیگری را «همان» نمی‌شمارد.

هر اجرا در چهار چیز با نسخهٔ گنجینه فرق دارد:
  • گام (تا هفت نیم‌پرده)
  • سرعت (تا ۲۵٪ تندتر یا کندتر)
  • رنگ آوا (هارمونیک‌های دیگر — خوانندهٔ دیگر)
  • نویز و پژواک (مجلس، جمعیت)
"""

import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from core.console import enable_utf8_console  # noqa: E402

enable_utf8_console()

import numpy as np  # noqa: E402

from core.audio import melody, verdict  # noqa: E402
from core.audio.decode import SAMPLE_RATE  # noqa: E402

# شش نوحه با خطِ آهنگِ جدا از هم
NOOHE = {
    "الف": [0, 2, 3, 5, 3, 2, 0, -2, 0, 3, 5, 7, 5, 3, 2, 0],
    "ب": [7, 5, 3, 2, 0, 2, 3, 5, 7, 8, 7, 5, 3, 2, 0, -2],
    "پ": [0, 0, 3, 3, 5, 5, 7, 5, 3, 2, 0, 2, 3, 2, 0, 0],
    "ت": [5, 7, 8, 7, 5, 3, 5, 7, 8, 10, 8, 7, 5, 3, 2, 0],
    "ث": [-2, 0, 2, 3, 2, 0, -2, -4, -2, 0, 3, 2, 0, -2, 0, 2],
    "ج": [3, 5, 7, 8, 10, 8, 7, 5, 3, 2, 0, 2, 3, 5, 3, 2],
}

# چهار «اجرا»ی گوناگون از هر نوحه
PERFORMANCES = (
    ("گام +۵، ۱۵٪ تندتر، صدای بازتر", dict(shift=5, timbre=2.2, noise=0.15, rate=1.15)),
    ("گام −۳، ۱۲٪ کندتر، صدای بسته‌تر", dict(shift=-3, timbre=0.6, noise=0.20, rate=0.88)),
    ("گام +۷، اندکی تندتر، پژواک", dict(shift=7, timbre=1.8, noise=0.10, rate=1.05, reverb=True)),
    ("گام −۵، ۲۰٪ کندتر، جمعیت", dict(shift=-5, timbre=1.3, noise=0.25, rate=0.80, reverb=True)),
)


def render(notes, spn=1.1, shift=0, timbre=1.0, noise=0.0, rate=1.0,
           reverb=False, seed=0):
    """آهنگی می‌سازد از دنبالهٔ نت‌ها، با رنگ آوا و شرایط دلخواه."""
    rng = np.random.default_rng(seed)
    pieces = []
    for note in notes:
        freq = 220.0 * (2 ** ((note + shift) / 12))
        duration = spn / rate
        t = np.arange(int(SAMPLE_RATE * duration)) / SAMPLE_RATE
        wave = np.sin(2 * np.pi * freq * t)
        for harmonic, amp in ((2, 0.5 * timbre), (3, 0.3 / timbre), (4, 0.2 * timbre)):
            wave = wave + amp * np.sin(2 * np.pi * freq * harmonic * t)
        wave *= np.hanning(wave.size) ** 0.3
        pieces.append(wave)

    audio = np.concatenate(pieces).astype(np.float32)
    if reverb:
        # پژواک مجلس: چند بازتاب میرا
        tail = np.zeros_like(audio)
        for delay_ms, gain in ((70, 0.35), (150, 0.22), (260, 0.12)):
            shift_n = int(SAMPLE_RATE * delay_ms / 1000)
            tail[shift_n:] += gain * audio[: audio.size - shift_n]
        audio = audio + tail
    if noise:
        audio = audio + noise * rng.standard_normal(audio.size).astype(np.float32)
    return audio


def main() -> int:
    problems: list[str] = []
    print("═" * 62)
    print("  لایهٔ خطِ آهنگ — یافتنِ اجرای دیگرِ همان نوحه")
    print("═" * 62)

    # ── ۱ — نمایه ───────────────────────────────────────────
    print(f"\n▸ نمایهٔ گنجینه ({len(NOOHE)} نوحه)")
    started = time.monotonic()
    library: dict[str, np.ndarray] = {}
    for name, notes in NOOHE.items():
        library[name] = melody.signature(render(notes * 2, seed=1))
    elapsed = time.monotonic() - started
    size = sum(len(melody.to_bytes(sig)) for sig in library.values())
    print(f"  ✓ {len(library)} نشان در {elapsed:.1f} ثانیه "
          f"({elapsed / len(library):.2f} ثانیه هر کدام)")
    print(f"  ✓ اندازه: {size / len(library):.0f} بایت برای هر نوا "
          f"(≈ {size / len(library) * 5000 / 1e6:.0f} مگابایت برای ۵۰۰۰ نوا)")

    # ── ۲ — بازشناسی ────────────────────────────────────────
    print(f"\n▸ بازشناسی: {len(NOOHE)} نوحه × {len(PERFORMANCES)} اجرا")
    corpus = list(enumerate(library.values()))
    index_to_name = {i: name for i, name in enumerate(library)}

    same_scores, other_scores = [], []
    hits = misses = wrong = 0
    started = time.monotonic()

    for name, notes in NOOHE.items():
        for seed, (label, kwargs) in enumerate(PERFORMANCES):
            query = melody.signature(render(notes * 2, seed=200 + seed, **kwargs))

            for index, target in corpus:
                score, _, _ = melody.compare(query, target)
                (same_scores if index_to_name[index] == name else other_scores).append(score)

            found = melody.search(query, corpus, limit=1)
            if not found:
                misses += 1
            elif index_to_name[found[0].track_id] == name:
                hits += 1
            else:
                wrong += 1

    total = len(NOOHE) * len(PERFORMANCES)
    elapsed = time.monotonic() - started
    print(f"  یافت شد   : {hits}/{total}")
    print(f"  نیافت      : {misses}/{total}   <i>(سکوت، نه خطا)</i>".replace("<i>", "").replace("</i>", ""))
    print(f"  نادرست     : {wrong}/{total}")
    print(f"  زمان هر بازجویی: {elapsed / total * 1000:.0f} میلی‌ثانیه "
          f"(روی {len(corpus)} نوا)")

    if wrong:
        problems.append(f"{wrong} بار نوحهٔ نادرست را «همان» شمرد")
    else:
        print("  ✓ هرگز نوحهٔ نادرستی را «همان» نشمرد")

    if hits < total * 0.75:
        problems.append(f"تنها {hits} از {total} اجرا یافته شد")
    else:
        print(f"  ✓ {hits} از {total} اجرای دیگر یافته شد")

    # ── ۳ — توزیع ───────────────────────────────────────────
    print("\n▸ توزیع هم‌بستگی")
    lo_same, hi_other = min(same_scores), max(other_scores)
    print(f"  همان نوحه : میانه {statistics.median(same_scores):.3f} · "
          f"کمینه {lo_same:.3f}")
    print(f"  نوحهٔ دیگر: میانه {statistics.median(other_scores):.3f} · "
          f"بیشینه {hi_other:.3f}")
    print(f"  شکاف      : {lo_same - hi_other:+.3f}   "
          f"(آستانه {melody.MIN_SIMILARITY})")

    if lo_same <= hi_other:
        problems.append(
            f"توزیع‌ها روی هم افتادند: کمینهٔ درست {lo_same:.3f} ≤ "
            f"بیشینهٔ نادرست {hi_other:.3f} — هیچ آستانه‌ای هر دو را درست نمی‌کند"
        )
    else:
        print("  ✓ توزیع‌ها جدایند؛ آستانه معنا دارد")

    if not (hi_other < melody.MIN_SIMILARITY < lo_same):
        problems.append(
            f"آستانهٔ {melody.MIN_SIMILARITY} میان دو توزیع ({hi_other:.3f} و "
            f"{lo_same:.3f}) نیست"
        )
    else:
        print(f"  ✓ آستانه درست میان دو توزیع نشسته")

    # ── ۴ — داوریِ آمیخته ──────────────────────────────────
    print("\n▸ داوریِ آمیخته: ترتیبِ نشانه‌ها")

    class FakeExact:
        track_id, confidence, offset_seconds = 7, 0.95, 3.0

    class FakeWeak:
        def __init__(self, tid, aligned):
            self.track_id, self.aligned_hashes = tid, aligned
            self.offset_seconds = 1.0

    class FakeMelody:
        def __init__(self, tid, sim=0.8):
            self.track_id, self.similarity, self.semitones = tid, sim, 3
            self.offset_seconds = 2.0
            self.confidence = 0.6

    cases = [
        ("اثر انگشتِ نیرومند بر همه چیره است",
         (FakeExact(), [FakeWeak(9, 10)], [FakeMelody(9)], [(9, 0.9)]),
         verdict.Kind.EXACT, 7),
        ("اثر انگشتِ ضعیف + خطِ آهنگ بر یک نوا",
         (None, [FakeWeak(4, 8)], [FakeMelody(4)], []),
         verdict.Kind.CORROBORATED, 4),
        ("اثر انگشتِ ضعیف بر نوای دیگر — آمیخته نمی‌شود",
         (None, [FakeWeak(4, 8)], [FakeMelody(5)], []),
         verdict.Kind.PERFORMANCE, 5),
        ("خطِ آهنگ به‌تنهایی",
         (None, [], [FakeMelody(6)], []),
         verdict.Kind.PERFORMANCE, 6),
        ("رنگ آوا به‌تنهایی",
         (None, [], [], [(8, 0.7)]),
         verdict.Kind.GUESS, 8),
        ("هیچ نشانه‌ای",
         (None, [], [], []),
         None, None),
    ]
    for label, args, want_kind, want_track in cases:
        got = verdict.decide(*args)
        kind = got.kind if got else None
        track = got.track_id if got else None
        ok = kind == want_kind and track == want_track
        print(f"  {'✓' if ok else '✗'} {label} → "
              f"{kind.value if kind else 'هیچ'}")
        if not ok:
            problems.append(
                f"داوری «{label}»: {kind}/{track} به جای {want_kind}/{want_track}"
            )

    # ── داوری ───────────────────────────────────────────────
    print("\n" + "═" * 62)
    if problems:
        print("  ✗ لایهٔ خطِ آهنگ ایراد دارد")
        print("═" * 62)
        for problem in problems:
            print(f"\n  • {problem}")
        return 1
    print(f"  ✓ {hits}/{total} اجرای دیگر یافته شد · صفر نادرست")
    print("═" * 62)
    print("\n  عددها با آوای ساختگی‌اند. نوحهٔ راستین خطِ آهنگِ")
    print("  پیچیده‌تری دارد — هم آسان‌تر برای جدا کردن، هم")
    print("  ناپایدارتر میان دو اجرا.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
