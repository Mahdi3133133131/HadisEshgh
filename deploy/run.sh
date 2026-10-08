#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────
#  حدیث عشق — اجرا در سندباکس (Daytona و مانندش)
#
#  چرا این و نه systemd: سندباکس یک کانتینر است و systemd ندارد،
#  پس واحدِ hadis.service آنجا کار نمی‌کند. این نوشته همان کار را
#  می‌کند: اگر ربات افتاد، برش می‌خیزاند.
#
#  اجرا:
#      chmod +x deploy/run.sh
#      ./deploy/run.sh
#
#  در پس‌زمینه (تا با بستنِ ترمینال نمیرد):
#      nohup ./deploy/run.sh > logs/runner.log 2>&1 &
# ─────────────────────────────────────────────────────────────
set -uo pipefail

cd "$(dirname "$0")/.." || exit 1
ROOT="$(pwd)"

PYTHON="${PYTHON:-$ROOT/.venv/bin/python}"
[ -x "$PYTHON" ] || PYTHON="$(command -v python3)"

mkdir -p logs data tmp backups

# ── سنجه‌های پیش از اجرا ─────────────────────────────────────
# ناکامی زودهنگام بهتر از ناکامی نیم‌شب است.
fail=0
if ! command -v ffmpeg >/dev/null 2>&1; then
    echo "✗ ffmpeg در PATH نیست — بی آن هیچ صوتی رمزگشایی نمی‌شود."
    echo "  نصب:  sudo apt update && sudo apt install -y ffmpeg"
    fail=1
fi
if [ ! -f "$ROOT/.env" ]; then
    echo "✗ پروندهٔ .env نیست."
    echo "  ساخت:  cp .env.example .env  && nano .env"
    fail=1
fi
[ "$fail" -eq 0 ] || exit 1

echo "▸ پایتون: $PYTHON"
echo "▸ ffmpeg: $(command -v ffmpeg)"
echo "▸ آغاز حلقهٔ نگهبان — با Ctrl+C بسته می‌شود."

# ── خاموشیِ آرام ─────────────────────────────────────────────
# بی این، Ctrl+C تنها پایتون را می‌کشت و حلقه بی‌درنگ از نو
# راهش می‌انداخت — یعنی بستنِ ربات ناممکن می‌شد.
child=""
shutdown() {
    echo ""
    echo "▸ خاموشی خواسته شد؛ بستنِ آرام…"
    [ -n "$child" ] && kill -INT "$child" 2>/dev/null
    wait "$child" 2>/dev/null
    exit 0
}
trap shutdown INT TERM

# ── حلقهٔ نگهبان ─────────────────────────────────────────────
# درنگِ فزاینده: اگر ایراد پایدار باشد (توکن باطل، شبکهٔ قطع)،
# چرخهٔ تندِ بی‌فایده نسازد.
delay=5
while true; do
    started=$(date +%s)

    "$PYTHON" main.py &
    child=$!
    wait "$child"
    code=$?
    child=""

    ran=$(( $(date +%s) - started ))

    if [ "$code" -eq 0 ]; then
        echo "▸ ربات آرام بسته شد."
        exit 0
    fi

    # اگر بیش از یک دقیقه دوام آورده، ایراد گذرا بوده؛ درنگ
    # از نو کوتاه می‌شود.
    if [ "$ran" -gt 60 ]; then
        delay=5
    else
        delay=$(( delay * 2 ))
        [ "$delay" -gt 300 ] && delay=300
    fi

    echo "✗ ربات با کد $code افتاد (پس از ${ran}s). ${delay}s دیگر از نو…"
    sleep "$delay"
done
