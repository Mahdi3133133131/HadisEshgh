<#
    ═══════════════════════════════════════════════════════════
      حدیث عشق — نصب پیش‌نیازها
    ═══════════════════════════════════════════════════════════

    اجرا:  روی install.bat دوبار بزنید
    یا:    powershell -ExecutionPolicy Bypass -File install.ps1

    این اسکریپت:
      ۱. پایتونِ مناسب را می‌یابد
      ۲. محیط مجازی .venv را می‌سازد
      ۳. بسته‌ها را نصب می‌کند (فایلِ درست را خودش برمی‌گزیند)
      ۴. ffmpeg را نصب می‌کند
      ۵. setup_project.py را می‌راند

    اجرای دوباره بی‌خطر است.

    گزینه‌ها:
      -Recreate    محیط مجازی را از نو بساز
      -SkipFfmpeg  از نصب ffmpeg بگذر
#>

[CmdletBinding()]
param(
    [switch]$Recreate,
    [switch]$SkipFfmpeg
)

$ErrorActionPreference = 'Stop'
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch { }

$Root = $PSScriptRoot
Set-Location -LiteralPath $Root

function Write-Head($text) {
    Write-Host ""
    Write-Host ("═" * 62)
    Write-Host "  $text"
    Write-Host ("═" * 62)
}
function Write-Step($text) { Write-Host ""; Write-Host "▸ $text" -ForegroundColor Cyan }
function Write-Ok($text)   { Write-Host "  ✓ $text" -ForegroundColor Green }
function Write-Add($text)  { Write-Host "  + $text" -ForegroundColor Green }
function Write-Warn2($text){ Write-Host "  ⚠ $text" -ForegroundColor Yellow }
function Write-Bad($text)  { Write-Host "  ✗ $text" -ForegroundColor Red }

Write-Head "حدیث عشق — نصب پیش‌نیازها"

# ═══════════════════════════════════════════════════════════
#  ۱. یافتن پایتون
# ═══════════════════════════════════════════════════════════
#
# ترتیبِ برگزیدن: ۳٫۱۲ و ۳٫۱۱ نخست، چون نسخه‌های سنجیدهٔ
# requirements.txt برای همان‌ها نوشته شده‌اند. ۳٫۱۳ هم کار
# می‌کند، ولی با فایلِ بستهٔ دیگری.

Write-Step "پایتون"

function Get-PythonInfo($exe, $prefix) {
    $code = "import sys;print(sys.executable+'|'+str(sys.version_info[0])+'.'+str(sys.version_info[1]))"
    # گلایهٔ py.exe خاموش می‌شود. نبودنِ نسخه‌ای، خطا نیست — ما
    # داریم می‌گردیم. بی این، کاربر سه بار «No suitable Python
    # runtime found» می‌بیند و می‌پندارد چیزی شکسته.
    $previous = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        if ($prefix) { $out = & $exe $prefix -c $code 2>$null } else { $out = & $exe -c $code 2>$null }
    } catch {
        return $null
    } finally {
        $ErrorActionPreference = $previous
    }
    if ($LASTEXITCODE -ne 0) { return $null }
    if (-not $out) { return $null }
    $parts = ("$out".Trim() -split '\|')
    if ($parts.Count -ne 2) { return $null }
    return [pscustomobject]@{ Exe = $parts[0]; Version = $parts[1] }
}

$found = @()
if (Get-Command py -ErrorAction SilentlyContinue) {
    foreach ($v in @('3.12', '3.11', '3.13', '3.10')) {
        $info = Get-PythonInfo 'py' "-$v"
        if ($info) { $found += $info }
    }
}
if (Get-Command python -ErrorAction SilentlyContinue) {
    $info = Get-PythonInfo 'python' $null
    if ($info) { $found += $info }
}

if ($found.Count -eq 0) {
    Write-Bad "هیچ پایتونی یافت نشد."
    Write-Host ""
    Write-Host "    پایتون ۳٫۱۲ را از اینجا بگیرید و نصب کنید:"
    Write-Host "      https://www.python.org/downloads/release/python-3128/"
    Write-Host "    هنگام نصب، گزینهٔ «Add python.exe to PATH» را بزنید."
    Write-Host ""
    Write-Host "    یا در همین پنجره:   winget install Python.Python.3.12"
    exit 1
}

# یکتا، سپس برگزیدن بهترین
$unique = @{}
foreach ($p in $found) { if (-not $unique.ContainsKey($p.Exe)) { $unique[$p.Exe] = $p } }
$all = @($unique.Values)

$rank = @{ '3.12' = 0; '3.11' = 1; '3.13' = 2; '3.10' = 3 }
$best = $null
foreach ($p in $all) {
    $r = 9
    if ($rank.ContainsKey($p.Version)) { $r = $rank[$p.Version] }
    if ($null -eq $best) { $best = $p; $bestRank = $r; continue }
    if ($r -lt $bestRank) { $best = $p; $bestRank = $r }
}

foreach ($p in $all) {
    if ($p.Exe -eq $best.Exe) { Write-Ok "پایتون $($p.Version) — برگزیده شد" }
    else { Write-Host "    پایتون $($p.Version) — $($p.Exe)" -ForegroundColor DarkGray }
}

$python = $best.Exe
$pyVersion = $best.Version

# ── فایلِ بسته‌ها ───────────────────────────────────────────
#
# یکی بیش نیست. نسخه‌هایی که روی پایتون ۳٫۱۳ فرق می‌کنند، درون
# همان فایل با نشانگرِ نسخه جدا شده‌اند و pip خودش برمی‌گزیند.
$reqFile = 'requirements.txt'
Write-Ok "فایل بسته‌ها: requirements.txt"

if (-not (Test-Path -LiteralPath (Join-Path $Root $reqFile))) {
    Write-Bad "$reqFile یافت نشد."
    exit 1
}

# ═══════════════════════════════════════════════════════════
#  ۲. محیط مجازی
# ═══════════════════════════════════════════════════════════
#
# چرا محیط مجازی: بسته‌های این ربات نسخه‌های ویژه‌ای می‌خواهند و
# ریختنشان در پایتونِ سراسری، ابزارهای دیگرِ شما را می‌شکند.

Write-Step "محیط مجازی"

$venv = Join-Path $Root '.venv'
$venvPy = Join-Path $venv 'Scripts\python.exe'

if ($Recreate -and (Test-Path -LiteralPath $venv)) {
    Write-Warn2 "محیط پیشین برداشته می‌شود…"
    Remove-Item -LiteralPath $venv -Recurse -Force
}

if (Test-Path -LiteralPath $venvPy) {
    Write-Ok ".venv از پیش هست"
} else {
    Write-Host "    ساختن .venv …" -ForegroundColor DarkGray
    & $python -m venv $venv
    if ($LASTEXITCODE -ne 0) { Write-Bad "ساختن محیط مجازی شکست خورد."; exit 1 }
    Write-Add ".venv ساخته شد"
}

if (-not (Test-Path -LiteralPath $venvPy)) {
    Write-Bad "python.exe در .venv نیست."
    exit 1
}

# ═══════════════════════════════════════════════════════════
#  ۳. بسته‌ها
# ═══════════════════════════════════════════════════════════

Write-Step "بسته‌های پایتون"
Write-Host "    این گام چند دقیقه می‌برد؛ حجمش نزدیک ۵۰۰ مگابایت است." -ForegroundColor DarkGray
Write-Host ""

& $venvPy -m pip install --upgrade pip --quiet --disable-pip-version-check
if ($LASTEXITCODE -ne 0) { Write-Warn2 "به‌روزرسانی pip نشد؛ ادامه می‌دهیم." }

& $venvPy -m pip install -r (Join-Path $Root $reqFile) --disable-pip-version-check
if ($LASTEXITCODE -ne 0) {
    Write-Host ""
    Write-Bad "نصب بسته‌ها شکست خورد."
    Write-Host ""
    Write-Host "    رایج‌ترین علت‌ها:"
    Write-Host "      • پیوند اینترنت — اگر تحریم می‌خورید، ابزار گذر را روشن کنید"
    Write-Host "      • نبودِ چرخِ آماده برای این نسخهٔ پایتون"
    Write-Host ""
    Write-Host "    اگر دومی است، پایتون ۳٫۱۲ را نصب کنید و دوباره بزنید:"
    Write-Host "      winget install Python.Python.3.12"
    exit 1
}
Write-Host ""
Write-Ok "بسته‌ها نصب شدند"

# ── سنجشِ درون‌بُرد ──────────────────────────────────────────
$check = @'
import importlib, sys
missing = []
for name in ("numpy","scipy","librosa","soundfile","sklearn","telegram",
             "dotenv","yaml","mutagen","PIL","yt_dlp","aiohttp","bs4","bidi"):
    try:
        importlib.import_module(name)
    except Exception as exc:
        missing.append(name + " (" + type(exc).__name__ + ")")
try:
    import faster_whisper
    asr = "هست"
except Exception:
    asr = "نیست — لایهٔ متن خاموش می‌ماند"
print("MISSING:" + (", ".join(missing) if missing else ""))
print("ASR:" + asr)
'@
$checkFile = Join-Path $env:TEMP 'hadis_check.py'
Set-Content -LiteralPath $checkFile -Value $check -Encoding UTF8
$result = & $venvPy $checkFile
Remove-Item -LiteralPath $checkFile -Force -ErrorAction SilentlyContinue

foreach ($line in $result) {
    if ($line -like 'MISSING:*') {
        $m = $line.Substring(8).Trim()
        if ($m) { Write-Bad "بار نشد: $m" } else { Write-Ok "همهٔ بسته‌های بایسته بار شدند" }
    }
    if ($line -like 'ASR:*') { Write-Ok "رونویسی محلی: $($line.Substring(4))" }
}

# ═══════════════════════════════════════════════════════════
#  ۴. ffmpeg
# ═══════════════════════════════════════════════════════════
#
# با pip نصب نمی‌شود و نبودنش، رمزگشاییِ صوت — یعنی قلبِ ربات —
# را از کار می‌اندازد. نخست winget، و اگر نشد، ساختِ رسمیِ
# gyan.dev که مستنداتِ خودِ پروژه هم به آن اشاره می‌کند.

Write-Step "ffmpeg"

function Test-Ffmpeg {
    $cmd = Get-Command ffmpeg -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    return $null
}

$ffmpeg = Test-Ffmpeg
if ($ffmpeg) {
    Write-Ok "از پیش هست: $ffmpeg"
} elseif ($SkipFfmpeg) {
    Write-Warn2 "از نصب ffmpeg گذشتیم (-SkipFfmpeg)"
} else {
    $done = $false

    if (Get-Command winget -ErrorAction SilentlyContinue) {
        Write-Host "    نصب با winget …" -ForegroundColor DarkGray
        try {
            & winget install --id Gyan.FFmpeg -e --accept-source-agreements --accept-package-agreements --disable-interactivity
        } catch { }
        # winget مسیر را در همین پنجره تازه نمی‌کند
        $env:Path = [Environment]::GetEnvironmentVariable('Path','Machine') + ';' + [Environment]::GetEnvironmentVariable('Path','User')
        $ffmpeg = Test-Ffmpeg
        if ($ffmpeg) { Write-Add "ffmpeg با winget نصب شد"; $done = $true }
    }

    if (-not $done) {
        Write-Host "    دریافت ساختِ رسمی از gyan.dev …" -ForegroundColor DarkGray
        $tools = Join-Path $Root 'tools'
        $zip = Join-Path $env:TEMP 'ffmpeg-release-essentials.zip'
        try {
            New-Item -ItemType Directory -Path $tools -Force | Out-Null
            $ProgressPreference = 'SilentlyContinue'
            Invoke-WebRequest -Uri 'https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip' -OutFile $zip
            Expand-Archive -LiteralPath $zip -DestinationPath $tools -Force
            Remove-Item -LiteralPath $zip -Force -ErrorAction SilentlyContinue

            $exe = Get-ChildItem -LiteralPath $tools -Recurse -Filter 'ffmpeg.exe' | Select-Object -First 1
            if ($exe) {
                $bin = $exe.Directory.FullName
                $env:Path = "$env:Path;$bin"

                # به PATHِ کاربر افزوده می‌شود، نه PATHِ سامانه —
                # پس دسترسی مدیر نمی‌خواهد و از «متغیرهای محیطی»
                # ویندوز به‌آسانی برداشتنی است.
                $userPath = [Environment]::GetEnvironmentVariable('Path','User')
                if ($null -eq $userPath) { $userPath = '' }
                if ($userPath -notlike "*$bin*") {
                    [Environment]::SetEnvironmentVariable('Path', ($userPath.TrimEnd(';') + ';' + $bin), 'User')
                    Write-Add "به PATHِ کاربر افزوده شد: $bin"
                }
                Write-Add "ffmpeg نصب شد: $bin"
                $done = $true
            }
        } catch {
            Write-Warn2 "دریافت خودکار نشد: $($_.Exception.Message)"
        }
    }

    if (-not $done) {
        Write-Warn2 "ffmpeg نصب نشد."
        Write-Host "     دستی بگیرید:  https://www.gyan.dev/ffmpeg/builds/" -ForegroundColor DarkGray
        Write-Host "     پوشهٔ bin را به PATH بیفزایید." -ForegroundColor DarkGray
        Write-Host "     بی آن، رمزگشاییِ صوت کار نمی‌کند." -ForegroundColor DarkGray
    }
}

# ═══════════════════════════════════════════════════════════
#  ۵. راه‌اندازی پروژه
# ═══════════════════════════════════════════════════════════
#
# از اینجا به بعد را خودِ پروژه می‌داند: پوشه‌ها، .env،
# پایگاه داده، و گنجینهٔ نوشتارها.

Write-Step "راه‌اندازی پروژه"
Write-Host ""

$env:PYTHONIOENCODING = 'utf-8'
& $venvPy (Join-Path $Root 'setup_project.py')
$setupCode = $LASTEXITCODE

# ═══════════════════════════════════════════════════════════
#  ۶. پایان
# ═══════════════════════════════════════════════════════════

if ($setupCode -eq 0) {
    Write-Head "✓ نصب کامل شد"
    Write-Host ""
    Write-Host "  برای روشن کردن ربات:  run.bat" -ForegroundColor Green
    Write-Host "  یا:                   .venv\Scripts\python.exe main.py"
} else {
    Write-Head "نصبِ بسته‌ها انجام شد — ولی پیکربندی نه"
    Write-Host ""
    Write-Host "  پروندهٔ .env را بگشایید و مقادیر راستین را بگذارید،"
    Write-Host "  سپس install.bat را دگربار بزنید."
    Write-Host ""
    Write-Host "  کمترین چیزی که باید پر شود:"
    Write-Host "    BOT_TOKEN، ADMIN_IDS، CHANNEL_ID،"
    Write-Host "    MADAHI_GROUP_ID، FEEDBACK_GROUP_ID"
}
Write-Host ""
exit $setupCode
