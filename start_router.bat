@echo off
chcp 65001 >nul
set PYTHONIOENCODING=utf-8
cd /d "%~dp0"
rem ยังไม่เคยติดตั้ง (ไม่มี .venv หรือยังไม่มี Token) — เรียกตัวติดตั้งก่อน ซึ่งจะถามค่าที่ต้องใช้
if not exist ".venv\Scripts\python.exe" goto install
if "%DISPATCH_TOKEN%"=="" goto install
goto run
:install
call "%~dp0install.bat"
echo.
echo ติดตั้งเสร็จแล้ว — ปิดหน้าต่างนี้แล้วดับเบิลคลิก 'AI Router' บน Desktop อีกครั้งเพื่อเริ่มใช้งาน
pause
exit /b
:run
rem เปิดหน้าสั่งงานด้วยเสียงในเบราว์เซอร์หลังเซิร์ฟเวอร์เริ่ม 3 วินาที
start "" /min powershell -NoProfile -WindowStyle Hidden -Command "Start-Sleep 3; Start-Process 'http://127.0.0.1:5000'"
".venv\Scripts\python.exe" local_dispatcher.py
pause
