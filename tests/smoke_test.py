"""
آزمون دود — جریان‌های مرحله ۲ با ربات بدلی رانده می‌شوند.

اجرا:  python tests/smoke_test.py

هیچ پیوندی با تلگرام گرفته نمی‌شود؛ همه چیز بدلی است. پس می‌توان
پیش از هر بارگذاری روی سرور، آزادانه اجرایش کرد.

این آزمون روی همان پایگاه دادهٔ .env کار می‌کند، ولی تنها رکوردهای
آزمایشی خودش (کاربر ۹۹۹۹۹۹۱۰۰) را می‌سازد و در پایان پاک می‌کند.
"""
import sys, os, asyncio, types, tempfile, atexit
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# ═════════════════════════════════════════════════════════════
#  پایگاه دادهٔ یکبارمصرف — پیش از هر import ای که config را
#  می‌خواند، وگرنه دیر است
# ═════════════════════════════════════════════════════════════
#
# این آزمون جریان‌های کامل را می‌راند: کاربر می‌سازد، پیشکش
# می‌گیرد، نوا به گنجینه می‌نشاند، و در پایان همه را برمی‌دارد.
# پیش‌تر همین برداشتن روی پایگاه دادهٔ راستین انجام می‌شد و شرطش
# `source='user'` بود — یعنی **نواهای راستینِ کاربران** را هم
# می‌برد. یک بار برد.
#
# چاره، دقیق‌تر کردن شرط DELETE نیست؛ چون شرطِ دقیق‌تر باز هم یک
# روز اشتباه نوشته می‌شود. چاره این است که آزمون اصلاً به پایگاه
# دادهٔ راستین نرسد.
_tmp_db = Path(tempfile.gettempdir()) / f"hadis_smoke_{os.getpid()}.db"
os.environ["DATABASE_PATH"] = str(_tmp_db)


@atexit.register
def _sweep_tmp_db():
    # ویندوز پروندهٔ باز را نمی‌گذارد پاک شود، پس نخست اتصال بسته
    # می‌شود. ناکامی اینجا زیانی ندارد: پرونده در پوشهٔ موقت است.
    try:
        from core.db.database import close_connection

        close_connection()
    except Exception:  # noqa: BLE001
        pass
    for suffix in ("", "-wal", "-shm"):
        try:
            Path(str(_tmp_db) + suffix).unlink(missing_ok=True)
        except OSError:
            pass


from core.console import enable_utf8_console; enable_utf8_console()

from core.db import database as db, submissions as subs, feedbacks as fbs, searches as srch
from core import texts
from bot import states
from bot.handlers import (start, menu, tokens, submission, feedback, admin,
                          curation, intake, search, archive)
from config import config

# نگهبان: اگر جداسازی بالا روزی شکست، آزمون همین‌جا می‌ایستد و
# دست به پایگاه دادهٔ راستین نمی‌زند.
if config.database_path != _tmp_db:
    raise SystemExit(
        f"\n✗ آزمون دود به پایگاه دادهٔ راستین اشاره می‌کند:\n"
        f"  {config.database_path}\n"
        f"  چشم‌به‌راه: {_tmp_db}\n"
        f"  اجرا نشد، تا داده‌ای از دست نرود.\n"
    )

db.init_db()
UID = 999999100
TRUSTED = 999999101
BEYT = 'دوسش دارم یه عالمه دختر پادشاهمه'
ADMIN = config.admin_ids[0]
sent_log = []


class Sent:
    """
    آنچه یک فرستادنِ کامیاب برمی‌گرداند.

    پیشتر `types.SimpleNamespace` بود و `delete` نداشت — حال آنکه
    `Message` راستینِ تلگرام دارد. هر کدِ تولیدی که پیامِ گذرایی
    را پس از کارش برمی‌داشت، اینجا با AttributeError می‌افتاد؛
    کمبودِ بدل بود، نه ایرادِ کد.
    """

    def __init__(self, message_id, chat_id=0):
        self.message_id = message_id
        self.chat_id = chat_id
        self.deleted = False

    async def delete(self):
        self.deleted = True
        sent_log.append(('delete', self.chat_id, ''))
        return True

    async def edit_text(self, text, **kw):
        sent_log.append(('edit', self.chat_id, str(text)[:60]))
        return self


class FakeBot:
    async def send_message(self, chat_id, text, **kw):
        sent_log.append(('send_message', chat_id, text[:60]))
        return Sent(len(sent_log), chat_id)
    async def send_audio(self, chat_id, audio, caption=None, **kw):
        sent_log.append(('send_audio', chat_id, (caption or '')[:60]))
        return Sent(len(sent_log), chat_id)
    async def send_sticker(self, chat_id, sticker, **kw):
        sent_log.append(('send_sticker', chat_id, sticker)); return None
    async def copy_message(self, chat_id, from_chat_id, message_id, **kw):
        sent_log.append(('copy_message', chat_id, f'from {from_chat_id}'))
        return Sent(len(sent_log), chat_id)
    async def get_chat_member(self, chat_id, user_id):
        from telegram.constants import ChatMemberStatus
        return types.SimpleNamespace(status=ChatMemberStatus.MEMBER, is_member=True)
    async def edit_message_text(self, **kw): return None


class FakeMessage:
    def __init__(self, text=None, audio=None, chat_id=UID, forwarded=False):
        self.text = text; self.audio = audio; self.caption = None
        self.forward_origin = object() if forwarded else None
        self.forward_date = None
        self.voice = self.document = self.photo = self.video = None
        self.video_note = self.animation = self.sticker = None
        self.chat_id = chat_id; self.message_id = 1
        self.replies = []
        self.markups = []
    async def reply_html(self, text, **kw):
        self.replies.append(text); sent_log.append(('reply', self.chat_id, text[:60]))
        self.markups.append(kw.get('reply_markup'))
        return Sent(len(sent_log), self.chat_id)
    def labels(self, index=-1):
        m = self.markups[index] if self.markups else None
        return [[b.text for b in row] for row in m.inline_keyboard] if m else []
    reply_text = reply_html
    async def reply_audio(self, audio=None, **kw):
        sent_log.append(('reply_audio', self.chat_id, str(audio)[:40]))
        return Sent(len(sent_log), self.chat_id)


class FakeQuery:
    # چرا chat_id پارامتر است: جریان بازبینی بر پایهٔ **گفتگو**
    # داوری می‌کند نه شخص — نواختی در گروه مداحی یعنی گرداننده،
    # در گفتگوی خصوصی یعنی همراه. بدلی که همیشه خود را در گروه
    # جا می‌زد، سوی همراه را اصلاً نمی‌آزمود.
    def __init__(self, data, user, chat_id=None):
        self.data = data; self.from_user = user
        self.message = types.SimpleNamespace(
            caption='زیرنویس', text=None, message_id=1,
            chat_id=config.madahi_group_id if chat_id is None else chat_id,
            reply_html=self._reply, reply_text=self._reply,
        )
        self.replies = []
        self.answers = []
        self.edits = []
        self.markup = None
    async def _reply(self, text, **kw):
        self.replies.append(text); sent_log.append(('reply', 0, text[:60]))
        return Sent(len(sent_log), 0)
    async def answer(self, text=None, show_alert=False):
        self.answers.append(text); sent_log.append(('answer', 0, (text or '')[:60]))
    async def edit_message_reply_markup(self, **kw):
        self.markup = kw.get('reply_markup'); return None
    async def edit_message_text(self, *a, **kw):
        self.edits.append(a[0] if a else kw.get('text', ''))
        self.markup = kw.get('reply_markup'); return None
    async def edit_message_caption(self, **kw):
        self.edits.append(kw.get('caption', ''))
        self.markup = kw.get('reply_markup'); return None
    def labels(self):
        """نوشتار دکمه‌های واپسین صفحه‌کلید، سطر به سطر."""
        if not self.markup:
            return []
        return [[b.text for b in row] for row in self.markup.inline_keyboard]


def _field_rows():
    """چیدمان چشم‌داشتیِ فهرست ویرایش — سه بخش، هرکدام در سطر خود."""
    return [
        [texts.btn('field_madah')],
        [texts.btn('field_style')],
        [texts.btn('field_title')],
        [texts.btn('confirm'), texts.btn('cancel')],
    ]


def mk_update(message=None, query=None, user_id=UID):
    user = types.SimpleNamespace(id=user_id, username='tester', first_name='آزماینده',
                                 last_name=None, full_name='آزماینده')
    return types.SimpleNamespace(effective_user=user, effective_message=message,
                                 message=message, callback_query=query)


def _swallow(coro):
    """کارِ پس‌زمینه در آزمون اجرا نمی‌شود؛ تنها بسته می‌شود."""
    coro.close()
    return None


def mk_ctx(user_data=None):
    return types.SimpleNamespace(bot=FakeBot(), user_data=user_data if user_data is not None else {},
                                 application=types.SimpleNamespace(create_task=_swallow))


async def main():
    db.execute('DELETE FROM users WHERE user_id=?', (UID,))
    db.execute('DELETE FROM submissions'); db.execute('DELETE FROM feedbacks')
    db.execute("DELETE FROM tracks WHERE source='user'")
    ud = {}

    def step(n, label): print(f'\n{n}. {label}')

    step(1, '/start برای کاربر تازه')
    m = FakeMessage('/start'); await start.start(mk_update(m), mk_ctx(ud))
    assert 'خوش آمدید' in m.replies[0], m.replies
    print(f'   ✓ خوش‌آمد فرستاده شد؛ توکن آغازین = {db.get_tokens(UID)}')

    step(2, 'منو پیش از تأیید هم‌نشینی — باید رد شود')
    m = FakeMessage('منو'); await menu.show_menu(mk_update(m), mk_ctx(ud))
    assert 'تأیید' in m.replies[0], m.replies
    print('   ✓ نگهبان require_verified جلو را گرفت')

    step(3, 'نواختن بر دکمهٔ صفحهٔ اینستاگرام')
    q = FakeQuery('gate:ig', None); await start.on_instagram_tap(mk_update(None, q), mk_ctx(ud))
    assert db.get_user(UID)['tapped_instagram'] == 1
    print(f'   ✓ ضربه ثبت شد (این همان چیزی است که دکمهٔ url نمی‌توانست)')

    step(4, 'بررسی هم‌نشینی')
    q = FakeQuery('gate:check', None); await start.on_check_membership(mk_update(None, q), mk_ctx(ud))
    assert db.get_user(UID)['is_verified'] == 1
    print('   ✓ تأیید شد و منو گشوده شد')

    step(5, 'منو و راهنما و کیسهٔ توکن')
    for fn, label in ((menu.show_menu,'منو'), (menu.show_help,'راهنما'), (tokens.show_balance,'توکن')):
        m = FakeMessage(label); await fn(mk_update(m), mk_ctx(ud))
        assert m.replies, f'{label} پاسخی نداد'
    print('   ✓ هر سه رندر شدند (جای‌گاه‌های YAML درست پر شد)')

    step(6, 'پیشکش نوا: شناسنامه از برچسب فایل، تنها سبک پرسیده شود')
    m = FakeMessage(); await submission.begin(mk_update(m), mk_ctx(ud))
    assert states.get_state(ud) == states.AWAITING_SUBMISSION_FILE
    # فایلِ برچسب‌دار: نام مداح و اسم مداحی باید از همین‌جا خوانده
    # شوند، نه از کاربر پرسیده شوند.
    audio = types.SimpleNamespace(file_id='F1', file_unique_id='UQ1',
                                  file_name='n.mp3', duration=300,
                                  performer='حاج محمود كريمي', title=BEYT)
    m = FakeMessage(audio=audio); await submission.on_audio(mk_update(m), mk_ctx(ud))
    assert states.get_state(ud) == states.AWAITING_SUBMISSION_STYLE, states.get_state(ud)
    assert 'حاج محمود' in m.replies[-1], m.replies[-1]
    print('   ✓ نام مداح و اسم مداحی از برچسب خوانده شد؛ مداح پرسیده نشد')

    m = FakeMessage('شور'); await submission.on_style(mk_update(m), mk_ctx(ud))
    assert states.get_state(ud) is None, states.get_state(ud)
    sid = db.query_one('SELECT id, madah, style, title FROM submissions ORDER BY id DESC LIMIT 1')
    assert sid['title'] == BEYT, sid['title']
    assert sid['style'] == 'شور', sid['style']
    print(f'   ✓ پیشکش {sid["id"]} ساخته شد: {sid["madah"]} / {sid["style"]}')
    print(f'   ✓ اسم مداحی از برچسب نشست: «{sid["title"]}»')

    # اکنون شناسنامه می‌آید، نه فرستادن یک‌راست به گروه
    assert 'شناسنامه' in m.replies[-1], m.replies[-1]
    assert m.labels() == [[texts.btn('confirm'), texts.btn('cancel')],
                          [texts.btn('edit')]], m.labels()
    print(f'   ✓ شناسنامه با دکمه‌ها: {m.labels()}')
    assert not any(k == 'send_audio' for k, _, _ in sent_log), 'پیش از تأیید به گروه رفت'
    print('   ✓ پیش از تأیید، چیزی به گروه نرفت')

    step(6.5, 'ویرایش: بخش ← نوشتار تازه ← دوباره سه دکمه')
    q = FakeQuery(f'sub:edit:{sid["id"]}', None, chat_id=UID)
    await submission.on_edit_open(mk_update(None, q), mk_ctx(ud))
    assert q.labels() == _field_rows(), q.labels()
    print('   ✓ «کدام بخش؟» با سه گزینه و تأیید/لغو زیرشان')

    q2 = FakeQuery(f'sub:field:{sid["id"]}:madah', None, chat_id=UID)
    await submission.on_edit_field(mk_update(None, q2), mk_ctx(ud))
    assert states.get_state(ud) == states.AWAITING_EDIT_VALUE
    assert 'نام مداح' in q2.edits[-1], q2.edits[-1]
    assert q2.labels() == [[texts.btn('back')]], q2.labels()
    print('   ✓ «ویرایش خود را برای بخش نام مداح اعمال کنید» + دکمهٔ بازگشت')

    m = FakeMessage('رسول برنا'); await submission.on_edit_value(mk_update(m), mk_ctx(ud))
    assert states.get_state(ud) is None
    fresh = db.query_one('SELECT madah FROM submissions WHERE id=?', (sid['id'],))
    assert fresh['madah'] == 'رسول برنا', fresh['madah']
    assert m.labels() == _field_rows(), m.labels()
    print(f'   ✓ نام مداح شد «{fresh["madah"]}» و سه دکمه دوباره آمد')

    step(6.9, 'تأیید همراه ← اکنون به گروه می‌رود')
    q = FakeQuery(f'sub:send:{sid["id"]}', None, chat_id=UID)
    await submission.on_user_send(mk_update(None, q), mk_ctx(ud))
    assert any(k == 'send_audio' for k, _, _ in sent_log), 'به گروه نرفت'
    print('   ✓ به گروه مداحی رفت')

    step(7, 'تأیید گرداننده (دوبار — باید یک توکن بدهد)')
    before = db.get_tokens(UID)
    for i in (1, 2):
        q = FakeQuery(f'sub:ok:{sid["id"]}', None)
        await submission.on_review(mk_update(None, q, user_id=ADMIN), mk_ctx({}))
    after = db.get_tokens(UID)
    assert after == before + 1, f'{before} -> {after}'
    print(f'   ✓ توکن {before} → {after} (تنها یک بار، با دو نواخت)')

    step(7.5, 'بیت شعر، نام نوا و lyrics_snippet شد')
    tr = db.query_one("SELECT title, lyrics_snippet FROM tracks WHERE source='user' ORDER BY id DESC LIMIT 1")
    assert tr['title'] == BEYT and tr['lyrics_snippet'] == BEYT, dict(tr)
    print(f'   ✓ هم نام نوا، هم بیتِ روی جلد: «{tr["title"]}»')

    step(8, 'پیشکش همان فایل دوباره')
    ud.clear()
    m = FakeMessage(); await submission.begin(mk_update(m), mk_ctx(ud))
    m = FakeMessage(audio=audio); await submission.on_audio(mk_update(m), mk_ctx(ud))
    assert 'آرشیو ما' in m.replies[0], m.replies
    assert db.get_tokens(UID) == after
    print(f'   ✓ تکراری رد شد؛ توکن همان {after} ماند')

    step(9, 'نقد و انتقادات')
    ud.clear()
    m = FakeMessage(); await feedback.begin(mk_update(m), mk_ctx(ud))
    m = FakeMessage('یک پیشنهاد'); await feedback.on_content(mk_update(m), mk_ctx(ud))
    fid = db.query_one('SELECT id FROM feedbacks ORDER BY id DESC LIMIT 1')['id']
    print(f'   ✓ سخن {fid} به گروه رفت')

    step(10, 'دو گرداننده هم‌زمان بر پاسخ‌گویی می‌نوازند')
    ud1, ud2 = {}, {}
    q1 = FakeQuery(f'fb:reply:{fid}', None)
    await feedback.on_reply_tap(mk_update(None, q1, user_id=config.admin_ids[0]), mk_ctx(ud1))
    q2 = FakeQuery(f'fb:reply:{fid}', None)
    await feedback.on_reply_tap(mk_update(None, q2, user_id=config.admin_ids[1]), mk_ctx(ud2))
    assert 'قفل' in (q1.answers[0] or ''), q1.answers
    assert 'دیگری' in (q2.answers[0] or ''), q2.answers
    print(f'   ✓ اولی: «{q1.answers[0]}»')
    print(f'   ✓ دومی: «{q2.answers[0].strip()[:45]}…»')

    step(11, 'گردانندهٔ نخست پاسخ می‌دهد')
    m = FakeMessage('پاسخ ما', chat_id=config.feedback_group_id)
    await feedback.on_admin_reply(mk_update(m, user_id=config.admin_ids[0]), mk_ctx(ud1))
    assert fbs.get(fid)['status'] == 'answered'
    print('   ✓ پاسخ رسید و قفل رها شد')

    step(12, 'آمار گردانندگان')
    m = FakeMessage('/stats'); await admin.stats(mk_update(m, user_id=ADMIN), mk_ctx({}))
    assert m.replies, 'آمار پاسخ نداد'
    print('   ✓ رندر شد')

    # ═══════════════════════════════════════════════════════
    #  خواسته‌های تازه
    # ═══════════════════════════════════════════════════════

    step(13, 'همراه مورد اعتماد — پیشکشش بی داوری به گنجینه می‌رود')
    db.upsert_user(TRUSTED, 'trusted_one', 'همراه امین')
    db.set_verified(TRUSTED)
    ctx = mk_ctx({}); ctx.args = [str(TRUSTED)]
    m = FakeMessage('/trust', chat_id=config.madahi_group_id)
    await curation.trust(mk_update(m, user_id=ADMIN), ctx)
    assert db.is_trusted(TRUSTED), 'اعتماد ثبت نشد'
    print('   ✓ /trust ثبت شد و همراه آگاه گشت')

    tud = {}
    before_tracks = db.count_tracks()
    a2 = types.SimpleNamespace(file_id='F2', file_unique_id='UQ2', file_name='b.mp3',
                               duration=420, performer=None, title=None, file_size=9)
    m = FakeMessage(); await submission.begin(mk_update(m, user_id=TRUSTED), mk_ctx(tud))
    m = FakeMessage(audio=a2, chat_id=TRUSTED)
    await submission.on_audio(mk_update(m, user_id=TRUSTED), mk_ctx(tud))
    m = FakeMessage('مهدی رسولی', chat_id=TRUSTED)
    await submission.on_madah(mk_update(m, user_id=TRUSTED), mk_ctx(tud))
    m = FakeMessage('واحد', chat_id=TRUSTED)
    await submission.on_style(mk_update(m, user_id=TRUSTED), mk_ctx(tud))
    m = FakeMessage('رد کردن', chat_id=TRUSTED)
    await submission.on_title(mk_update(m, user_id=TRUSTED), mk_ctx(tud))

    # همراه مورد اعتماد هم شناسنامهٔ خودش را می‌بیند و تأیید می‌کند؛
    # اعتماد یعنی پریدن از داوریِ گردانندگان، نه از بازبینیِ خودش.
    tsid = db.query_one('SELECT id FROM submissions ORDER BY id DESC LIMIT 1')['id']
    assert db.count_tracks() == before_tracks, 'پیش از تأیید به گنجینه رفت'
    q = FakeQuery(f'sub:send:{tsid}', None, chat_id=TRUSTED)
    await submission.on_user_send(mk_update(None, q, user_id=TRUSTED), mk_ctx(tud))

    assert db.count_tracks() == before_tracks + 1, 'یک‌راست به گنجینه نرفت'
    sub2 = db.query_one('SELECT status FROM submissions ORDER BY id DESC LIMIT 1')
    assert sub2['status'] == 'approved', sub2['status']
    notice = [t for k, c, t in sent_log if k == 'send_message' and c == config.madahi_group_id]
    assert notice, 'گروه هیچ آگاهی‌ای نگرفت'
    print(f'   ✓ نوا بی داوری نشست (گنجینه {before_tracks} → {db.count_tracks()})')
    print('   ✓ گروه آگاهیِ بی‌دکمه گرفت')

    step(14, 'افزودن انبوه ← دفتر پذیرش، نوا به نوا')
    bud = {}
    bctx = mk_ctx(bud); bctx.args = ['حاج', 'محمود', 'کریمی']
    # افزودن و برداشتن به گروه بایگانی رفتند: همان‌جا که نسخهٔ
    # نهایی هر مداحی می‌نشیند.
    GID = config.ornate_target
    m = FakeMessage('/bulk', chat_id=GID)
    await curation.begin_bulk(mk_update(m, user_id=ADMIN), bctx)
    assert states.get_state(bud) == states.AWAITING_BULK_AUDIO

    before_tracks = db.count_tracks()
    for i in range(4):
        au = types.SimpleNamespace(file_id=f'B{i}', file_unique_id=f'UB{i}',
                                   file_name=f'{i}.mp3', duration=300,
                                   performer='مداح آزمایشی',
                                   title=f'نوای آزمایشی {i}', file_size=9)
        m = FakeMessage(audio=au, chat_id=GID)
        await curation.on_bulk_audio(mk_update(m, user_id=ADMIN), mk_ctx(bud))
    # همان فایل، دوباره — نباید دوبار در صف بنشیند
    m = FakeMessage(audio=au, chat_id=GID)
    await curation.on_bulk_audio(mk_update(m, user_id=ADMIN), mk_ctx(bud))
    assert len(states.get_data(bud)['items']) == 4, states.get_data(bud)['items']
    assert db.count_tracks() == before_tracks, 'پیش از تأیید چیزی نشست'
    print('   ✓ ۴ نوا گردآوری شد، تکراری رد شد، و هیچ‌کدام هنوز ننشسته')

    m = FakeMessage('/bulk_end', chat_id=GID)
    await curation.end_bulk(mk_update(m, user_id=ADMIN), mk_ctx(bud))
    # نام مداحِ دسته داده شده، پس گام مداح پرسیده نمی‌شود
    assert states.get_state(bud) == states.AWAITING_INTAKE_STYLE, states.get_state(bud)
    print('   ✓ پذیرش آغاز شد و چون مداحِ دسته داده شده بود، از گام مداح گذشت')

    async def accept_one(tap_style=True):
        # تنها یک پرسش: سبک. اسم مداحی از برچسب فایل آمده و پس از
        # سبک، یک‌راست کارت شناسنامه می‌آید.
        seq = states.get_data(bud)['seq']
        if tap_style:
            q = FakeQuery(f'in:style:{seq}:0', None, chat_id=GID)
            await intake.on_style_tap(mk_update(None, q, user_id=ADMIN), mk_ctx(bud))
        else:
            mm = FakeMessage('شور', chat_id=GID)
            await intake.on_style(mk_update(mm, user_id=ADMIN), mk_ctx(bud))
        assert states.get_state(bud) == states.AWAITING_INTAKE_CARD, states.get_state(bud)
        shown = [t for k, c, t in sent_log if k == 'send_message'][-1]
        q = FakeQuery(f'in:ok:{seq}', None, chat_id=GID)
        await intake.on_confirm(mk_update(None, q, user_id=ADMIN), mk_ctx(bud))
        return shown

    card = await accept_one()
    assert 'شناسنامه' in card, card
    assert db.count_tracks() == before_tracks + 1, db.count_tracks()
    print('   ✓ کارت شناسنامه آمد و تنها پس از تأیید، نوا نشست')

    # کارت کهنه: نواختن دوباره بر شمارهٔ گذشته نباید کاری کند
    stale = FakeQuery('in:ok:1', None, chat_id=GID)
    await intake.on_confirm(mk_update(None, stale, user_id=ADMIN), mk_ctx(bud))
    assert 'کهنه' in (stale.answers[0] or ''), stale.answers
    assert db.count_tracks() == before_tracks + 1, 'کارت کهنه نوایی افزود'
    print('   ✓ کارت کهنه رد شد و نوایی نیفزود')

    # ویرایش: نام مداح این یکی فرق دارد
    seq = states.get_data(bud)['seq']
    q = FakeQuery(f'in:style:{seq}:0', None, chat_id=GID)
    await intake.on_style_tap(mk_update(None, q, user_id=ADMIN), mk_ctx(bud))
    mm = FakeMessage('نوای آزمایشی دوم', chat_id=GID)
    await intake.on_title(mk_update(mm, user_id=ADMIN), mk_ctx(bud))
    q = FakeQuery(f'in:edit:{seq}', None, chat_id=GID)
    await intake.on_edit(mk_update(None, q, user_id=ADMIN), mk_ctx(bud))
    assert len(q.labels()) == 4, q.labels()
    assert q.labels()[-1] == [texts.btn('confirm'), texts.btn('cancel')], q.labels()
    print(f'   ✓ فهرست ویرایش: {[r[0] for r in q.labels()[:3]]}')
    q = FakeQuery(f'in:field:{seq}:madah', None, chat_id=GID)
    await intake.on_field(mk_update(None, q, user_id=ADMIN), mk_ctx(bud))
    assert states.get_state(bud) == states.AWAITING_INTAKE_EDIT
    assert q.labels() == [[texts.btn('back')]], q.labels()
    mm = FakeMessage('سید رضا نریمانی', chat_id=GID)
    await intake.on_value(mk_update(mm, user_id=ADMIN), mk_ctx(bud))
    assert states.get_state(bud) == states.AWAITING_INTAKE_CARD
    q = FakeQuery(f'in:ok:{seq}', None, chat_id=GID)
    await intake.on_confirm(mk_update(None, q, user_id=ADMIN), mk_ctx(bud))
    edited = db.query_one("SELECT madah, title FROM tracks WHERE file_unique_id='UB1'")
    assert edited['madah'] == 'سید رضا نریمانی', dict(edited)
    print('   ✓ ویرایش نام مداح نشست و بر گنجینه رفت')

    # چشم‌پوشی: سومی نباید بنشیند
    seq = states.get_data(bud)['seq']
    q = FakeQuery(f'in:no:{seq}', None, chat_id=GID)
    await intake.on_drop(mk_update(None, q, user_id=ADMIN), mk_ctx(bud))
    assert db.query_one("SELECT id FROM tracks WHERE file_unique_id='UB2'") is None
    print('   ✓ «چشم‌پوشی» نوا را ننشاند')

    await accept_one(tap_style=False)
    assert states.get_state(bud) is None, states.get_state(bud)
    assert db.count_tracks() == before_tracks + 3, db.count_tracks()
    madah_of = db.query_one("SELECT madah FROM tracks WHERE file_unique_id='UB3'")['madah']
    assert madah_of == 'حاج محمود کریمی', madah_of
    print(f'   ✓ نام مداح دسته بر بقیه نشست: «{madah_of}»')
    print('   ✓ پذیرش پایان یافت: ۳ نشسته، ۱ رهاشده')

    step(15, 'بازجویی ناکام ← گرداننده نسخهٔ کامل را می‌فرستد')
    sid2 = srch.create(user_id=UID, input_kind='audio', input_sha256='deadbeef',
                       input_file_id='CLIP1', input_duration=12)
    srch.finish(sid2, 'not_found')
    srch.set_hint(sid2, 'مهدی رسولی')
    assert srch.get(sid2)['hint_text'] == 'مهدی رسولی'
    print('   ✓ گمانهٔ کاربر («نام مداح را می‌دانید؟») در دفتر نشست')

    fud = {}
    q = FakeQuery(f'fail:fill:{sid2}', None)
    await curation.on_fill_tap(mk_update(None, q, user_id=ADMIN), mk_ctx(fud))
    assert states.get_state(fud) == states.AWAITING_FILL_AUDIO, states.get_state(fud)

    q2 = FakeQuery(f'fail:fill:{sid2}', None)
    await curation.on_fill_tap(mk_update(None, q2, user_id=config.admin_ids[1]), mk_ctx({}))
    assert 'دیگری' in (q2.answers[0] or ''), q2.answers
    print(f'   ✓ قفل گرفته شد؛ دومی دید: «{q2.answers[0].strip()[:38]}…»')

    au = types.SimpleNamespace(file_id='FULL1', file_unique_id='UFULL1',
                               file_name='full.mp3', duration=600,
                               performer='مهدی رسولی', title=BEYT, file_size=9)
    m = FakeMessage(audio=au, chat_id=GID)
    await curation.on_fill_audio(mk_update(m, user_id=ADMIN), mk_ctx(fud))
    assert states.get_state(fud) == states.AWAITING_INTAKE_STYLE, states.get_state(fud)
    m = FakeMessage('شور', chat_id=GID)
    await intake.on_style(mk_update(m, user_id=ADMIN), mk_ctx(fud))

    assert srch.get(sid2)['status'] == 'not_found', 'پیش از تأیید، بازجویی بسته شد'
    seq = states.get_data(fud)['seq']
    q = FakeQuery(f'in:ok:{seq}', None, chat_id=GID)
    await intake.on_confirm(mk_update(None, q, user_id=ADMIN), mk_ctx(fud))

    filled = srch.get(sid2)
    assert filled['status'] == 'fulfilled', filled['status']
    assert filled['matched_track_id'], 'نوا به بازجویی بسته نشد'
    track = db.get_track(int(filled['matched_track_id']))
    assert track['madah'] == 'کربلایی مهدی رسولی' and track['style'] == 'شور', dict(track)
    assert track['title'] == BEYT, track['title']
    assert [c for k, c, _ in sent_log if k == 'send_audio' and c == UID], 'برای جوینده نرفت'
    # قاعدهٔ تازه: نوایی که گرداننده دستی می‌رساند، سکه می‌ستاند.
    # جست‌وجو ناکام مانده و سکه‌ای گرفته نشده بود، ولی سرانجام
    # آنچه کاربر می‌خواست به دستش رسید — و همان است که بها دارد.
    assert db.get_tokens(UID) == after - 1, (db.get_tokens(UID), after)
    assert filled['token_charged'] == 1, 'سکه نشان نخورد، پس «این نیست» بازش نمی‌گرداند'
    print(f'   ✓ نوا ثبت شد، برای جوینده رفت، و یک سکه ستانده شد ({after} ← {after - 1})')
    print(f'   ✓ بازجویی از «ناکام» به «{filled["status"]}» رفت')

    step(16, 'نگهبان گمانه‌زنی — با گنجینهٔ خُرد چیزی پیشنهاد نمی‌شود')
    import numpy as np
    from core.audio.classifier import MIN_CORPUS_FOR_GUESS, get_classifier
    cls = get_classifier()
    fake = types.SimpleNamespace(voice=np.zeros(42), tempo=90.0, pulse_clarity=0.9)
    cls._voice_center = None
    assert cls.similar_tracks(fake) == [], 'بی هنجارسازی گمانه زد'
    print('   ✓ بی هنجارسازی: هیچ پیشنهادی')
    cls._voice_center = np.zeros(42); cls._voice_scale = np.ones(42)
    cls.sample_count = MIN_CORPUS_FOR_GUESS - 1
    assert cls.similar_tracks(fake) == [], 'با گنجینهٔ خُرد گمانه زد'
    print(f'   ✓ زیر {MIN_CORPUS_FOR_GUESS} نوا: هیچ — همان باگی که کاربر دید')

    step(17, 'کیسهٔ سکه — موجودی حتی در تهی بودن دیده می‌شود')
    db.execute('UPDATE users SET tokens = 0 WHERE user_id = ?', (UID,))
    m = FakeMessage('🪙 کیسهٔ سکه')
    await tokens.show_balance(mk_update(m), mk_ctx({}))
    body = m.replies[0]
    assert 'سکه' in body, body[:120]
    assert 'توکن' not in body, 'واژهٔ توکن هنوز هست'
    assert '۰' in body, 'موجودی صفر نشان داده نشد'
    print('   ✓ واژهٔ «توکن» نمانده و موجودی ۰ هم دیده می‌شود')

    # بی‌خطر است: این پایگاه داده یکبارمصرف است و در پایان برداشته می‌شود
    step(18, 'برداشتن نوا از گنجینه — تنها در گروه، تنها گرداننده')
    keep = db.count_tracks()
    # UB2 در گام ۱۴ چشم‌پوشی شد و هرگز ننشست؛ UB3 نشسته است.
    victim = db.query_one("SELECT id, madah FROM tracks WHERE file_unique_id='UB3'")

    # در گفتگوی خصوصی نباید کار کند
    pctx = mk_ctx({}); pctx.args = []
    m = FakeMessage('/delete', chat_id=UID)
    await curation.begin_delete(mk_update(m, user_id=ADMIN), pctx)
    assert 'گروه بایگانی' in m.replies[-1], m.replies[-1]
    print('   ✓ در گفتگوی خصوصی رد شد')

    gctx = mk_ctx({}); gctx.args = ['حاج', 'محمود']
    m = FakeMessage('/delete', chat_id=config.ornate_target)
    await curation.begin_delete(mk_update(m, user_id=ADMIN), gctx)
    rows = m.labels()
    assert len(rows) >= 2, rows
    print(f'   ✓ {len(rows) - 1} نامزد یافت شد (به‌علاوهٔ دکمهٔ چشم‌پوشی)')

    q = FakeQuery(f'del:pick:{victim["id"]}', None)
    await curation.on_delete_pick(mk_update(None, q, user_id=ADMIN), mk_ctx({}))
    assert 'برداشته شود؟' in q.edits[-1], q.edits[-1]
    assert q.labels() == [[texts.btn('delete_yes'), texts.btn('cancel')]], q.labels()
    print('   ✓ پرسش واپسین، با شناسنامهٔ نوا')

    # ناگرداننده نباید بتواند
    q_bad = FakeQuery(f'del:yes:{victim["id"]}', None)
    await curation.on_delete_confirm(mk_update(None, q_bad, user_id=UID), mk_ctx({}))
    assert db.count_tracks() == keep, 'ناگرداننده توانست بردارد'
    print('   ✓ ناگرداننده نتوانست')

    q = FakeQuery(f'del:yes:{victim["id"]}', None)
    await curation.on_delete_confirm(mk_update(None, q, user_id=ADMIN), mk_ctx({}))
    assert db.count_tracks() == keep - 1, db.count_tracks()
    assert db.get_track(victim['id']) is None
    left = db.query_one('SELECT COUNT(*) c FROM fingerprints WHERE track_id=?',
                        (victim['id'],))['c']
    assert left == 0, f'{left} اثر انگشت یتیم ماند'
    print(f'   ✓ نوا برداشته شد (گنجینه {keep} → {db.count_tracks()}) و اثر انگشتی یتیم نماند')

    step(19, 'گردانندگان — تنها از دست مالک')
    OWNER, OTHER_ADMIN = config.admin_ids[0], config.admin_ids[1]
    NEWBIE = 999999102
    db.upsert_user(NEWBIE, 'newbie', 'تازه‌وارد')

    # گردانندهٔ ساده نباید بتواند
    ctx = mk_ctx({}); ctx.args = [str(NEWBIE)]
    m = FakeMessage('/addadmin', chat_id=config.madahi_group_id)
    await curation.add_admin(mk_update(m, user_id=OTHER_ADMIN), ctx)
    assert not db.is_db_admin(NEWBIE), 'گردانندهٔ ساده توانست گرداننده بیفزاید'
    assert 'مالک' in m.replies[-1], m.replies[-1]
    print('   ✓ گردانندهٔ ساده نتوانست — و دلیلش را دید')

    ctx = mk_ctx({}); ctx.args = [str(NEWBIE)]
    m = FakeMessage('/addadmin', chat_id=config.madahi_group_id)
    await curation.add_admin(mk_update(m, user_id=OWNER), ctx)
    assert db.is_db_admin(NEWBIE), 'مالک نتوانست بیفزاید'
    assert config.is_admin(NEWBIE), 'config او را گرداننده نمی‌شمارد'
    print('   ✓ مالک افزود و config بی‌درنگ او را گرداننده شمرد')

    ctx = mk_ctx({}); ctx.args = [str(OWNER)]
    m = FakeMessage('/deladmin', chat_id=config.madahi_group_id)
    await curation.remove_admin(mk_update(m, user_id=OWNER), ctx)
    assert config.is_admin(OWNER), 'مالک خودش را برداشت'
    print('   ✓ مالک نتوانست خودش را بردارد')

    ctx = mk_ctx({}); ctx.args = [str(NEWBIE)]
    m = FakeMessage('/deladmin', chat_id=config.madahi_group_id)
    await curation.remove_admin(mk_update(m, user_id=OWNER), ctx)
    assert not db.is_db_admin(NEWBIE)
    print('   ✓ و توانست پس بگیرد')
    db.execute('DELETE FROM users WHERE user_id=?', (NEWBIE,))

    step(20, 'ویرایش سوی گرداننده — همان جریان، در گروه')
    m = FakeMessage(); await submission.begin(mk_update(m), mk_ctx(ud))
    a3 = types.SimpleNamespace(file_id='F3', file_unique_id='UQ3', file_name='c.mp3',
                               duration=200, performer=None, title=None, file_size=9)
    m = FakeMessage(audio=a3); await submission.on_audio(mk_update(m), mk_ctx(ud))
    m = FakeMessage('نامعلوم'); await submission.on_madah(mk_update(m), mk_ctx(ud))
    m = FakeMessage('روضه'); await submission.on_style(mk_update(m), mk_ctx(ud))
    m = FakeMessage('-'); await submission.on_title(mk_update(m), mk_ctx(ud))
    s3 = db.query_one('SELECT id FROM submissions ORDER BY id DESC LIMIT 1')['id']
    q = FakeQuery(f'sub:send:{s3}', None, chat_id=UID)
    await submission.on_user_send(mk_update(None, q), mk_ctx(ud))

    # اکنون گرداننده در گروه ویرایش می‌کند
    aud = {}
    q = FakeQuery(f'sub:edit:{s3}', None)          # گفتگو = گروه مداحی
    await submission.on_edit_open(mk_update(None, q, user_id=ADMIN), mk_ctx(aud))
    assert q.labels()[-1] == [texts.btn('confirm'), texts.btn('reject')], q.labels()
    print(f'   ✓ همان سه بخش، ولی تأییدش «{q.labels()[-1]}» است نه فرستادن')

    q2 = FakeQuery(f'sub:field:{s3}:madah', None)
    await submission.on_edit_field(mk_update(None, q2, user_id=ADMIN), mk_ctx(aud))
    m = FakeMessage('حاج مهدی رسولی', chat_id=config.madahi_group_id)
    await submission.on_edit_value(mk_update(m, user_id=ADMIN), mk_ctx(aud))
    fixed = db.query_one('SELECT madah FROM submissions WHERE id=?', (s3,))['madah']
    assert fixed == 'حاج مهدی رسولی', fixed
    print(f'   ✓ گرداننده «نامعلوم» را به «{fixed}» اصلاح کرد')

    # و همان اصلاح باید به گنجینه برود
    q = FakeQuery(f'sub:ok:{s3}', None)
    await submission.on_review(mk_update(None, q, user_id=ADMIN), mk_ctx({}))
    tr = db.query_one("SELECT madah FROM tracks WHERE file_unique_id='UQ3'")
    assert tr and tr['madah'] == 'حاج مهدی رسولی', tr and tr['madah']
    print('   ✓ نوا با نام اصلاح‌شده به گنجینه رفت')

    step(21, 'نوای بازفرستاده — دیگر جریان پیشکش را نمی‌بلعد')
    from bot.handlers import router

    au = types.SimpleNamespace(file_id='FW1', file_unique_id='UFW1',
                               file_name='fw.mp3', duration=200,
                               performer=None, title=None, file_size=9)

    # ۱) گرداننده در میانهٔ پیشکش است: نوا باید به همان پیشکش برود
    # وضعیت را دستی می‌نشانیم؛ آزمودنی اینجا مسیریابی است نه
    # نگهبان هم‌نشینی، و گرداننده در این پایگاه دادهٔ یکبارمصرف
    # /start نزده است.
    # گرداننده در این پایگاه دادهٔ یکبارمصرف /start نزده است؛
    # پیشکش کلید بیگانه به جدول کاربران دارد، پس نخست می‌نشیند.
    db.upsert_user(ADMIN, username='owner', first_name='مالک')
    sud = {}
    states.set_state(sud, states.AWAITING_SUBMISSION_FILE)
    m = FakeMessage(audio=au, chat_id=ADMIN, forwarded=True)
    await router._on_private_text_or_media(mk_update(m, user_id=ADMIN), mk_ctx(sud))
    assert states.get_state(sud) == states.AWAITING_SUBMISSION_STYLE, states.get_state(sud)
    print('   ✓ در میانهٔ پیشکش، نوای بازفرستاده به همان جریان رفت (باگ گزارش‌شده)')

    # ۲) بی هیچ وضعی: پرسیده می‌شود، نه اینکه خودکار بنشیند
    aud = {}
    before_fw = db.count_tracks()
    m = FakeMessage(audio=au, chat_id=ADMIN, forwarded=True)
    await router._on_private_text_or_media(mk_update(m, user_id=ADMIN), mk_ctx(aud))
    assert m.labels() == [[texts.btn('forward_add')], [texts.btn('forward_seek')]], m.labels()
    assert db.count_tracks() == before_fw, 'خودکار نشست'
    print(f'   ✓ پرسیده شد: {[r[0] for r in m.labels()]}')

    # ۳) «به گنجینه بیفزا» ← همان دفتر پذیرش، این‌بار در گفتگوی خصوصی
    q = FakeQuery('arc:add', None, chat_id=ADMIN)
    await archive.on_forward_add(mk_update(None, q, user_id=ADMIN), mk_ctx(aud))
    assert states.get_state(aud) == states.AWAITING_INTAKE_STYLE, states.get_state(aud)
    print('   ✓ «به گنجینه بیفزا» پذیرش را در گفتگوی خصوصی آغاز کرد')

    # ۴) همراه ساده: بی زدنِ دکمه، هیچ جست‌وجویی راه نمی‌افتد
    uud = {}
    m = FakeMessage(audio=au, chat_id=UID, forwarded=True)
    await router._on_private_text_or_media(mk_update(m, user_id=UID), mk_ctx(uud))
    assert states.get_state(uud) is None, states.get_state(uud)
    assert m.labels() == [[texts.btn('menu_search')]], m.labels()
    print('   ✓ فایلِ بی‌مقدمه جست‌وجو نشد؛ راهنما با دکمهٔ میان‌بر آمد')

    step(22, 'دروازهٔ جست‌وجو — نوشتار هم بی دکمه کاری نمی‌کند')
    uud = {}
    m = FakeMessage('محمود کریمی', chat_id=UID)
    await router._on_private_text_or_media(mk_update(m, user_id=UID), mk_ctx(uud))
    assert states.get_state(uud) is None, states.get_state(uud)
    assert m.labels() == [[texts.btn('menu_search')]], m.labels()
    print('   ✓ نوشتارِ بی‌مقدمه هم جست‌وجو نشد')

    # و اکنون از راهِ درست: دکمه، سپس فایل
    db.adjust_tokens(UID, 3, reason='admin', note='آزمون دروازه')
    q = FakeQuery('srch:begin', None, chat_id=UID)
    m = FakeMessage(chat_id=UID)
    await search.on_begin_tap(mk_update(m, q, user_id=UID), mk_ctx(uud))
    assert states.get_state(uud) == states.AWAITING_SEARCH_INPUT, states.get_state(uud)

    m = FakeMessage(audio=au, chat_id=UID)
    await router._on_private_text_or_media(mk_update(m, user_id=UID), mk_ctx(uud))
    assert states.get_state(uud) == states.AWAITING_SEARCH_HINT, states.get_state(uud)
    print('   ✓ پس از زدن دکمه، همان جست‌وجوی همیشگی')

    step(23, 'ترتیب ناکامی — بی خبرِ آرشیو، اینترنت، سپس صوت و دکمه‌ها')
    # ترتیب، خودش بخشِ گزارش‌شدهٔ ایراد بود. خواستهٔ کاربر:
    # هیچ خبری از نبودن در آرشیو داده نشود؛ یک‌راست «در اینترنت
    # می‌گردم»؛ و در پایان صوتِ خودِ کلیپ با دو دکمه زیرش.
    seen = []
    last_markup = []

    class OrderMsg:
        chat_id = UID
        message_id = 1
        async def reply_html(self, text, **kw):
            seen.append(text.split('\n')[0])
            return Sent(len(seen), self.chat_id)
        async def reply_audio(self, **kw):
            seen.append('«صوت»')
            return Sent(len(seen), 0)

    class OrderBot:
        async def send_message(self, chat_id, text, **kw):
            seen.append(text.split('\n')[0])
            last_markup.append(kw.get('reply_markup'))
            return Sent(len(seen), chat_id)

    async def _nothing_text(message, context, term, search_id=None):
        return False

    async def _nothing_sites(message, context, term, search_id=None):
        seen.append('«گشتن در اینترنت»')
        return False

    async def _nothing_similar(message, path):
        return False

    keep = (search._text_search_fallback, search._offer_sites, search._offer_similar)
    search._text_search_fallback = _nothing_text
    search._offer_sites = _nothing_sites
    search._offer_similar = _nothing_similar
    try:
        om = OrderMsg()
        octx = types.SimpleNamespace(bot=OrderBot(), user_data={}, application=None)
        await search._continue_with_hint(om, octx, None, 'محمود کریمی', 'x.mp3')
    finally:
        search._text_search_fallback, search._offer_sites, search._offer_similar = keep

    joined = ' | '.join(seen)
    assert 'در آرشیو نبود' not in joined, seen
    assert 'اینترنت' in seen[0], seen
    net_at = next(i for i, t in enumerate(seen) if 'گشتن در اینترنت' in t)
    # نشانهٔ پیامِ پایانی از خودِ متن گرفته می‌شود، نه رونویسی
    # دستی: وگرنه هر بار که نوشتار کوتاه یا بازنویسی شود، این
    # سنجه می‌شکند بی آنکه رفتاری عوض شده باشد.
    sorry_mark = texts.msg('search_sorry_no_clip').splitlines()[0]
    sorry_mark = sorry_mark.replace('<b>', '').replace('</b>', '').strip('🙏 ')
    end_at = next(i for i, t in enumerate(seen) if sorry_mark in t)
    assert net_at < end_at, seen
    assert end_at == len(seen) - 1, seen
    rows = [[b.text for b in row] for row in last_markup[-1].inline_keyboard]
    assert rows == [[texts.btn('send_full')], [texts.btn('cancel')]], rows
    print('   ✓ خبرِ آرشیو داده نشد؛ اینترنت ← پایان با دکمه‌ها')
    print(f'   ✓ دکمه‌های زیر پیام پایانی: {[r[0] for r in rows]}')

    db.execute('DELETE FROM users WHERE user_id IN (?, ?, ?)', (UID, TRUSTED, ADMIN))
    db.execute('DELETE FROM submissions'); db.execute('DELETE FROM feedbacks')
    db.execute("DELETE FROM searches WHERE input_sha256 = 'deadbeef'")
    db.execute("DELETE FROM tracks WHERE source IN ('user', 'trusted', 'admin')")
    print('\n' + '═'*58)
    print('  ✓ هر ۲۳ گام گذشت')
    print('═'*58)

asyncio.run(main())
