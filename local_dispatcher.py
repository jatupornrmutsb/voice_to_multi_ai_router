import ctypes
import glob
import hmac
import itertools
import json
import os
import shutil
import subprocess
import threading
import time
from datetime import datetime
from typing import Literal

import pyautogui
import pygetwindow as gw
import pyperclip
import requests
from flask import Flask, Response, abort, jsonify, request
from google import genai
from google.genai import types
from pydantic import BaseModel, Field

# ---------------------------------------------------------------
# 1. ตั้งค่าพื้นฐาน (อ่านจาก Environment Variables)
# ---------------------------------------------------------------
DISPATCH_TOKEN = os.environ.get("DISPATCH_TOKEN", "")    # รหัสลับร่วมกับหน้าเว็บ (บังคับ)
if len(DISPATCH_TOKEN) < 24:
    # Token สั้นเดาง่าย — ใครรู้ Token สั่งพิมพ์/รันคำสั่งบนเครื่องนี้ได้ จึงไม่ยอมเริ่มทำงาน
    raise SystemExit("DISPATCH_TOKEN ไม่ได้ตั้งหรือสั้นเกินไป (ต้องยาว ≥ 24 ตัวอักษร) — รัน install.bat เพื่อสร้างใหม่")
MAX_PROMPT_CHARS = 8000          # ข้อความยาวเกินนี้ถูกปฏิเสธ (บรรทัดคำสั่งของ Windows จำกัด ~32,000 ตัวอักษร)
# รุ่น Lite เร็วและโควตาฟรีมากกว่า พอสำหรับงานเลือกเครื่องมือ
# ใช้ชื่อแฝง "latest" เพื่อไม่ต้องแก้โค้ดเมื่อ Google เลิกให้บริการรุ่นเก่า (gemini-2.5-flash ใช้ไม่ได้กับผู้ใช้ใหม่แล้ว)
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-flash-lite-latest")
# รุ่นที่ใช้ตอบคำถามในปุ่ม "Gemini API" (ถ้าโควตาเต็ม/ไม่ว่าง จะลองรุ่น GEMINI_MODEL แทน)
GEMINI_ANSWER_MODEL = os.environ.get("GEMINI_ANSWER_MODEL", "gemini-flash-latest")
# โฟลเดอร์ที่ Claude Code / Gemini CLI ทำงาน
CLAUDE_WORKDIR = os.environ.get("CLAUDE_WORKDIR", os.getcwd())
CLAUDE_PERMISSION_MODE = os.environ.get("CLAUDE_PERMISSION_MODE", "")      # เช่น acceptEdits
GEMINI_CLI_APPROVAL_MODE = os.environ.get("GEMINI_CLI_APPROVAL_MODE", "")  # เช่น auto_edit
GEMINI_CLI_MODEL = os.environ.get("GEMINI_CLI_MODEL", "gemini-flash-latest")
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "llama3.2")
PORT = 5000
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PAGE_PATH = os.path.join(BASE_DIR, "voice_panel.html")   # หน้าเว็บสั่งงานด้วยเสียง
LOG_DIR = os.path.join(BASE_DIR, "logs")
GEMINI_CLI_SETTINGS = os.path.join(BASE_DIR, "gemini_cli_settings.json")
os.makedirs(LOG_DIR, exist_ok=True)

LOCAL = os.environ.get("LOCALAPPDATA", "")
PROGRAMS = os.path.join(LOCAL, "Programs")
PROGRAM_FILES = os.environ.get("ProgramFiles", r"C:\Program Files")

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 64 * 1024   # คำขอใหญ่กว่า 64 KB ถูกปฏิเสธ (413)


@app.after_request
def security_headers(resp):
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["Referrer-Policy"] = "no-referrer"
    resp.headers["Cache-Control"] = "no-store"
    return resp

# ไม่มี GEMINI_API_KEY ก็รันได้ — ใช้ได้เฉพาะการกดปุ่มเลือกเครื่องมือ
# (ปุ่ม 🤖 อัตโนมัติ, ถาม Gemini และ Gemini CLI จะปิด)
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
# timeout 20 วินาที — บางครั้ง Google ไม่ตอบเลย (เคยค้างจนหน้าเว็บขึ้น "กำลังส่ง…" ไม่จบ)
client = genai.Client(api_key=GEMINI_API_KEY,
                      http_options=types.HttpOptions(timeout=20_000)) if GEMINI_API_KEY else None
gui_lock = threading.Lock()   # กันไม่ให้สองคำขอแย่งคีย์บอร์ด/คลิปบอร์ดพร้อมกัน
pyautogui.FAILSAFE = True     # เลื่อนเมาส์ไปมุมซ้ายบนเพื่อหยุดฉุกเฉิน


# ---------------------------------------------------------------
# 2. ตรวจหาโปรแกรมที่ติดตั้งในเครื่อง
# ---------------------------------------------------------------
def first_existing(*paths):
    return next((p for p in paths if p and os.path.isfile(p)), None)


def find_claude_exe():
    """คืน path ของ claude.exe ตัวจริงเท่านั้น (ไม่ใช้ .cmd เพราะ cmd.exe ตีความอักขระพิเศษได้)"""
    exe = shutil.which("claude")
    if exe:
        if exe.lower().endswith(".exe"):
            return exe
        # ติดตั้งผ่าน npm: claude.cmd เป็นตัวห่อ — ใช้ claude.exe ในแพ็กเกจแทน
        npm_exe = os.path.join(os.path.dirname(exe), "node_modules",
                               "@anthropic-ai", "claude-code", "bin", "claude.exe")
        if os.path.isfile(npm_exe):
            return npm_exe
    # ติดตั้งแบบ native installer
    return first_existing(os.path.expanduser(r"~\.local\bin\claude.exe"))


def find_gemini_cli():
    """คืน (node.exe, gemini.js) — เรียก node ตรงๆ แทน gemini.cmd เพื่อไม่ผ่าน cmd.exe"""
    node, shim = shutil.which("node"), shutil.which("gemini")
    if not (node and shim):
        return None
    pkg_dir = os.path.join(os.path.dirname(shim), "node_modules", "@google", "gemini-cli")
    try:
        with open(os.path.join(pkg_dir, "package.json"), encoding="utf-8") as f:
            bin_path = json.load(f)["bin"]["gemini"]
    except (OSError, KeyError, ValueError):
        return None
    script = os.path.join(pkg_dir, bin_path)
    # ใช้ได้เฉพาะเมื่อมี GEMINI_API_KEY (ล็อกอินด้วยบัญชี Google ใช้ไม่ได้แล้ว)
    return (node, script) if os.path.isfile(script) and GEMINI_API_KEY else None


def find_vscode():
    return first_existing(os.path.join(PROGRAMS, "Microsoft VS Code", "Code.exe"),
                          os.path.join(PROGRAM_FILES, "Microsoft VS Code", "Code.exe"))


def find_appx(name):
    """หาแอปที่ติดตั้งจาก Microsoft Store"""
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-Command", f"(Get-AppxPackage -Name {name}).InstallLocation"],
            capture_output=True, text=True, timeout=20,
        ).stdout.strip()
        return out or None
    except (OSError, subprocess.SubprocessError):
        return None


def find_gemini_desktop():
    return first_existing(os.path.join(LOCAL, "Google", "Gemini", "Gemini.exe"),
                          *glob.glob(os.path.join(LOCAL, "Google", "Gemini", "app-*", "Gemini.exe")))


def ollama_ready():
    try:
        return requests.get(f"{OLLAMA_URL}/api/tags", timeout=1).ok
    except requests.RequestException:
        return False


def claude_cli_args(exe, prompt):
    args = [exe, "-p", prompt]
    if CLAUDE_PERMISSION_MODE:
        args += ["--permission-mode", CLAUDE_PERMISSION_MODE]
    return args


def gemini_cli_args(found, prompt):
    node, script = found
    # ระบุรุ่นเอง — ค่าเริ่มต้นของ CLI ชี้ไปรุ่นที่ Google เลิกให้บริการผู้ใช้ใหม่แล้ว
    args = [node, script, "-m", GEMINI_CLI_MODEL, "-p", prompt]
    if GEMINI_CLI_APPROVAL_MODE:
        args += ["--approval-mode", GEMINI_CLI_APPROVAL_MODE]
    return args


def gemini_cli_env():
    # Google ปิดการล็อกอินด้วยบัญชี Google (Gemini Code Assist for individuals) สำหรับ Gemini CLI แล้ว
    # จึงบังคับให้ใช้ GEMINI_API_KEY ผ่านไฟล์ system settings — มีผลเฉพาะ CLI ที่ระบบนี้สั่งรัน
    # (การใช้ gemini ในเทอร์มินัลตามปกติไม่ถูกเปลี่ยน)
    with open(GEMINI_CLI_SETTINGS, "w", encoding="utf-8") as f:
        json.dump({"security": {"auth": {"selectedType": "gemini-api-key"}}}, f)
    env = os.environ.copy()
    env["GEMINI_CLI_SYSTEM_SETTINGS_PATH"] = GEMINI_CLI_SETTINGS
    env["COLORTERM"] = "truecolor"   # ปิดคำเตือนเรื่องสีของเทอร์มินัลใน log
    return env


# แคตตาล็อกเครื่องมือ: เพิ่มเครื่องมือใหม่ได้ที่นี่ที่เดียว
#   kind  : cli (รันเบื้องหลัง แสดงผลในส่วนงานเบื้องหลัง) / gui (สลับหน้าต่างแล้ววาง)
#           ollama / gemini_api (เรียก API แล้วตอบทันที)
#   hint  : คำอธิบายให้ Gemini ใช้ตัดสินใจ และใช้เป็น tooltip ของปุ่ม
#   find  : คืนสิ่งที่ต้องใช้รัน (path) หรือ None ถ้าไม่ได้ติดตั้ง
#   args  : (cli) สร้างคำสั่งเป็น list — ไม่ผ่าน shell
#   match : (gui) ตรวจชื่อหน้าต่างให้เฉพาะเจาะจง เพื่อไม่ให้วางผิดหน้าต่าง
#   prefocus: (gui) ปุ่มลัดที่กดก่อน hotkey (ถ้ามี) · hotkey: (gui) ปุ่มลัดเปิดช่องแชตก่อนวาง · hotkey_wait: วินาทีที่รอหลังกดปุ่มลัด (ค่าเริ่มต้น 0.3)
TOOLS = {
    "claude_cli": {
        "label": "Claude Code", "kind": "cli",
        "hint": "ใช้เมื่อผู้ใช้ระบุ Claude Code หรืองานใหญ่ทั้งโปรเจกต์ที่ต้องการ Claude โดยเฉพาะ (ทำเบื้องหลัง)",
        "find": find_claude_exe,
        "args": claude_cli_args,
    },
    "gemini_cli": {
        "label": "Gemini CLI", "kind": "cli",
        "hint": "ผู้ใช้ระบุ Gemini CLI หรืองานค้นข้อมูลจากเว็บ สรุปเนื้อหา เขียนโค้ด แบบทำเบื้องหลัง (ใช้โควตา API Key)",
        "find": find_gemini_cli,
        "args": gemini_cli_args,
        "env": gemini_cli_env,
    },
    "gemini_api": {
        "label": "ถาม Gemini (เร็ว)", "kind": "gemini_api",
        "hint": "คำถามสั้นๆ ทั่วไปที่ต้องการคำตอบทันทีในหน้าเว็บ ไม่ต้องใช้โปรแกรมอื่น",
        "find": lambda: GEMINI_MODEL if client else None,
    },
    # VS Code: ส่งเข้าแชตของส่วนขยาย Claude Code / Antigravity (ไม่ใช่ Copilot Chat)
    # ปุ่มลัดตั้งไว้ใน %APPDATA%\Code\User\keybindings.json (ctrl+shift+alt+F9/F10 → คำสั่งโฟกัสช่องแชต)
    "vscode_claude": {
        "label": "VS Code · Claude", "kind": "gui",
        "hint": "ผู้ใช้ระบุว่าให้ทำใน VS Code หรือ Claude ใน VS Code",
        "find": find_vscode,
        "match": lambda t: t.endswith(" - Visual Studio Code"),
        "hotkey": ("ctrl", "shift", "alt", "f9"),
        "hotkey_wait": 0.8,
    },
    "vscode_antigravity": {
        "label": "VS Code · Antigravity", "kind": "gui",
        "hint": "ผู้ใช้ระบุว่าให้ทำใน Antigravity ที่อยู่ใน VS Code",
        "find": find_vscode,
        "match": lambda t: t.endswith(" - Visual Studio Code"),
        "hotkey": ("ctrl", "shift", "alt", "f10"),
        "hotkey_wait": 1.2,
    },
    "cursor": {
        "label": "Cursor", "kind": "gui",
        "hint": "ผู้ใช้ระบุว่าให้ทำใน Cursor หรืองานแก้ฟังก์ชันเฉพาะจุด",
        "find": lambda: first_existing(os.path.join(PROGRAMS, "cursor", "Cursor.exe")),
        "match": lambda t: t.endswith(" - Cursor"),
        "hotkey": ("ctrl", "l"),
    },
    "antigravity": {
        "label": "Antigravity", "kind": "gui",
        "hint": "ผู้ใช้ระบุชัดว่าแอป Antigravity ตัวที่ไม่ใช่ IDE (ถ้าพูดแค่ 'Antigravity' ให้เลือก antigravity_ide)",
        "find": lambda: first_existing(os.path.join(PROGRAMS, "Antigravity", "Antigravity.exe")),
        "match": lambda t: t.endswith(" - Antigravity") or t.strip() == "Antigravity",
        "hotkey": ("ctrl", "l"),   # ตรวจกับเครื่องจริงก่อน
    },
    "antigravity_ide": {
        # ไม่ใช้ CLI "antigravity-ide chat" — ทดสอบแล้วข้อความไม่เข้าแผง Agent (เข้าแชตแบบ VS Code เดิม)
        # Ctrl+L เป็นแบบสลับ — ถ้าช่องแชตโฟกัสอยู่แล้วจะปิดแผง จึงกด Ctrl+1 (โฟกัส editor) ก่อน
        # แล้ว Ctrl+L จะโฟกัสช่องพิมพ์ของแชตเดิมเสมอ (Ctrl+Shift+L = เปิดแชตใหม่ทุกครั้ง)
        "label": "Antigravity IDE", "kind": "gui",
        "hint": "งานเขียน/แก้โค้ดทั่วไป (ตัวเลือกหลักสำหรับงานโค้ด) หรือผู้ใช้ระบุ Antigravity IDE / Antigravity (ใช้สิทธิ์ Gemini Pro)",
        "find": lambda: first_existing(os.path.join(PROGRAMS, "Antigravity IDE", "Antigravity IDE.exe")),
        "match": lambda t: t.endswith(" - Antigravity IDE") or t.strip() == "Antigravity IDE",
        "prefocus": ("ctrl", "1"),
        "hotkey": ("ctrl", "l"),
        "hotkey_wait": 1.2,   # แผงแชตต้องใช้เวลาวาดช่องพิมพ์ — วางเร็วกว่านี้ข้อความจะไม่เข้า
    },
    "claude_gui": {
        "label": "Claude", "kind": "gui",
        "hint": "งานเอกสาร งานเขียน สนทนาทั่วไปกับ Claude",
        "find": lambda: first_existing(os.path.join(LOCAL, "AnthropicClaude", "claude.exe"))
                        or find_appx("Claude"),
        "match": lambda t: t.strip() == "Claude",
        "hotkey": None,
    },
    "gemini_gui": {
        "label": "Gemini", "kind": "gui",
        "hint": "ผู้ใช้ระบุว่าให้ทำในแอป Gemini (Desktop)",
        "find": find_gemini_desktop,
        "match": lambda t: t.strip() == "Gemini",
        "hotkey": None,
    },
    "ollama": {
        "label": "Ollama", "kind": "ollama",
        "hint": "ผู้ใช้ระบุว่าใช้โมเดลในเครื่อง/ออฟไลน์",
        "find": lambda: shutil.which("ollama")
                        or first_existing(os.path.join(PROGRAMS, "Ollama", "ollama.exe")),
    },
}

# ค่าใช้จ่ายของแต่ละเครื่องมือ (ป้ายบนปุ่ม):
#   free     🟢 ฟรี — Gemini API Key ฟรี / โมเดลในเครื่อง
#   included 🟡 ฟรีแบบจำกัด หรือใช้สิทธิ์ที่มีอยู่แล้ว (Gemini Pro / แพ็กเกจฟรีของแอป) — ไม่เสียเงินเพิ่ม
#   paid     🔴 ใช้โควตาแพ็กเกจ Claude — เก็บไว้ใช้เฉพาะงานที่ต้องการความสามารถของ Claude
TOOL_COST = {
    "gemini_api": "free", "gemini_cli": "free", "ollama": "free",
    "antigravity": "included", "antigravity_ide": "included", "vscode_antigravity": "included",
    "gemini_gui": "included", "cursor": "included", "claude_gui": "included",
    "claude_cli": "paid", "vscode_claude": "paid",
}
# ลำดับปุ่ม: ฟรีก่อน → ใช้สิทธิ์ที่มี → ใช้โควตา Claude (Alt+1…9 ตามลำดับนี้)
# เครื่องมือที่เพิ่มใหม่แต่ไม่อยู่ในรายการนี้จะต่อท้ายตามกลุ่มค่าใช้จ่าย
TOOL_ORDER = [
    "gemini_api", "gemini_cli", "ollama",
    "antigravity", "antigravity_ide", "vscode_antigravity", "gemini_gui", "cursor", "claude_gui",
    "claude_cli", "vscode_claude",
]
COST_RANK = {"free": 0, "included": 1, "paid": 2}
TOOLS = {tid: TOOLS[tid] for tid in sorted(TOOLS, key=lambda t: (
    COST_RANK[TOOL_COST.get(t, "included")], TOOL_ORDER.index(t) if t in TOOL_ORDER else len(TOOL_ORDER)))}

TargetName = Literal["claude_cli", "gemini_cli", "gemini_api", "vscode_claude", "vscode_antigravity",
                     "cursor", "antigravity",
                     "antigravity_ide", "claude_gui", "gemini_gui", "ollama", "none"]

installed = {}   # id → สิ่งที่ find คืนมา (None = ไม่พบ) — สแกนตอนเริ่มและเมื่อสั่ง rescan


def scan_installed():
    for tid, tool in TOOLS.items():
        try:
            installed[tid] = tool["find"]()
        except Exception:
            installed[tid] = None
    return installed


def find_window(tid):
    match = TOOLS[tid]["match"]
    for win in gw.getAllWindows():
        if win.title and match(win.title):
            return win
    return None


def is_running(tid):
    if not installed.get(tid):
        return False
    kind = TOOLS[tid]["kind"]
    if kind in ("cli", "gemini_api"):
        return True
    if kind == "ollama":
        return ollama_ready()
    return find_window(tid) is not None


def tool_list():
    return [
        {"id": tid, "label": t["label"], "kind": t["kind"], "hint": t["hint"],
         "cost": TOOL_COST.get(tid, "included"),
         "installed": bool(installed.get(tid)), "running": is_running(tid)}
        for tid, t in TOOLS.items()
    ]


def print_tools():
    print("=" * 56)
    print("🔍 เครื่องมือ AI ในเครื่อง")
    print("=" * 56)
    for t in tool_list():
        icon = ("🟢 พร้อมใช้งาน" if t["running"] else "⚪ ติดตั้งแล้ว/ยังไม่เปิด") if t["installed"] \
            else "⚫ ไม่ได้ติดตั้ง"
        print(f"{icon:<22} : {t['label']}")
    print(f"{'🟢' if client else '⚫'} Gemini (โหมดอัตโนมัติ) : {'พร้อม' if client else 'ไม่ได้ตั้ง GEMINI_API_KEY'}")
    print("=" * 56)


# ---------------------------------------------------------------
# 3. Gemini API: จำแนกปลายทาง และตอบคำถามเร็ว
# ---------------------------------------------------------------
class AIRoutingDecision(BaseModel):
    target_ai: TargetName = Field(
        description="ปลายทางที่เหมาะสมที่สุด เลือกจากรายการที่พร้อมใช้งานเท่านั้น หรือ 'none'"
    )
    clean_prompt: str = Field(
        description="คำสั่งที่ตัดคำเรียกชื่อ AI และคำฟุ่มเฟือยออกแล้ว เหลือเฉพาะเนื้องาน"
    )


def gemini_error_message(e):
    """แปลง error ของ Gemini เป็นข้อความภาษาไทยที่บอกว่าต้องทำอะไร"""
    code = getattr(e, "code", None)
    if code == 429:
        return "โควตาฟรีของ Gemini เต็มชั่วคราว — รอประมาณ 1 นาที หรือกดปุ่มเลือกเครื่องมือเองแทน"
    if code == 503:
        return "Gemini มีผู้ใช้มากชั่วคราว — ลองใหม่อีกครั้ง หรือกดปุ่มเลือกเครื่องมือเองแทน"
    if code == 504 or "timed out" in str(e).lower() or "timeout" in type(e).__name__.lower():
        return "Gemini ตอบช้าเกินไป (หมดเวลา) — ลองใหม่อีกครั้ง หรือกดปุ่มเลือกเครื่องมือเองแทน"
    if code in (400, 401, 403):
        return "Gemini API Key ไม่ถูกต้องหรือถูกยกเลิก — ตรวจ GEMINI_API_KEY แล้วเปิด start_router.bat ใหม่"
    # รายละเอียด error อาจมีข้อมูลภายใน — แสดงเฉพาะในหน้าต่างเซิร์ฟเวอร์ ไม่ส่งให้หน้าเว็บ
    print(f"[Gemini error] {type(e).__name__}: {e}")
    return "Gemini ผิดพลาด — ดูรายละเอียดในหน้าต่าง AI Router แล้วลองใหม่ หรือกดปุ่มเลือกเครื่องมือเองแทน"


def route(text):
    if client is None:
        raise RuntimeError("ยังไม่ได้ตั้ง GEMINI_API_KEY — กดเลือกเครื่องมือเองแทน")
    rules = "\n".join(
        f"- '{t['id']}': {t['hint']} ({'พร้อมใช้' if t['running'] else 'ไม่พร้อม'}, ค่าใช้จ่าย: {t['cost']})"
        for t in tool_list() if t["installed"]
    )
    response = client.models.generate_content(
        model=GEMINI_MODEL,
        contents=(
            "เลือกปลายทางสำหรับคำสั่งของผู้ใช้จากรายการนี้:\n"
            f"{rules}\n"
            "- 'none': จำแนกไม่ได้ หรือผู้ใช้ระบุเครื่องมือที่ไม่อยู่ในรายการ\n"
            "ถ้าผู้ใช้เอ่ยชื่อเครื่องมือในรายการ ให้เลือกตัวนั้นเสมอ แม้สถานะจะไม่พร้อมใช้ "
            "(ระบบจะแจ้งผู้ใช้ให้เปิดโปรแกรมเอง) ถ้าไม่เอ่ยชื่อ ให้เลือกเฉพาะตัวที่พร้อมใช้ "
            "และเลือกตัวที่ประหยัดก่อน: free → included → paid (ใช้ paid เฉพาะงานที่ต้องการ Claude จริงๆ "
            "เช่น ผู้ใช้ขอ Claude หรืองานแก้โค้ดทั้งโปรเจกต์)\n\n"
            f"คำสั่งเสียงของผู้ใช้ (ถอดความแล้ว): {text!r}"
        ),
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=AIRoutingDecision,
            temperature=0.1,
        ),
    )
    if isinstance(response.parsed, AIRoutingDecision):
        return response.parsed
    return AIRoutingDecision.model_validate_json(response.text)


def ask_gemini(prompt):
    """ถามตอบเร็ว — ถ้ารุ่นหลักโควตาเต็ม/ไม่ว่าง/หมดเวลา จะลองรุ่น Lite แทน"""
    last_error = None
    models = list(dict.fromkeys([GEMINI_ANSWER_MODEL, GEMINI_MODEL]))
    for i, model in enumerate(models):
        try:
            r = client.models.generate_content(
                model=model,
                contents=prompt,
                config=types.GenerateContentConfig(
                    system_instruction="ตอบเป็นภาษาเดียวกับคำถาม กระชับ ตรงประเด็น",
                    # รุ่นหลักรอแค่ 10 วินาที (ค่าต่ำสุดที่ Google ยอม) แล้วสลับไปรุ่น Lite
                    http_options=types.HttpOptions(timeout=10_000 if i < len(models) - 1 else 20_000),
                ),
            )
            return r.text or "", model
        except Exception as e:
            last_error = e
            if getattr(e, "code", None) in (400, 401, 403):   # Key ผิด — ลองรุ่นอื่นก็ไม่ช่วย
                break
    raise last_error


# ---------------------------------------------------------------
# 4. งานเบื้องหลัง (Jobs) — เก็บสถานะและผลลัพธ์ให้หน้าเว็บแสดง
# ---------------------------------------------------------------
MAX_JOBS_PER_TOOL = 3    # แสดงงานล่าสุดไม่เกินเครื่องมือละกี่งาน
MAX_OUTPUT = 20000       # ตัวอักษรสูงสุดของผลลัพธ์ที่ส่งให้หน้าเว็บ
jobs = {}                # id → dict
jobs_lock = threading.Lock()
job_ids = itertools.count(1)


def new_job(tid, prompt, status="running", output="", log_path=None, proc=None):
    job = {
        "id": next(job_ids), "tool": tid, "label": TOOLS[tid]["label"], "prompt": prompt,
        "status": status, "started": time.time(), "ended": None if status == "running" else time.time(),
        "output": output, "log_path": log_path, "returncode": None, "proc": proc,
    }
    with jobs_lock:
        jobs[job["id"]] = job
        # เครื่องมือเดียวกันเกินจำนวน → ลบงานเก่าสุด (ยกเว้นงานที่โปรแกรมยังรันอยู่จริง)
        same = sorted((j for j in jobs.values() if j["tool"] == tid and not j["proc"]), key=lambda j: j["id"])
        for old in same[:max(0, len(same) - MAX_JOBS_PER_TOOL)]:
            drop_job(old)
    return job


def drop_job(job):
    """ลบงานออกจากรายการ (เรียกขณะถือ jobs_lock) — งานติดตาม Antigravity จะหยุดติดตามเอง"""
    if job["status"] == "running":
        job["status"] = "cancelled"
    jobs.pop(job["id"], None)


LOG_NOISE = ("Ripgrep is not available", "Warning: True color", "Warning: 256-color")


def read_log(path):
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            text = "".join(line for line in f if not line.startswith(LOG_NOISE))
    except OSError:
        return ""
    return text if len(text) <= MAX_OUTPUT else "…(ตัดส่วนต้น)\n" + text[-MAX_OUTPUT:]


def watch_job(job):
    rc = job["proc"].wait()
    with jobs_lock:
        job["returncode"] = rc
        job["ended"] = time.time()
        job["output"] = read_log(job["log_path"])
        if job["status"] == "running":
            job["status"] = "done" if rc == 0 else "error"
        job["proc"] = None


def job_view(job):
    out = job["output"]
    if job["status"] == "running" and job["log_path"]:
        out = read_log(job["log_path"])   # ผลลัพธ์ระหว่างทำ
    end = job["ended"] or time.time()
    return {k: job[k] for k in ("id", "tool", "label", "prompt", "status", "returncode")} | {
        "elapsed": round(end - job["started"]), "output": out,
        "log": os.path.basename(job["log_path"]) if job["log_path"] else None,
    }


# ---------------------------------------------------------------
# 5. ส่งงานไปยังปลายทาง — คืนค่า (สำเร็จหรือไม่, ข้อความ, ผลลัพธ์)
# ---------------------------------------------------------------
def run_cli(tid, prompt):
    tool = TOOLS[tid]
    args = tool["args"](installed[tid], prompt)          # ส่งเป็น list ไม่ผ่าน shell
    env = tool["env"]() if "env" in tool else None
    log_path = os.path.join(LOG_DIR, f"{tid}_{time.strftime('%Y%m%d_%H%M%S')}.log")
    with open(log_path, "w", encoding="utf-8") as log:
        proc = subprocess.Popen(
            args, cwd=CLAUDE_WORKDIR, env=env,
            stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    job = new_job(tid, prompt, log_path=log_path, proc=proc)
    threading.Thread(target=watch_job, args=(job,), daemon=True).start()
    return True, f"เริ่มงาน {tool['label']} เบื้องหลังแล้ว — ดูผลในส่วน \"งานเบื้องหลัง\" (งาน #{job['id']})", None


# Antigravity IDE ไม่มีช่องทางส่งคำตอบกลับ — อ่านจากไฟล์บันทึกแชตที่ IDE เขียนเอง
# (รูปแบบไฟล์ไม่ได้เปิดเป็นทางการ ถ้าอัปเดตแล้วอ่านไม่ได้ การส่งข้อความยังใช้ได้ตามเดิม)
ANTIGRAVITY_BRAIN = os.path.join(os.path.expanduser("~"), ".gemini", "antigravity-ide", "brain")
# แอป Antigravity และส่วนขยาย Antigravity ใน VS Code ใช้โฟลเดอร์นี้ร่วมกัน (app_data_dir=antigravity) รูปแบบไฟล์เดียวกัน
ANTIGRAVITY_APP_BRAIN = os.path.join(os.path.expanduser("~"), ".gemini", "antigravity", "brain")
AG_WAIT_SEND = 1800   # รอข้อความเข้าแชตสูงสุด (วินาที) — ถ้า Agent ทำงานอยู่ ข้อความจะต่อคิวจนกว่างานเดิมเสร็จ
AG_TIMEOUT = 3600     # เลิกติดตามงานที่นานเกินนี้
AG_QUIET = 4          # คำตอบสุดท้ายแล้วไม่มีขั้นตอนใหม่นานเท่านี้ = เสร็จ
AG_STEP_TEXT = {"RUN_COMMAND": "รันคำสั่ง", "VIEW_FILE": "เปิดไฟล์", "LIST_DIRECTORY": "ดูโฟลเดอร์",
                "PLANNER_RESPONSE": "คิด/วางแผน"}


def ag_steps(path):
    steps = []
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            for line in f:
                try:
                    steps.append(json.loads(line))
                except ValueError:
                    pass   # บรรทัดสุดท้ายอาจยังเขียนไม่จบ
    except OSError:
        pass
    return steps


def ag_step_time(step):
    try:
        return datetime.fromisoformat(step["created_at"].replace("Z", "+00:00")).timestamp()
    except (KeyError, ValueError):
        return 0


def ag_find_request(prompt, since, brain=ANTIGRAVITY_BRAIN):
    """หาแชตที่มีข้อความที่เราส่ง (หลังเวลา since) → (ไฟล์, ลำดับขั้นตอน)"""
    key = prompt.strip()[:40]
    pattern = os.path.join(brain, "*", ".system_generated", "logs", "transcript.jsonl")
    for path in glob.glob(pattern):
        if os.path.getmtime(path) < since - 5:
            continue
        for i, s in enumerate(ag_steps(path)):
            if s.get("type") == "USER_INPUT" and key in s.get("content", "") and ag_step_time(s) >= since - 5:
                return path, i
    return None, None


def watch_antigravity(job, since, brain=ANTIGRAVITY_BRAIN):
    where = job["label"]
    path = idx = None
    while True:
        now = time.time()
        status = output = None
        if path is None:
            path, idx = ag_find_request(job["prompt"], since, brain)
            if path is None and now - since > AG_WAIT_SEND:
                status, output = "error", f"ไม่พบข้อความนี้ในแชต {where} — ยังไม่ได้กด Enter ส่งหรือเปล่า?"
        if path is not None:
            turn = ag_steps(path)[idx + 1:]
            nxt = next((i for i, s in enumerate(turn) if s.get("type") == "USER_INPUT"), None)
            if nxt is not None:
                turn = turn[:nxt]   # ผู้ใช้ส่งข้อความถัดไปแล้ว = งานนี้จบ
            text = "\n\n".join(s["content"] for s in turn
                               if s.get("type") == "PLANNER_RESPONSE" and s.get("content"))
            last = turn[-1] if turn else {}
            answered = (last.get("type") == "PLANNER_RESPONSE" and last.get("content")
                        and not last.get("tool_calls"))
            if nxt is not None or (answered and now - os.path.getmtime(path) >= AG_QUIET):
                status, output = "done", text or f"(ไม่มีคำตอบเป็นข้อความ — ดูในหน้าต่าง {where})"
            else:
                doing = AG_STEP_TEXT.get(last.get("type"), last.get("type") or "เริ่มทำงาน")
                output = (text + "\n\n" if text else "") + f"… กำลัง{doing}"
        elif status is None:
            output = f"รอให้กด Enter ส่งในแชต {where}…"
        if status is None and now - since > AG_TIMEOUT:
            status = "error"
            output = (output or "") + f"\n\nเลิกติดตามแล้ว (นานเกิน 1 ชั่วโมง) — ดูต่อในหน้าต่าง {where}"
        with jobs_lock:
            if job["status"] != "running":   # ผู้ใช้กดหยุดติดตาม
                return
            job["output"] = output[-MAX_OUTPUT:]
            if status:
                job["status"], job["ended"] = status, now
                return
        time.sleep(1)


# Claude Code ใน VS Code ก็ไม่ส่งคำตอบกลับ — อ่านจากไฟล์บันทึกแชต ~/.claude/projects/<โปรเจกต์>/<เซสชัน>.jsonl
# (หนึ่งบรรทัดต่อหนึ่งรายการ: user = ข้อความผู้ใช้/ผลของเครื่องมือ, assistant = คำตอบ, stop_reason "end_turn" = ตอบจบ)
CLAUDE_PROJECTS = os.path.join(os.path.expanduser("~"), ".claude", "projects")


def cc_text(entry, block_type="text"):
    content = (entry.get("message") or {}).get("content")
    if isinstance(content, str):
        return content if block_type == "text" else ""
    if isinstance(content, list):
        return "\n".join(b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == block_type)
    return ""


def cc_is_prompt(entry):
    """ข้อความที่ผู้ใช้พิมพ์จริง (ไม่ใช่ผลลัพธ์ของเครื่องมือหรือข้อความระบบ)"""
    return entry.get("type") == "user" and not entry.get("isMeta") and bool(cc_text(entry).strip())


def cc_entries(path, offset=0):
    """อ่านรายการตั้งแต่ byte offset → [(offset ของบรรทัด, dict)]"""
    out = []
    try:
        with open(path, "rb") as f:
            f.seek(offset)
            pos = offset
            for raw in f:
                try:
                    out.append((pos, json.loads(raw)))
                except ValueError:
                    pass   # บรรทัดสุดท้ายอาจยังเขียนไม่จบ
                pos += len(raw)
    except OSError:
        pass
    return out


def cc_find_request(prompt, since):
    """หาเซสชันที่มีข้อความที่เราส่ง (หลังเวลา since) → (ไฟล์, offset ของข้อความนั้น)"""
    key = prompt.strip()[:40]
    for path in glob.glob(os.path.join(CLAUDE_PROJECTS, "*", "*.jsonl")):
        if os.path.getmtime(path) < since - 5:
            continue
        for pos, e in cc_entries(path):
            if cc_is_prompt(e) and key in cc_text(e) and ag_step_time({"created_at": e.get("timestamp", "")}) >= since - 5:
                return path, pos
    return None, None


def watch_claude_vscode(job, since):
    path = offset = None
    while True:
        now = time.time()
        status = output = None
        if path is None:
            path, offset = cc_find_request(job["prompt"], since)
            if path is None and now - since > AG_WAIT_SEND:
                status, output = "error", "ไม่พบข้อความนี้ในแชต Claude ของ VS Code — ยังไม่ได้กด Enter ส่งหรือเปล่า?"
        if path is not None:
            turn = [e for _, e in cc_entries(path, offset)][1:]   # ตัดข้อความของเราออก
            nxt = next((i for i, e in enumerate(turn) if cc_is_prompt(e)), None)
            if nxt is not None:
                turn = turn[:nxt]   # ผู้ใช้ส่งข้อความถัดไปแล้ว = งานนี้จบ
            replies = [e for e in turn if e.get("type") == "assistant" and not e.get("isSidechain")]
            text = "\n\n".join(t for t in (cc_text(e).strip() for e in replies) if t)
            last = replies[-1] if replies else {}
            answered = (last.get("message") or {}).get("stop_reason") == "end_turn"
            if nxt is not None or (answered and now - os.path.getmtime(path) >= AG_QUIET):
                status, output = "done", text or "(ไม่มีคำตอบเป็นข้อความ — ดูในหน้าต่าง VS Code)"
            else:
                tools = [b.get("name") for b in ((last.get("message") or {}).get("content") or [])
                         if isinstance(b, dict) and b.get("type") == "tool_use"]
                doing = f"ใช้เครื่องมือ {', '.join(tools)}" if tools else "คิด/เขียนคำตอบ"
                output = (text + "\n\n" if text else "") + f"… กำลัง{doing}"
        elif status is None:
            output = "รอให้กด Enter ส่งในแชต Claude ของ VS Code…"
        if status is None and now - since > AG_TIMEOUT:
            status = "error"
            output = (output or "") + "\n\nเลิกติดตามแล้ว (นานเกิน 1 ชั่วโมง) — ดูต่อในหน้าต่าง VS Code"
        with jobs_lock:
            if job["status"] != "running":   # ผู้ใช้กดหยุดติดตาม
                return
            job["output"] = output[-MAX_OUTPUT:]
            if status:
                job["status"], job["ended"] = status, now
                return
        time.sleep(1)


# เครื่องมือ GUI ที่อ่านคำตอบกลับมาแสดงในหน้าเว็บได้ → (ตัวติดตาม, โฟลเดอร์ที่ต้องมี)
#   ยังทำไม่ได้: Cursor (แชตใน state.vscdb เข้ารหัส — blobEncryptionKey), Claude Desktop และ Gemini Desktop
#   (แชตเก็บบนเซิร์ฟเวอร์ ไม่มีไฟล์บันทึกในเครื่องให้อ่าน)
GUI_WATCHERS = {
    "antigravity_ide": (watch_antigravity, ANTIGRAVITY_BRAIN),
    "antigravity": (lambda job, since: watch_antigravity(job, since, ANTIGRAVITY_APP_BRAIN), ANTIGRAVITY_APP_BRAIN),
    "vscode_antigravity": (lambda job, since: watch_antigravity(job, since, ANTIGRAVITY_APP_BRAIN), ANTIGRAVITY_APP_BRAIN),
    "vscode_claude": (watch_claude_vscode, CLAUDE_PROJECTS),
}


def run_gemini_api(prompt):
    try:
        answer, model = ask_gemini(prompt)
    except Exception as e:
        msg = gemini_error_message(e)
        new_job("gemini_api", prompt, status="error", output=msg)
        return False, msg, None
    new_job("gemini_api", prompt, status="done", output=answer)
    return True, f"Gemini ตอบแล้ว ({model})", answer


def run_ollama(prompt):
    try:
        r = requests.post(
            f"{OLLAMA_URL}/api/generate",
            json={"model": OLLAMA_MODEL, "prompt": prompt, "stream": False},
            timeout=180,
        )
        r.raise_for_status()
        answer = r.json().get("response", "")
    except requests.RequestException as e:
        print(f"[Ollama error] {type(e).__name__}: {e}")
        msg = "เรียก Ollama ไม่สำเร็จ — Ollama เปิดอยู่หรือไม่? (รายละเอียดในหน้าต่าง AI Router)"
        new_job("ollama", prompt, status="error", output=msg)
        return False, msg, None
    new_job("ollama", prompt, status="done", output=answer)
    return True, "Ollama ตอบกลับแล้ว", answer


def force_foreground(hwnd):
    """Windows ไม่ยอมให้โปรแกรมเบื้องหลังดึงหน้าต่างขึ้นหน้า — ผูก input กับหน้าต่างที่อยู่หน้าสุดชั่วคราวก่อน"""
    user32, kernel32 = ctypes.windll.user32, ctypes.windll.kernel32
    fg_thread = user32.GetWindowThreadProcessId(user32.GetForegroundWindow(), None)
    my_thread = kernel32.GetCurrentThreadId()
    attached = fg_thread != my_thread and user32.AttachThreadInput(my_thread, fg_thread, True)
    try:
        user32.ShowWindow(hwnd, 9 if user32.IsIconic(hwnd) else 5)   # SW_RESTORE / SW_SHOW
        user32.BringWindowToTop(hwnd)
        # ขยับเมาส์ 0 พิกเซล = input ล่าสุดมาจากโปรแกรมนี้ → Windows ยอมให้สลับหน้าต่าง
        user32.mouse_event(0x0001, 0, 0, 0, 0)                       # MOUSEEVENTF_MOVE
        user32.SetForegroundWindow(hwnd)
    finally:
        if attached:
            user32.AttachThreadInput(my_thread, fg_thread, False)


VK = {"ctrl": 0x11, "shift": 0x10, "alt": 0x12, "enter": 0x0D, "f9": 0x78, "f10": 0x79}


def hotkey(*keys):
    """กดปุ่มลัดด้วยรหัสปุ่มจริง (virtual-key) — ใช้ได้ทั้งแป้นไทย/อังกฤษ
    (pyautogui แปลงตัวอักษรตามภาษาแป้นปัจจุบัน แป้นไทยไม่มี 'v' จึงกด Ctrl+V ไม่ได้)"""
    codes = [VK.get(k) or ord(k.upper()) for k in keys]
    for c in codes:
        ctypes.windll.user32.keybd_event(c, 0, 0, 0)
    for c in reversed(codes):
        ctypes.windll.user32.keybd_event(c, 0, 2, 0)   # KEYEVENTF_KEYUP


def send_to_gui(tid, prompt, auto_send):
    label = TOOLS[tid]["label"]
    win = find_window(tid)
    if not win:
        return False, f"ไม่พบหน้าต่างของ {label} (เปิดโปรแกรมไว้หรือยัง?)", None
    with gui_lock:
        old_clip = pyperclip.paste()
        try:
            force_foreground(win._hWnd)
            time.sleep(0.4)
            if ctypes.windll.user32.GetForegroundWindow() != win._hWnd:
                return False, f"สลับไปหน้าต่าง {label} ไม่สำเร็จ", None
            prefocus = TOOLS[tid].get("prefocus")
            if prefocus:
                hotkey(*prefocus)
                time.sleep(0.2)
            chat_key = TOOLS[tid]["hotkey"]
            if chat_key:
                hotkey(*chat_key)
                time.sleep(TOOLS[tid].get("hotkey_wait", 0.3))
            pyperclip.copy(prompt)
            hotkey("ctrl", "v")
            if auto_send:
                time.sleep(0.1)
                hotkey("enter")
        finally:
            # โปรแกรมปลายทางอ่านคลิปบอร์ดหลังกด Ctrl+V แบบไม่พร้อมกัน — คืนเร็วไปจะวางของเดิมแทน
            time.sleep(1.0)
            if old_clip:   # คลิปบอร์ดเดิมเป็นรูป/ว่าง (paste() คืน "") ก็ไม่ต้องเขียนทับ
                pyperclip.copy(old_clip)   # คืนคลิปบอร์ดเดิมให้ผู้ใช้
    action = "ส่งแล้ว" if auto_send else "วางไว้แล้ว รอผู้ใช้กด Enter"
    return True, f"{action} ที่ {label}", None


def execute_dispatch(decision, auto_send):
    tid, prompt = decision.target_ai, decision.clean_prompt
    print(f"\n🚀 [{tid}] {prompt}")
    if tid == "none" or tid not in TOOLS:
        return False, "ไม่ได้ส่งต่อ: จำแนกปลายทางไม่ได้ — กดเลือกเครื่องมือเอง", None
    if not installed.get(tid):
        return False, f"{TOOLS[tid]['label']} ไม่ได้ติดตั้งในเครื่องนี้", None
    kind = TOOLS[tid]["kind"]
    if kind == "cli":
        return run_cli(tid, prompt)
    if kind == "gemini_api":
        return run_gemini_api(prompt)
    if kind == "ollama":
        return run_ollama(prompt)
    since = time.time()
    ok, msg, output = send_to_gui(tid, prompt, auto_send)
    watcher, watch_dir = GUI_WATCHERS.get(tid, (None, None))
    if ok and watcher and os.path.isdir(watch_dir):
        job = new_job(tid, prompt)
        threading.Thread(target=watcher, args=(job, since), daemon=True).start()
        msg += f" — คำตอบจะขึ้นในส่วน \"งานเบื้องหลัง\" (งาน #{job['id']})"
    return ok, msg, output


# ---------------------------------------------------------------
# 6. API Endpoints
# ---------------------------------------------------------------
ALLOWED_HOSTS = {f"127.0.0.1:{PORT}", f"localhost:{PORT}"}


@app.before_request
def check_host():
    # กัน DNS rebinding: เว็บภายนอกที่ชี้โดเมนมาที่ 127.0.0.1 จะถูกปฏิเสธ
    if request.host not in ALLOWED_HOSTS:
        abort(403)


# GET / — หน้าเว็บสั่งงานด้วยเสียง (ใส่ Token ให้ตอนเปิดหน้า)
# เว็บอื่นอ่านหน้านี้ไม่ได้ (same-origin policy) จึงไม่เห็น Token
@app.get("/")
def handle_index():
    with open(PAGE_PATH, encoding="utf-8") as f:
        html = f.read().replace("__DISPATCH_TOKEN__", DISPATCH_TOKEN)
    return Response(html, mimetype="text/html",
                    headers={
                        "X-Frame-Options": "DENY",
                        # หน้าเว็บใช้ได้เฉพาะไฟล์/การเชื่อมต่อจากเซิร์ฟเวอร์นี้ — กันสคริปต์ภายนอกและการฝังหน้า
                        "Content-Security-Policy": (
                            "default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; "
                            "connect-src 'self'; img-src 'self' data:; base-uri 'none'; form-action 'none'; "
                            "frame-ancestors 'none'"),
                        "Permissions-Policy": "microphone=(self), camera=(), geolocation=()",
                    })


def authorized():
    token = request.headers.get("X-Dispatch-Token", "")
    return hmac.compare_digest(token, DISPATCH_TOKEN)


# GET /tools — รายการเครื่องมือ + สถานะติดตั้ง/เปิดอยู่ (ใช้สร้างปุ่มเลือกเครื่องมือ)
#   ?rescan=1 : สแกนโปรแกรมที่ติดตั้งใหม่ (เช่น หลังติดตั้งโปรแกรมเพิ่ม)
@app.get("/tools")
def handle_tools():
    if not authorized():
        return jsonify(ok=False, error="unauthorized"), 401
    if request.args.get("rescan"):
        scan_installed()
    return jsonify(ok=True, tools=tool_list(), gemini=client is not None)


# GET /jobs — งานเบื้องหลังล่าสุด (ใหม่สุดก่อน)
@app.get("/jobs")
def handle_jobs():
    if not authorized():
        return jsonify(ok=False, error="unauthorized"), 401
    with jobs_lock:
        items = [job_view(j) for j in sorted(jobs.values(), key=lambda j: -j["id"])]
    return jsonify(ok=True, jobs=items)


# POST /jobs/<id>/cancel — หยุดงานที่กำลังทำ
@app.post("/jobs/<int:job_id>/cancel")
def handle_job_cancel(job_id):
    if not authorized():
        return jsonify(ok=False, error="unauthorized"), 401
    with jobs_lock:
        job = jobs.get(job_id)
        if not job or job["status"] != "running":
            return jsonify(ok=False, error="งานนี้ไม่ได้กำลังทำอยู่"), 409
        job["status"] = "cancelled"
        if job["proc"]:
            job["proc"].terminate()
        else:
            job["ended"] = time.time()   # งาน Antigravity: หยุดติดตามเท่านั้น งานใน IDE ยังทำต่อ
    return jsonify(ok=True)


# POST /jobs/clear — ล้างรายการงาน (ไฟล์ log ยังอยู่)
#   งานที่โปรแกรมยังรันอยู่จริง (Claude Code / Gemini CLI) ไม่ถูกลบ — กด "หยุด" ก่อน
#   งานติดตามคำตอบ Antigravity ถูกลบได้ (หยุดติดตามเท่านั้น งานใน IDE ยังทำต่อ)
@app.post("/jobs/clear")
def handle_jobs_clear():
    if not authorized():
        return jsonify(ok=False, error="unauthorized"), 401
    with jobs_lock:
        for job in [j for j in jobs.values() if not j["proc"]]:
            drop_job(job)
    return jsonify(ok=True)


# POST /dispatch — Body (JSON):
#   prompt     : ข้อความคำสั่ง (บังคับ)
#   target     : id ของเครื่องมือที่กดเลือก → ส่งตรง ข้าม Gemini (ไม่ใส่ = ให้ Gemini เลือก)
#   auto_send  : true = กด Enter ให้ด้วย (ค่าเริ่มต้น false)
#   dry_run    : true = ให้ Gemini จำแนกอย่างเดียว ยังไม่ส่ง (โหมด Manual Review)
@app.post("/dispatch")
def handle_dispatch():
    if not authorized():
        return jsonify(ok=False, error="unauthorized"), 401

    data = request.get_json(silent=True) or {}
    text = str(data.get("prompt") or "").strip()
    if not text:
        return jsonify(ok=False, error="ไม่มีข้อความ prompt"), 400
    if len(text) > MAX_PROMPT_CHARS:
        return jsonify(ok=False, error=f"ข้อความยาวเกิน {MAX_PROMPT_CHARS:,} ตัวอักษร"), 413
    auto_send = bool(data.get("auto_send", False))

    if data.get("target") in TOOLS:
        decision = AIRoutingDecision(target_ai=data["target"], clean_prompt=text)
    else:
        try:
            decision = route(text)
        except Exception as e:
            return jsonify(ok=False, error=gemini_error_message(e)), 502

    result = {"target": decision.target_ai, "clean_prompt": decision.clean_prompt}
    if data.get("dry_run"):
        return jsonify(ok=True, status="dry_run", **result)

    ok, msg, output = execute_dispatch(decision, auto_send)
    return jsonify(ok=ok, status=msg, output=output, **result), (200 if ok else 409)


if __name__ == "__main__":
    scan_installed()
    print_tools()
    print(f"🎧 เปิดหน้าสั่งงานด้วยเสียงใน Chrome: http://127.0.0.1:{PORT}")
    # ฟังเฉพาะ 127.0.0.1 — เครื่องอื่นในเครือข่ายเข้าไม่ได้
    app.run(host="127.0.0.1", port=PORT, threaded=True)
