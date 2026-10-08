# Graph Report - .  (2026-08-20)

## Corpus Check
- cluster-only mode — file stats not available

## Summary
- 1115 nodes · 2854 edges · 55 communities (52 shown, 3 thin omitted)
- Extraction: 99% EXTRACTED · 1% INFERRED · 0% AMBIGUOUS · INFERRED: 36 edges (avg confidence: 0.58)
- Token cost: 0 input · 0 output

## Community Hubs (Navigation)
- intake.py
- msg
- admin.py
- curation.py
- melody_store.py
- crawler.py
- Classifier
- search.py
- decode
- to_persian_digits
- clear_state
- JobQueue
- btn
- indexer.py
- inline.py
- instagram.py
- config.py
- execute
- main.py
- extract
- main
- fingerprints.py
- database.py
- searches.py
- router.py
- _TextStore
- start.py
- feedbacks.py
- archive.py
- smoke_test.py
- query_one
- pipeline_test.py
- features_store.py
- add_track
- enable_utf8_console
- Match
- _deliver
- setup_project.py
- FakeQuery
- signature
- synth
- commands.py
- _reply
- example/.opencode/plugins/graphify.js
- .opencode/plugins/graphify.js

## God Nodes (most connected - your core abstractions)
1. `msg()` - 85 edges
2. `main()` - 68 edges
3. `execute()` - 64 edges
4. `query_one()` - 47 edges
5. `clear_state()` - 46 edges
6. `set_state()` - 34 edges
7. `query_all()` - 33 edges
8. `to_persian_digits()` - 31 edges
9. `btn()` - 28 edges
10. `get_data()` - 25 edges

## Surprising Connections (you probably didn't know these)
- `store()` --indirect_call--> `version()`  [INFERRED]
  core/db/features_store.py → services/instagram.py
- `IndexError_` --uses--> `DecodeError`  [INFERRED]
  services/indexer.py → core/audio/decode.py
- `IndexError_` --uses--> `FeatureError`  [INFERRED]
  services/indexer.py → core/audio/features.py
- `IndexError_` --uses--> `Fingerprint`  [INFERRED]
  services/indexer.py → core/audio/fingerprint.py
- `IndexError_` --uses--> `FingerprintError`  [INFERRED]
  services/indexer.py → core/audio/fingerprint.py

## Import Cycles
- None detected.

## Communities (55 total, 3 thin omitted)

### Community 0 - "intake.py"
Cohesion: 0.06
Nodes (71): _ask_title(), _card_text(), _clean(), _commit(), _fa(), _finalize(), _finish(), _fulfil() (+63 more)

### Community 1 - "msg"
Cohesion: 0.09
Nodes (54): _accept_trusted(), _approve(), begin(), _grant_trust(), _index_new_track(), _mark_caption(), _notify_user(), on_edit_back() (+46 more)

### Community 2 - "admin.py"
Cohesion: 0.08
Nodes (51): admin_only(), تنها گردانندگان می‌گذرند. غیرگرداننده خاموش رد می‌شود — پاسخ ندادن، بهتر از…, backup_now(), begin_broadcast(), crawl_status(), engine(), _fa(), failures() (+43 more)

### Community 3 - "curation.py"
Cohesion: 0.08
Nodes (50): add_admin(), begin_bulk(), begin_delete(), end_bulk(), _fa(), _finish_bulk(), list_admins(), on_bulk_audio() (+42 more)

### Community 4 - "melody_store.py"
Cohesion: 0.06
Nodes (43): compare(), from_bytes(), MelodyMatch, _profile(), ndarray, نشان خطِ آهنگ — لایهٔ سومِ تشخیص.…, یک نوای گنجینه که خطِ آهنگش به پارهٔ کاربر می‌ماند., اطمینان میان ۰ و ۱. هم‌بستگیِ خام از ۰٫۸۶ به بالا معنا دارد، پس همان بازه به… (+35 more)

### Community 5 - "crawler.py"
Cohesion: 0.06
Nodes (48): fix_display(), نویسه‌های عربی را به همتای پارسی برمی‌گرداند، ولی تنها آنجا که معنا را دگرگون…, crawl_all(), crawl_site(), CrawlError, discover(), _ensure_table(), fetch_file() (+40 more)

### Community 6 - "Classifier"
Cohesion: 0.07
Nodes (27): Classifier, get_classifier(), Guess, ndarray, گمانه‌زنی سبک و مداح.…, گمانه‌زن سبک و مداح. درون حافظه نگه داشته می‌شود و با فرمان گردانندگان از نو…, از نواهای برچسب‌خوردهٔ گنجینه آموزش می‌بیند. بازگشتی: (شمار مداح، شمار سبک،…, تصویری می‌سازد که مداحان را از هم دور و ضبط‌های یک مداح را به هم نزدیک کند. اگر… (+19 more)

### Community 7 - "search.py"
Cohesion: 0.08
Nodes (43): _after_failure(), clip_path(), _deliver_clip_after_wrong(), _fingerprint_and_match(), _hash_file(), _launch(), _not_found(), _offer_similar() (+35 more)

### Community 8 - "decode"
Cohesion: 0.08
Nodes (34): decode(), DecodeError, extract_audio(), ffmpeg_path(), probe_duration(), ndarray, Path, RuntimeError (+26 more)

### Community 9 - "to_persian_digits"
Cohesion: 0.08
Nodes (35): _empty_article(), _hint_article(), on_inline_query(), on_text_search(), DEFAULT_TYPE, Update, جست‌وجوی متنی و حالت درون‌خطی. ## چرا این بخش، با آنکه در سند نبود، افزوده شد…, کاربر در گفتگویی دیگر ‎@YourBot ...‎ نوشته است. نکتهٔ سنجش دسترسی: در حالت… (+27 more)

### Community 10 - "clear_state"
Cohesion: 0.11
Nodes (37): _amend_failure_report(), begin(), begin_for_file(), on_cancel(), on_hint(), on_hint_after_fail(), on_hint_skip(), on_input() (+29 more)

### Community 11 - "JobQueue"
Cohesion: 0.07
Nodes (22): Boom, busy(), failing(), main(), RuntimeError, آزمون بار — بیست بازجویی هم‌زمان. اجرا: python tests/load_test.py سنگین‌ترین…, همان گونه خطایی که DecodeError و FingerprintError‌اند., حلقهٔ پایتونیِ خالص — **بدترین حالت**، نه کار راستین. قفل مفسر را در سراسر کار… (+14 more)

### Community 12 - "btn"
Cohesion: 0.10
Nodes (28): نگهبانان دسترسی. سه شرط پیش از هر کار سنجیده می‌شود: کاربر بن نباشد،…, تنها کاربری که بن نیست و هم‌نشینی‌اش تأیید شده، می‌گذرد. کاربر ناشناخته هم رد…, require_verified(), cancel(), DEFAULT_TYPE, Update, مسیریابی منوی اصلی. هر دکمهٔ منو نخست وضعیت پیشین را پاک می‌کند. این یک سطر،…, از هر جریانی که کاربر در آن است بیرون می‌آید. (+20 more)

### Community 13 - "indexer.py"
Cohesion: 0.12
Nodes (27): Bot, get_setting(), ensure_table(), جدول را می‌سازد. اجرای دوباره بی‌خطر است., ensure_table(), جدول را می‌سازد. اجرای دوباره بی‌خطر است., download(), finalize_track() (+19 more)

### Community 14 - "inline.py"
Cohesion: 0.10
Nodes (26): ناکامی را با **خودِ کلیپ** به گروه گردانندگان می‌برد. پیش‌تر تنها یک شناسهٔ…, _report_failure(), delete_candidates(), delete_confirm(), failure_fill(), forwarded_choice(), intake_back(), intake_card() (+18 more)

### Community 15 - "instagram.py"
Cohesion: 0.11
Nodes (23): _looks_like_query(), آیا کاربر بی‌مقدمه چیزی فرستاده که روشن است می‌خواهد بجوید. آوا، نماهنگ و نشانی…, Exception, _cookies_file(), download(), find_url(), InstagramError, InstagramVideo (+15 more)

### Community 16 - "config.py"
Cohesion: 0.14
Nodes (17): _chat_id(), Config, ConfigError, _float(), _id_list(), _int(), load_config(), _optional() (+9 more)

### Community 17 - "execute"
Cohesion: 0.10
Nodes (24): execute(), mark_blocked_bot(), همراهی را مورد اعتماد می‌کند یا اعتماد را پس می‌گیرد. اعتماد یعنی پیشکش او بی…, کاربری که ربات را مسدود کرده، تا از همگانی‌رسانی کنار گذاشته شود., گردانندگی را می‌دهد یا پس می‌گیرد., set_db_admin(), set_trusted(), delete_for_track() (+16 more)

### Community 18 - "main.py"
Cohesion: 0.13
Nodes (24): آوای استخراجیِ کهنه را برمی‌دارد. این فایل‌ها تنها برای آنند که اگر کاربر «این…, sweep_clips(), retrain(), پیکربندی گزارش‌برداری. گزارش‌ها هم روی پرده و هم در پرونده نوشته می‌شوند.…, setup_logging(), _at(), build_application(), _fail() (+16 more)

### Community 19 - "extract"
Cohesion: 0.14
Nodes (22): _guess_similar(), گمانهٔ نواهای همانند، هنگامی که اثر انگشت چیزی نیافت. این پاسخ قطعی نیست و هرگز…, _center_slice(), describe_tempo(), extract(), extract_file(), FeatureError, _pulse_clarity() (+14 more)

### Community 20 - "main"
Cohesion: 0.17
Nodes (19): begin(), _detect_kind(), on_admin_reply(), on_content(), on_release_tap(), on_reply_tap(), DEFAULT_TYPE, Update (+11 more)

### Community 21 - "fingerprints.py"
Cohesion: 0.14
Nodes (18): Connection, _connect(), get_connection(), نوا را از گنجینه برمی‌دارد. سه چیز با هم برداشته می‌شود، وگرنه گنجینه ناسازگار…, یک اتصال به ازای هر ریسه؛ اتصال‌ها میان ریسه‌ها به اشتراک گذاشته نمی‌شوند., تراکنش با بازگردانی خودکار در صورت خطا. هر جا چند نوشتن باید با هم انجام شوند…, remove_track(), transaction() (+10 more)

### Community 22 - "database.py"
Cohesion: 0.17
Nodes (18): find_duplicate_track(), list_db_admins(), list_trusted(), Row, query_all(), لایهٔ دسترسی به پایگاه داده. همهٔ کار با SQLite از همین جا می‌گذرد. دو نکتهٔ…, کاربر را می‌سازد یا شناسنامه‌اش را تازه می‌کند. بازگشتی: (رکورد کاربر، آیا تازه…, تکراری آشکار را پیش از افزودن می‌یابد. این جلوی سوءاستفاده را می‌گیرد: کاربر… (+10 more)

### Community 23 - "searches.py"
Cohesion: 0.13
Nodes (18): by_user(), find_cached(), get(), mark_fulfilled(), mark_refunded(), Row, دفتر بازجویی‌ها. سه کار از این دفتر برمی‌آید که هر سه در سند خواسته یا لازم…, می‌کوشد پرکردن این ناکامی را به نام این گرداننده قفل کند. همان الگوی… (+10 more)

### Community 24 - "router.py"
Cohesion: 0.16
Nodes (16): cancel(), `/cancel` در میانهٔ پذیرش. بازگشتی می‌گوید آیا پذیرشی بود که بسته شود — تا…, _cancel(), _is_admin(), _is_forwarded_audio(), _looks_like_name(), _on_private_text_or_media(), Application (+8 more)

### Community 25 - "_TextStore"
Cohesion: 0.13
Nodes (11): MissingPlaceholder, Any, کلید خواسته‌شده در گنجینهٔ نوشتارها نیست., نوشتار جای‌گاهی دارد که مقدارش داده نشده است., نوشتار خام، بی‌آنکه جای‌گاهی پر شود., نوشتار را با پر شدن جای‌گاه‌ها برمی‌گرداند. >>> texts.get("welcome",…, شناسهٔ برچسب یا None اگر تعریف نشده باشد. تهی بودن، خطا نیست: برچسب‌ها تدریجی…, _StickerStore (+3 more)

### Community 26 - "start.py"
Cohesion: 0.21
Nodes (16): _fa(), is_channel_member(), on_check_membership(), on_instagram_tap(), DEFAULT_TYPE, Update, آغاز و آستانهٔ ورود. جریان کار: /start ← پیام خوش‌آمد با سه دکمه ← کاربر در…, نواختن بر دکمهٔ صفحه را ثبت می‌کند و دکمه را به پیوند راستین دگرگون می‌سازد.… (+8 more)

### Community 27 - "feedbacks.py"
Cohesion: 0.15
Nodes (15): by_user(), create(), current_lock_holder(), get(), mark_answered(), open_count(), Row, نقد و انتقادات کاربران، همراه با قفل پاسخ‌گویی. سند خواسته بود وقتی گرداننده‌ای… (+7 more)

### Community 28 - "archive.py"
Cohesion: 0.16
Nodes (18): ask_forwarded(), _index_later(), _ingest(), on_channel_post(), on_forward_add(), on_forward_seek(), DEFAULT_TYPE, Update (+10 more)

### Community 29 - "smoke_test.py"
Cohesion: 0.12
Nodes (9): close_connection(), FakeBot, FakeMessage, mk_ctx(), mk_update(), آزمون دود — جریان‌های مرحله ۲ با ربات بدلی رانده می‌شوند. اجرا: python…, کارِ پس‌زمینه در آزمون اجرا نمی‌شود؛ تنها بسته می‌شود., _swallow() (+1 more)

### Community 30 - "query_one"
Cohesion: 0.14
Nodes (14): count_tracks(), count_users(), is_db_admin(), Any, query_one(), آیا این کاربر را مالک، گرداننده کرده است. جدا از ADMIN_IDS در .env نگه داشته…, count(), count_for_track() (+6 more)

### Community 31 - "pipeline_test.py"
Cohesion: 0.20
Nodes (13): init_db(), _migrate(), ستون‌های نوافزوده را می‌نشاند، اگر نباشند. SQLite هنوز ADD COLUMN IF NOT EXISTS…, ساختار را می‌سازد. اجرای دوباره بی‌خطر است., cleanup(), cut(), cut_video(), main() (+5 more)

### Community 32 - "features_store.py"
Cohesion: 0.18
Nodes (13): all_vectors(), delete_for_track(), get(), has(), labelled(), pending(), Row, انبار ویژگی‌های صوتی. جدا از جدول اثر انگشت است، چون کارشان یکی نیست: اثر انگشت… (+5 more)

### Community 33 - "add_track"
Cohesion: 0.21
Nodes (12): _create_track(), نوا را از روی پیشکش در گنجینه می‌نشاند. عنوان، بیت شعری است که کاربر نوشت؛ اگر…, add_track(), new_uuid(), مداحی تازه در آرشیو ثبت می‌کند و شناسهٔ آن را برمی‌گرداند., add_noise(), cleanup(), main() (+4 more)

### Community 34 - "enable_utf8_console"
Cohesion: 0.40
Nodes (3): enable_utf8_console(), درست کردن رمزگذاری پایانهٔ ویندوز. پایانهٔ پیش‌فرض ویندوز با cp1252 کار می‌کند…, خروجی و خطای استاندارد را به UTF-8 برمی‌گرداند. errors="replace" گذاشته شده تا…

### Community 35 - "Match"
Cohesion: 0.20
Nodes (8): _best_alignment(), Match, match_many(), ndarray, برای هر نوا، بلندترین ستون بافهٔ فاصله را می‌یابد. بازگشتی: (شناسهٔ نوا، بلندی…, چند تطبیق برتر را برمی‌گرداند، هر نوا تنها یک بار. برای هنگامی که اطمینان کم…, اطمینان میان ۰ و ۱، برای نمایش به کاربر. نسبت خام هم‌راستایی هرگز به یک نمی‌رسد…, بهترین تطبیق را در گنجینه می‌جوید. None یعنی هیچ نوایی به اندازهٔ بسنده…

### Community 36 - "_deliver"
Cohesion: 0.20
Nodes (10): _bar(), _deliver(), نوای یافته‌شده را می‌فرستد و سکه را برمی‌دارد. سکه پس از فرستادن کامیاب برداشته…, نوار دیداری همانندی — سند نمایش تصویری درصد را خواسته بود., adjust_tokens(), InsufficientTokens, RuntimeError, موجودی توکن کاربر برای این کار بس نیست. (+2 more)

### Community 37 - "setup_project.py"
Cohesion: 0.42
Nodes (9): check_config_and_db(), check_ffmpeg(), check_texts(), ensure_directories(), ensure_env_file(), main(), اگر .env نبود، از روی .env.example می‌سازد. بازگشتی: آیا .env آمادهٔ استفاده…, ffmpeg با pip نصب نمی‌شود و نبودنش، مرحلهٔ پردازش صوت را خاموش از کار… (+1 more)

### Community 39 - "signature"
Cohesion: 0.33
Nodes (7): MelodyError, RuntimeError, ساختن نشان خطِ آهنگ شدنی نبود., نشان خطِ آهنگ: آرایه‌ای ۱۲×N از float32، هر ستون هنجارشده. ستون‌ها زمان‌اند و…, هموار می‌کند، نمونه‌برداری را کم می‌کند، و هر ستون را هنجار. هموارسازی پیش از…, signature(), _smooth_and_normalize()

### Community 40 - "synth"
Cohesion: 0.38
Nodes (7): _crowd(), ndarray, پژواک مجلس — هم‌آمیزی با دنبالهٔ فروکش نمایی. این همان چیزی است که در ضبط…, جواب جمعیت — انفجارهای نویز پهن‌باند روی ضرب., یک ضبط مجلسی ساختگی می‌سازد., _reverb(), synth()

### Community 41 - "commands.py"
Cohesion: 0.40
Nodes (5): _commands(), publish(), فهرست دستورها — همان که در تلگرام با دکمهٔ «/» کنار کادر نوشتن گشوده می‌شود. ##…, فهرست‌ها را به تلگرام می‌سپارد. ناکامی هیچ‌کدام کار را نمی‌ایستاند: نبودِ فهرست…, BotCommand

### Community 43 - "_reply"
Cohesion: 0.67
Nodes (3): Update, پاسخ می‌دهد، چه از پیام آمده باشد چه از دکمهٔ درون‌خطی., _reply()

## Knowledge Gaps
- **3 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `main()` connect `main` to `intake.py`, `msg`, `admin.py`, `curation.py`, `Classifier`, `search.py`, `clear_state`, `JobQueue`, `btn`, `execute`, `database.py`, `searches.py`, `router.py`, `start.py`, `feedbacks.py`, `archive.py`, `smoke_test.py`, `query_one`, `FakeQuery`?**
  _High betweenness centrality (0.066) - this node is a cross-community bridge._
- **Why does `execute()` connect `execute` to `intake.py`, `msg`, `admin.py`, `melody_store.py`, `crawler.py`, `Classifier`, `search.py`, `clear_state`, `JobQueue`, `indexer.py`, `main`, `fingerprints.py`, `database.py`, `searches.py`, `feedbacks.py`, `query_one`, `pipeline_test.py`, `features_store.py`, `add_track`, `_deliver`?**
  _High betweenness centrality (0.055) - this node is a cross-community bridge._
- **Should `intake.py` be split into smaller, more focused modules?**
  _Cohesion score 0.05981981981981982 - nodes in this community are weakly interconnected._
- **Should `msg` be split into smaller, more focused modules?**
  _Cohesion score 0.08754208754208755 - nodes in this community are weakly interconnected._
- **Should `admin.py` be split into smaller, more focused modules?**
  _Cohesion score 0.08127721335268505 - nodes in this community are weakly interconnected._
- **Should `curation.py` be split into smaller, more focused modules?**
  _Cohesion score 0.08235294117647059 - nodes in this community are weakly interconnected._
- **Should `melody_store.py` be split into smaller, more focused modules?**
  _Cohesion score 0.05959183673469388 - nodes in this community are weakly interconnected._