"""
گمانه‌زنی سبک و مداح.

═══════════════════════════════════════════════════════════════
  این لایه چیست و چه نیست
═══════════════════════════════════════════════════════════════

**نیست:** جایگزین اثر انگشت. یافتن نوا کار fingerprint.py است و
دقتش نزدیک به بی‌خطاست.

**هست:** لایه‌ای که وقتی اثر انگشت چیزی نیافت، به جای دست خالی،
گمانه‌ای پیش می‌گذارد: «شاید این‌ها را می‌خواستید» — بر پایهٔ
همانندی آوای مداح و نزدیکی سبک.

هرگز نباید ادعای قطعیت کند. پیامش همیشه با «شاید» می‌آید.

═══════════════════════════════════════════════════════════════
  چگونه یاد می‌گیرد
═══════════════════════════════════════════════════════════════

از همان روز نخست، هنگام پیشکش نوا، از کاربر نام مداح و سبک
پرسیده شد. آن برچسب‌ها اکنون دیتاست‌اند.

**سه گام:**

۱. **هنجارسازی** — کم کردن میانگین گنجینه و بخش بر انحراف معیار.
   بی این، مؤلفهٔ مشترک همهٔ آواها بر همانندی چیره می‌شود.

۲. **تصویر جداساز (LDA)** — بزرگ‌ترین اهرم دقت با دادهٔ کم.
   این لایه `scikit-learn` می‌خواهد؛ در نبودش خاموش می‌ماند و
   `/features` علتش را می‌گوید.
   بردار ۴۲ بُعدی آوا (`features.VOICE_DIM`)، ابعادی دارد که میان ضبط‌های *یک* مداح هم
   پراکنده‌اند (پژواک اتاق، بلندی، حال آن شب). LDA راستایی می‌یابد
   که پراکندگی *میان* مداحان را بیشینه و پراکندگی *درون* هر مداح
   را کمینه کند — یعنی درست همان چیزی که می‌خواهیم.

۳. **نزدیک‌ترین مرکز در فضای تصویرشده** — پس از تصویر، مرکزها
   به‌روشنی از هم جدا می‌شوند و شمردن ساده بس است.

اگر داده برای LDA بس نباشد (کمتر از دو مداح یا نمونهٔ اندک)،
خودبه‌خود به همان همانندی کسینوسی هنجارشده بازمی‌گردد. هیچ‌گاه
نمی‌شکند؛ تنها کم‌دقت‌تر می‌شود.

**چرا نه شبکهٔ عصبی:** با ده نمونه در هر مداح کار می‌کند (شبکه
صدها می‌خواهد)، آموزشش ثانیه‌ای است، و می‌توان دید چرا چنین گفته.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import numpy as np

from core.audio.features import Features, voice_similarity

logger = logging.getLogger(__name__)

# کمترین نمونه برای آنکه یک برچسب به کار آموزش بیاید
MIN_SAMPLES_PER_LABEL = 3

# کمترین شرط برای آنکه تصویر جداساز ساخته شود
MIN_CLASSES_FOR_LDA = 2
MIN_SAMPLES_FOR_LDA = 8

# زیر این همانندی، گمانه‌ای گفته نمی‌شود
MIN_VOICE_CONFIDENCE = 0.62
MIN_STYLE_CONFIDENCE = 0.45

# در فضای تصویرشده، اطمینان از حاشیهٔ نسبی ساخته می‌شود
MIN_PROJECTED_MARGIN = 0.55

# ── دو نگهبانِ گمانه‌زنی ─────────────────────────────────────
#
# کمتر از این شمار نوا در گنجینه، هیچ گمانه‌ای زده نمی‌شود.
# دلیلش آمار است، نه احتیاط: هنجارسازیِ آوا میانگین و انحراف
# معیارِ گنجینه را می‌خواهد، و میانگینِ چهار بردار، میانگین نیست.
# با گنجینهٔ خُرد، «نزدیک‌ترین» بی‌معناست — نزدیک‌ترینِ چهار چیزِ
# نامربوط، باز هم نامربوط است.
MIN_CORPUS_FOR_GUESS = 20

# نامزد باید از همانندیِ **معمولِ** گنجینه این‌قدر سر باشد.
# آستانهٔ مطلق به‌تنهایی بس نیست: اگر هنجارسازی نباشد یا سست باشد،
# همانندی همهٔ جفت‌ها میان ۰٫۹۷ و ۰٫۹۹ می‌افتد و هر آستانهٔ ثابتی
# از هیچ‌کس جلو نمی‌گیرد. پرسش درست این است: «آیا این نوا نسبت به
# نوای تصادفی، **به‌طور نامعمول** نزدیک است؟»
MIN_MARGIN_OVER_MEDIAN = 0.15


@dataclass(frozen=True)
class Guess:
    """یک گمانه، با اندازهٔ اطمینانش."""

    label: str
    confidence: float

    def __str__(self) -> str:
        return f"{self.label} ({self.confidence:.0%})"


class Classifier:
    """
    گمانه‌زن سبک و مداح.

    درون حافظه نگه داشته می‌شود و با فرمان گردانندگان از نو
    آموزش می‌بیند؛ آموزشش چند ثانیه بیش نمی‌برد.
    """

    def __init__(self) -> None:
        self._voice_centroids: dict[str, np.ndarray] = {}
        self._style_centroids: dict[str, np.ndarray] = {}
        self._style_scale: np.ndarray | None = None
        self._voice_center: np.ndarray | None = None
        self._voice_scale: np.ndarray | None = None

        # تصویر جداساز و مرکزهای تصویرشده.
        #
        # `_projection` یک برآوردگرِ sklearn است (نه آرایه) و تنها
        # از راه `.transform` به کار می‌رود؛ پیش‌تر `np.ndarray`
        # اعلام شده بود که هرگز درست نبود.
        self._projection = None
        self._projected_centroids: dict[str, np.ndarray] = {}

        self._trained = False
        self.madah_count = 0
        self.style_count = 0
        self.sample_count = 0
        self.uses_projection = False
        # چرا تصویر جداساز خاموش است — برای پنل گردانندگان.
        self.projection_reason = "هنوز آموزشی نرفته"

    # ── آموزش ────────────────────────────────────────────────
    def train(self) -> tuple[int, int, int]:
        """
        از نواهای برچسب‌خوردهٔ گنجینه آموزش می‌بیند.

        بازگشتی: (شمار مداح، شمار سبک، شمار نمونه)
        """
        from core.db import features_store

        rows = features_store.labelled()
        if not rows:
            logger.info("هیچ نوای برچسب‌خورده‌ای برای آموزش نیست.")
            self._reset()
            return 0, 0, 0

        by_madah: dict[str, list[np.ndarray]] = {}
        by_style: dict[str, list[np.ndarray]] = {}
        all_voice: list[np.ndarray] = []

        for row in rows:
            raw = row["features"]
            # بردارهای ساختهٔ نسخهٔ کهنه، بُعدشان فرق دارد و
            # آمیختنشان با تازه‌ها آموزش را خراب می‌کند.
            if not Features.is_current(raw):
                continue
            style_vector, voice_vector = Features.from_bytes(raw)
            all_voice.append(voice_vector)
            if row["madah_norm"]:
                by_madah.setdefault(row["madah_norm"], []).append(voice_vector)
            if row["style"]:
                by_style.setdefault(row["style"], []).append(style_vector)

        usable = len(all_voice)
        if usable < len(rows):
            logger.info(
                "%s نوا با ساختار کهنهٔ ویژگی نادیده گرفته شد؛ /reindex آن‌ها را نو می‌کند.",
                len(rows) - usable,
            )
        if not all_voice:
            self._reset()
            return 0, 0, 0

        # ── هنجارسازی آوا ───────────────────────────────────
        stacked = np.vstack(all_voice)
        self._voice_center = stacked.mean(axis=0)
        voice_std = stacked.std(axis=0)
        voice_std[voice_std < 1e-9] = 1.0
        self._voice_scale = voice_std

        self._voice_centroids = {
            label: np.mean(vectors, axis=0)
            for label, vectors in by_madah.items()
            if len(vectors) >= MIN_SAMPLES_PER_LABEL
        }

        # ── تصویر جداساز ────────────────────────────────────
        self._fit_projection(by_madah)

        # ── سبک ─────────────────────────────────────────────
        #
        # پیش از هر چیز، حالتِ آموزشِ پیشین پاک می‌شود.
        #
        # ## باگی که این دو سطر می‌بندد
        #
        # اگر در آموزشِ تازه هیچ برچسب سبکی نبود، شاخهٔ زیر رد
        # می‌شد و `_style_centroids` از آموزشِ **پیشین** سرِ جایش
        # می‌ماند — در حالی که `style_count` صفر می‌شد. یعنی
        # `/features` می‌گفت «۰ سبک» و `guess_style` همچنان با
        # مرکزهای مرده گمانه می‌زد.
        self._style_centroids = {}
        self._style_scale = None

        all_style = [v for vs in by_style.values() for v in vs]
        if all_style:
            style_stack = np.vstack(all_style)
            scale = style_stack.std(axis=0)
            scale[scale < 1e-6] = 1.0
            self._style_scale = scale
            self._style_centroids = {
                label: np.mean([v / scale for v in vectors], axis=0)
                for label, vectors in by_style.items()
                if len(vectors) >= MIN_SAMPLES_PER_LABEL
            }

        self.madah_count = len(self._voice_centroids)
        self.style_count = len(self._style_centroids)
        self.sample_count = usable
        self._trained = bool(self._voice_centroids or self._style_centroids)

        logger.info(
            "گمانه‌زن آموزش دید: %s مداح، %s سبک، از %s نمونه%s.",
            self.madah_count, self.style_count, self.sample_count,
            "، با تصویر جداساز" if self.uses_projection else "",
        )
        return self.madah_count, self.style_count, self.sample_count

    def _reset(self) -> None:
        """
        همه‌چیز را به حالتِ نیاموخته برمی‌گرداند.

        آمارِ هنجارسازی هم پاک می‌شود، و همین تازه است: پیش‌تر
        `_voice_center` و `_voice_scale` دست‌نخورده می‌ماندند، پس
        `is_normalized` پس از پاک‌سازی همچنان «آری» می‌گفت و
        گمانه‌زنی به میانگین و انحرافِ گنجینه‌ای تکیه می‌کرد که
        دیگر وجود نداشت.
        """
        self._voice_centroids.clear()
        self._style_centroids.clear()
        self._projected_centroids.clear()
        self._projection = None
        self._voice_center = None
        self._voice_scale = None
        self._style_scale = None
        self._trained = False
        self.uses_projection = False
        self.projection_reason = "گنجینه برچسبی ندارد"
        self.madah_count = self.style_count = self.sample_count = 0

    def _normalize_voice(self, vector: np.ndarray) -> np.ndarray:
        out = vector.astype(np.float64)
        if self._voice_center is not None:
            out = out - self._voice_center
        if self._voice_scale is not None:
            out = out / self._voice_scale
        return out

    def _fit_projection(self, by_madah: dict[str, list[np.ndarray]]) -> None:
        """
        تصویری می‌سازد که مداحان را از هم دور و ضبط‌های یک مداح را
        به هم نزدیک کند.

        اگر داده بس نباشد یا sklearn نباشد، خاموش می‌ماند و
        گمانه‌زنی به همان روش کسینوسی پیش می‌رود.
        """
        self._projection = None
        self._projected_centroids = {}
        self.uses_projection = False

        usable = {k: v for k, v in by_madah.items() if len(v) >= MIN_SAMPLES_PER_LABEL}
        total = sum(len(v) for v in usable.values())
        if len(usable) < MIN_CLASSES_FOR_LDA or total < MIN_SAMPLES_FOR_LDA:
            self.projection_reason = (
                f"داده بس نیست — {len(usable)} مداح و {total} نمونه؛ "
                f"دست‌کم {MIN_CLASSES_FOR_LDA} مداح و {MIN_SAMPLES_FOR_LDA} نمونه بایسته است"
            )
            return

        try:
            from sklearn.discriminant_analysis import LinearDiscriminantAnalysis
        except ImportError:
            # ## چرا این علت باید دیده شود
            #
            # پیش‌تر تنها یک `logger.debug` بود و پنل `/features`
            # خاموشیِ این لایه را همیشه به «داده کم است» نسبت
            # می‌داد. ولی روی نصبِ تمیز، علت چیز دیگری بود:
            # `scikit-learn` در requirements نبود، پس بزرگ‌ترین
            # اهرمِ دقتِ این ماژول **هرگز** روشن نمی‌شد و هیچ‌کس
            # نمی‌فهمید چرا.
            self.projection_reason = (
                "scikit-learn نصب نیست — pip install -r requirements.txt"
            )
            logger.info(
                "sklearn نیست؛ تصویر جداساز ساخته نشد و گمانه‌زن به روش "
                "کسینوسیِ کم‌دقت‌تر بازمی‌گردد."
            )
            return

        features: list[np.ndarray] = []
        labels: list[str] = []
        for label, vectors in usable.items():
            for vector in vectors:
                features.append(self._normalize_voice(vector))
                labels.append(label)

        matrix = np.vstack(features)
        try:
            # solver='eigen' با shrinkage برای نمونهٔ کم ساخته شده:
            # ماتریس کوواریانس درون‌کلاسی با این شمار نمونه
            # تک‌شکل می‌شود و بی shrinkage وارون‌ناپذیر است.
            lda = LinearDiscriminantAnalysis(
                solver="eigen", shrinkage="auto",
                n_components=min(len(usable) - 1, matrix.shape[1]),
            )
            lda.fit(matrix, labels)
            projected = lda.transform(matrix)
        except Exception as exc:  # noqa: BLE001
            self.projection_reason = f"ساختِ تصویر شکست خورد: {exc}"
            logger.debug("ساخت تصویر جداساز شکست خورد: %s", exc)
            return

        self._projection = lda

        # مرکزها با یک گذر ساخته می‌شوند. پیش‌تر برای **هر** برچسب
        # کلِ فهرست برچسب‌ها پیموده می‌شد — و نامِ متغیرِ حلقه `l`
        # بود که از `1` بازشناختنی نیست.
        rows_of: dict[str, list[int]] = {}
        for index, label in enumerate(labels):
            rows_of.setdefault(label, []).append(index)
        self._projected_centroids = {
            label: projected[indices].mean(axis=0)
            for label, indices in rows_of.items()
        }

        self.uses_projection = True
        self.projection_reason = ""

    @property
    def is_trained(self) -> bool:
        return self._trained

    @property
    def is_normalized(self) -> bool:
        """
        آیا هنجارسازی آوا ساخته شده است.

        بی این، voice_similarity به کسینوسِ خام روی بردارهای
        هنجارنشده فرو می‌افتد و همانندی همه‌چیز میان ۰٫۹۷ و ۰٫۹۹
        می‌نشیند. آنگاه هر آستانه‌ای بی‌اثر است و گمانه‌زن هر چه
        در گنجینه هست را «همانند» می‌شمارد.
        """
        return self._voice_center is not None and self._voice_scale is not None

    def _corpus_is_big_enough(self) -> bool:
        """آیا گنجینه آن‌قدر هست که گمانه‌زدن معنا داشته باشد."""
        return self.sample_count >= MIN_CORPUS_FOR_GUESS

    # ── گمانه ────────────────────────────────────────────────
    def guess_madah(self, features: Features) -> Guess | None:
        """نزدیک‌ترین مداح، یا None اگر اطمینان بسنده نبود."""
        if not self._voice_centroids:
            return None
        if not (self.is_normalized and self._corpus_is_big_enough()):
            return None

        if self.uses_projection and self._projection is not None:
            return self._guess_projected(features)

        scored = [
            (
                label,
                voice_similarity(
                    features.voice, centroid, self._voice_center, self._voice_scale
                ),
            )
            for label, centroid in self._voice_centroids.items()
        ]
        scored.sort(key=lambda item: item[1], reverse=True)
        label, score = scored[0]
        if score < MIN_VOICE_CONFIDENCE:
            return None
        return Guess(label=label, confidence=score)

    def _guess_projected(self, features: Features) -> Guess | None:
        """
        گمانه در فضای تصویرشده.

        اطمینان از **حاشیه** ساخته می‌شود نه از فاصلهٔ خام: اگر
        نزدیک‌ترین و دومین مرکز هم‌فاصله باشند، گمانه سست است هرچند
        هر دو نزدیک باشند.
        """
        try:
            point = self._projection.transform(
                self._normalize_voice(features.voice).reshape(1, -1)
            )[0]
        except Exception:  # noqa: BLE001
            return None

        distances = sorted(
            (
                (float(np.linalg.norm(point - centroid)), label)
                for label, centroid in self._projected_centroids.items()
            )
        )
        if not distances:
            return None

        best_distance, best_label = distances[0]
        if len(distances) > 1:
            second = distances[1][0]
            confidence = float(second / (best_distance + second + 1e-9))
        else:
            confidence = 1.0 / (1.0 + best_distance)

        if confidence < MIN_PROJECTED_MARGIN:
            return None
        return Guess(label=best_label, confidence=confidence)

    def guess_style(self, features: Features) -> Guess | None:
        """
        نزدیک‌ترین سبک، یا None اگر اطمینان بسنده نبود.

        نخست وزن‌دار بودن سنجیده می‌شود: نوای بی‌وزن هرگز نباید
        «شور» یا «واحد» گمانه زده شود، هر چقدر هم بقیهٔ ویژگی‌هایش
        نزدیک باشند.
        """
        if not self._style_centroids or self._style_scale is None:
            return None
        if not self._corpus_is_big_enough():
            return None

        from core.audio.features import METRICAL_THRESHOLD

        vector = features.style_vector() / self._style_scale

        # پالودن بر پایهٔ وزن — نیرومندترین نشانهٔ سبک
        metrical = features.is_metrical
        allowed = {
            label: centroid
            for label, centroid in self._style_centroids.items()
            if self._label_is_metrical(label) == metrical
        }
        if not allowed:
            allowed = self._style_centroids

        ordered = sorted(
            (float(np.linalg.norm(vector - centroid)), label)
            for label, centroid in allowed.items()
        )
        best_distance, best_label = ordered[0]

        if len(ordered) > 1:
            second = ordered[1][0]
            confidence = (
                float(second / (best_distance + second))
                if (best_distance + second) > 0 else 0.5
            )
        else:
            # تنها یک نامزد ماند — یعنی پالودنِ وزن خودش تصمیم را
            # گرفت. آنگاه اطمینان باید از **همان پالوده** بیاید، نه
            # از فاصلهٔ خام.
            #
            # سنجیده شد که فرمول فاصله اینجا عدد کوچکی می‌داد و
            # آستانه، پاسخِ درست را رد می‌کرد: روضه به‌درستی جدا
            # می‌شد و بعد دور ریخته می‌شد. هرچه رسایی ضربان از مرز
            # دورتر باشد، داوری وزن استوارتر است.
            margin = abs(features.pulse_clarity - METRICAL_THRESHOLD) / METRICAL_THRESHOLD
            confidence = float(np.clip(0.55 + 0.40 * margin, 0.55, 0.95))

        if confidence < MIN_STYLE_CONFIDENCE:
            return None
        return Guess(label=best_label, confidence=confidence)

    def _label_is_metrical(self, label: str) -> bool:
        """
        آیا این سبک ذاتاً وزن دارد.

        روضه و مناجات آواز آزادند؛ بقیه ضرب دارند. این دانشِ حوزه
        است، نه چیزی که از داده درآید — و آوردنش، خطای سبک را
        به‌روشنی می‌کاهد.
        """
        return label not in ("روضه", "مناجات")

    def similar_tracks(
        self, features: Features, limit: int = 3
    ) -> list[tuple[int, float]]:
        """
        نزدیک‌ترین نواهای گنجینه بر پایهٔ آوا.

        بازگشتی: فهرست (شناسهٔ نوا، همانندی)، از نزدیک به دور.
        فهرست تهی، پاسخِ درست و رایج است — نه نشانهٔ خرابی.

        ═══════════════════════════════════════════════════════
          چرا سه نگهبان، نه یک آستانه
        ═══════════════════════════════════════════════════════

        این تابع پیش‌تر تنها یک آستانهٔ مطلق داشت و نتیجه‌اش یک
        باگ راستین بود: کاربر نوایی فرستاد که در گنجینه نبود،
        ربات به‌درستی گفت «نیافتم»، و سپس **هر چه در گنجینه
        داشت** را به‌عنوان «شاید این‌ها را می‌خواستید» فرستاد.

        سه چیز با هم آن را ساخته بودند:

        ۱. **هنجارسازی شاید اصلاً نبود.** اگر گمانه‌زن آموزش
           ندیده باشد، voice_similarity به کسینوسِ خام فرو
           می‌افتد و همه‌چیز ۰٫۹۷ تا ۰٫۹۹ می‌شود. آستانهٔ ۰٫۶۲
           آنگاه از هیچ‌کس جلو نمی‌گیرد.

        ۲. **گنجینه خُرد بود.** با چهار نوا، «نزدیک‌ترین» معنا
           ندارد؛ نزدیک‌ترینِ چهار چیزِ نامربوط، باز هم نامربوط
           است.

        ۳. **سنجش مطلق بود، نه نسبی.** پرسش درست این نیست که
           «همانندی بالاتر از ۰٫۶۲ است؟» بلکه این است که «آیا
           این نوا نسبت به نوای تصادفیِ همین گنجینه، به‌طور
           نامعمول نزدیک است؟» — و پاسخش را تنها می‌توان با
           سنجیدن در برابر میانهٔ همان گنجینه داد.
        """
        from core.db import features_store

        # نگهبان یکم و دوم
        if not self.is_normalized or not self._corpus_is_big_enough():
            return []

        track_ids, matrix = features_store.voice_matrix()
        if track_ids.size < MIN_CORPUS_FOR_GUESS:
            # بردارهای به‌روز کمتر از آنند که میانه معنا داشته باشد
            return []

        scores = self._voice_scores(features.voice, matrix)
        if scores is None:
            return []

        # نگهبان سوم: سنجش نسبی
        median = float(np.median(scores))
        floor = max(MIN_VOICE_CONFIDENCE, median + MIN_MARGIN_OVER_MEDIAN)

        order = np.argsort(-scores, kind="stable")[:limit]
        return [
            (int(track_ids[i]), float(scores[i]))
            for i in order
            if scores[i] >= floor
        ]

    def _voice_scores(
        self, query: np.ndarray, matrix: np.ndarray
    ) -> np.ndarray | None:
        """
        همانندیِ یک نشان با همهٔ نشان‌های گنجینه، یکجا.

        همان چیزی را می‌دهد که `voice_similarity` تک‌به‌تک می‌داد —
        هنجارسازی با میانگین و انحرافِ گنجینه، سپس کسینوس نگاشته به
        بازهٔ ۰ تا ۱ — ولی با یک ضرب ماتریسی به جای یک حلقهٔ
        پایتونی روی هزاران ردیف.

        None اگر ابعاد نخوانند.
        """
        if matrix.ndim != 2 or matrix.shape[0] == 0:
            return None
        if (
            self._voice_center is None
            or self._voice_scale is None
            or query.size != matrix.shape[1]
            or self._voice_center.size != query.size
        ):
            return None

        safe = np.where(self._voice_scale < 1e-9, 1.0, self._voice_scale)
        q = (query.astype(np.float64) - self._voice_center) / safe
        rows = (matrix - self._voice_center) / safe

        q_norm = float(np.linalg.norm(q))
        row_norms = np.linalg.norm(rows, axis=1)
        if q_norm == 0.0:
            return np.zeros(matrix.shape[0], dtype=np.float64)

        # ردیفِ با هنجارِ صفر، همانندی صفر می‌گیرد — همان کاری که
        # `voice_similarity` می‌کرد.
        denominator = np.where(row_norms == 0.0, 1.0, row_norms) * q_norm
        cosine = (rows @ q) / denominator
        cosine[row_norms == 0.0] = -1.0

        return np.clip((cosine + 1.0) / 2.0, 0.0, 1.0)


_classifier: Classifier | None = None


def get_classifier() -> Classifier:
    """گمانه‌زن یگانهٔ برنامه."""
    global _classifier
    if _classifier is None:
        _classifier = Classifier()
    return _classifier


def retrain() -> tuple[int, int, int]:
    return get_classifier().train()
