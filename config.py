"""
پیکربندی مرکزی — همهٔ مقادیر از فایل .env خوانده می‌شود.

هیچ توکن، شناسه یا کلیدی نباید در متن کد نوشته شود.
اگر مقدار لازمی نبود، برنامه همان ابتدا با پیام روشن متوقف می‌شود
تا خطا در میانهٔ کار و به شکل مبهم بروز نکند.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv
import os

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")


class ConfigError(RuntimeError):
    """پیکربندی ناقص یا نادرست است."""


def _required(key: str) -> str:
    value = os.getenv(key, "").strip()
    if not value:
        raise ConfigError(
            f"مقدار «{key}» در فایل .env یافت نشد.\n"
            f"فایل .env.example را به .env کپی کنید و مقادیر را وارد نمایید."
        )
    return value


def _optional(key: str, default: str = "") -> str:
    return os.getenv(key, default).strip()


def _int(key: str, default: int) -> int:
    raw = os.getenv(key, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise ConfigError(f"مقدار «{key}» باید عدد صحیح باشد، ولی «{raw}» است.") from exc


def _float(key: str, default: float) -> float:
    raw = os.getenv(key, "").strip()
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError as exc:
        raise ConfigError(f"مقدار «{key}» باید عدد باشد، ولی «{raw}» است.") from exc


def _chat_id(
    key: str, required: bool = True, allow_plain_negative: bool = False
) -> int:
    """
    شناسهٔ گفتگو را می‌خواند و درستی شکل آن را می‌سنجد.

    شناسهٔ کانال و ابرگروه در تلگرام همیشه منفی و با -100 آغاز می‌شود.
    خطای رایج، جا افتادن این پیشوند هنگام رونویسی است؛ اینجا گرفته می‌شود.

    ولی **گروه ساده** چنین پیشوندی ندارد؛ شناسه‌اش تنها منفی است
    (مانند -4123456789). برای چنین گفتگویی allow_plain_negative
    داده می‌شود تا سنجش پیشوند از میان برداشته شود. درستی راستین
    را هر روی، پیش‌پرواز با get_chat می‌سنجد.
    """
    raw = _required(key) if required else _optional(key)
    if not raw:
        return 0
    try:
        value = int(raw)
    except ValueError as exc:
        raise ConfigError(f"شناسهٔ «{key}» باید عدد باشد، ولی «{raw}» است.") from exc

    if allow_plain_negative:
        if value >= 0:
            raise ConfigError(
                f"شناسهٔ «{key}» برابر {value} است و باید منفی باشد. "
                f"شناسهٔ هر گروه و کانالی در تلگرام منفی است."
            )
        return value

    if value > 0:
        digits = str(abs(value))
        # هنگام رونویسی، پیشوند -100 گاه در سرِ سطر می‌شکند و
        # پاره‌ای از آن به عدد می‌چسبد. هر دو گمانه پیشنهاد می‌شود.
        guesses = [f"-100{digits}"]
        for prefix in ("100", "00", "0", "1"):
            if digits.startswith(prefix) and len(digits) > len(prefix):
                guesses.append(f"-100{digits[len(prefix):]}")
        raise ConfigError(
            f"شناسهٔ «{key}» برابر {value} است و مثبت می‌باشد.\n"
            f"شناسهٔ کانال و گروه همواره منفی و با -100 آغاز می‌شود.\n"
            f"گمانهٔ درست: {' یا '.join(guesses)}\n"
            f"برای یافتن شناسهٔ قطعی، پیامی از کانال را به @userinfobot بازفرستید."
        )
    if not str(value).startswith("-100"):
        raise ConfigError(
            f"شناسهٔ «{key}» برابر {value} است ولی با -100 آغاز نمی‌شود.\n"
            f"شناسهٔ کانال و ابرگروه همواره با -100 آغاز می‌گردد."
        )
    return value


def _id_list(key: str) -> tuple[int, ...]:
    raw = _required(key)
    out: list[int] = []
    for piece in raw.replace("،", ",").split(","):
        piece = piece.strip()
        if not piece:
            continue
        try:
            out.append(int(piece))
        except ValueError as exc:
            raise ConfigError(
                f"در «{key}» مقدار «{piece}» عدد نیست. شناسه‌ها را با ویرگول جدا کنید."
            ) from exc
    if not out:
        raise ConfigError(f"«{key}» تهی است؛ دست‌کم یک شناسهٔ ادمین لازم است.")
    return tuple(out)


@dataclass(frozen=True)
class Config:
    # تلگرام
    bot_token: str
    admin_ids: tuple[int, ...]
    channel_id: int
    channel_username: str
    channel_url: str
    madahi_group_id: int
    feedback_group_id: int
    archive_channel_id: int
    ornate_group_id: int
    users_group_id: int
    local_bot_api_url: str

    # اینستاگرام
    instagram_page: str
    instagram_url: str
    instagram_cookies_file: str

    # اقتصاد توکن
    initial_tokens: int
    token_cost_per_search: int
    token_reward_per_approved: int
    invite_reward: int

    # شبکه
    proxy_url: str
    connect_timeout: float
    read_timeout: float
    write_timeout: float
    pool_timeout: float
    connection_pool_size: int
    network_retries: int
    concurrent_updates: int

    # اجرا
    database_path: Path
    log_level: str
    max_concurrent_jobs: int
    admin_reply_lock_timeout: int
    broadcast_delay: float

    # ── لایهٔ متن ────────────────────────────────────────────
    # اگر مدل نصب نباشد، لایه خودش خاموش می‌ماند؛ پس این‌ها
    # پیش‌فرض دارند و کار دستی نمی‌خواهند.
    whisper_model: str
    whisper_device: str
    whisper_compute: str

    # مسیرها
    base_dir: Path = field(default=BASE_DIR)

    @property
    def data_dir(self) -> Path:
        return self.base_dir / "data"

    @property
    def logs_dir(self) -> Path:
        return self.base_dir / "logs"

    @property
    def tmp_dir(self) -> Path:
        return self.base_dir / "tmp"

    @property
    def texts_dir(self) -> Path:
        return self.base_dir / "texts"

    def is_admin(self, user_id: int) -> bool:
        """
        آیا این کاربر گرداننده است.

        دو سرچشمه دارد: فهرست ثابت .env، و گردانندگانی که
        مالک از راه /addadmin افزوده است. دومی در پایگاه
        داده می‌نشیند تا افزودن گرداننده، بازراه‌اندازی
        ربات نخواهد.
        """
        if user_id in self.admin_ids:
            return True
        # درون‌آورد دیرهنگام: config پیش از پایگاه داده
        # ساخته می‌شود و درون‌آورد بالای پرونده حلقه می‌سازد.
        try:
            from core.db import database

            return database.is_db_admin(user_id)
        except Exception:  # noqa: BLE001
            return False

    def is_owner(self, user_id: int) -> bool:
        """
        مالک — نخستین شناسهٔ ADMIN_IDS در .env.

        تنها اوست که می‌تواند گرداننده بیفزاید یا بردارد.
        اگر هر گرداننده‌ای می‌توانست، اختیارِ مالک بی‌معنا
        می‌شد: یکی می‌افزود و همان تازه‌وارد، مالک را
        برمی‌داشت.
        """
        return bool(self.admin_ids) and user_id == self.admin_ids[0]

    @property
    def ornate_target(self) -> int:
        """
        جایی که نسخهٔ آراسته و بایگانی‌شده می‌نشیند.

        اگر گروه ویژه‌ای پیکربندی نشده باشد، به گروه مداحی فرو
        می‌افتد — تا نبودِ یک کلید اختیاری، برچسب‌گذاری را که کار
        درستی است نشکند.
        """
        return self.ornate_group_id or self.madahi_group_id


def load_config() -> Config:
    db_path = Path(_optional("DATABASE_PATH", "data/hadis.db"))
    # ── لایهٔ متن ────────────────────────────────────────────
    # اگر مدل نصب نباشد، لایه خودش خاموش می‌ماند و چیزی نمی‌شکند.
    # پس پیش‌فرض روشن است و نیازی به کار دستی ندارد.
    whisper_model = _optional("WHISPER_MODEL", "small")
    whisper_device = _optional("WHISPER_DEVICE", "cpu")
    whisper_compute = _optional("WHISPER_COMPUTE", "int8")
    if not db_path.is_absolute():
        db_path = BASE_DIR / db_path

    return Config(
        bot_token=_required("BOT_TOKEN"),
        admin_ids=_id_list("ADMIN_IDS"),
        channel_id=_chat_id("CHANNEL_ID"),
        channel_username=_optional("CHANNEL_USERNAME").lstrip("@"),
        channel_url=_optional("CHANNEL_URL"),
        madahi_group_id=_chat_id("MADAHI_GROUP_ID"),
        feedback_group_id=_chat_id("FEEDBACK_GROUP_ID"),
        archive_channel_id=_chat_id("ARCHIVE_CHANNEL_ID", required=False),
        # بایگانی نسخه‌های آراسته. گروه ساده است، پس پیشوند -100 ندارد.
        ornate_group_id=_chat_id(
            "ORNATE_GROUP_ID", required=False, allow_plain_negative=True
        ),
        # گروه گزارش کاربران تازه. آن هم گروه ساده است.
        users_group_id=_chat_id(
            "USERS_GROUP_ID", required=False, allow_plain_negative=True
        ),
        local_bot_api_url=_optional("LOCAL_BOT_API_URL"),
        instagram_page=_optional("INSTAGRAM_PAGE").lstrip("@"),
        instagram_url=_optional("INSTAGRAM_URL"),
        instagram_cookies_file=_optional("INSTAGRAM_COOKIES_FILE"),
        initial_tokens=_int("INITIAL_TOKENS", 3),
        token_cost_per_search=_int("TOKEN_COST_PER_SEARCH", 1),
        token_reward_per_approved=_int("TOKEN_REWARD_PER_APPROVED", 1),
        invite_reward=_int("INVITE_REWARD", 3),
        proxy_url=_optional("PROXY_URL"),
        # مهلت‌های سخاوتمند، چون پیوند به تلگرام از ایران
        # کند و ناپایدار است. پیش‌فرض PTB پنج ثانیه است و
        # همان، سرچشمهٔ انبوه TimedOut در گزارش‌ها بود.
        connect_timeout=_float("CONNECT_TIMEOUT", 20.0),
        read_timeout=_float("READ_TIMEOUT", 60.0),
        write_timeout=_float("WRITE_TIMEOUT", 120.0),
        pool_timeout=_float("POOL_TIMEOUT", 20.0),
        connection_pool_size=_int("CONNECTION_POOL_SIZE", 32),
        # چند به‌روزرسانی هم‌زمان رسیدگی شود.
        #
        # پیش‌فرض PTB یک است، یعنی همه‌چیز پشت سر هم. با پیوندی که
        # هر فرستادن پیامش می‌تواند ده‌ها ثانیه بکشد، آن یعنی
        # نواختنِ کاربر بر یک دکمه، دقیقه‌ها بی‌پاسخ می‌ماند و او
        # گمان می‌کند دکمه گیر کرده است. همین بود.
        concurrent_updates=_int("CONCURRENT_UPDATES", 8),
        network_retries=_int("NETWORK_RETRIES", 3),
        database_path=db_path,
        log_level=_optional("LOG_LEVEL", "INFO").upper(),
        max_concurrent_jobs=_int("MAX_CONCURRENT_JOBS", 3),
        admin_reply_lock_timeout=_int("ADMIN_REPLY_LOCK_TIMEOUT", 600),
        broadcast_delay=_float("BROADCAST_DELAY", 0.05),
        whisper_model=whisper_model,
        whisper_device=whisper_device,
        whisper_compute=whisper_compute,
    )


try:
    config = load_config()
except ConfigError as error:
    print(f"\n[خطای پیکربندی]\n{error}\n", file=sys.stderr)
    raise SystemExit(1)
