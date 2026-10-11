# 🎙 Voice to Multi-AI Router

สั่งงาน AI หลายตัวในเครื่องด้วยเสียงภาษาไทย — พูดหรือพิมพ์ในหน้าเว็บเดียว แล้วส่งไปยัง Gemini, Antigravity, Claude Code, VS Code, Cursor ฯลฯ พร้อมดึงคำตอบกลับมาแสดง

> **English:** A local, single-user Windows tool. Speak (Thai speech recognition in Chrome/Edge) or type a prompt in a local web page, pick an AI tool (or let Gemini pick the cheapest suitable one), and the router dispatches it via CLI/API or by focusing the app window and pasting. Replies from supported tools are shown back in the page. Local-only (`127.0.0.1`), token-protected. See [SECURITY.md](SECURITY.md).

## ความสามารถ

- 🎤 **พูดภาษาไทย** ผ่านไมค์ (Web Speech API ของ Chrome/Edge) หรือพิมพ์เอง
- 🔍 **ตรวจหาเครื่องมือ AI ที่ติดตั้งในเครื่องอัตโนมัติ** แล้วสร้างปุ่มเฉพาะตัวที่มี (ปุ่มจาง = ติดตั้งแต่ยังไม่เปิด)
- 🤖 **โหมดอัตโนมัติ** — Gemini เลือกเครื่องมือจากคำพูด โดย **เลือกตัวฟรีก่อน** (🟢 → 🟡 → 🔴) เว้นแต่พูดชื่อเครื่องมือเอง
- 📥 **ดึงคำตอบกลับ** มาแสดงในหน้าเว็บ (Claude Code, Gemini CLI, Gemini API, Antigravity, VS Code · Claude)
- ⏳ **งานเบื้องหลัง** — สั่งหลายงานพร้อมกัน เห็นสถานะ ⏳/✅/❌ หยุดงานได้ คัดลอกคำตอบได้
- 🔒 **ปลอดภัยโดยค่าเริ่มต้น** — ฟังเฉพาะเครื่องตัวเอง, Token, ตรวจ Host, CSP, ไม่ผ่าน shell

## เครื่องมือที่รองรับ

| เครื่องมือ | ค่าใช้จ่าย | วิธีส่งงาน | คำตอบกลับหน้าเว็บ |
| :--- | :--- | :--- | :--- |
| ถาม Gemini (เร็ว) | 🟢 ฟรี (Gemini API Key) | Gemini API | ✅ |
| Gemini CLI | 🟢 ฟรี (Gemini API Key) | `gemini -p` เบื้องหลัง | ✅ |
| Ollama | 🟢 ฟรี (ในเครื่อง) | REST API | ✅ |
| Antigravity / Antigravity IDE / VS Code · Antigravity | 🟡 บัญชี Google (Gemini Pro ได้โควตามากกว่า) | สลับหน้าต่าง → ปุ่มลัดเปิดแชต → วาง | ✅ |
| Gemini (แอป Desktop) | 🟡 | สลับหน้าต่าง → วาง | ❌ |
| Cursor | 🟡 แพ็กเกจฟรีจำกัด | สลับหน้าต่าง → `Ctrl+L` → วาง | ❌ |
| Claude (แอป Desktop) | 🟡 แพ็กเกจฟรีจำกัด | สลับหน้าต่าง → วาง | ❌ |
| Claude Code | 🔴 แพ็กเกจ Claude | `claude -p` เบื้องหลัง | ✅ |
| VS Code · Claude | 🔴 แพ็กเกจ Claude | สลับหน้าต่าง → `Ctrl+Shift+Alt+F9` → วาง | ✅ |

ค่าใช้จ่ายและโควตาของแต่ละบริการเปลี่ยนได้ — ตรวจที่หน้าบัญชีของบริการนั้น

## ความต้องการของระบบ

- Windows 10/11
- Python 3.10+ — <https://www.python.org/downloads/> (ตอนติดตั้ง **ติ๊ก "Add python.exe to PATH"**)
- Google Chrome หรือ Microsoft Edge
- (แนะนำ) Gemini API Key ฟรี — <https://aistudio.google.com/apikey>
- (ตามต้องการ) โปรแกรม AI ที่จะใช้ — ติดตั้งและล็อกอินให้เรียบร้อย · Gemini CLI: `npm install -g @google/gemini-cli`

## ติดตั้ง

1. ดาวน์โหลด repo (**Code → Download ZIP**) แล้วแตกไฟล์ไว้ในไดรฟ์ของเครื่อง เช่น `C:\Users\<ชื่อ>\voice_to_multi_ai_router`
   (ไม่แนะนำ Google Drive / OneDrive — ระบบจะสร้างไฟล์ `.venv` จำนวนมาก)
2. ดับเบิลคลิก **`install.bat`**
3. ตอบคำถามตอนรันครั้งแรก (กด Enter เพื่อข้ามได้):
   - **Gemini API Key** — ตัวอักษรไม่แสดงบนจอ
   - **โฟลเดอร์โปรเจกต์** ที่ให้ Claude Code / Gemini CLI ทำงาน
4. ดับเบิลคลิก **AI Router** บน Desktop → เบราว์เซอร์เปิด `http://127.0.0.1:5000`

ตัวติดตั้งจะ: สร้าง `.venv` + ติดตั้งไลบรารี · สร้าง Token ลับ (`DISPATCH_TOKEN`) · บันทึกค่าเป็น Environment Variables ของผู้ใช้ · เพิ่มปุ่มลัดใน VS Code (สำรองไฟล์เดิมเป็น `keybindings.json.bak-airouter`) · สร้างทางลัดบน Desktop
รันซ้ำได้โดยไม่ทับค่าเดิม · ถอนการติดตั้ง: **`uninstall.bat`**

## วิธีใช้

> 📘 คู่มือละเอียดทีละขั้น ตัวอย่าง และการแก้ปัญหา: [docs/USER_GUIDE.md](docs/USER_GUIDE.md)

1. เปิดโปรแกรม AI ที่จะใช้ไว้ (ยกเว้น Claude Code / Gemini CLI ที่รันเบื้องหลัง)
2. ในหน้า AI Router: กดปุ่มเครื่องมือ (หรือ `Alt+0…9`) — หรือกด **🤖 อัตโนมัติ**
3. กด 🎤 (`Alt+M`) แล้วพูด หรือกดปุ่ม **ส่ง ▶** ค้างไว้แล้วพูด
4. ส่ง (`Ctrl+Enter`) — ติ๊ก **Auto Send** ถ้าต้องการให้กด Enter ในโปรแกรมปลายทางให้ด้วย
5. ดูคำตอบในส่วน **งานเบื้องหลัง / คำตอบที่ดึงกลับ**

ระหว่างระบบสลับหน้าต่างและวางข้อความ (~1 วินาที) **อย่าขยับเมาส์หรือพิมพ์** · หยุดฉุกเฉิน: ลากเมาส์ไปมุมซ้ายบนของจอ

## ตั้งค่าเพิ่มเติม (Environment Variables)

| ตัวแปร | ค่าเริ่มต้น | ความหมาย |
| :--- | :--- | :--- |
| `DISPATCH_TOKEN` | สร้างโดย `install.bat` | Token ลับระหว่างหน้าเว็บกับเซิร์ฟเวอร์ (≥ 24 ตัวอักษร) |
| `GEMINI_API_KEY` | — | เปิดใช้ 🤖 อัตโนมัติ, ถาม Gemini, Gemini CLI |
| `CLAUDE_WORKDIR` | โฟลเดอร์โปรแกรม | โฟลเดอร์ที่ Claude Code / Gemini CLI ทำงาน (ควรตั้งเป็นโปรเจกต์ที่อยู่ใน git) |
| `CLAUDE_PERMISSION_MODE` | — | เช่น `acceptEdits` ให้ Claude Code แก้ไฟล์เองได้ |
| `GEMINI_CLI_APPROVAL_MODE` | — | `default` / `auto_edit` / `yolo` / `plan` |
| `GEMINI_MODEL` | `gemini-flash-lite-latest` | รุ่นที่ใช้เลือกเครื่องมือ |
| `GEMINI_ANSWER_MODEL` | `gemini-flash-latest` | รุ่นที่ใช้ตอบในปุ่ม ถาม Gemini (ไม่ตอบใน 10 วิ → สลับไปรุ่น Lite) |
| `GEMINI_CLI_MODEL` | `gemini-flash-latest` | รุ่นของ Gemini CLI |
| `OLLAMA_URL` / `OLLAMA_MODEL` | `http://127.0.0.1:11434` / `llama3.2` | โมเดลในเครื่อง |

ตั้งค่าด้วย `setx ชื่อตัวแปร "ค่า"` ใน PowerShell แล้วปิด/เปิด AI Router ใหม่

## ความปลอดภัยและความเป็นส่วนตัว

ระบบนี้ **พิมพ์ข้อความลงโปรแกรมและรันเครื่องมือ AI บนเครื่องของคุณ** — อ่าน [SECURITY.md](SECURITY.md) ก่อนใช้งาน สรุปสั้นๆ:

- ใช้บนเครื่องเดียวเท่านั้น (ฟัง `127.0.0.1`) — อย่าเปิดให้เครื่องอื่นเข้าถึง
- เสียงถูกส่งไปถอดความที่ Google และข้อความในโหมด Gemini ถูกส่งไป Gemini API — **อย่าพูดข้อมูลลับ**
- แต่ละคนใช้ API Key ของตัวเอง · โฟลเดอร์ `logs/` เก็บคำสั่งและคำตอบไว้ในเครื่อง

## ข้อจำกัดที่ทราบ

- รองรับเฉพาะ Windows (ใช้ Win32 API สลับหน้าต่างและจำลองการกดแป้น)
- การดึงคำตอบกลับอ่านไฟล์บันทึกแชตในเครื่องของ Claude Code / Antigravity ซึ่งไม่มีเอกสารทางการ — ถ้าโปรแกรมอัปเดตแล้วรูปแบบเปลี่ยน การส่งข้อความยังใช้ได้ แต่คำตอบอาจไม่กลับมา
- Gemini CLI ล็อกอินด้วยบัญชี Google ไม่ได้แล้ว ระบบจึงใช้ Gemini API Key แทน (ตั้งค่าเฉพาะ CLI ที่ระบบนี้รัน)
- ปุ่มลัดเปิดแชตของแต่ละโปรแกรมอาจต่างกันตามเวอร์ชัน — แก้ได้ที่ `hotkey` ใน `TOOLS` ของ `local_dispatcher.py`

## โครงสร้างไฟล์

| ไฟล์ | หน้าที่ |
| :--- | :--- |
| `local_dispatcher.py` | เซิร์ฟเวอร์ Flask: ตรวจหาเครื่องมือ, เลือกเครื่องมือด้วย Gemini, ส่งงาน, ติดตามคำตอบ |
| `voice_panel.html` | หน้าเว็บ: ไมค์, ปุ่มเครื่องมือ, งานเบื้องหลัง |
| `install.bat` / `install.ps1` | ตัวติดตั้ง |
| `start_router.bat` | เปิดใช้งาน (ยังไม่ติดตั้ง → เรียกตัวติดตั้งให้) |
| `uninstall.bat` / `uninstall.ps1` | ถอนการตั้งค่า |
| `requirements.txt` | ไลบรารี Python (ล็อกเวอร์ชัน) |

## สัญญาอนุญาต

[MIT](LICENSE)
