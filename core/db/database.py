"""
لایهٔ دسترسی به پایگاه داده.

همهٔ کار با SQLite از همین جا می‌گذرد. دو نکتهٔ مهم:

۱) حالت WAL روشن است تا خواندن و نوشتن هم‌زمان یکدیگر را نبندند.
   ربات چند کار را با هم پیش می‌برد و بدون WAL به «database is locked»
   برمی‌خورد.

۲) موجودی توکن هرگز مستقیم دستکاری نمی‌شود؛ تنها از راه adjust_tokens
   که هم ستون خلاصه و هم دفتر را در یک تراکنش می‌نویسد. اگر این دو
   از هم جدا بیفتند، اختلاف حساب پیش می‌آید و پیگیری‌اش ممکن نیست.
"""

from __future__ import annotations

import logging
import sqlite3
import threading
import uuid as uuid_lib
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator, Sequence

from config import config
from core.normalize import normalize

logger = logging.getLogger(__name__)

SCHEMA_PATH = Path(__file__).parent / "schema.sql"

_local = threading.local()


def _connect() -> sqlite3.Connection:
    config.database_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(
        config.database_path,
        timeout=30.0,
        isolation_level=None,  # تراکنش را خودمان مدیریت می‌کنیم
        check_same_thread=False,
    )
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = NORMAL")
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 30000")
    # حافظهٔ نهان بزرگ‌تر، چون جدول اثر انگشت پرخوان است
    conn.execute("PRAGMA cache_size = -64000")  # ۶۴ مگابایت
    return conn


def get_connection() -> sqlite3.Connection:
    """یک اتصال به ازای هر ریسه؛ اتصال‌ها میان ریسه‌ها به اشتراک گذاشته نمی‌شوند."""
    conn = getattr(_local, "conn", None)
    if conn is None:
        conn = _connect()
        _local.conn = conn
    return conn


def close_connection() -> None:
    conn = getattr(_local, "conn", None)
    if conn is not None:
        conn.close()
        _local.conn = None


@contextmanager
def transaction() -> Iterator[sqlite3.Connection]:
    """
    تراکنش با بازگردانی خودکار در صورت خطا.

    هر جا چند نوشتن باید با هم انجام شوند یا هیچ‌کدام، از این استفاده شود.
    """
    conn = get_connection()
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield conn
    except Exception:
        conn.execute("ROLLBACK")
        raise
    else:
        conn.execute("COMMIT")


# ═════════════════════════════════════════════════════════════
#  آماده‌سازی
# ═════════════════════════════════════════════════════════════

def init_db() -> None:
    """ساختار را می‌سازد. اجرای دوباره بی‌خطر است."""
    conn = get_connection()
    conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
    _migrate(conn)


# ستون‌هایی که پس از ساختار نخستین افزوده شده‌اند.
# schema.sql همه‌جا CREATE TABLE IF NOT EXISTS است، پس بر پایگاه
# داده‌ای که از پیش هست هیچ ستونی نمی‌افزاید — جدول موجود را
# دست‌نخورده رد می‌کند. بی این مهاجرت، بروزرسانی روی نصب زنده،
# خطای «no such column» می‌داد.
_MIGRATIONS: tuple[tuple[str, str, str], ...] = (
    ("users", "is_trusted", "INTEGER NOT NULL DEFAULT 0"),
    ("users", "trusted_by", "INTEGER"),
    ("users", "trusted_at", "TEXT"),
    ("users", "is_admin", "INTEGER NOT NULL DEFAULT 0"),
    ("users", "admin_by", "INTEGER"),
    ("users", "admin_at", "TEXT"),
    ("submissions", "title", "TEXT"),
    # کِی نسخهٔ آراسته‌اش در گروه بایگانی نشست. تهی بودنش یعنی
    # هنوز ننشسته — و کار دوره‌ای همان‌ها را دوباره می‌آزماید.
    ("tracks", "ornate_at", "TEXT"),
    # شمار دفعاتی که این نوا به دست کسی رسیده. زیر هر فایلی که
    # می‌فرستیم نوشته می‌شود؛ کاربر می‌بیند چند نفر پیش از او
    # همین را گرفته‌اند.
    ("tracks", "sent_count", "INTEGER NOT NULL DEFAULT 0"),
    ("searches", "hint_text", "TEXT"),
    # کجا گزارشِ این ناکامی در گروه گردانندگان نشست. اگر خودِ
    # کاربر نسخهٔ کامل را بفرستد، همان گزارش باید برداشته شود —
    # و بی این دو ستون، نشانی‌اش را نداشتیم.
    ("searches", "report_msg_id", "INTEGER"),
    ("searches", "report_clip_id", "INTEGER"),
    ("searches", "fill_admin_id", "INTEGER"),
    ("searches", "fill_expires_at", "TEXT"),
    # اگر این نوا با نوای دیگری یکی بود و در آن ادغام شد، شناسهٔ
    # برنده اینجا می‌نشیند. تهی بودنش یعنی نوایی مستقل است.
    #
    # چرا ردیف پاک نمی‌شود: نشانی‌اش (file_id) شاید جایی رفته
    # باشد، و «چرا این نوا رفت» باید پاسخی داشته باشد.
    ("tracks", "merged_into", "INTEGER"),
    # جوینده خواسته است اگر روزی این نوا پیدا شد خبرش کنیم.
    #
    # چرا این ستون: ناکامی تا امروز پایانِ راه بود — کاربر
    # دست‌خالی می‌رفت و دیگر برنمی‌گشت. با این، ناکامی به
    # «سفارشت ثبت شد» بدل می‌شود.
    ("searches", "notify_user", "INTEGER NOT NULL DEFAULT 0"),
    # کِی خبر داده شد. دوباره خبر ندهیم.
    ("searches", "notified_at", "TEXT"),
    # آنچه در این نوا خوانده می‌شود، به نوشتار.
    #
    # یک بار هنگام نمایه‌سازی درمی‌آید و می‌ماند؛ رونویسی گران
    # است و دوباره کردنش برای هر بازجویی، ربات را زمین می‌زد.
    #
    # تهی بودنش بی‌خطر است: یا مدل نبوده، یا نوا هنوز نمایه
    # نشده. لایهٔ متن آنگاه ساکت می‌ماند و بقیه کار می‌کنند.
    ("tracks", "transcript", "TEXT"),
    # نگارشِ هنجارشدهٔ همان متن.
    #
    # ## چرا ستونِ جدا و نه هنجارسازی هنگام جست‌وجو
    #
    # عبارتِ کاربر پیش از جست‌وجو هنجار می‌شود («آ» به «ا»، «ي»
    # به «ی»)، ولی متن خام ذخیره می‌شد. پس `LIKE '%ازمایشی%'`
    # روی متنی که «آزمایشی» دارد هرگز نمی‌خواند — یعنی جست‌وجوی
    # شعر برای هر واژه‌ای که «آ» یا «ي» داشت خاموش شکست می‌خورد.
    #
    # SQLite نمی‌تواند `normalize` پایتون را در `LIKE` صدا بزند،
    # پس همان راهِ `title_norm` و `madah_norm`: یک ستونِ هنجارشده.
    ("tracks", "transcript_norm", "TEXT"),
    # چند بار کوشیدیم این نوا را نمایه کنیم و نشد.
    #
    # ## چرا این ستون
    #
    # پنج نوای گنجینه هر پانزده دقیقه دوباره فرو گرفته و دوباره
    # ناکام می‌شدند — روزی نزدیک پانصد فرو گرفتنِ بیهوده، برای
    # فایل‌هایی که ffmpeg نمی‌گشایدشان. بی این شمارنده، صف
    # نمایه‌سازی هرگز از دستشان رها نمی‌شد.
    #
    # صفر بودنش یعنی هنوز کوششی نشده یا کوشش کامیاب بوده.
    ("tracks", "index_attempts", "INTEGER NOT NULL DEFAULT 0"),
    # ── دعوت ────────────────────────────────────────────────
    #
    # چه کسی این همراه را آورده. تهی یعنی خودش آمده.
    ("users", "invited_by", "INTEGER"),
    # آیا پاداشِ این دعوت داده شده.
    #
    # ## چرا روی ردیفِ **دعوت‌شده** می‌نشیند و نه دعوت‌کننده
    #
    # خواستهٔ روشن بود: «اگر اون کسی که عضو شد دوباره ربات پاک
    # کرد و دوباره عضو شد، دیگه سکه‌ای تعلق نمی‌گیره». ردیفِ کاربر
    # با پاک کردنِ ربات از بین نمی‌رود — تنها `is_blocked_bot`
    # می‌شود — پس این نشان می‌ماند و دوباره‌آمدن پاداشِ تازه
    # نمی‌دهد. اگر روی دعوت‌کننده می‌نشست، شمارنده بود نه نشان،
    # و همین را نمی‌گرفت.
    ("users", "invite_rewarded", "INTEGER NOT NULL DEFAULT 0"),
    # کِی آخرین بار عضویتش راستی‌آزمایی شد.
    #
    # ## چرا کش
    #
    # عضویت باید **همیشگی** باشد، نه یک‌بار — کسی که بیرون رفت
    # نباید دسترسی داشته باشد. ولی سنجیدنش در هر کنش یعنی یک
    # فراخوانِ تلگرام برای هر پیام، و آن هم کند است و هم به
    # سقفِ نرخ می‌خورد. پس هر چند دقیقه یک بار سنجیده می‌شود.
    ("users", "membership_checked_at", "TEXT"),
    # عضویتِ این کانال همیشگی است یا تنها یک بار لازم بوده.
    ("required_channels", "enforce", "TEXT NOT NULL DEFAULT 'always'"),
)


# ایندکس‌هایی که پس از ساختار نخستین افزوده شده‌اند. برخلاف
# ستون‌ها، CREATE INDEX IF NOT EXISTS خودش بی‌خطر است، پس تنها
# باید اجرا شوند — ولی جدولشان باید از پیش باشد.
_LATE_INDEXES: tuple[str, ...] = (
    "CREATE INDEX IF NOT EXISTS idx_tracks_popular"
    " ON tracks(sent_count DESC, id DESC) WHERE is_active = 1",
)


def _migrate(conn: sqlite3.Connection) -> None:
    """
    ستون‌ها و ایندکس‌های نوافزوده را می‌نشاند، اگر نباشند.

    SQLite هنوز ADD COLUMN IF NOT EXISTS ندارد، پس نخست
    PRAGMA table_info پرسیده می‌شود. اجرای دوباره بی‌خطر است.

    ستون‌ها بر پایهٔ **جدول** دسته می‌شوند نه یک‌به‌یک: پیش‌تر برای
    هر ردیفِ فهرست یک PRAGMA زده می‌شد — چهارده بار برای چهار
    جدول. هزینه‌اش ناچیز بود، ولی کارِ سه‌برابر برای هیچ.
    """
    wanted: dict[str, list[tuple[str, str]]] = {}
    for table, column, declaration in _MIGRATIONS:
        wanted.setdefault(table, []).append((column, declaration))

    for table, columns in wanted.items():
        have = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
        if not have:
            continue  # جدول هنوز ساخته نشده؛ schema.sql خودش می‌سازدش
        for column, declaration in columns:
            if column not in have:
                conn.execute(
                    f"ALTER TABLE {table} ADD COLUMN {column} {declaration}"
                )

    for statement in _LATE_INDEXES:
        try:
            conn.execute(statement)
        except sqlite3.OperationalError as exc:
            # جدولی که هنوز نیست — schema.sql در همین اجرا ساختش
            logger.debug("ساختن ایندکس دیرآمده نشد: %s", exc)


# ═════════════════════════════════════════════════════════════
#  ابزار عمومی
# ═════════════════════════════════════════════════════════════

def query_one(sql: str, params: Sequence[Any] = ()) -> sqlite3.Row | None:
    return get_connection().execute(sql, params).fetchone()


def query_all(sql: str, params: Sequence[Any] = ()) -> list[sqlite3.Row]:
    return get_connection().execute(sql, params).fetchall()


def execute(sql: str, params: Sequence[Any] = ()) -> sqlite3.Cursor:
    return get_connection().execute(sql, params)


def new_uuid() -> str:
    return str(uuid_lib.uuid4())


# ═════════════════════════════════════════════════════════════
#  کاربران
# ═════════════════════════════════════════════════════════════

def get_user(user_id: int) -> sqlite3.Row | None:
    return query_one("SELECT * FROM users WHERE user_id = ?", (user_id,))


def upsert_user(
    user_id: int,
    username: str | None = None,
    first_name: str | None = None,
    last_name: str | None = None,
) -> tuple[sqlite3.Row, bool]:
    """
    کاربر را می‌سازد یا شناسنامه‌اش را تازه می‌کند.

    بازگشتی: (رکورد کاربر، آیا تازه ساخته شد)

    توکن آغازین تنها هنگام ساخت داده می‌شود و در دفتر هم ثبت می‌گردد.
    """
    existing = get_user(user_id)

    if existing is None:
        with transaction() as conn:
            conn.execute(
                """
                INSERT INTO users (user_id, username, first_name, last_name, tokens)
                VALUES (?, ?, ?, ?, ?)
                """,
                (user_id, username, first_name, last_name, config.initial_tokens),
            )
            if config.initial_tokens:
                conn.execute(
                    """
                    INSERT INTO token_ledger (user_id, delta, balance, reason, note)
                    VALUES (?, ?, ?, 'initial', 'هدیهٔ آغازین')
                    """,
                    (user_id, config.initial_tokens, config.initial_tokens),
                )
        return get_user(user_id), True  # type: ignore[return-value]

    execute(
        """
        UPDATE users
           SET username     = COALESCE(?, username),
               first_name   = COALESCE(?, first_name),
               last_name    = COALESCE(?, last_name),
               last_seen_at = datetime('now'),
               updated_at   = datetime('now'),
               is_blocked_bot = 0
         WHERE user_id = ?
        """,
        (username, first_name, last_name, user_id),
    )
    return get_user(user_id), False  # type: ignore[return-value]


def set_verified(user_id: int, verified: bool = True) -> None:
    execute(
        "UPDATE users SET is_verified = ?, updated_at = datetime('now') WHERE user_id = ?",
        (int(verified), user_id),
    )


def set_instagram_tapped(user_id: int) -> None:
    execute(
        "UPDATE users SET tapped_instagram = 1, updated_at = datetime('now') WHERE user_id = ?",
        (user_id,),
    )


def set_trusted(user_id: int, trusted: bool = True, by_admin: int | None = None) -> bool:
    """
    همراهی را مورد اعتماد می‌کند یا اعتماد را پس می‌گیرد.

    اعتماد یعنی پیشکش او بی داوری گردانندگان یک‌راست به گنجینه
    می‌رود. **سنجش تکراری از این پرش مستثنا نیست**؛ اعتماد، پریدن
    از داوری است نه از نگهبان تکراری.

    بازگشتی: آیا چنین همراهی در دفتر بود.
    """
    cursor = execute(
        """
        UPDATE users
           SET is_trusted = ?,
               trusted_by = ?,
               trusted_at = CASE WHEN ? THEN datetime('now') ELSE NULL END,
               updated_at = datetime('now')
         WHERE user_id = ?
        """,
        (int(trusted), by_admin if trusted else None, int(trusted), user_id),
    )
    return cursor.rowcount > 0


def is_trusted(user_id: int) -> bool:
    row = query_one("SELECT is_trusted FROM users WHERE user_id = ?", (user_id,))
    return bool(row and row["is_trusted"])


def list_trusted() -> list[sqlite3.Row]:
    return query_all(
        """
        SELECT user_id, username, first_name, last_name, trusted_at
          FROM users
         WHERE is_trusted = 1 AND is_banned = 0
         ORDER BY trusted_at DESC
        """
    )


def mark_blocked_bot(user_id: int) -> None:
    """کاربری که ربات را مسدود کرده، تا از همگانی‌رسانی کنار گذاشته شود."""
    execute("UPDATE users SET is_blocked_bot = 1 WHERE user_id = ?", (user_id,))


def set_banned(user_id: int, banned: bool, reason: str | None = None) -> None:
    execute(
        """
        UPDATE users SET is_banned = ?, ban_reason = ?, updated_at = datetime('now')
         WHERE user_id = ?
        """,
        (int(banned), reason, user_id),
    )


def is_db_admin(user_id: int) -> bool:
    """
    آیا این کاربر را مالک، گرداننده کرده است.

    جدا از ADMIN_IDS در .env نگه داشته می‌شود: آن فهرست ثابت است و
    دگرگون کردنش بازراه‌اندازی می‌خواهد؛ این یکی زنده است.
    """
    row = query_one(
        "SELECT is_admin FROM users WHERE user_id = ? AND is_banned = 0", (user_id,)
    )
    return bool(row and row["is_admin"])


def set_db_admin(user_id: int, admin: bool, by_owner: int | None = None) -> None:
    """گردانندگی را می‌دهد یا پس می‌گیرد."""
    if admin:
        execute(
            """
            UPDATE users
               SET is_admin = 1, admin_by = ?, admin_at = datetime('now'),
                   updated_at = datetime('now')
             WHERE user_id = ?
            """,
            (by_owner, user_id),
        )
    else:
        execute(
            """
            UPDATE users
               SET is_admin = 0, admin_by = NULL, admin_at = NULL,
                   updated_at = datetime('now')
             WHERE user_id = ?
            """,
            (user_id,),
        )


def list_db_admins() -> list[sqlite3.Row]:
    return query_all(
        """
        SELECT user_id, username, first_name, admin_by, admin_at
          FROM users WHERE is_admin = 1 AND is_banned = 0
         ORDER BY admin_at
        """
    )


def count_users(only_verified: bool = False) -> int:
    sql = "SELECT COUNT(*) AS c FROM users WHERE is_banned = 0"
    if only_verified:
        sql += " AND is_verified = 1"
    row = query_one(sql)
    return int(row["c"]) if row else 0


def iter_broadcast_targets() -> list[int]:
    """کاربرانی که می‌توان برایشان پیام همگانی فرستاد."""
    rows = query_all(
        """
        SELECT user_id FROM users
         WHERE is_banned = 0 AND is_blocked_bot = 0 AND is_verified = 1
         ORDER BY user_id
        """
    )
    return [int(r["user_id"]) for r in rows]


# ═════════════════════════════════════════════════════════════
#  توکن
# ═════════════════════════════════════════════════════════════

class InsufficientTokens(RuntimeError):
    """موجودی توکن کاربر برای این کار بس نیست."""


def adjust_tokens(
    user_id: int,
    delta: int,
    reason: str,
    ref_type: str | None = None,
    ref_id: int | None = None,
    note: str | None = None,
    allow_negative: bool = False,
) -> int:
    """
    موجودی توکن را تغییر می‌دهد و همزمان در دفتر ثبت می‌کند.

    اگر delta منفی باشد و موجودی بس نباشد، InsufficientTokens
    برخاسته می‌شود و هیچ چیز نوشته نمی‌شود.

    بازگشتی: موجودی تازه.
    """
    with transaction() as conn:
        row = conn.execute(
            "SELECT tokens FROM users WHERE user_id = ?", (user_id,)
        ).fetchone()
        if row is None:
            raise ValueError(f"کاربر {user_id} در پایگاه داده نیست.")

        balance = int(row["tokens"]) + delta
        if balance < 0 and not allow_negative:
            raise InsufficientTokens(
                f"موجودی {row['tokens']} است و برای برداشت {abs(delta)} بس نیست."
            )

        conn.execute(
            "UPDATE users SET tokens = ?, updated_at = datetime('now') WHERE user_id = ?",
            (balance, user_id),
        )
        conn.execute(
            """
            INSERT INTO token_ledger (user_id, delta, balance, reason, ref_type, ref_id, note)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (user_id, delta, balance, reason, ref_type, ref_id, note),
        )
    return balance


def set_inviter(user_id: int, inviter_id: int) -> bool:
    """
    دعوت‌کننده را می‌نشاند — تنها یک بار، و تنها اگر تهی باشد.

    بازگشتی: آیا همین فراخوان نشاندش.

    خودْدعوتی رد می‌شود؛ وگرنه هر کس با لینکِ خودش سکه می‌ساخت.
    """
    if int(user_id) == int(inviter_id):
        return False
    cursor = execute(
        "UPDATE users SET invited_by = ?, updated_at = datetime('now')"
        " WHERE user_id = ? AND invited_by IS NULL",
        (int(inviter_id), int(user_id)),
    )
    return cursor.rowcount > 0


def claim_invite_reward(user_id: int) -> int | None:
    """
    پاداشِ دعوتِ این همراه را — اگر هنوز داده نشده — نشان می‌زند.

    بازگشتی: شناسهٔ دعوت‌کننده، یا None اگر دعوتی نبوده یا پیش‌تر
    پاداشش داده شده.

    نشان‌زدن و خواندن در **یک** جمله انجام می‌شود تا دو فراخوانِ
    هم‌زمان دو بار پاداش ندهند — همان درسی که در `mark_refunded`
    گرفتیم.
    """
    with transaction() as conn:
        row = conn.execute(
            "SELECT invited_by FROM users"
            " WHERE user_id = ? AND invited_by IS NOT NULL"
            "   AND COALESCE(invite_rewarded, 0) = 0",
            (int(user_id),),
        ).fetchone()
        if row is None or row["invited_by"] is None:
            return None
        cursor = conn.execute(
            "UPDATE users SET invite_rewarded = 1, updated_at = datetime('now')"
            " WHERE user_id = ? AND COALESCE(invite_rewarded, 0) = 0",
            (int(user_id),),
        )
        if cursor.rowcount == 0:
            return None
        return int(row["invited_by"])


def count_invites(user_id: int) -> int:
    """چند نفر با لینکِ این همراه آمدند و تأیید شدند."""
    row = query_one(
        "SELECT COUNT(*) AS c FROM users"
        " WHERE invited_by = ? AND COALESCE(invite_rewarded, 0) = 1",
        (int(user_id),),
    )
    return int(row["c"]) if row else 0


def get_tokens(user_id: int) -> int:
    row = query_one("SELECT tokens FROM users WHERE user_id = ?", (user_id,))
    return int(row["tokens"]) if row else 0


def token_history(user_id: int, limit: int = 10) -> list[sqlite3.Row]:
    return query_all(
        """
        SELECT * FROM token_ledger
         WHERE user_id = ?
         ORDER BY created_at DESC, id DESC
         LIMIT ?
        """,
        (user_id, limit),
    )


# ═════════════════════════════════════════════════════════════
#  آرشیو مداحی
# ═════════════════════════════════════════════════════════════

def add_track(
    file_id: str | None,
    file_unique_id: str | None,
    source: str,
    title: str | None = None,
    madah: str | None = None,
    style: str | None = None,
    duration: int | None = None,
    file_size: int | None = None,
    sha256: str | None = None,
    source_url: str | None = None,
    source_chat_id: int | None = None,
    source_msg_id: int | None = None,
    added_by: int | None = None,
) -> int:
    """مداحی تازه در آرشیو ثبت می‌کند و شناسهٔ آن را برمی‌گرداند."""
    cursor = execute(
        """
        INSERT INTO tracks (
            uuid, file_id, file_unique_id, title, madah, style,
            title_norm, madah_norm, duration, file_size, sha256,
            source, source_url, source_chat_id, source_msg_id, added_by
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            new_uuid(), file_id, file_unique_id, title, madah, style,
            normalize(title or ""), normalize(madah or ""),
            duration, file_size, sha256,
            source, source_url, source_chat_id, source_msg_id, added_by,
        ),
    )
    return int(cursor.lastrowid)


def get_track(track_id: int) -> sqlite3.Row | None:
    return query_one("SELECT * FROM tracks WHERE id = ?", (track_id,))


def ensure_fingerprint_version() -> bool:
    """
    اگر الگوریتم اثر انگشت عوض شده باشد، همه را برای نمایه‌سازی
    دوباره نشان می‌کند.

    ## چرا این لازم است

    اثر انگشتِ نسخهٔ کهنه با نسخهٔ تازه هم‌خوان نیست — عددها با
    قاعدهٔ دیگری ساخته شده‌اند. آمیختنشان یعنی هیچ‌کدام کار نکند:
    پرس‌وجوی تازه با نمایهٔ کهنه هیچ اشتراکی ندارد.

    پس عددهای کهنه پاک می‌شوند و نواها `is_indexed = 0` می‌گیرند؛
    کار دوره‌ای `reindex_pending` که از پیش هست، در پس‌زمینه از نو
    می‌سازدشان.

    بازگشتی: آیا کاری انجام شد.
    """
    from core.audio.fingerprint import FINGERPRINT_VERSION

    current = str(FINGERPRINT_VERSION)
    if get_setting("fingerprint_version") == current:
        return False

    stale = query_one("SELECT COUNT(*) AS c FROM fingerprints")
    count = int(stale["c"]) if stale else 0

    execute("DELETE FROM fingerprints")
    execute("UPDATE tracks SET is_indexed = 0 WHERE is_active = 1")
    set_setting("fingerprint_version", current)

    pending = query_one(
        "SELECT COUNT(*) AS c FROM tracks WHERE is_active = 1 AND is_indexed = 0"
    )
    logger.warning(
        "الگوریتم اثر انگشت به نسخهٔ %s رفت: %s عدد کهنه پاک شد و %s نوا "
        "برای نمایه‌سازی دوباره نشان خورد. تا پایان این کار، جست‌وجو "
        "ناقص خواهد بود.",
        current, f"{count:,}", int(pending["c"]) if pending else 0,
    )
    return True


def popular_tracks(limit: int = 8, offset: int = 0) -> list[sqlite3.Row]:
    """
    پرخواسته‌ترین نواهای آرشیو.

    مرتب بر شمارِ فرستادن، و سپس بر تازگی. نواهایی که هنوز به
    دست کسی نرسیده‌اند کنار گذاشته **نمی‌شوند** — با آرشیوی که
    تازه پر می‌شود، شمارِ همه صفر است و فیلترِ سخت‌گیر، فهرست را
    تهی می‌گذاشت. آن‌ها ته فهرست می‌نشینند و همان، «تازه‌ها» را
    هم نشان می‌دهد.
    """
    return query_all(
        """
        SELECT * FROM tracks
         WHERE is_active = 1 AND file_id IS NOT NULL
         ORDER BY sent_count DESC, id DESC
         LIMIT ? OFFSET ?
        """,
        (limit, offset),
    )


def count_popular() -> int:
    """شمارِ نواهایی که در فهرستِ محبوب‌ترین‌ها می‌آیند."""
    row = query_one(
        "SELECT COUNT(*) AS c FROM tracks"
        " WHERE is_active = 1 AND file_id IS NOT NULL"
    )
    return int(row["c"]) if row else 0


def bump_sent_count(track_id: int) -> int:
    """
    یک بار به شمارِ فرستادنِ این نوا می‌افزاید و شمارِ تازه را
    برمی‌گرداند.

    هر جا نوایی به دست کسی می‌رسد این خوانده می‌شود — یافتنِ
    اثر انگشتی، جست‌وجوی متنی، گمانهٔ نواهای همانند، آوردن از
    سایت، و رساندنِ بازجویی پرشده. پس عدد، «چند نفر این را
    گرفته‌اند» است نه «چند بار جست‌وجو شده».

    شکستنش نباید فرستادن را بشکند: عدد آماری است، نه بخشی از
    خودِ کار. پس خطا بلعیده و گزارش می‌شود.
    """
    try:
        execute(
            "UPDATE tracks SET sent_count = sent_count + 1 WHERE id = ?",
            (track_id,),
        )
        row = query_one("SELECT sent_count FROM tracks WHERE id = ?", (track_id,))
        return int(row["sent_count"]) if row else 0
    except Exception:  # noqa: BLE001
        logger.debug("افزودن به شمارِ فرستادنِ نوای %s نشد.", track_id)
        return 0


def find_duplicate_track(
    file_unique_id: str | None = None, sha256: str | None = None
) -> sqlite3.Row | None:
    """
    تکراری آشکار را پیش از افزودن می‌یابد.

    این جلوی سوءاستفاده را می‌گیرد: کاربر نمی‌تواند فایلی را که خودِ
    ربات به او داده، دوباره بفرستد و توکن بگیرد.
    """
    if file_unique_id:
        row = query_one(
            "SELECT * FROM tracks WHERE file_unique_id = ? AND is_active = 1",
            (file_unique_id,),
        )
        if row:
            return row
    if sha256:
        return query_one(
            "SELECT * FROM tracks WHERE sha256 = ? AND is_active = 1", (sha256,)
        )
    return None


def remove_track(track_id: int) -> bool:
    """
    نوا را از گنجینه برمی‌دارد.

    سه چیز با هم برداشته می‌شود، وگرنه گنجینه ناسازگار می‌ماند:
    خودِ نوا، اثر انگشتش، و بردار ویژگی‌اش. اگر تنها نوا برداشته
    می‌شد، ده‌ها هزار عدد اثر انگشتِ یتیم می‌ماند که هم فضا می‌خورد
    و هم در بازجویی به نوایی اشاره می‌کند که دیگر نیست.

    خودِ فایل در تلگرام دست‌نخورده می‌ماند؛ ما تنها نشانی‌اش را
    داشتیم، نه خودش.

    بازگشتی: آیا چیزی برداشته شد.
    """
    with transaction() as conn:
        row = conn.execute(
            "SELECT id FROM tracks WHERE id = ?", (track_id,)
        ).fetchone()
        if row is None:
            return False
        conn.execute("DELETE FROM fingerprints WHERE track_id = ?", (track_id,))
        try:
            conn.execute("DELETE FROM track_features WHERE track_id = ?", (track_id,))
        except sqlite3.OperationalError:
            pass  # جدول ویژگی هنوز ساخته نشده
        try:
            conn.execute("DELETE FROM track_melody WHERE track_id = ?", (track_id,))
        except sqlite3.OperationalError:
            pass
        conn.execute("DELETE FROM tracks WHERE id = ?", (track_id,))
    return True


def count_tracks(indexed_only: bool = False) -> int:
    sql = "SELECT COUNT(*) AS c FROM tracks WHERE is_active = 1"
    if indexed_only:
        sql += " AND is_indexed = 1"
    row = query_one(sql)
    return int(row["c"]) if row else 0


def tracks_with_transcript(limit: int = 5000) -> list[sqlite3.Row]:
    """
    نواهایی که متنشان درآمده — خوراکِ لایهٔ متن.

    تنها دو ستون برمی‌گردد، نه `SELECT *`: متنِ کاملِ چند هزار
    نوا در حافظه، ده‌ها مگابایت می‌شود و بیشترش به کار این
    پرس‌وجو نمی‌آید.
    """
    return query_all(
        """
        SELECT id, transcript FROM tracks
         WHERE is_active = 1
           AND transcript IS NOT NULL
           AND TRIM(transcript) <> ''
         LIMIT ?
        """,
        (limit,),
    )


def set_transcript(track_id: int, text: str | None) -> None:
    """
    متنِ درآمدهٔ یک نوا را می‌نشاند — خام و هنجارشده، با هم.

    جدا نوشتنشان یعنی دیر یا زود یکی به‌روز شود و دیگری نه؛ و
    آنگاه جست‌وجو خاموش شکست می‌خورد.
    """
    execute(
        "UPDATE tracks SET transcript = ?, transcript_norm = ?,"
        " updated_at = datetime('now') WHERE id = ?",
        (text, normalize(text or "") or None, track_id),
    )


def madahs_with_counts(offset: int = 0, limit: int = 10) -> list[dict]:
    """
    مداحان گنجینه با شمار نواهایشان، به ترتیب الفبای فارسی.

    ## چرا بر `madah_norm` گروه می‌خورد

    یک مداح در برچسب فایل‌ها چند جور نوشته می‌شود. اگر بر خودِ
    `madah` گروه بخورد، «حاج محمود کریمی» و «محمود کریمی» دو ردیف
    می‌شوند و هیچ‌کدام شمارِ درست را نشان نمی‌دهند.

    نامِ نمایشی، پرتکرارترین نگارش است — نه هنجارشده، که برای
    چشم ناخوش است.

    ## چرا چینش در پایتون است و نه در SQL

    SQLite چینشِ فارسی ندارد و `ORDER BY` آن بر کدِ یونیکد است،
    که برای فارسی غلط درمی‌آید: «پیام» پس از «حسین» می‌افتد، چون
    پ در بلوکِ دیگری نشسته. پس همه خوانده و با `persian_key`
    چیده می‌شوند. شمارِ مداحان کوچک است و بهایش ناچیز.

    ## چرا `anchor` در همین پرس‌وجوست

    فراخوان برای رفتن به فهرستِ نواهای یک مداح، شناسهٔ یکی از
    نواهایش را می‌خواهد (نامِ فارسی در سقفِ ۶۴ بایتیِ فراخوان جا
    نمی‌شود). پیش‌تر برای **هر ردیف** یک پرس‌وجوی جدا زده می‌شد؛
    با سی‌ودو ردیف در هر برگه، سی‌ودو پرس‌وجوی اضافه.
    """
    from core.normalize import persian_key

    rows = query_all(
        """
        SELECT madah_norm,
               COUNT(*) AS tracks,
               (SELECT madah FROM tracks t2
                 WHERE t2.madah_norm = t.madah_norm AND t2.is_active = 1
                 GROUP BY t2.madah ORDER BY COUNT(*) DESC LIMIT 1) AS madah,
               (SELECT t3.id FROM tracks t3
                 WHERE t3.madah_norm = t.madah_norm AND t3.is_active = 1
                 ORDER BY t3.id LIMIT 1) AS anchor
          FROM tracks t
         WHERE is_active = 1 AND madah_norm IS NOT NULL AND madah_norm != ''
         GROUP BY madah_norm
        """
    )
    ordered = sorted((dict(r) for r in rows), key=lambda r: persian_key(r["madah"]))
    return ordered[offset : offset + limit]


def count_madahs() -> int:
    """شمار مداحانِ یکتا — برای صفحه‌بندی و سرنویس."""
    row = query_one(
        "SELECT COUNT(DISTINCT madah_norm) AS c FROM tracks"
        " WHERE is_active = 1 AND madah_norm IS NOT NULL AND madah_norm != ''"
    )
    return int(row["c"]) if row else 0


def tracks_of_madah(
    madah_norm: str, offset: int = 0, limit: int = 10
) -> list[dict]:
    """
    نواهای یک مداح، به ترتیب الفبای فارسی.

    پیش‌تر تازه‌ترین نخست بود. الفبایی شد چون کسی که در فهرستِ یک
    مداح می‌گردد، دنبالِ نوای **مشخصی** است و نامش را می‌داند —
    نه دنبالِ تازه‌ترین. چینش در پایتون است، به همان دلیلِ
    `madahs_with_counts`: SQLite چینشِ فارسی ندارد.
    """
    from core.normalize import persian_key

    rows = query_all(
        """
        SELECT * FROM tracks
         WHERE is_active = 1 AND madah_norm = ?
        """,
        (madah_norm,),
    )
    ordered = sorted((dict(r) for r in rows), key=lambda r: persian_key(r["title"]))
    return ordered[offset : offset + limit]


def count_tracks_of_madah(madah_norm: str) -> int:
    row = query_one(
        "SELECT COUNT(*) AS c FROM tracks WHERE is_active = 1 AND madah_norm = ?",
        (madah_norm,),
    )
    return int(row["c"]) if row else 0


def search_tracks_by_text(term: str, limit: int = 20) -> list[sqlite3.Row]:
    """
    جست‌وجوی متنی روی نام مداح، عنوان، و **متنِ شنیده‌شدهٔ نوا**.

    عبارت ورودی هنجار می‌شود تا «كريمي» و «کریمی» یکی شمرده شوند.

    ## چرا متنِ نوا هم

    خواستهٔ کاربر: «طرف تیکه از مداحی نوشت، براش بفرستی». یعنی
    کسی که تنها بیتی از شعر را به یاد دارد — نه نام مداح و نه
    اسم نوا — باید بتواند همان را بنویسد و نوا را بگیرد.

    متنِ نواها را `services/indexer.transcribe_pending` با Whisperِ
    **لوکال** درمی‌آورد و در ستون `transcript` می‌نشاند؛ هیچ
    سرویسِ بیرونی در کار نیست.

    ## چرا رتبه‌بندی

    خواندن در نام و عنوان گواهِ استوارتری است تا خواندن در متن:
    متن دراز است و واژهٔ رایج در آن زیاد. پس یافته‌های نام و
    عنوان **نخست** می‌آیند، و یافته‌های متن پس از آن‌ها.
    """
    needle = f"%{normalize(term)}%"
    return query_all(
        """
        SELECT *,
               CASE
                   WHEN madah_norm LIKE ? OR title_norm LIKE ? THEN 0
                   ELSE 1
               END AS match_rank
          FROM tracks
         WHERE is_active = 1
           AND (
                madah_norm LIKE ?
             OR title_norm LIKE ?
             OR (transcript_norm IS NOT NULL AND transcript_norm LIKE ?)
           )
         ORDER BY match_rank, created_at DESC
         LIMIT ?
        """,
        (needle, needle, needle, needle, needle, limit),
    )


def search_tracks_by_lyrics(term: str, limit: int = 10) -> list[sqlite3.Row]:
    """
    در متنِ شنیده‌شدهٔ نواها می‌گردد — **واژه‌به‌واژه**.

    ## چرا واژه‌به‌واژه و نه عبارتِ یکسان

    کسی که بیتی را به یاد دارد، عیناً به یاد ندارد: واژه‌ای را
    جابه‌جا می‌گوید، «که» و «را» را می‌اندازد، یا نگارشِ دیگری
    می‌نویسد. `LIKE '%کلِ عبارت%'` چنین کسی را دست‌خالی
    برمی‌گرداند.

    پس هر واژهٔ بلندتر از دو حرف جدا سنجیده می‌شود و همه باید
    باشند. ترتیب مهم نیست.

    ## چرا رونویسی خودش لغزش دارد

    متن را Whisperِ لوکال درمی‌آورد و مداحیِ فارسی — با پژواکِ
    مجلس و آوازِ کشیده — سخت‌ترین حالتش است. پس تکهٔ بلندتر
    بهتر می‌گیرد تا سه واژه، و یافته نیافتن به معنای نبودنِ نوا
    نیست.
    """
    needle = normalize(term)
    if not needle:
        return []

    words = [w for w in needle.split() if len(w) > 2][:8]
    if not words:
        words = [needle]

    where = " AND ".join(["transcript_norm LIKE ?"] * len(words))
    params: list[object] = [f"%{w}%" for w in words]
    params.append(limit)
    return query_all(
        "SELECT * FROM tracks"
        " WHERE is_active = 1 AND transcript_norm IS NOT NULL AND " + where +
        " ORDER BY sent_count DESC, created_at DESC"
        " LIMIT ?",
        tuple(params),
    )


# ═════════════════════════════════════════════════════════════
#  تنظیمات زمان اجرا
# ═════════════════════════════════════════════════════════════

def get_setting(key: str, default: str | None = None) -> str | None:
    row = query_one("SELECT value FROM settings WHERE key = ?", (key,))
    return row["value"] if row else default


def set_setting(key: str, value: str) -> None:
    execute(
        """
        INSERT INTO settings (key, value) VALUES (?, ?)
        ON CONFLICT(key) DO UPDATE SET value = excluded.value,
                                       updated_at = datetime('now')
        """,
        (key, value),
    )
