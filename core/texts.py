"""
بارگذار گنجینهٔ نوشتارها.

پیام‌ها، نوشتار دکمه‌ها و برچسب‌ها از پرونده‌های YAML خوانده می‌شوند،
نه از متن کد. دلیلش این است که ویرایش نوشتار کاری روزمره است و نباید
هر بار دست بردن در کد را بطلبد.

دو نکته که این پیمانه را از یک dict ساده جدا می‌کند:

۱) نبودِ کلید، هنگام اجرا خطای خاموش نمی‌دهد؛ TextNotFound برمی‌خیزد
   با نام کلید و نام پرونده، تا فوری پیدا شود.

۲) get() جای‌گاه‌های کم را می‌گیرد: اگر نوشتار {name} خواسته و شما
   ندادید، به جای پرتاب KeyError در میانهٔ پاسخ‌دهی به کاربر،
   خطای روشن با نام جای‌گاهِ کم‌بود می‌دهد.
"""

from __future__ import annotations

import logging
import string
from pathlib import Path
from typing import Any

import yaml

from config import config

logger = logging.getLogger(__name__)


class TextNotFound(KeyError):
    """کلید خواسته‌شده در گنجینهٔ نوشتارها نیست."""


class MissingPlaceholder(KeyError):
    """نوشتار جای‌گاهی دارد که مقدارش داده نشده است."""


# ═════════════════════════════════════════════════════════════
#  ایمن‌سازی مقدارها در برابر HTML
#
#  همهٔ پیام‌های این ربات با parse_mode="HTML" فرستاده می‌شوند، و
#  مقدارهایی که در آن‌ها می‌نشیند از دست کاربر یا از برچسب ID3
#  فایل‌ها می‌آید. اگر یکی از آن‌ها نشانهٔ < داشته باشد، تلگرام کل
#  پیام را رد می‌کند.
#
#  و این تنها یک احتمال نبود؛ رخ داد: نام مداحِ یکی از فایل‌ها در
#  برچسبش «<unknown>» بود — چیزی که بسیاری از برچسب‌زن‌های ام‌پی‌تری
#  خودکار می‌گذارند — و فرستادن هر پاسخِ یافتن با
#  «unsupported start tag "unknown"» می‌شکست.
#
#  پس هر مقدار ایمن می‌شود، مگر آن چند تایی که خودشان HTML‌اند و
#  عمداً چنین ساخته شده‌اند.
# ═════════════════════════════════════════════════════════════

# جای‌گاه‌هایی که مقدارشان از پیش HTML است و نباید ایمن شوند
RAW_PLACEHOLDERS = frozenset({"reasons", "history", "madah_line"})


def _shield(name: str, value: Any) -> Any:
    """نشانه‌های HTML را در مقدار بی‌اثر می‌کند."""
    if name in RAW_PLACEHOLDERS or not isinstance(value, str):
        return value
    return (
        value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    )


class _TextStore:
    def __init__(self, filename: str) -> None:
        self._filename = filename
        self._path: Path = config.texts_dir / filename
        self._data: dict[str, Any] = {}
        self.reload()

    def reload(self) -> None:
        if not self._path.exists():
            raise FileNotFoundError(
                f"پروندهٔ نوشتار «{self._path}» یافت نشد.\n"
                f"شاید setup_project.py هنوز اجرا نشده باشد."
            )
        with self._path.open(encoding="utf-8") as handle:
            loaded = yaml.safe_load(handle) or {}
        if not isinstance(loaded, dict):
            raise ValueError(f"ساختار «{self._filename}» باید نگاشت کلید/مقدار باشد.")
        self._data = loaded
        logger.debug("گنجینهٔ «%s» با %d کلید بارگذاری شد.", self._filename, len(loaded))

    def raw(self, key: str, default: str | None = None) -> str:
        """نوشتار خام، بی‌آنکه جای‌گاهی پر شود."""
        if key in self._data:
            return str(self._data[key]).strip()
        if default is not None:
            return default
        raise TextNotFound(f"کلید «{key}» در «{self._filename}» نیست.")

    def get(self, key: str, **values: Any) -> str:
        """
        نوشتار را با پر شدن جای‌گاه‌ها برمی‌گرداند.

        >>> texts.get("welcome", name="مهدی")
        """
        template = self.raw(key)
        values = {name: _shield(name, value) for name, value in values.items()}
        try:
            return template.format(**values)
        except KeyError as exc:
            wanted = {
                field
                for _, field, _, _ in string.Formatter().parse(template)
                if field
            }
            missing = wanted - set(values)
            raise MissingPlaceholder(
                f"نوشتار «{key}» در «{self._filename}» به جای‌گاه‌های "
                f"{sorted(missing)} نیاز دارد که داده نشده‌اند."
            ) from exc

    def has(self, key: str) -> bool:
        return key in self._data

    def keys(self) -> list[str]:
        return sorted(self._data)


class _StickerStore(_TextStore):
    def get_id(self, key: str) -> str | None:
        """
        شناسهٔ برچسب یا None اگر تعریف نشده باشد.

        تهی بودن، خطا نیست: برچسب‌ها تدریجی افزوده می‌شوند و ربات
        باید پیش از کامل شدنشان هم کار کند.
        """
        value = self._data.get(key)
        if value is None:
            return None
        value = str(value).strip()
        return value or None


messages = _TextStore("messages.yaml")
buttons = _TextStore("buttons.yaml")
stickers = _StickerStore("stickers.yaml")


def reload_all() -> None:
    """هر سه گنجینه را از نو می‌خواند — بی‌آنکه ربات از کار بیفتد."""
    for store in (messages, buttons, stickers):
        store.reload()
    logger.info("گنجینهٔ نوشتارها از نو بارگذاری شد.")


# سرنام‌های کوتاه، چون در سراسر کد پرکاربردند
def msg(key: str, **values: Any) -> str:
    return messages.get(key, **values)


def btn(key: str) -> str:
    return buttons.raw(key)


def escape(value: Any) -> str:
    """
    مقداری را برای نشاندن در پیام HTML ایمن می‌کند.

    برای جاهایی که پیام دستی ساخته می‌شود و از راه msg نمی‌گذرد —
    مانند سرنویس‌هایی که سطربه‌سطر در فهرست چیده می‌شوند.
    """
    return _shield("", "" if value is None else str(value))


def sticker(key: str) -> str | None:
    return stickers.get_id(key)
