-- ═══════════════════════════════════════════════════════════════
--  حدیث عشق — ساختار پایگاه داده
--  این پرونده هنگام آغاز به کار برنامه به‌صورت خودکار اجرا می‌شود.
--  همهٔ دستورها با IF NOT EXISTS نوشته شده‌اند تا اجرای دوباره
--  بی‌خطر باشد.
-- ═══════════════════════════════════════════════════════════════

PRAGMA foreign_keys = ON;


-- ───────────────────────────────────────────────────────────────
--  کاربران
-- ───────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS users (
    user_id         INTEGER PRIMARY KEY,          -- شناسهٔ عددی تلگرام
    username        TEXT,
    first_name      TEXT,
    last_name       TEXT,

    tokens          INTEGER NOT NULL DEFAULT 0,
    is_verified     INTEGER NOT NULL DEFAULT 0,   -- عضویت کانال تأیید شده؟
    tapped_instagram INTEGER NOT NULL DEFAULT 0,  -- دکمهٔ پیج را زده؟

    is_banned       INTEGER NOT NULL DEFAULT 0,
    ban_reason      TEXT,

    -- همراهی که گردانندگان به او اعتماد کرده‌اند: پیشکشش بی داوری
    -- یک‌راست به گنجینه می‌رود. سنجش تکراری همچنان بر او هم روا
    -- می‌شود، وگرنه یک فایل را بارها می‌فرستاد و بی‌پایان سکه می‌ستاند.
    is_trusted      INTEGER NOT NULL DEFAULT 0,
    trusted_by      INTEGER,
    trusted_at      TEXT,

    -- اگر کاربر ربات را مسدود کند اینجا نشانه‌گذاری می‌شود
    -- تا در همگانی‌رسانی بیهوده تلاش نشود.
    is_blocked_bot  INTEGER NOT NULL DEFAULT 0,

    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at      TEXT NOT NULL DEFAULT (datetime('now')),
    last_seen_at    TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_users_verified ON users(is_verified, is_banned, is_blocked_bot);


-- ───────────────────────────────────────────────────────────────
--  دفتر توکن — هر تغییر موجودی اینجا ثبت می‌شود.
--  ستون tokens در جدول users تنها خلاصهٔ همین دفتر است؛
--  داشتن دفتر، پیگیری اختلاف حساب و بازگرداندن توکن را ممکن می‌کند.
-- ───────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS token_ledger (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    delta       INTEGER NOT NULL,                 -- مثبت یا منفی
    balance     INTEGER NOT NULL,                 -- موجودی پس از این تغییر
    reason      TEXT NOT NULL,                    -- initial | search | refund | contribution | admin
    ref_type    TEXT,                             -- search | submission | manual
    ref_id      INTEGER,
    note        TEXT,
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_ledger_user ON token_ledger(user_id, created_at DESC);


-- ───────────────────────────────────────────────────────────────
--  آرشیو مداحی‌ها
--
--  فایل صوتی روی دیسک نگهداری نمی‌شود؛ به جای آن file_id تلگرام
--  ذخیره می‌گردد و ارسال دوباره بی‌درنگ و بدون بارگذاری مجدد
--  انجام می‌شود. تنها اثر انگشت و شناسنامه محلی می‌ماند.
-- ───────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS tracks (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    uuid            TEXT NOT NULL UNIQUE,

    -- شناسهٔ فایل در تلگرام
    file_id         TEXT,
    file_unique_id  TEXT UNIQUE,                  -- برای یافتن تکراری‌های آشکار

    -- شناسنامه
    title           TEXT,
    madah           TEXT,                         -- نام مداح
    style           TEXT,                         -- شور | واحد | زمینه | تک | لطمه | روضه
    title_norm      TEXT,                         -- شکل هنجارشده برای جست‌وجوی متنی
    madah_norm      TEXT,
    lyrics_snippet  TEXT,                         -- بیتی از متن، برای جلد و جست‌وجو

    duration        INTEGER,                      -- ثانیه
    file_size       INTEGER,                      -- بایت
    sha256          TEXT,                         -- برای یافتن تکراری دقیق

    -- خاستگاه
    source          TEXT NOT NULL,                -- channel | user | crawler | admin
    source_url      TEXT,
    source_chat_id  INTEGER,
    source_msg_id   INTEGER,
    added_by        INTEGER,

    is_indexed      INTEGER NOT NULL DEFAULT 0,   -- اثر انگشت ساخته شده؟
    is_active       INTEGER NOT NULL DEFAULT 1,

    -- چند بار این نوا به دست کسی رسیده. زیر فایلی که می‌فرستیم
    -- نوشته می‌شود. جدا از شمار جست‌وجوهاست: نوا از چند راه
    -- می‌رود (یافتن، جست‌وجوی متنی، گمانه، سایت) و همه شمرده
    -- می‌شوند.
    sent_count      INTEGER NOT NULL DEFAULT 0,

    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_tracks_madah   ON tracks(madah_norm);
CREATE INDEX IF NOT EXISTS idx_tracks_style   ON tracks(style);
CREATE INDEX IF NOT EXISTS idx_tracks_sha     ON tracks(sha256);
CREATE INDEX IF NOT EXISTS idx_tracks_pending ON tracks(is_indexed) WHERE is_indexed = 0;

-- فهرست «محبوب‌ترین‌ها». بی این، هر بار کلِ جدول پویش می‌شد و
-- سپس در یک درختِ موقت مرتب — با دو هزار نوا، کاری بیهوده که
-- ایندکس از پیش انجامش داده است.
CREATE INDEX IF NOT EXISTS idx_tracks_popular
    ON tracks(sent_count DESC, id DESC) WHERE is_active = 1;


-- ───────────────────────────────────────────────────────────────
--  اثر انگشت صوتی
--
--  WITHOUT ROWID با کلید اصلی آغازشده به hash، جدول را بر پایهٔ
--  hash خوشه‌بندی می‌کند؛ یعنی جست‌وجوی «این هش در کدام آهنگ‌هاست»
--  یک پویش پیوسته است نه پرش‌های پراکنده روی دیسک. برای ده‌ها
--  میلیون سطر تفاوت آن چشمگیر است و فضای کمتری هم می‌گیرد.
-- ───────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS fingerprints (
    hash        INTEGER NOT NULL,
    track_id    INTEGER NOT NULL,
    offset_ms   INTEGER NOT NULL,
    PRIMARY KEY (hash, track_id, offset_ms)
) WITHOUT ROWID;

CREATE INDEX IF NOT EXISTS idx_fp_track ON fingerprints(track_id);


-- ───────────────────────────────────────────────────────────────
--  جست‌وجوها — هم برای بازگرداندن توکن، هم برای کشِ نتیجه،
--  هم برای گزارش جست‌وجوهای ناکام (که می‌گوید چه چیزی کم داریم)
-- ───────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS searches (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id         INTEGER NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,

    input_kind      TEXT NOT NULL,                -- audio | video | voice | instagram | text
    input_sha256    TEXT,                         -- کلید کش
    input_file_id   TEXT,
    input_duration  INTEGER,
    query_text      TEXT,

    -- آنچه کاربر در پاسخ «نام مداح را می‌دانید؟» نوشت.
    -- هم جست‌وجوی متنی از آن بهره می‌برد، هم گزارش ناکامی به
    -- گردانندگان — که وگرنه تنها یک شناسهٔ عددی می‌بینند و
    -- نمی‌دانند دنبال چه بگردند.
    hint_text       TEXT,

    -- گرداننده‌ای که پرکردن این ناکامی را بر عهده گرفته است.
    -- همان الگوی قفل feedbacks: اتمی و مهلت‌دار، تا دو گرداننده
    -- یک نوا را دوبار نفرستند و قفلِ رهاشده برای همیشه نماند.
    fill_admin_id   INTEGER,
    fill_expires_at TEXT,

    -- گزارش این ناکامی در گروه گردانندگان کجا نشست.
    -- اگر خودِ کاربر نسخهٔ کامل را بفرستد، همان گزارش برداشته
    -- می‌شود؛ کارِ گردانندگان دیگر لازم نیست.
    report_msg_id   INTEGER,
    report_clip_id  INTEGER,

    status          TEXT NOT NULL DEFAULT 'pending',  -- pending | found | not_found | failed | fulfilled
    matched_track_id INTEGER REFERENCES tracks(id) ON DELETE SET NULL,
    confidence      REAL,

    feedback        TEXT,                         -- correct | wrong | (تهی: بی‌پاسخ)
    token_charged   INTEGER NOT NULL DEFAULT 0,
    token_refunded  INTEGER NOT NULL DEFAULT 0,

    error_message   TEXT,
    duration_ms     INTEGER,                      -- زمان پردازش، برای تخمین بهتر دفعهٔ بعد

    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    finished_at     TEXT
);

CREATE INDEX IF NOT EXISTS idx_searches_user  ON searches(user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_searches_cache ON searches(input_sha256, status);
CREATE INDEX IF NOT EXISTS idx_searches_fail  ON searches(status, created_at DESC);


-- ───────────────────────────────────────────────────────────────
--  مداحی‌های پیشنهادی کاربران (در انتظار تأیید ادمین)
-- ───────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS submissions (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id         INTEGER NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,

    file_id         TEXT NOT NULL,
    file_unique_id  TEXT,
    file_name       TEXT,
    duration        INTEGER,
    sha256          TEXT,

    madah           TEXT,
    style           TEXT,

    -- بیتی از شعر که پیشکش‌کننده نوشته؛ نام نوا از همین ساخته
    -- می‌شود و هم روی فایل می‌نشیند، هم روی جلد، هم کلید یافتنش
    -- در جست‌وجوی متنی می‌گردد.
    title           TEXT,

    status          TEXT NOT NULL DEFAULT 'pending',  -- pending | approved | rejected | duplicate
    is_duplicate_of INTEGER REFERENCES tracks(id) ON DELETE SET NULL,

    group_msg_id    INTEGER,                      -- پیام در گروه مداحی
    reviewed_by     INTEGER,
    reviewed_at     TEXT,
    track_id        INTEGER REFERENCES tracks(id) ON DELETE SET NULL,

    -- اگر از دکمهٔ «کامل این مداحی» در جریان جست‌وجو آمده باشد
    origin_search_id INTEGER REFERENCES searches(id) ON DELETE SET NULL,

    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_sub_status ON submissions(status, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_sub_user   ON submissions(user_id, created_at DESC);


-- ───────────────────────────────────────────────────────────────
--  نقد و انتقادات — با قفل پاسخگویی و مهلت زمانی،
--  تا اگر ادمینی دکمه را زد و رها کرد، قفل برای همیشه نماند.
-- ───────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS feedbacks (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id         INTEGER NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,

    content_kind    TEXT NOT NULL,                -- text | photo | audio | video | voice | document
    content_text    TEXT,
    file_id         TEXT,

    group_msg_id    INTEGER,

    lock_admin_id   INTEGER,                      -- ادمینی که در حال پاسخ است
    lock_expires_at TEXT,                         -- مهلت قفل

    status          TEXT NOT NULL DEFAULT 'open', -- open | answering | answered
    answered_by     INTEGER,
    answered_at     TEXT,

    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_fb_status ON feedbacks(status, created_at DESC);


-- ───────────────────────────────────────────────────────────────
--  همگانی‌رسانی
-- ───────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS broadcasts (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    admin_id        INTEGER NOT NULL,
    from_chat_id    INTEGER,
    from_msg_id     INTEGER,
    status          TEXT NOT NULL DEFAULT 'pending',  -- pending | running | done | cancelled
    total           INTEGER NOT NULL DEFAULT 0,
    sent            INTEGER NOT NULL DEFAULT 0,
    failed          INTEGER NOT NULL DEFAULT 0,
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    finished_at     TEXT
);


-- ───────────────────────────────────────────────────────────────
--  کانال‌های عضویت اجباری
--
--  کاربر باید در همهٔ این‌ها عضو باشد تا بتواند از ربات بهره ببرد.
--  تا پیش از این تنها یکی بود و در .env سفت شده بود؛ عوض کردنش
--  بازراه‌اندازی می‌خواست. اکنون با دستور افزوده و برداشته می‌شود،
--  تا بشود کانالِ دیگران را هم برای مدتی تبلیغ کرد.
--
--  ردیف هرگز پاک نمی‌شود، تنها is_active صفر می‌گردد: تاریخچهٔ
--  «چه کسی کِی افزود» می‌ماند.
-- ───────────────────────────────────────────────────────────────
-- پیام‌های **گذرای** ربات در گروه‌ها.
--
-- ## چرا تنها گذراها
--
-- در گروه بایگانی، پیام‌های ربات همان نواهای بایگانی‌شده‌اند —
-- پاک کردنشان یعنی نابود کردنِ بایگانی. پس تنها چیزهایی اینجا
-- ثبت می‌شوند که کارشان تمام شده و ماندنشان تنها شلوغی است:
-- گزارش ناکامی، کارتِ داوری، پیام وضعیت.
--
-- نوایی که در گروه بایگانی می‌نشیند **هرگز** اینجا ثبت نمی‌شود،
-- پس /clean هرگز نمی‌تواند برش دارد.
-- نام‌های مستعارِ مداحان: هر نگارشی ← نامِ درست.
--
-- ## چرا
--
-- یک مداح در برچسب فایل‌ها ده جور نوشته می‌شود: فینگلیش
-- (morteza yebovkzhad)، تنها نام خانوادگی (Borna)، یا با
-- غلط املایی. هر کدام یک ردیفِ جدا در گنجینه می‌ساخت و
-- «همهٔ مداحی‌های فلانی» هرگز کامل نبود.
--
-- این جدول هر بار که گرداننده نامی را **اصلاح** کند پر
-- می‌شود، پس ربات از تصحیح‌های خودِ آدم‌ها یاد می‌گیرد.
-- نواهایی که ربات خودش از تارنماها یافته و در انتظار داوری‌اند.
--
-- ## چرا صف، و نه افزودنِ مستقیم
--
-- شناسنامهٔ تارنماها اغلب ناقص یا نادرست است، و آنچه «مداحی»
-- خوانده می‌شود گاه سخنرانی یا تیزر است. افزودنِ بی‌داوری،
-- گنجینه را با آشغال پر می‌کرد — و پاک کردنشان بسی سخت‌تر از
-- نپذیرفتنشان است.
--
-- پس هر یافته اینجا می‌نشیند تا گرداننده در گروه بایگانی
-- بشنود و تأیید کند. پیش از تأیید، در `tracks` خبری نیست.
CREATE TABLE IF NOT EXISTS harvest_queue (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    site        TEXT NOT NULL,
    page_url    TEXT NOT NULL UNIQUE,
    file_url    TEXT,
    title       TEXT,
    madah       TEXT,
    duration    INTEGER,
    file_id     TEXT,               -- پس از بارگذاری در تلگرام
    file_unique_id TEXT,
    card_msg_id INTEGER,            -- کارتِ داوری در گروه بایگانی
    status      TEXT NOT NULL DEFAULT 'pending',  -- pending|approved|rejected
    track_id    INTEGER,            -- پس از پذیرش
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_harvest_status
    ON harvest_queue(status, created_at);

CREATE TABLE IF NOT EXISTS madah_aliases (
    alias_key   TEXT PRIMARY KEY,          -- اسکلتِ آواییِ نگارشِ دیده‌شده
    alias_text  TEXT NOT NULL,             -- خودِ نگارش، برای گزارش
    canonical   TEXT NOT NULL,             -- نامِ درست
    added_by    INTEGER,
    hits        INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_madah_aliases_canonical
    ON madah_aliases(canonical);

CREATE TABLE IF NOT EXISTS bot_messages (
    chat_id     INTEGER NOT NULL,
    message_id  INTEGER NOT NULL,
    kind        TEXT,
    created_at  TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (chat_id, message_id)
);

CREATE INDEX IF NOT EXISTS idx_bot_messages_chat
    ON bot_messages(chat_id, created_at);

CREATE TABLE IF NOT EXISTS required_channels (
    chat_id     INTEGER PRIMARY KEY,
    title       TEXT,
    url         TEXT NOT NULL,
    added_by    INTEGER,
    added_at    TEXT NOT NULL DEFAULT (datetime('now')),
    is_active   INTEGER NOT NULL DEFAULT 1
);


-- ───────────────────────────────────────────────────────────────
--  کانال‌های منبع
--
--  کانال‌های مداحی که مدیرانشان ربات را در آن‌ها مدیر کرده‌اند. هر
--  فایل تازه‌ای که آنجا گذاشته شود خودکار به آرشیو می‌آید.
--
--  ⚠️ ربات تلگرام هیچ راهی برای خواندن پست‌های **گذشتهٔ** کانال
--  ندارد؛ تلگرام چنین امکانی نمی‌دهد. پس تنها از لحظه‌ای که کانال
--  افزوده می‌شود به بعد کار می‌کند.
-- ───────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS source_channels (
    chat_id     INTEGER PRIMARY KEY,
    title       TEXT,
    url         TEXT NOT NULL,
    added_by    INTEGER,
    added_at    TEXT NOT NULL DEFAULT (datetime('now')),
    is_active   INTEGER NOT NULL DEFAULT 1
);


-- ───────────────────────────────────────────────────────────────
--  تنظیمات زمان اجرا (کلید/مقدار) — برای کلیدهایی که ادمین
--  می‌تواند بی‌آنکه ربات را از نو راه بیندازد تغییر دهد.
-- ───────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS settings (
    key         TEXT PRIMARY KEY,
    value       TEXT NOT NULL,
    updated_at  TEXT NOT NULL DEFAULT (datetime('now'))
);


-- ───────────────────────────────────────────────────────────────
--  نسخهٔ ساختار — برای مهاجرت‌های آینده
-- ───────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS schema_version (
    version     INTEGER PRIMARY KEY,
    applied_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

INSERT OR IGNORE INTO schema_version (version) VALUES (1);
