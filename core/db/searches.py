"""
دفتر بازجویی‌ها.

سه کار از این دفتر برمی‌آید که هر سه در سند خواسته یا لازم بود:

۱) **بازگرداندن توکن.** کاربر که «این آن نیست» را می‌نوازد، باید
   توکنش برگردد. بی نگه داشتن رد بازجویی، دانستن اینکه کدام توکن
   باید برگردد ناشدنی است.

۲) **کش.** یک کلیپ میان مردم می‌چرخد و ده‌ها نفر همان را می‌فرستند.
   با درهم‌سازی ورودی، پاسخ بی‌درنگ و بی‌پردازش داده می‌شود.

۳) **گزارش ناکامی‌ها.** هر تکه‌ای که یافت نشد، نشان می‌دهد چه
   نوایی در گنجینه کم است. چون بایگانی تنها از این پس پر می‌شود،
   این دفتر تنها راهنمای رشد گنجینه است.
"""

from __future__ import annotations

import sqlite3

from core.db.database import execute, query_all, query_one, transaction


def create(
    user_id: int,
    input_kind: str,
    input_sha256: str | None = None,
    input_file_id: str | None = None,
    input_duration: int | None = None,
    query_text: str | None = None,
) -> int:
    cursor = execute(
        """
        INSERT INTO searches (
            user_id, input_kind, input_sha256, input_file_id, input_duration, query_text
        ) VALUES (?, ?, ?, ?, ?, ?)
        """,
        (user_id, input_kind, input_sha256, input_file_id, input_duration, query_text),
    )
    return int(cursor.lastrowid)


def get(search_id: int) -> sqlite3.Row | None:
    return query_one("SELECT * FROM searches WHERE id = ?", (search_id,))


def finish(
    search_id: int,
    status: str,
    matched_track_id: int | None = None,
    confidence: float | None = None,
    duration_ms: int | None = None,
    error_message: str | None = None,
) -> None:
    execute(
        """
        UPDATE searches
           SET status = ?, matched_track_id = ?, confidence = ?,
               duration_ms = ?, error_message = ?, finished_at = datetime('now')
         WHERE id = ?
        """,
        (status, matched_track_id, confidence, duration_ms, error_message, search_id),
    )


def set_report(
    search_id: int, msg_id: int | None, clip_id: int | None = None
) -> None:
    """جای گزارشِ این ناکامی در گروه گردانندگان را به یاد می‌سپارد."""
    execute(
        "UPDATE searches SET report_msg_id = ?, report_clip_id = ? WHERE id = ?",
        (msg_id, clip_id, search_id),
    )


def clear_report(search_id: int) -> None:
    """نشانِ گزارش را برمی‌دارد، پس از آنکه پیام‌ها پاک شدند."""
    execute(
        "UPDATE searches SET report_msg_id = NULL, report_clip_id = NULL"
        " WHERE id = ?",
        (search_id,),
    )


def mark_charged(search_id: int) -> None:
    execute("UPDATE searches SET token_charged = 1 WHERE id = ?", (search_id,))


def mark_refunded(search_id: int) -> bool:
    """
    بازگرداندن توکن را ثبت می‌کند.

    بازگشتی: آیا همین فراخوان آن را دگرگون کرد. اگر پیش‌تر بازگردانده
    شده باشد False می‌دهد — وگرنه کاربر با نواختن دوباره بر «این آن
    نیست» می‌توانست توکن‌های بی‌شمار بستاند.
    """
    cursor = execute(
        """
        UPDATE searches SET token_refunded = 1
         WHERE id = ? AND token_charged = 1 AND token_refunded = 0
        """,
        (search_id,),
    )
    return cursor.rowcount > 0


def set_feedback(search_id: int, feedback: str) -> bool:
    """بازخورد کاربر؛ تنها نخستین بازخورد پذیرفته می‌شود."""
    cursor = execute(
        "UPDATE searches SET feedback = ? WHERE id = ? AND feedback IS NULL",
        (feedback, search_id),
    )
    return cursor.rowcount > 0


# ═════════════════════════════════════════════════════════════
#  راهنمای کاربر
# ═════════════════════════════════════════════════════════════

def set_hint(search_id: int, hint: str | None) -> None:
    """
    آنچه کاربر در پاسخ «نام مداح را می‌دانید؟» نوشت.

    سه جا به کار می‌آید: جست‌وجوی متنی هنگام ناکامی اثر انگشت،
    گزارش ناکامی به گردانندگان (که وگرنه نمی‌دانند دنبال چه
    بگردند)، و پالودن گمانهٔ نواهای همانند.
    """
    execute("UPDATE searches SET hint_text = ? WHERE id = ?", (hint, search_id))


# ═════════════════════════════════════════════════════════════
#  پرکردن ناکامی به دست گردانندگان
# ═════════════════════════════════════════════════════════════

def try_acquire_fill(
    search_id: int, admin_id: int, timeout_seconds: int
) -> tuple[bool, sqlite3.Row | None]:
    """
    می‌کوشد پرکردن این ناکامی را به نام این گرداننده قفل کند.

    همان الگوی core/db/feedbacks.py::try_acquire_lock است و به همان
    دو دلیل: قفل با یک دستور اتمی گرفته می‌شود نه با خواندن و سپس
    نوشتن (وگرنه دو گرداننده که هم‌زمان می‌نوازند هر دو می‌گیرند و
    نوا دوبار برای کاربر می‌رود)، و مهلت دارد (وگرنه گرداننده‌ای که
    دکمه را زد و رفت، آن ناکامی را برای همیشه قفل می‌گذاشت).

    بازگشتی: (آیا گرفته شد، رکورد تازه)
    """
    modifier = f"{int(timeout_seconds):+d} seconds"

    with transaction() as conn:
        cursor = conn.execute(
            """
            UPDATE searches
               SET fill_admin_id   = ?,
                   fill_expires_at = datetime('now', ?)
             WHERE id = ?
               AND status != 'fulfilled'
               AND (
                     fill_admin_id IS NULL
                  OR fill_admin_id = ?
                  OR fill_expires_at IS NULL
                  OR fill_expires_at < datetime('now')
               )
            """,
            (admin_id, modifier, search_id, admin_id),
        )
        acquired = cursor.rowcount > 0

    return acquired, get(search_id)


def release_fill(search_id: int, admin_id: int | None = None) -> bool:
    """قفل پرکردن را رها می‌کند."""
    sql = "UPDATE searches SET fill_admin_id = NULL, fill_expires_at = NULL WHERE id = ?"
    params: list[object] = [search_id]
    if admin_id is not None:
        sql += " AND fill_admin_id = ?"
        params.append(admin_id)
    cursor = execute(sql, params)
    return cursor.rowcount > 0


def current_fill_holder(search_id: int) -> int | None:
    """گرداننده‌ای که هم‌اکنون قفل پرکردن را دارد، یا None."""
    row = query_one(
        """
        SELECT fill_admin_id FROM searches
         WHERE id = ?
           AND fill_admin_id IS NOT NULL
           AND fill_expires_at > datetime('now')
        """,
        (search_id,),
    )
    return int(row["fill_admin_id"]) if row and row["fill_admin_id"] else None


def mark_fulfilled(search_id: int, track_id: int, admin_id: int) -> bool:
    """
    ناکامی‌ای که گرداننده‌ای دستی پرش کرد.

    وضعیت جدا از 'found' است و بی‌سبب نیست: 'found' یعنی موتور
    یافت. اگر این را هم 'found' می‌شمردیم، نرخ کامیابی موتور در
    /engine دروغ می‌گفت — حال آنکه آن سنجه تنها راهی است که
    می‌فهمیم گنجینه از آنچه مردم می‌جویند تهی است یا نه.

    بازگشتی: آیا همین فراخوان دگرگونش کرد (تک‌بارمصرف).
    """
    cursor = execute(
        """
        UPDATE searches
           SET status = 'fulfilled',
               matched_track_id = ?,
               fill_admin_id = ?,
               fill_expires_at = NULL,
               finished_at = datetime('now')
         WHERE id = ? AND status != 'fulfilled'
        """,
        (track_id, admin_id, search_id),
    )
    return cursor.rowcount > 0


def find_cached(input_sha256: str) -> sqlite3.Row | None:
    """
    بازجویی کامیابِ پیشین با همین ورودی.

    تنها بازجویی‌هایی به کار می‌آیند که کاربر نگفته باشد نادرست
    بوده‌اند؛ وگرنه یک پاسخ نادرست برای همیشه به همه داده می‌شد.
    """
    return query_one(
        """
        SELECT * FROM searches
         WHERE input_sha256 = ?
           AND status = 'found'
           AND matched_track_id IS NOT NULL
           AND (feedback IS NULL OR feedback = 'correct')
         ORDER BY (feedback = 'correct') DESC, created_at DESC
         LIMIT 1
        """,
        (input_sha256,),
    )


def recent_failures(limit: int = 20) -> list[sqlite3.Row]:
    """
    بازجویی‌های ناکام تازه — راهنمای اینکه چه چیزی به گنجینه بیفزاییم.
    """
    return query_all(
        """
        SELECT s.*, u.username, u.first_name
          FROM searches s
          LEFT JOIN users u ON u.user_id = s.user_id
         WHERE s.status = 'not_found'
         ORDER BY s.created_at DESC
         LIMIT ?
        """,
        (limit,),
    )


def want_notice(search_id: int) -> None:
    """جوینده خواست که اگر پیدا شد خبرش کنیم."""
    execute(
        "UPDATE searches SET notify_user = 1 WHERE id = ?", (search_id,)
    )


def open_wishes() -> list[sqlite3.Row]:
    """
    خواسته‌هایی که هنوز برآورده نشده‌اند.

    تنها آن‌هایی که کاربر صریح خواسته خبردار شود، و هنوز خبری
    نرفته. بی شرط دوم، هر افزودنِ تازه همان خبر را دوباره
    می‌فرستاد.
    """
    return query_all(
        """
        SELECT * FROM searches
         WHERE notify_user = 1
           AND notified_at IS NULL
           AND COALESCE(NULLIF(TRIM(hint_text), ''), TRIM(query_text)) IS NOT NULL
         ORDER BY created_at
        """
    )


def mark_notified(search_id: int, track_id: int | None = None) -> None:
    """خبر رفت — دوباره نرود."""
    execute(
        """
        UPDATE searches
           SET notified_at = datetime('now'),
               status = 'fulfilled',
               matched_track_id = COALESCE(?, matched_track_id)
         WHERE id = ?
        """,
        (track_id, search_id),
    )


def most_wanted(limit: int = 20) -> list[tuple[str, int, int]]:
    """
    پرخواسته‌ترین نواهایی که **نداریم**.

    ## چرا این هست

    هر بازجویی ناکام از پیش با گمانهٔ خودِ جوینده در دفتر می‌نشیند،
    ولی هیچ‌کس جمعش نمی‌بست. `recent_failures` آن‌ها را یکی‌یکی و
    به ترتیبِ زمان می‌دهد — خوب برای «همین حالا چه شد»، بی‌فایده
    برای «کجا وقت بگذارم».

    این تابع همان داده را **گرد** می‌کند: اگر بیست نفر یک نوا را
    خواسته باشند، یک ردیف با شمارِ بیست دیده می‌شود، نه بیست ردیف
    پراکنده. با گنجینهٔ کوچک، همین فهرست می‌گوید نخست چه بیفزاییم.

    گِردکردن بر شکلِ **هنجار** انجام می‌شود، وگرنه «محمود کریمی» و
    «حاج‌محمود  كريمي» دو چیز شمرده می‌شدند.

    بازگشتی: فهرست (نمایه‌ترین نگارش، شمار خواهندگان، شمار جویندگانِ
    یکتا)، از پرخواسته‌ترین.
    """
    from core.normalize import normalize

    rows = query_all(
        """
        SELECT COALESCE(NULLIF(TRIM(hint_text), ''), TRIM(query_text)) AS term,
               user_id
          FROM searches
         WHERE status = 'not_found'
           AND COALESCE(NULLIF(TRIM(hint_text), ''), TRIM(query_text)) IS NOT NULL
        """
    )

    # شکلِ هنجار کلیدِ گِردکردن است، ولی آنچه نشان داده می‌شود باید
    # نگارشِ راستینِ کاربر باشد — پس پرتکرارترین نگارش نگه داشته
    # می‌شود، نه شکلِ هنجارشده که برای چشم ناخوش است.
    groups: dict[str, dict] = {}
    for row in rows:
        term = (row["term"] or "").strip()
        if not term:
            continue
        key = normalize(term)
        if not key:
            continue
        bucket = groups.setdefault(
            key, {"count": 0, "users": set(), "spellings": {}}
        )
        bucket["count"] += 1
        bucket["users"].add(row["user_id"])
        bucket["spellings"][term] = bucket["spellings"].get(term, 0) + 1

    out = [
        (
            max(data["spellings"].items(), key=lambda kv: kv[1])[0],
            data["count"],
            len(data["users"]),
        )
        for data in groups.values()
    ]
    out.sort(key=lambda item: (-item[1], -item[2]))
    return out[:limit]


def success_rate(days: int = 7) -> tuple[int, int]:
    """(شمار کامیاب، شمار همه) در بازهٔ گذشته."""
    row = query_one(
        """
        SELECT SUM(status = 'found') AS ok, COUNT(*) AS total
          FROM searches
         WHERE created_at >= datetime('now', ?)
           AND status IN ('found', 'not_found')
        """,
        (f"-{int(days)} days",),
    )
    if row is None or not row["total"]:
        return 0, 0
    return int(row["ok"] or 0), int(row["total"])


def by_user(user_id: int, limit: int = 20) -> list[sqlite3.Row]:
    return query_all(
        "SELECT * FROM searches WHERE user_id = ? ORDER BY created_at DESC LIMIT ?",
        (user_id, limit),
    )
