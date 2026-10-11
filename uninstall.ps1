# ถอนการตั้งค่าที่ install.ps1 ทำไว้ (ไม่ลบโฟลเดอร์โปรแกรม — ลบเองได้หลังรันสคริปต์นี้)
$Here = Split-Path -Parent $MyInvocation.MyCommand.Path
Write-Host "จะลบ: ตัวแปร DISPATCH_TOKEN / GEMINI_API_KEY / CLAUDE_WORKDIR, ทางลัดบน Desktop, ปุ่มลัด AI Router ใน VS Code"
if ((Read-Host "ยืนยัน? (y/N)") -notmatch "^[yY]") { exit 0 }

foreach ($v in "DISPATCH_TOKEN", "GEMINI_API_KEY", "CLAUDE_WORKDIR") { [Environment]::SetEnvironmentVariable($v, $null, "User") }
Remove-Item (Join-Path ([Environment]::GetFolderPath("Desktop")) "AI Router.lnk") -ErrorAction SilentlyContinue

$kb = Join-Path $env:APPDATA "Code\User\keybindings.json"
if (Test-Path $kb) {
    $lines = [IO.File]::ReadAllLines($kb) | Where-Object {
        $_ -notmatch "claude-vscode\.focus|antigravity\.toggleChatFocus|AI Router:|toggleChatFocus จะปิดแผง"
    }
    [IO.File]::WriteAllLines($kb, $lines, (New-Object Text.UTF8Encoding $false))
}
Write-Host "เสร็จแล้ว — ลบโฟลเดอร์ $Here ได้เลยถ้าไม่ใช้แล้ว"
Read-Host "กด Enter เพื่อปิด"
