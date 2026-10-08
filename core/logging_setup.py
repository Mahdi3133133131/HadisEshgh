"""
پیکربندی گزارش‌برداری.

گزارش‌ها هم روی پرده و هم در پرونده نوشته می‌شوند. پروندهٔ گزارش
روزانه چرخانده می‌شود و سی روز نگه داشته می‌شود؛ چون هنگام
واکاوی یک اشکال، معمولاً چند روز پیش‌تر باید دیده شود.

خطاهای بی‌درنگ (سطح ERROR) در پروندهٔ جداگانه هم می‌آیند تا لازم
نباشد میان انبوه سطرهای INFO دنبالشان بگردیم.
"""

from __future__ import annotations

import logging
import logging.handlers
import sys
from pathlib import Path

from config import config
from core.console import enable_utf8_console

_FORMAT = "%(asctime)s │ %(levelname)-7s │ %(name)-28s │ %(message)s"
_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


def setup_logging() -> None:
    # گزارش‌ها پارسی‌اند و پایانهٔ ویندوز بی این اصلاح آن‌ها را برنمی‌تابد.
    enable_utf8_console()
    config.logs_dir.mkdir(parents=True, exist_ok=True)

    formatter = logging.Formatter(_FORMAT, datefmt=_DATE_FORMAT)
    root = logging.getLogger()
    root.setLevel(getattr(logging, config.log_level, logging.INFO))
    root.handlers.clear()

    # پرده
    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(formatter)
    root.addHandler(console)

    # پروندهٔ همگانی، چرخش روزانه
    general = logging.handlers.TimedRotatingFileHandler(
        config.logs_dir / "bot.log",
        when="midnight",
        backupCount=30,
        encoding="utf-8",
    )
    general.setFormatter(formatter)
    root.addHandler(general)

    # تنها خطاها
    errors = logging.handlers.TimedRotatingFileHandler(
        config.logs_dir / "error.log",
        when="midnight",
        backupCount=90,
        encoding="utf-8",
    )
    errors.setFormatter(formatter)
    errors.setLevel(logging.ERROR)
    root.addHandler(errors)

    # این‌ها پرگویند و گزارش را از خواندن می‌اندازند
    for noisy in ("httpx", "httpcore", "telegram.vendor", "asyncio", "urllib3"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    logging.getLogger(__name__).info(
        "گزارش‌برداری در سطح %s آماده شد؛ پرونده‌ها در %s",
        config.log_level,
        config.logs_dir,
    )
