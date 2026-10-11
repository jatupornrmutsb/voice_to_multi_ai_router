# ติดตั้ง AI Router บนเครื่อง Windows เครื่องใหม่
# ใช้ได้กับ Windows PowerShell 5.1 และ PowerShell 7 — รันผ่าน install.bat (ดับเบิลคลิก)
$ErrorActionPreference = "Stop"
$Here = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Here

function Step($text) { Write-Host ""; Write-Host "==> $text" -ForegroundColor Cyan }
function Ok($text)   { Write-Host "    [OK] $text" -ForegroundColor Green }
function Warn($text) { Write-Host "    [!]  $text" -ForegroundColor Yellow }
function Fail($text) { Write-Host "    [X]  $text" -ForegroundColor Red; Read-Host "กด Enter เพื่อปิด"; exit 1 }

function Get-UserEnv($name) { [Environment]::GetEnvironmentVariable($name, "User") }
function Set-UserEnv($name, $value) {
    [Environment]::SetEnvironmentVariable($name, $value, "User")
    Set-Item "env:$name" $value
}

Write-Host "============================================" -ForegroundColor Cyan
Write-Host "  ติดตั้ง AI Router (สั่งงาน AI ด้วยเสียง)" -ForegroundColor Cyan
Write-Host "  โฟลเดอร์: $Here"
Write-Host "============================================" -ForegroundColor Cyan

if ($Here -match "My Drive|Google Drive|OneDrive|Dropbox") {
    Warn "โฟลเดอร์นี้อยู่ใน Cloud Drive — ไฟล์ .venv จำนวนมากจะถูกซิงก์และอาจทำให้ช้า/ล็อกไฟล์"
    Warn "แนะนำให้ย้ายโฟลเดอร์ไปไว้ที่ เช่น C:\Users\<ชื่อ>\ai_router แล้วรันใหม่"
    $ans = Read-Host "    ติดตั้งที่นี่ต่อเลยไหม? (y/N)"
    if ($ans -notmatch "^[yY]") { exit 0 }
}

# ---------------------------------------------------------------
Step "1/6 ตรวจหา Python 3.10 ขึ้นไป"
$py = $null
foreach ($cand in @(@("py", "-3"), @("python"))) {
    try {
        $ver = & $cand[0] @($cand[1..9] | Where-Object { $_ }) -c "import sys; print('%d.%d' % sys.version_info[:2])" 2>$null
        if ($LASTEXITCODE -eq 0 -and $ver -and ([version]$ver -ge [version]"3.10")) { $py = $cand; break }
    } catch { }
}
if (-not $py) {
    Fail "ไม่พบ Python 3.10+ — ติดตั้งจาก https://www.python.org/downloads/ (ติ๊ก 'Add python.exe to PATH') แล้วรัน install.bat ใหม่"
}
Ok "ใช้ Python $ver ($($py -join ' '))"

# ---------------------------------------------------------------
Step "2/6 สร้าง Python แยกเฉพาะโปรแกรม (.venv) และติดตั้งไลบรารี"
if (-not (Test-Path "$Here\.venv\Scripts\python.exe")) {
    & $py[0] @($py[1..9] | Where-Object { $_ }) -m venv "$Here\.venv"
    if ($LASTEXITCODE -ne 0) { Fail "สร้าง .venv ไม่สำเร็จ" }
}
& "$Here\.venv\Scripts\python.exe" -m pip install --disable-pip-version-check -q -r "$Here\requirements.txt"
if ($LASTEXITCODE -ne 0) { Fail "ติดตั้งไลบรารีไม่สำเร็จ — ตรวจอินเทอร์เน็ตแล้วรันใหม่" }
Ok "ติดตั้งไลบรารีครบ"

# ---------------------------------------------------------------
Step "3/6 Token ลับระหว่างหน้าเว็บกับเซิร์ฟเวอร์ (DISPATCH_TOKEN)"
if (Get-UserEnv "DISPATCH_TOKEN") {
    Ok "มีอยู่แล้ว — ใช้ค่าเดิม"
} else {
    $tok = & "$Here\.venv\Scripts\python.exe" -c "import secrets; print(secrets.token_urlsafe(32))"
    Set-UserEnv "DISPATCH_TOKEN" $tok
    Ok "สร้างใหม่และบันทึกแล้ว"
}

# ---------------------------------------------------------------
Step "4/6 Gemini API Key (ไม่บังคับ — ใช้กับปุ่ม 🤖 อัตโนมัติ, ถาม Gemini, Gemini CLI)"
if (Get-UserEnv "GEMINI_API_KEY") {
    Ok "มีอยู่แล้ว — ใช้ค่าเดิม"
} else {
    Write-Host "    ขอ Key ฟรีได้ที่ https://aistudio.google.com/apikey (กด Create API key แล้ว Copy)"
    $sec = Read-Host "    วาง Key แล้วกด Enter (ข้าม = กด Enter เฉยๆ)" -AsSecureString
    $key = [Runtime.InteropServices.Marshal]::PtrToStringAuto([Runtime.InteropServices.Marshal]::SecureStringToBSTR($sec))
    if ($key.Trim()) { Set-UserEnv "GEMINI_API_KEY" $key.Trim(); Ok "บันทึก Key แล้ว" }
    else { Warn "ข้าม — ใช้ได้เฉพาะการกดปุ่มเลือกเครื่องมือ (เพิ่มทีหลังด้วย: setx GEMINI_API_KEY ""<Key>"")" }
}

$wd = Get-UserEnv "CLAUDE_WORKDIR"
if ($wd) {
    Ok "โฟลเดอร์ทำงานของ AI (CLAUDE_WORKDIR): $wd"
} else {
    Write-Host "    โฟลเดอร์โปรเจกต์ที่ให้ Claude Code / Gemini CLI ทำงาน (ไม่ใส่ = โฟลเดอร์โปรแกรมนี้ — ไม่แนะนำ)"
    $wd = Read-Host "    เช่น C:\Users\<ชื่อ>\Projects\myapp (ข้าม = Enter)"
    if ($wd.Trim()) {
        if (Test-Path $wd.Trim()) { Set-UserEnv "CLAUDE_WORKDIR" $wd.Trim(); Ok "บันทึกแล้ว" }
        else { Warn "ไม่พบโฟลเดอร์นี้ — ข้าม (ตั้งทีหลังด้วย: setx CLAUDE_WORKDIR ""<โฟลเดอร์>"")" }
    }
}

# ---------------------------------------------------------------
Step "5/6 ปุ่มลัดใน VS Code (ใช้กับปุ่ม VS Code · Claude / VS Code · Antigravity)"
$kbDir = Join-Path $env:APPDATA "Code\User"
$kb = Join-Path $kbDir "keybindings.json"
$entries = @'
  // AI Router: ส่งข้อความเข้าช่องแชตใน VS Code (ลบได้ถ้าเลิกใช้)
  { "key": "ctrl+shift+alt+f9", "command": "claude-vscode.focus" },
  // toggleChatFocus จะปิดแผงถ้าแชตโฟกัสอยู่แล้ว — จำกัดให้ทำงานเฉพาะตอนแชตยังไม่โฟกัส
  { "key": "ctrl+shift+alt+f10", "command": "antigravity.toggleChatFocus", "when": "!antigravity.chatFocused" },
'@
if (-not (Test-Path $kbDir)) {
    Warn "ไม่พบ VS Code — ข้าม"
} elseif ((Test-Path $kb) -and ((Get-Content $kb -Raw -Encoding UTF8) -match "claude-vscode\.focus")) {
    Ok "มีปุ่มลัดอยู่แล้ว"
} else {
    $utf8 = New-Object Text.UTF8Encoding $false
    if (Test-Path $kb) {
        Copy-Item $kb "$kb.bak-airouter" -Force
        $old = [IO.File]::ReadAllText($kb)
        $i = $old.IndexOf("[")
        if ($i -lt 0) { Warn "รูปแบบ keybindings.json ไม่ปกติ — ข้าม (ดูวิธีเพิ่มเองใน README)" }
        else {
            [IO.File]::WriteAllText($kb, $old.Substring(0, $i + 1) + "`r`n" + $entries + $old.Substring($i + 1), $utf8)
            Ok "เพิ่มปุ่มลัดแล้ว (สำรองไฟล์เดิมไว้ที่ keybindings.json.bak-airouter)"
        }
    } else {
        [IO.File]::WriteAllText($kb, "[`r`n" + $entries + "]`r`n", $utf8)
        Ok "สร้าง keybindings.json พร้อมปุ่มลัดแล้ว"
    }
}

# ---------------------------------------------------------------
Step "6/6 สร้างทางลัด 'AI Router' บน Desktop"
try {
    $ws = New-Object -ComObject WScript.Shell
    $lnk = $ws.CreateShortcut((Join-Path ([Environment]::GetFolderPath("Desktop")) "AI Router.lnk"))
    $lnk.TargetPath = Join-Path $Here "start_router.bat"
    $lnk.WorkingDirectory = $Here
    $lnk.IconLocation = "$env:SystemRoot\System32\SHELL32.dll,138"
    $lnk.Save()
    Ok "สร้างทางลัดแล้ว"
} catch { Warn "สร้างทางลัดไม่สำเร็จ — ใช้ start_router.bat ในโฟลเดอร์นี้แทน" }

# ---------------------------------------------------------------
Step "ตรวจเครื่องมือ AI ที่พบในเครื่องนี้"
$env:PYTHONIOENCODING = "utf-8"
foreach ($v in "DISPATCH_TOKEN", "GEMINI_API_KEY") { $x = Get-UserEnv $v; if ($x) { Set-Item "env:$v" $x } }
& "$Here\.venv\Scripts\python.exe" -c "import local_dispatcher as ld; ld.scan_installed(); ld.print_tools()"

Write-Host ""
Write-Host "ติดตั้งเสร็จแล้ว!" -ForegroundColor Green
Write-Host "เริ่มใช้งาน: ดับเบิลคลิก 'AI Router' บน Desktop (หรือ start_router.bat) แล้วเปิด http://127.0.0.1:5000 ใน Chrome/Edge"
Read-Host "กด Enter เพื่อปิด"
