"""
داوریِ آمیخته — سه نشانه، یک پاسخ.

═══════════════════════════════════════════════════════════════
  چرا آمیختن
═══════════════════════════════════════════════════════════════

سه لایه داریم و هر کدام چیز دیگری می‌بیند:

  ۱. **اثر انگشت** — «آیا این پاره از همان ضبط بریده شده؟»
     قطعی است. اگر بگوید آری، آری است.

  ۲. **خطِ آهنگ** — «آیا این همان نوحه است، در اجرایی دیگر؟»
     محتمل است. به گام و سرعت وابسته نیست.

  ۳. **رنگ آوا** — «آیا این همان مداح است؟»
     گمانه است. حتی درستش هم نوا را نمی‌یابد، تنها نزدیک می‌کند.

تا امروز هر کدام جدا کار می‌کردند و پاسخِ زیرِ آستانه دور ریخته
می‌شد. ولی **شواهدِ مستقل روی هم می‌نشینند**: اگر اثر انگشت روی
نوای ۱۲ شش عدد هم‌راستا بیابد — که به‌تنهایی بی‌معناست — و خطِ
آهنگ هم همان نوای ۱۲ را بالا بیاورد، آن دو با هم چیزی می‌گویند
که هیچ‌کدام تنها نمی‌گفتند.

این همان جایی است که آمیختن سود می‌دهد، نه بلندتر یا کوتاه‌تر
کردن آستانه‌ها.

═══════════════════════════════════════════════════════════════
  ترتیب، و چرا ترتیب مهم است
═══════════════════════════════════════════════════════════════

هرگز میانگین گرفته نمی‌شود. اثر انگشتِ نیرومند **همیشه** برنده
است، هر چه دو لایهٔ دیگر بگویند؛ چون آن یکی می‌داند و این دو
گمان می‌زنند. میانگین گرفتن یعنی گذاشتنِ گمان در برابر دانش.

پس:

  نیرومند؟           → همان ضبط، قطعی
  ضعیف + خطِ آهنگ؟   → همان نوحه، بسیار محتمل   ← تازه
  خطِ آهنگ تنها؟     → اجرای دیگر، محتمل        ← تازه
  رنگ آوا تنها؟      → گمانه، با «شاید»
  هیچ؟               → نیافتیم
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum

logger = logging.getLogger(__name__)


class Kind(str, Enum):
    """گونهٔ پاسخ — و لحنی که باید با آن گفته شود."""

    EXACT = "exact"          # همان ضبط. قطعی.
    CORROBORATED = "corro"   # دو نشانه بر یک نوا. بسیار محتمل.
    PERFORMANCE = "perf"     # همان نوحه، اجرای دیگر. محتمل.
    GUESS = "guess"          # تنها رنگ آوا. گمانه.


@dataclass(frozen=True)
class Verdict:
    """پاسخ پایانی به یک بازجویی."""

    track_id: int
    kind: Kind
    confidence: float
    offset_seconds: float = 0.0
    semitones: int = 0
    why: str = ""

    @property
    def is_certain(self) -> bool:
        return self.kind is Kind.EXACT

    @property
    def message_key(self) -> str:
        """کلید نوشتاری که با این گونه پاسخ می‌خواند."""
        return {
            Kind.EXACT: "search_found",
            Kind.CORROBORATED: "search_found_corroborated",
            Kind.PERFORMANCE: "search_found_performance",
            Kind.GUESS: "search_found_guess",
        }[self.kind]


# ── آستانه‌ها ────────────────────────────────────────────────

# اثر انگشتِ زیرِ آستانه، ولی نه تصادفی. کمتر از این، نویز است.
#
# چرا شش: هر عددِ اثر انگشت ۳۲ بیتی است و هم‌راستا بودنِ تصادفیِ
# شش عدد در یک بازهٔ زمانیِ یکسان، شدنی نیست. ولی شش عدد هم برای
# «قطعی» بس نیست — برای همین به‌تنهایی پذیرفته نمی‌شود و تنها
# آنگاه به کار می‌آید که نشانهٔ دیگری هم بر همان نوا انگشت بگذارد.
WEAK_ALIGNED_MIN = 6

# آمیختنِ اثر انگشتِ ضعیف با خطِ آهنگ، این‌قدر اطمینان می‌دهد.
# کمتر از تطبیق قطعی، بیشتر از خطِ آهنگِ تنها.
CORROBORATED_CONFIDENCE = 0.92

# کف اطمینان برای آنکه اثر انگشت «قطعی» خوانده شود.
#
# ## چرا این کف لازم شد
#
# شمردنِ عددهای هم‌راستا به‌تنهایی بس نبود. در کار راستین، نوایی
# با ۱۶ عدد هم‌راستا از آستانهٔ ۱۵ رد شد و با لحنِ «یافتم» به
# کاربر رفت — حال آنکه اطمینانش ۶٪ بود و پاسخ یکسره نادرست.
#
# ریشه‌اش این است که آستانهٔ شمارشی، درازای کلیپ را نمی‌بیند:
# ۱۶ عدد در یک کلیپ سه ثانیه‌ای پرمایه است و در کلیپ سی
# ثانیه‌ای، نویز. نرخ در ثانیه — همان که `matcher._score`
# می‌سنجد — این را می‌بیند.
#
# اندازه‌گیری روی پانزده نوا و شش سناریو: تطبیقِ راستین هرگز
# زیر ۲۵٫۵٪ نیامد، حتی در نویزِ ۰dB که نویز به بلندیِ خودِ
# صداست. پس ۰٫۱۸ زیرِ بدترین راستین می‌ماند و بالای آن ۶٪ که
# در کار راستین دیده شد.
#
# زیر این کف، تطبیق دور ریخته **نمی‌شود** — به لایهٔ گواهی
# سپرده می‌شود. اگر خطِ آهنگ هم بر همان نوا انگشت بگذارد،
# همچنان پذیرفته است؛ تنها به‌تنهایی «قطعی» خوانده نمی‌شود.
EXACT_CONFIDENCE_MIN = 0.18


def decide(
    exact,
    weak_matches,
    melody_matches,
    voice_guesses,
    text_match=None,
) -> Verdict | None:
    """
    از چهار نشانه یک پاسخ می‌سازد.

    آرگومان‌ها:
      exact          — Match نیرومند، یا None
      weak_matches   — فهرست Match های زیرِ آستانه
      melody_matches — فهرست MelodyMatch
      voice_guesses  — فهرست (شناسهٔ نوا، همانندی)
      text_match     — (شناسهٔ نوا، هم‌پوشانی) از لایهٔ متن، یا None

    بازگشتی: Verdict، یا None اگر هیچ نشانه‌ای نبود.

    ## چرا متن رأی می‌دهد و به‌تنهایی داوری نمی‌کند

    سنجش نشان داد جداییِ متنِ درست از متنِ بیگانه ۰٫۱۰ تا ۰٫۱۶
    است — بس برای «نشانه‌ای هست»، نه برای «همین است». پس متن
    نشانه‌های دیگر را **استوار می‌کند** و تنها اگر هیچ نشانهٔ
    دیگری نبود، خودش تا اندازهٔ «اجرای دیگر» حرف می‌زند.

    و این، همان کاری است که شنوندهٔ آشنا می‌کند: نه از متن تنها،
    نه از صدا تنها — از هم‌خوانیِ آن‌ها.
    """
    # ── ۱. اثر انگشتِ نیرومند: قطعی ────────────────────────
    #
    # «بی چون‌وچرا» بود و همان، نادرستی می‌ساخت: هر تطبیقی که از
    # آستانهٔ شمارشی رد می‌شد، هرچقدر هم نازک، «قطعی» خوانده
    # می‌شد. اکنون کفِ اطمینان هم باید برآورده شود.
    if exact is not None and exact.confidence >= EXACT_CONFIDENCE_MIN:
        return Verdict(
            track_id=exact.track_id,
            kind=Kind.EXACT,
            confidence=exact.confidence,
            offset_seconds=exact.offset_seconds,
            why="اثر انگشت",
        )

    # تطبیقِ نازک — آنکه از آستانهٔ شمارشی رد شد ولی کفِ اطمینان
    # را نداشت — دور ریخته نمی‌شود. اگر خطِ آهنگ هم همان را
    # بگوید، دو نشانهٔ مستقل‌اند و با هم پذیرفتنی.
    weak_matches = list(weak_matches or ())
    if exact is not None and not any(
        w.track_id == exact.track_id for w in weak_matches
    ):
        weak_matches.insert(0, exact)

    melody_by_track = {m.track_id: m for m in (melody_matches or ())}
    text_track = text_match[0] if text_match else None
    text_score = float(text_match[1]) if text_match else 0.0

    # ── ۱٫۵. متن + اثر انگشتِ ضعیف، بر یک نوا ───────────────
    #
    # متن از ضبط مستقل است و اثر انگشت از متن؛ دو نشانهٔ یکسره
    # جدا که یک چیز بگویند، از هر کدام به‌تنهایی بسیار
    # استوارترند — استوارتر حتی از خطِ آهنگ، که با اثر انگشت
    # نشانه‌های هم‌بسته‌ای دارند (هر دو از طیفِ همان ضبط).
    if text_track is not None:
        for weak in weak_matches or ():
            if weak.track_id == text_track and weak.aligned_hashes >= WEAK_ALIGNED_MIN:
                return Verdict(
                    track_id=text_track,
                    kind=Kind.CORROBORATED,
                    confidence=CORROBORATED_CONFIDENCE,
                    offset_seconds=weak.offset_seconds,
                    why=f"متن و اثر انگشتِ ضعیف ({weak.aligned_hashes} عدد)، هر دو",
                )
        # متن + خطِ آهنگ: هر دو نوحه را می‌شناسند نه ضبط را، ولی
        # از دو راهِ جدا — یکی از کلمات، یکی از آهنگ.
        melody = melody_by_track.get(text_track)
        if melody is not None:
            return Verdict(
                track_id=text_track,
                kind=Kind.CORROBORATED,
                confidence=CORROBORATED_CONFIDENCE,
                offset_seconds=melody.offset_seconds,
                semitones=melody.semitones,
                why="متن و خطِ آهنگ، هر دو",
            )

    # ── ۲. اثر انگشتِ ضعیف + خطِ آهنگ، بر یک نوا ────────────
    #
    # جانِ این ماژول همین‌جاست. دو نشانهٔ مستقل که یک چیز می‌گویند،
    # از هر کدامشان به‌تنهایی بسیار استوارترند.
    for weak in weak_matches or ():
        if weak.aligned_hashes < WEAK_ALIGNED_MIN:
            continue
        melody = melody_by_track.get(weak.track_id)
        if melody is None:
            continue
        return Verdict(
            track_id=weak.track_id,
            kind=Kind.CORROBORATED,
            confidence=CORROBORATED_CONFIDENCE,
            offset_seconds=weak.offset_seconds,
            semitones=melody.semitones,
            why=f"اثر انگشتِ ضعیف ({weak.aligned_hashes} عدد) و خطِ آهنگ، هر دو",
        )

    # ── ۳. خطِ آهنگ به‌تنهایی: اجرای دیگرِ همان نوحه ────────
    if melody_matches:
        best = melody_matches[0]
        return Verdict(
            track_id=best.track_id,
            kind=Kind.PERFORMANCE,
            confidence=best.confidence,
            offset_seconds=best.offset_seconds,
            semitones=best.semitones,
            why="خطِ آهنگ",
        )

    # ── ۳٫۵. متن به‌تنهایی: همان نوحه، شاید اجرای دیگر ─────
    #
    # کلماتِ یکسان، نوحه را می‌شناسانند نه ضبط را — درست مانند
    # خطِ آهنگ. پس همان درجه: «گمانم این است»، نه «یافتم».
    if text_track is not None:
        return Verdict(
            track_id=text_track,
            kind=Kind.PERFORMANCE,
            confidence=text_score,
            why="متنِ خوانده‌شده",
        )

    # ── ۴. رنگ آوا: تنها گمانه ─────────────────────────────
    if voice_guesses:
        track_id, score = voice_guesses[0]
        return Verdict(
            track_id=track_id,
            kind=Kind.GUESS,
            confidence=float(score),
            why="رنگ آوا",
        )

    return None
