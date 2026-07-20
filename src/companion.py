#!/usr/bin/env python3
"""春田桌宠 · 伴侣版 — OpenPets 风格功能 + Claude 状态联动。

在基础桌宠(pet.py)之上增加:
  - 虚拟属性:饱食/心情/精力/等级经验(随时间衰减,喂食/摸摸/玩耍回升)
  - 专注计时器(番茄钟)· 喝水提醒 · 自定义提醒
  - 情绪记录 · 小游戏(石头剪刀布)· 启动快捷方式
  - 头顶说话气泡 + 系统通知
  - Claude Code 状态联动(读 ~/.springfield_pet/claude_state)
  - 单击小人 -> 弹框输入 prompt -> 新终端启动 claude

运行: python3 springfield_companion.py
"""
from __future__ import annotations

import json
import os
import random
import re
import shlex
import shutil
import subprocess
import sys
import time
from pathlib import Path

from PySide6 import QtCore, QtGui, QtWidgets
from PySide6.QtMultimedia import QMediaPlayer, QAudioOutput

import pet as base   # 复用动画引擎/拖动/换肤

AUDIO_EXTS = {".mp3", ".m4a", ".flac", ".wav", ".ogg", ".aac", ".opus"}

# 5 套衣服,每套 = 战斗动作集(M) + 休息动作集(RM),合并成一套完整动画
OUTFITS = {
    "default":  {"name": "默认 · 水手服", "combat": "M1903",      "rest": "RM1903"},
    "witch":    {"name": "女巫装",        "combat": "M1903_5",    "rest": "RM1903_5"},
    "cloak":    {"name": "红斗篷",        "combat": "M1903_302",  "rest": "RM1903_302"},
    "dress":    {"name": "蓝礼服",        "combat": "M1903_802",  "rest": "RM1903_802"},
    "swimsuit": {"name": "泳装",          "combat": "M1903_1107", "rest": "RM1903_1107"},
}

STATE_DIR = Path.home() / ".springfield_pet"
STATE_FILE = STATE_DIR / "state.json"
CLAUDE_STATE_FILE = STATE_DIR / "claude_state"

# Claude Code 一键接入
CLAUDE_SETTINGS = Path.home() / ".claude" / "settings.json"
HOOK_TAG = "claude_hook.py"                 # 用于识别本项目写入的 hook
CLAUDE_HOOK_HELPER = STATE_DIR / "claude_hook.py"
ACTIVITY_FILE = STATE_DIR / "claude_activity"
PROJECT_FILE = STATE_DIR / "claude_project"
CODEX_STATE_FILE = STATE_DIR / "codex_state"
CODEX_ACTIVITY_FILE = STATE_DIR / "codex_activity"
CODEX_PROJECT_FILE = STATE_DIR / "codex_project"

# 助手脚本:被 Claude hook 调用,解析事件 JSON(stdin)-> 写状态/活动/项目名
HOOK_HELPER_SRC = r'''#!/usr/bin/env python3
import sys, json, os
from pathlib import Path
D = Path.home() / ".springfield_pet"
try: D.mkdir(parents=True, exist_ok=True)
except Exception: pass
event = sys.argv[1] if len(sys.argv) > 1 else ""
try: data = json.load(sys.stdin)
except Exception: data = {}
def w(name, val):
    try: (D / name).write_text(str(val))
    except Exception: pass
cwd = data.get("cwd") or os.getcwd()
w("claude_project", os.path.basename(str(cwd).rstrip("/")) or "Claude")
w("claude_state", {"UserPromptSubmit": "working", "PreToolUse": "working",
                   "Notification": "waiting", "Stop": "done",
                   "SessionStart": "idle"}.get(event, "working"))
def bn(p):
    try: return os.path.basename(str(p))
    except Exception: return str(p)
act = ""
if event == "PreToolUse":
    t = data.get("tool_name", ""); ti = data.get("tool_input", {}) or {}
    if t == "Read": act = "读取 " + bn(ti.get("file_path", ""))
    elif t in ("Edit", "Write", "NotebookEdit"): act = "编辑 " + bn(ti.get("file_path", ""))
    elif t == "Bash": act = "运行: " + str(ti.get("command", ""))[:48]
    elif t in ("Grep", "Glob"): act = "搜索: " + str(ti.get("pattern", ""))[:40]
    elif t == "Task": act = "子任务: " + str(ti.get("description", ""))[:36]
    elif t in ("WebFetch", "WebSearch"): act = "联网: " + str(ti.get("query") or ti.get("url", ""))[:40]
    else: act = t or "工作中"
elif event == "UserPromptSubmit": act = "思考中…"
elif event == "Notification": act = "需要你确认"
elif event == "Stop":
    act = "完成"
    tp = data.get("transcript_path", "")
    try:
        if tp and os.path.exists(tp):
            last = ""
            for line in open(tp, encoding="utf-8"):
                try: o = json.loads(line)
                except Exception: continue
                if o.get("type") == "assistant":
                    for blk in (o.get("message", {}).get("content") or []):
                        if isinstance(blk, dict) and blk.get("type") == "text" and blk.get("text"):
                            last = blk["text"]
            last = " ".join(last.split())
            if last: act = "完成:" + last[:60]
    except Exception: pass
w("claude_activity", act)
'''
# (事件, 写入的状态词, matcher 或 None)
HOOK_EVENTS = [
    ("UserPromptSubmit", "working", None),
    ("PreToolUse", "working", "*"),
    ("Notification", "waiting", None),
    ("Stop", "done", None),
    ("SessionStart", "idle", None),
]

# Codex 一键接入(通过 config.toml 的 notify;串联保留原有 notify)
CODEX_CONFIG = Path.home() / ".codex" / "config.toml"
CODEX_WRAPPER = STATE_DIR / "codex_notify.sh"
CODEX_ORIG = STATE_DIR / "codex_orig_notify.sh"

DEFAULT_STATE = {
    "stats": {"hunger": 80, "happiness": 80, "energy": 80, "xp": 0, "level": 1},
    "mood_log": [],
    "reminders": [],          # [{"text":..,"at":epoch}]
    "water_enabled": True,
    "water_interval_min": 60,
    "shortcuts": {
        "VS Code": "open -a 'Visual Studio Code'",
        "终端": "open -a Terminal",
        "浏览器": "open https://www.google.com",
    },
    "claude_cwd": str(Path.home()),
    "send_mode": "current",       # current=键入当前终端 / new=新终端
    "terminal_app": "Terminal",   # Terminal / iTerm2 / Code ...
    "auto_outfit": False,         # 定时自动换装
    "auto_outfit_min": 30,        # 换装间隔(分钟)
    "music_folder": "",           # 音乐文件夹
    "music_loop": "all",          # off/all/one/shuffle
    "pet_scale": 1.0,             # 小人大小
    "banner_lines": 1,            # 状态对话框显示行数
}


def load_state():
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    if STATE_FILE.exists():
        try:
            s = json.loads(STATE_FILE.read_text())
            for k, v in DEFAULT_STATE.items():
                s.setdefault(k, v)
            for k, v in DEFAULT_STATE["stats"].items():
                s["stats"].setdefault(k, v)
            return s
        except Exception:
            pass
    return json.loads(json.dumps(DEFAULT_STATE))


class SpeechBubble(QtWidgets.QWidget):
    """跟随小人头顶的说话气泡。"""
    def __init__(self):
        super().__init__(None)
        self.setWindowFlags(QtCore.Qt.FramelessWindowHint | QtCore.Qt.WindowStaysOnTopHint)
        self.setAttribute(QtCore.Qt.WA_TranslucentBackground)
        self.setAttribute(QtCore.Qt.WA_ShowWithoutActivating)
        self.setAttribute(QtCore.Qt.WA_TransparentForMouseEvents)   # 气泡不拦截点击
        self.label = QtWidgets.QLabel("", self)
        self.label.setStyleSheet(
            "QLabel{background:rgba(255,255,255,240);border:2px solid #7a8695;"
            "border-radius:12px;padding:8px 12px;color:#33383f;font-size:13px;}")
        self.label.setWordWrap(True)
        self.label.setMaximumWidth(220)
        self._timer = QtCore.QTimer(self); self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.hide)

    def say(self, text, secs=4):
        self.label.setText(text); self.label.adjustSize()
        self.resize(self.label.size())
        self.show(); self._timer.start(int(secs * 1000))

    def place_above(self, pet_widget):
        if not self.isVisible():
            return
        g = pet_widget.frameGeometry()
        cx = g.x() + base.ANCHOR_WX
        top = g.y() + base.ANCHOR_WY - 230
        self.move(int(cx - self.width() / 2), int(top))


class PromptEdit(QtWidgets.QTextEdit):
    sent = QtCore.Signal()
    cancelled = QtCore.Signal()

    def keyPressEvent(self, e):
        if e.key() in (QtCore.Qt.Key_Return, QtCore.Qt.Key_Enter) and not (e.modifiers() & QtCore.Qt.ShiftModifier):
            self.sent.emit(); return
        if e.key() == QtCore.Qt.Key_Escape:
            self.cancelled.emit(); return
        super().keyPressEvent(e)


class PromptBubble(QtWidgets.QWidget):
    """头顶浮现的指令输入框。"""
    submitted = QtCore.Signal(str)

    def __init__(self):
        super().__init__(None)
        self.setWindowFlags(QtCore.Qt.FramelessWindowHint | QtCore.Qt.WindowStaysOnTopHint)
        self.setAttribute(QtCore.Qt.WA_TranslucentBackground)
        self.edit = PromptEdit(self)
        self.edit.setPlaceholderText("跟春田说点什么…回车发送,Shift+回车换行,Esc 取消")
        self.edit.setStyleSheet(
            "QTextEdit{background:rgba(255,255,255,245);border:2px solid #7a8695;"
            "border-radius:14px;padding:8px 10px;color:#2c313a;font-size:13px;}")
        self.edit.setFixedSize(250, 74)
        lay = QtWidgets.QVBoxLayout(self); lay.setContentsMargins(0, 0, 0, 0); lay.addWidget(self.edit)
        self.resize(254, 78)
        self.edit.sent.connect(self._submit)
        self.edit.cancelled.connect(self.hide)

    def _submit(self):
        t = self.edit.toPlainText().strip(); self.hide()
        if t:
            self.submitted.emit(t)

    def popup(self, pet):
        g = pet.frameGeometry()
        cx = g.x() + base.ANCHOR_WX
        self.move(int(cx - self.width() / 2), int(g.y() + base.ANCHOR_WY - 250))
        self.edit.clear(); self.show(); self.raise_(); self.activateWindow(); self.edit.setFocus()


class StatusPanel(QtWidgets.QWidget):
    """悬浮显示的小人+Claude 状态面板。"""
    def __init__(self):
        super().__init__(None)
        self.setWindowFlags(QtCore.Qt.FramelessWindowHint | QtCore.Qt.WindowStaysOnTopHint)
        self.setAttribute(QtCore.Qt.WA_TranslucentBackground)
        self.setAttribute(QtCore.Qt.WA_ShowWithoutActivating)
        self.setAttribute(QtCore.Qt.WA_TransparentForMouseEvents)   # 状态栏不拦截点击
        self.label = QtWidgets.QLabel(self)
        self.label.setStyleSheet(
            "QLabel{background:rgba(38,42,48,235);border-radius:12px;padding:10px 14px;"
            "color:#f0f2f5;font-size:12px;}")
        self.label.setTextFormat(QtCore.Qt.RichText)

    def show_html(self, html, pet):
        self.label.setText(html); self.label.adjustSize(); self.resize(self.label.size())
        g = pet.frameGeometry()
        x = g.x() + base.ANCHOR_WX + 70
        y = g.y() + base.ANCHOR_WY - 180
        self.move(int(x), int(y)); self.show(); self.raise_()


def _esc(s):
    return (str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


class AgentBanner(QtWidgets.QWidget):
    """头顶状态对话框(显示专用,鼠标穿透,可多行):[●Agent] 项目 · 活动 + 转圈/✅。"""
    def __init__(self, agent, color):
        super().__init__(None)
        self.setWindowFlags(QtCore.Qt.FramelessWindowHint | QtCore.Qt.WindowStaysOnTopHint)
        self.setAttribute(QtCore.Qt.WA_TranslucentBackground)
        self.setAttribute(QtCore.Qt.WA_ShowWithoutActivating)
        self.setAttribute(QtCore.Qt.WA_TransparentForMouseEvents)   # 由玻璃标签控制,自身不挡点击
        self.agent = agent; self.color = color
        self.label = QtWidgets.QLabel(self)
        self.label.setTextFormat(QtCore.Qt.RichText)
        self.label.setWordWrap(True)
        self.label.setStyleSheet(
            "QLabel{background:rgba(247,249,252,240);border-radius:18px;"
            "padding:9px 16px;color:#2b3038;font-size:13px;}")

    def update_status(self, proj, act, right, max_lines=1):
        one_line = max_lines <= 1
        self.label.setWordWrap(not one_line)
        width = 320 if one_line else 400
        cap = 44 if one_line else max_lines * 42
        act = self._one(act)
        act = act if len(act) <= cap else act[:cap] + "…"
        tag = f"<span style='color:{self.color};font-size:15px'>●</span> <b>{self.agent}</b>"
        proj = f"{_esc(self._one(proj))}&nbsp;·&nbsp;" if proj else ""
        html = (f"{tag}&nbsp;&nbsp;{proj}{_esc(act)}"
                f"&nbsp;&nbsp;<span style='color:#8a93a0'>{right}</span>")
        self.label.setMaximumWidth(width)
        self.label.setText(html); self.label.adjustSize()
        self.resize(self.label.size())
        self.show()

    @staticmethod
    def _one(s):
        return " ".join(str(s).split())

    def place(self, cx, ybottom):
        self.move(int(cx - self.width() / 2), int(ybottom - self.height()))


class ToggleBadge(QtWidgets.QWidget):
    """小人右上角的玻璃质感圆形标签,上/下箭头切换展开/收起对话框。"""
    clicked = QtCore.Signal()

    def __init__(self):
        super().__init__(None)
        self.setWindowFlags(QtCore.Qt.FramelessWindowHint | QtCore.Qt.WindowStaysOnTopHint)
        self.setAttribute(QtCore.Qt.WA_TranslucentBackground)
        self.setAttribute(QtCore.Qt.WA_ShowWithoutActivating)
        self.resize(30, 30)
        self.expanded = True

    def paintEvent(self, _):
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        # 玻璃圆:半透明白 + 细边 + 高光
        p.setBrush(QtGui.QColor(255, 255, 255, 180))
        p.setPen(QtGui.QPen(QtGui.QColor(150, 160, 175, 170), 1.4))
        p.drawEllipse(2, 2, 26, 26)
        p.setPen(QtGui.QPen(QtGui.QColor(255, 255, 255, 200), 1))
        p.drawArc(4, 3, 22, 22, 40 * 16, 110 * 16)
        # 箭头:展开时朝上(∧,点了收起),收起时朝下(∨,点了展开)
        p.setPen(QtGui.QPen(QtGui.QColor(70, 80, 96), 2.2, QtCore.Qt.SolidLine,
                            QtCore.Qt.RoundCap, QtCore.Qt.RoundJoin))
        cx, cy = 15, 15
        if self.expanded:
            p.drawLine(cx - 5, cy + 2, cx, cy - 3); p.drawLine(cx, cy - 3, cx + 5, cy + 2)
        else:
            p.drawLine(cx - 5, cy - 2, cx, cy + 3); p.drawLine(cx, cy + 3, cx + 5, cy - 2)
        p.end()

    def mousePressEvent(self, e):
        self.clicked.emit(); e.accept()


class MiniPlayer(QtWidgets.QWidget):
    """迷你音乐播放器悬浮窗。"""
    LOOP_ORDER = ["off", "all", "one", "shuffle"]
    LOOP_ICON = {"off": "➡", "all": "🔁", "one": "🔂", "shuffle": "🔀"}

    def __init__(self, loop="all"):
        super().__init__(None)
        self.setWindowFlags(QtCore.Qt.FramelessWindowHint | QtCore.Qt.WindowStaysOnTopHint | QtCore.Qt.Tool)
        self.setAttribute(QtCore.Qt.WA_TranslucentBackground)
        self.player = QMediaPlayer(self); self.audio = QAudioOutput(self)
        self.player.setAudioOutput(self.audio); self.audio.setVolume(0.7)
        self.playlist = []; self.index = -1; self.loop = loop if loop in self.LOOP_ORDER else "all"
        self._build_ui()
        self.player.positionChanged.connect(self._on_pos)
        self.player.durationChanged.connect(lambda d: self.slider.setRange(0, d))
        self.player.mediaStatusChanged.connect(self._on_status)
        self.player.playbackStateChanged.connect(self._sync_play_icon)

    def _build_ui(self):
        card = QtWidgets.QFrame(self); card.setObjectName("card")
        card.setStyleSheet("#card{background:rgba(34,38,44,238);border-radius:14px;}"
                           "QLabel{color:#eef1f4;font-size:12px;}"
                           "QPushButton{background:transparent;border:none;color:#eef1f4;font-size:16px;}"
                           "QPushButton:hover{color:#9fd0ff;}"
                           "QSlider::groove:horizontal{height:4px;background:#556;border-radius:2px;}"
                           "QSlider::sub-page:horizontal{background:#9fd0ff;border-radius:2px;}"
                           "QSlider::handle:horizontal{width:10px;background:#fff;border-radius:5px;margin:-3px 0;}")
        self.title = QtWidgets.QLabel("未选择音乐"); self.title.setFixedWidth(232)
        self.time = QtWidgets.QLabel("0:00 / 0:00")
        self.slider = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        self.slider.sliderMoved.connect(self.player.setPosition)
        self.btn_prev = QtWidgets.QPushButton("⏮"); self.btn_prev.clicked.connect(self.prev)
        self.btn_play = QtWidgets.QPushButton("▶"); self.btn_play.clicked.connect(self.toggle)
        self.btn_next = QtWidgets.QPushButton("⏭"); self.btn_next.clicked.connect(self.next)
        self.btn_loop = QtWidgets.QPushButton(self.LOOP_ICON[self.loop]); self.btn_loop.clicked.connect(self.cycle_loop)
        row = QtWidgets.QHBoxLayout()
        for b in (self.btn_prev, self.btn_play, self.btn_next, self.btn_loop):
            row.addWidget(b)
        v = QtWidgets.QVBoxLayout(card); v.setContentsMargins(12, 8, 12, 8); v.setSpacing(4)
        v.addWidget(self.title); v.addWidget(self.slider)
        h = QtWidgets.QHBoxLayout(); h.addWidget(self.time); h.addStretch(); h.addLayout(row)
        v.addLayout(h)
        outer = QtWidgets.QVBoxLayout(self); outer.setContentsMargins(0, 0, 0, 0); outer.addWidget(card)
        self.resize(258, 96)

    @staticmethod
    def _fmt(ms):
        s = ms // 1000; return f"{s//60}:{s%60:02d}"

    def _on_pos(self, pos):
        if not self.slider.isSliderDown():
            self.slider.setValue(pos)
        self.time.setText(f"{self._fmt(pos)} / {self._fmt(self.player.duration())}")

    def _sync_play_icon(self, *_):
        playing = self.player.playbackState() == QMediaPlayer.PlayingState
        self.btn_play.setText("⏸" if playing else "▶")

    def _on_status(self, status):
        if status == QMediaPlayer.EndOfMedia:
            if self.loop == "one":
                self.play_index(self.index)
            elif self.loop == "shuffle" and len(self.playlist) > 1:
                self.play_index(random.randrange(len(self.playlist)))
            elif self.loop == "all":
                self.next()
            else:  # off
                if self.index < len(self.playlist) - 1:
                    self.next()

    def load_folder(self, folder):
        files = []
        for root, _dirs, names in os.walk(folder):
            for n in sorted(names):
                if os.path.splitext(n)[1].lower() in AUDIO_EXTS:
                    files.append(os.path.join(root, n))
        self.playlist = files; self.index = -1
        return len(files)

    def play_index(self, i):
        if not self.playlist:
            return
        self.index = i % len(self.playlist)
        path = self.playlist[self.index]
        self.player.setSource(QtCore.QUrl.fromLocalFile(path))
        self.player.play()
        self.title.setText(f"♪ {os.path.basename(path)}")

    def toggle(self):
        if self.player.playbackState() == QMediaPlayer.PlayingState:
            self.player.pause()
        elif self.playlist:
            if self.index < 0:
                self.play_index(0)
            else:
                self.player.play()

    def next(self):
        if self.playlist:
            self.play_index((self.index + 1) % len(self.playlist))

    def prev(self):
        if self.playlist:
            self.play_index((self.index - 1) % len(self.playlist))

    def cycle_loop(self):
        self.loop = self.LOOP_ORDER[(self.LOOP_ORDER.index(self.loop) + 1) % 4]
        self.btn_loop.setText(self.LOOP_ICON[self.loop])
        return self.loop

    def place_near(self, pet):
        g = pet.frameGeometry()
        self.move(int(g.x() + base.ANCHOR_WX - self.width() / 2),
                  int(g.y() + base.ANCHOR_WY + 20))

    # 播放器窗口可拖动
    def mousePressEvent(self, e):
        if e.button() == QtCore.Qt.LeftButton:
            self._drag = e.globalPosition().toPoint() - self.frameGeometry().topLeft(); e.accept()

    def mouseMoveEvent(self, e):
        if getattr(self, "_drag", None) is not None and (e.buttons() & QtCore.Qt.LeftButton):
            self.move(e.globalPosition().toPoint() - self._drag); e.accept()


class Companion(base.Pet):
    def __init__(self):
        super().__init__()
        # 按"衣服"加载:合并战斗+休息动作集
        self.outfit = "default"
        self.skin = OUTFITS["default"]["combat"]
        self.anims = self.load_outfit("default")
        self.set_anim("wait")

        self.data = load_state()
        self.bubble = SpeechBubble()
        self.prompt_bubble = None
        self.status_panel = StatusPanel()
        self.hover_timer = QtCore.QTimer(self); self.hover_timer.setSingleShot(True)
        self.hover_timer.timeout.connect(self.show_status_hover)
        self.setMouseTracking(True)
        self._hit_key = None; self._hit_img = None   # 命中测试图像缓存(避免每次鼠标移动都 toImage)
        self.scale = float(self.data.get("pet_scale", 1.0))
        self.external_state = None       # Claude 状态:working/waiting
        self.focus_end = 0
        self.last_water = time.time()
        self.last_outfit_change = time.time()
        self._last_claude = ""

        self.waiting_since = 0.0
        self.last_wait_remind = 0.0
        self.pending_ack = None       # "done":跑完待理会,持续提醒直到用户互动
        self.last_ack_remind = 0.0
        self.activity = ""; self.project = ""; self._spin_i = 0; self._claude_word = ""
        self.banner_claude = AgentBanner("Claude", "#3b82f6")   # 蓝
        self.banner_codex = AgentBanner("Codex", "#10b981")     # 绿
        self.banners_collapsed = False
        self.badge = ToggleBadge()
        self.badge.clicked.connect(self.toggle_banners)

        # 音乐播放器
        self.player = MiniPlayer(loop=self.data.get("music_loop", "all"))
        if self.data.get("music_folder") and os.path.isdir(self.data["music_folder"]):
            self.player.load_folder(self.data["music_folder"])

        # 秒级计时器:属性衰减/专注/喝水/提醒
        self.sec_timer = QtCore.QTimer(self)
        self.sec_timer.timeout.connect(self.second_tick)
        self.sec_timer.start(1000)

        # 快速轮询 Claude 状态(300ms,近实时)
        self.claude_poll = QtCore.QTimer(self)
        self.claude_poll.timeout.connect(self.read_claude_state)
        self.claude_poll.start(300)

        # 监听 Claude 状态文件
        CLAUDE_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        if not CLAUDE_STATE_FILE.exists():
            CLAUDE_STATE_FILE.write_text("idle")
        self.watcher = QtCore.QFileSystemWatcher(self)
        self.watcher.addPath(str(CLAUDE_STATE_FILE))
        self.watcher.fileChanged.connect(self.read_claude_state)

        self.bubble.say("春田上线啦～ 单击我发指令,右键看菜单", 5)

    # ---------- 衣服(合并战斗+休息动作) ----------
    def load_outfit(self, outfit_id):
        o = OUTFITS[outfit_id]
        anims = {}
        anims.update(base.load_skin(o["rest"], self.manifest))    # 休息:sit/lying/pick…
        anims.update(base.load_skin(o["combat"], self.manifest))  # 战斗覆盖同名(wait/move 用完好版)
        return anims

    def switch_outfit(self, outfit_id):
        if outfit_id == self.outfit:
            return
        self.outfit = outfit_id
        self.skin = OUTFITS[outfit_id]["combat"]
        self.anims = self.load_outfit(outfit_id)
        self.state = "idle"; self.dwell = random.randint(30, 80); self.set_anim("wait")
        self.speak(f"换上「{OUTFITS[outfit_id]['name']}」啦~", 3)

    # ---------- 存档 ----------
    def save(self):
        try:
            if hasattr(self, "player"):
                self.data["music_loop"] = self.player.loop
            STATE_FILE.write_text(json.dumps(self.data, ensure_ascii=False, indent=2))
        except Exception:
            pass

    # ---------- 通知 ----------
    @staticmethod
    def _as_str(s):
        # AppleScript 字符串字面量(UTF-8 直传,不用 \u 转义)
        return '"' + str(s).replace("\\", "\\\\").replace('"', '\\"') + '"'

    def notify(self, title, text):
        try:
            subprocess.Popen(["osascript", "-e",
                f'display notification {self._as_str(text)} with title {self._as_str(title)}'])
        except Exception:
            pass

    def speak(self, text, secs=4, notify=False, title="春田"):
        self.bubble.say(text, secs)
        self.bubble.place_above(self)
        if notify:
            self.notify(title, text)

    # ---------- 每秒逻辑 ----------
    def second_tick(self):
        now = time.time()
        st = self.data["stats"]
        # 属性缓慢衰减
        st["hunger"] = max(0, st["hunger"] - 0.06)
        st["energy"] = max(0, st["energy"] - 0.04)
        st["happiness"] = max(0, st["happiness"] - 0.03)

        # 专注计时
        if self.focus_end:
            left = int(self.focus_end - now)
            if left <= 0:
                self.focus_end = 0
                self.external_state = None
                self.add_xp(20); st["happiness"] = min(100, st["happiness"] + 10)
                self.state = "perform"; self.set_anim("victory", fallbacks=("pick", "wait"))
                self.speak("专注完成!休息一下吧 🎉", 6, notify=True, title="专注结束")
            elif left % 60 == 0 or left <= 5:
                self.speak(f"专注中… 还剩 {left // 60}分{left % 60}秒", 2)

        # 喝水提醒
        if self.data.get("water_enabled") and now - self.last_water >= self.data["water_interval_min"] * 60:
            self.last_water = now
            self.speak("该喝水啦 💧", 6, notify=True, title="喝水提醒")
            self.bounce()

        # 到点提醒
        due = [r for r in self.data["reminders"] if r["at"] <= now]
        for r in due:
            self.speak(f"⏰ 提醒:{r['text']}", 8, notify=True, title="提醒")
            self.bounce()
        if due:
            self.data["reminders"] = [r for r in self.data["reminders"] if r["at"] > now]
            self.save()

        # 定时自动换装
        if self.data.get("auto_outfit") and now - self.last_outfit_change >= self.data.get("auto_outfit_min", 30) * 60:
            self.last_outfit_change = now
            others = [o for o in OUTFITS if o != self.outfit]
            if others:
                self.switch_outfit(random.choice(others))

        # 兜底轮询 Claude 状态(watcher 有时漏)
        self.read_claude_state()

        # 待理会 -> 每 13 秒持续提醒,直到点击(ack)或状态改变(在终端继续)
        if self.pending_ack and now - self.last_ack_remind >= 13:
            self.last_ack_remind = now
            if self.pending_ack == "waiting":
                self.set_anim("spine", fallbacks=("thinking", "wait"))
                self.speak("还在等你确认/授权哦 👀", 5, notify=True, title="需要操作")
            else:   # done
                self.state = "perform"; self.set_anim("victory", fallbacks=("pick", "wait"))
                self.speak("跑完啦,回来看看我嘛~ ✅", 5, notify=True, title="运行完毕")

        # 状态栏可见时刷新内容
        if self.status_panel.isVisible():
            self.status_panel.show_html(self.build_status_html(), self)

    def add_xp(self, n):
        st = self.data["stats"]; st["xp"] += n
        need = st["level"] * 100
        while st["xp"] >= need:
            st["xp"] -= need; st["level"] += 1; need = st["level"] * 100
            self.speak(f"升级啦!Lv.{st['level']} ✨", 5, notify=True, title="升级")
            self.state = "perform"; self.set_anim("victory", fallbacks=("pick", "wait"))
        self.save()

    def bounce(self):
        self.state = "perform"
        self.set_anim("victory" if not self.skin.startswith("R") else "pick", fallbacks=("wait",))

    # ---------- Claude 状态联动 ----------
    SPIN = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"

    @staticmethod
    def _read_small(p):
        try:
            return p.read_text().strip()
        except Exception:
            return ""

    def read_claude_state(self, *_):
        # 驱动小人动作 + 行为(仅 Claude,细粒度)
        try:
            word = CLAUDE_STATE_FILE.read_text().strip()
        except Exception:
            word = ""
        self.activity = self._read_small(ACTIVITY_FILE)
        self.project = self._read_small(PROJECT_FILE)
        if str(CLAUDE_STATE_FILE) not in self.watcher.files():
            self.watcher.addPath(str(CLAUDE_STATE_FILE))
        if word and word != self._last_claude:
            self._last_claude = word
            if word == "working":
                self.external_state = "working"; self.pending_ack = None
            elif word == "waiting":
                self.external_state = "waiting"
                self.pending_ack = "waiting"; self.last_ack_remind = time.time()
                self.set_anim("spine", fallbacks=("thinking", "wait"))
                self.speak("需要你确认/授权 👀 处理完点我一下", 6, notify=True, title="需要操作")
            elif word == "done":
                self.external_state = None
                self.pending_ack = "done"; self.last_ack_remind = time.time()
                self.state = "perform"; self.set_anim("victory", fallbacks=("pick", "wait"))
                # 结果显示在横幅里,这里不再冒重复气泡
                self.notify("运行完毕", (self.activity or "完成"))
            else:
                self.external_state = None; self.pending_ack = None
        self._spin_i = (self._spin_i + 1) % len(self.SPIN)
        self._claude_word = word
        self.refresh_banners()

    def toggle_banners(self):
        self.banners_collapsed = not self.banners_collapsed
        self.badge.expanded = not self.banners_collapsed
        self.badge.update()
        self.refresh_banners()

    def _badge_pos(self):
        g = self.frameGeometry(); s = self.scale
        cx = g.x() + int(base.ANCHOR_WX)
        return cx, cx + int(70 * s), g.y() + int(base.ANCHOR_WY - 205 * s)

    def refresh_banners(self):
        lines = int(self.data.get("banner_lines", 1))
        cw = self._claude_word
        c_active = cw in ("working", "waiting", "done")
        try:
            xw = CODEX_STATE_FILE.read_text().strip()
            x_active = (time.time() - os.path.getmtime(CODEX_STATE_FILE)) < 15 \
                and xw in ("working", "waiting", "done")
        except Exception:
            xw = ""; x_active = False

        if not (c_active or x_active):
            self.badge.hide(); self.banner_claude.hide(); self.banner_codex.hide(); return

        cx, bx, by = self._badge_pos()
        self.badge.move(bx, by); self.badge.show(); self.badge.raise_()
        if self.banners_collapsed:
            self.banner_claude.hide(); self.banner_codex.hide(); return

        if c_active:
            self._fill(self.banner_claude, cw, self.project, self.activity, lines)
        else:
            self.banner_claude.hide()
        if x_active:
            self._fill(self.banner_codex, xw, self._read_small(CODEX_PROJECT_FILE) or "Codex",
                       self._read_small(CODEX_ACTIVITY_FILE), lines)
        else:
            self.banner_codex.hide()
        ybottom = by - 4
        for b in (self.banner_claude, self.banner_codex):
            if b.isVisible():
                b.place(cx, ybottom); b.raise_(); ybottom -= b.height() + 6

    def _fill(self, banner, word, proj, act, lines):
        right = self.SPIN[self._spin_i] if word == "working" else ("👀" if word == "waiting" else "✅")
        act = act or {"working": "工作中", "waiting": "需要确认", "done": "完成"}.get(word, "")
        banner.update_status(proj, act, right, lines)

    # ---------- 覆盖:行为受属性/状态影响 ----------
    def behave(self):
        if self.external_state == "working":
            if self.cur is None or self.cur.name not in ("inspect", "thinking"):
                self.set_anim("inspect", fallbacks=("thinking", "wait"))
            return
        if self.external_state == "waiting":
            if self.cur is None or self.cur.name not in ("spine", "thinking", "wait"):
                self.set_anim("spine", fallbacks=("thinking", "wait"))
            return
        super().behave()

    IDLE_DWELL = (150, 320)   # 待机停顿帧数(约6-13秒),更沉稳

    def choose_action(self):
        st = self.data["stats"]
        a = self.anims
        # 精力低 -> 休息(坐/躺,回精力)
        if st["energy"] < 25 and ("lying" in a or "sit" in a) and random.random() < 0.6:
            self.state = "perform"
            self.set_anim("lying" if "lying" in a else "sit", fallbacks=("wait",))
            QtCore.QTimer.singleShot(random.randint(4000, 8000), self.end_perform)
            st["energy"] = min(100, st["energy"] + 8)
            return
        r = random.random()
        if r < 0.60:                      # 多数时间待机
            self.state = "idle"; self.dwell = random.randint(*self.IDLE_DWELL); self.set_anim("wait")
        elif r < 0.78:                    # 偶尔短距离走动
            screen = QtWidgets.QApplication.primaryScreen().availableGeometry()
            cur = self.x()
            lo = max(screen.left() + 40, cur - 300)
            hi = min(screen.right() - base.WIN_W - 40 + base.ANCHOR_WX, cur + 300)
            self.walk_target = random.randint(int(lo), int(hi)) if hi > lo else cur
            self.state = "walk"; self.facing_right = self.walk_target > cur; self.set_anim("move")
        elif r < 0.90 and ("sit" in a or "inspect" in a):   # 坐一会/研究一会
            self.state = "perform"
            self.set_anim("sit" if "sit" in a else "inspect", fallbacks=("wait",))
            QtCore.QTimer.singleShot(random.randint(4000, 7000), self.end_perform)
        else:                             # 少量卖萌
            emotes = [e for e in ("victory", "spine", "attack") if e in a]
            if emotes:
                self.state = "perform"; self.set_anim(random.choice(emotes), fallbacks=("wait",))
                if self.cur and self.cur.loop:
                    QtCore.QTimer.singleShot(random.randint(2500, 4500), self.end_perform)
            else:
                self.state = "idle"; self.dwell = random.randint(*self.IDLE_DWELL); self.set_anim("wait")

    # 走完/表演完后,停顿更久,别急着再动
    def on_oneshot_done(self):
        self.state = "idle"; self.dwell = random.randint(*self.IDLE_DWELL); self.set_anim("wait")

    def step_walk(self):
        speed = 3; x = self.x()
        if abs(x - self.walk_target) <= speed:
            self.state = "idle"; self.dwell = random.randint(*self.IDLE_DWELL); self.set_anim("wait")
            return
        self.move(x + (speed if self.walk_target > x else -speed), self.y())

    # ---------- 命中测试(带缓存) ----------
    def opaque_at(self, pos):
        if not self.cur:
            return False
        pm = self.cur.frames[self.frame_i]
        key = (self.cur.name, self.frame_i)
        if key != self._hit_key:
            self._hit_img = pm.toImage(); self._hit_key = key
        s = self.scale
        ax, ay = self.cur.anchor
        # 反算到未缩放图像坐标(交互区域随大小变化)
        fx = int((pos.x() - (base.ANCHOR_WX - ax * s)) / s)
        fy = int((pos.y() - (base.ANCHOR_WY - ay * s)) / s)
        img = self._hit_img
        if 0 <= fx < img.width() and 0 <= fy < img.height():
            return QtGui.QColor(img.pixel(fx, fy)).alpha() > 30
        return False

    # ---------- 悬浮状态栏 ----------
    def show_status_hover(self):
        self.status_panel.show_html(self.build_status_html(), self)

    def build_status_html(self):
        st = self.data["stats"]
        cs = self._last_claude or "idle"
        dlg = {"working": "Claude 正忙,我盯着 🔍", "waiting": "Claude 在等你确认 👀",
               "done": "刚跑完,好耶 ✅", "idle": "空闲中,陪你发呆 😌"}.get(cs, "待命中 😌")
        def bar(v):
            n = int(round(v / 10)); return "█" * n + "░" * (10 - n)
        return (f"<b>春田 · Lv.{st['level']}</b>  <span style='color:#bbb'>({int(st['xp'])}/{st['level']*100})</span><br>"
                f"♥ 心情 {bar(st['happiness'])} {int(st['happiness'])}<br>"
                f"🍚 饱食 {bar(st['hunger'])} {int(st['hunger'])}<br>"
                f"⚡ 精力 {bar(st['energy'])} {int(st['energy'])}<br>"
                f"<span style='color:#9fd0ff'>{dlg}</span>")

    def leaveEvent(self, e):
        self.hover_timer.stop(); self.status_panel.hide()

    # ---------- 形状遮罩:只让小人身体区域可交互,其余点击穿透 ----------
    def update_mask(self):
        if not self.cur:
            return
        pm = self.cur.frames[self.frame_i]
        s = self.scale
        ax, ay = self.cur.anchor
        if s != 1.0:   # 遮罩(可交互区域)随大小缩放
            pm = pm.scaled(max(1, int(pm.width() * s)), max(1, int(pm.height() * s)),
                           QtCore.Qt.KeepAspectRatio, QtCore.Qt.SmoothTransformation)
        ox, oy = int(base.ANCHOR_WX - ax * s), int(base.ANCHOR_WY - ay * s)
        m = pm.mask()
        if m is not None and not m.isNull():
            region = QtGui.QRegion(m); region.translate(ox, oy)
        else:
            # 兜底:限制到像素包围盒,绝不放开整窗(否则会挡住 Dock/别的窗口)
            region = QtGui.QRegion(ox, oy, pm.width(), pm.height())
        self.setMask(region)

    # ---------- 覆盖:每帧同步气泡/面板位置 + 更新遮罩 ----------
    def tick(self):
        super().tick()
        self.update_mask()
        self.bubble.place_above(self)
        if self.badge.isVisible():
            cx, bx, by = self._badge_pos()
            self.badge.move(bx, by)
            ybottom = by - 4
            for b in (self.banner_claude, self.banner_codex):
                if b.isVisible():
                    b.place(cx, ybottom); ybottom -= b.height() + 6
        if self.status_panel.isVisible():
            g = self.frameGeometry()
            self.status_panel.move(int(g.x() + base.ANCHOR_WX + 70),
                                   int(g.y() + base.ANCHOR_WY - 180))

    # ---------- 覆盖:单击=发指令,拖动=移动 ----------
    def mousePressEvent(self, e):
        if e.button() == QtCore.Qt.LeftButton and self.opaque_at(e.position().toPoint()):
            self._press_pos = e.globalPosition().toPoint()
            self._maybe_drag = True
            self.drag_offset = e.globalPosition().toPoint() - self.frameGeometry().topLeft()
            e.accept()

    def mouseMoveEvent(self, e):
        if getattr(self, "_maybe_drag", False):
            if not self.dragging:
                if (e.globalPosition().toPoint() - self._press_pos).manhattanLength() > 6:
                    self.dragging = True
                    self.state = "drag"
                    self.ack()
                    # 每套衣服都有休息动作集,拖动统一用 pick(弯腰/被拎)
                    self.set_anim("pick", fallbacks=("sit", "wait"))
            if self.dragging:
                self.move(e.globalPosition().toPoint() - self.drag_offset)
            e.accept()
        else:
            # 悬浮:停在小人身上一会儿 -> 显示状态栏
            if self.opaque_at(e.position().toPoint()):
                if not self.hover_timer.isActive() and not self.status_panel.isVisible():
                    self.hover_timer.start(650)
            else:
                self.hover_timer.stop(); self.status_panel.hide()

    def mouseReleaseEvent(self, e):
        if e.button() != QtCore.Qt.LeftButton:
            return
        was_drag = self.dragging
        self._maybe_drag = False
        self.dragging = False
        if was_drag:
            self.state = "idle"; self.dwell = random.randint(30, 80); self.set_anim("wait")
        else:
            self.pet_pat()   # 单击=摸摸(避免误触输入)
        e.accept()

    def ack(self):
        """理会提醒:跑完/等待的持续提醒到此为止。"""
        if self.pending_ack:
            self.pending_ack = None
            self.speak("好的~ 收到 👌", 2)

    def pet_pat(self):
        self.ack()
        self.data["stats"]["happiness"] = min(100, self.data["stats"]["happiness"] + 3)
        self.add_xp(1); self.speak("嘿嘿~ ♥", 2)

    def mouseDoubleClickEvent(self, e):
        # 双击=弹出头顶输入框发指令
        if self.opaque_at(e.position().toPoint()):
            self.open_prompt()

    # ---------- 发指令给 Claude ----------
    def open_prompt(self):
        self.ack()
        if self.prompt_bubble is None:
            self.prompt_bubble = PromptBubble()
            self.prompt_bubble.submitted.connect(self._on_prompt)
        self.prompt_bubble.popup(self)

    def _on_prompt(self, text):
        if self.data.get("send_mode", "current") == "current":
            self.send_to_current(text)
        else:
            self.send_new(text)

    def _osa(self, script, label=""):
        r = subprocess.run(["osascript", "-e", script], capture_output=True, text=True)
        try:
            with open(STATE_DIR / "debug.log", "a") as f:
                f.write(f"[{label}] rc={r.returncode} err={r.stderr.strip()}\n")
        except Exception:
            pass
        return r.returncode, (r.stderr or "")

    def send_to_current(self, text):
        """粘贴到当前终端会话并回车;失败则复制+呼出终端让用户手动 Cmd+V。"""
        app = self.data.get("terminal_app", "Terminal")
        QtWidgets.QApplication.clipboard().setText(text)   # 先复制(CJK/emoji 可靠)
        script = (
            f'tell application {self._as_str(app)} to activate\n'
            'delay 0.4\n'
            'tell application "System Events"\n'
            '  keystroke "v" using command down\n'
            '  delay 0.15\n'
            '  key code 36\n'
            'end tell')
        rc, err = self._osa(script, "send")
        if rc == 0:
            self.speak("已发送到当前会话 ⌨️", 3); self.add_xp(3)
            return
        # 兜底:已复制,呼出终端,提示手动粘贴
        subprocess.Popen(["open", "-a", app])
        self.speak("已复制✂️并呼出终端,按 Cmd+V 粘贴发送(想全自动请授权辅助功能)", 9)
        if any(k in err.lower() for k in ("assistive", "not allowed", "-1719", "-25211", "1002", "-1743")):
            subprocess.Popen(["open",
                "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility"])

    def send_new(self, text):
        cwd = self.data.get("claude_cwd", str(Path.home()))
        cmd = f"cd {shlex.quote(cwd)} && claude {shlex.quote(text)}"
        script = (f'tell application "Terminal" to do script {self._as_str(cmd)}\n'
                  'tell application "Terminal" to activate')
        try:
            subprocess.Popen(["osascript", "-e", script])
            self.speak("已在新终端启动任务 🚀", 3); self.add_xp(3)
        except Exception as ex:
            self.speak(f"启动失败: {ex}", 4)

    def raise_claude(self):
        # 用 open -a(LaunchServices),不需要 Automation 权限
        app = self.data.get("terminal_app", "Terminal")
        subprocess.Popen(["open", "-a", app])
        self.speak(f"呼出 {app} 窗口", 2)

    # ---------- 右键菜单 ----------
    def contextMenuEvent(self, e):
        self.timer.stop()          # 菜单期间暂停动画,避免抢主线程导致菜单卡顿
        self.hover_timer.stop(); self.status_panel.hide()
        m = QtWidgets.QMenu(self)
        st = self.data["stats"]
        m.addAction(f"Lv.{st['level']}  ♥{int(st['happiness'])} 🍚{int(st['hunger'])} ⚡{int(st['energy'])}").setEnabled(False)
        m.addSeparator()
        m.addAction("💬 发指令给 Claude", self.open_prompt)
        m.addAction("🖥 呼出 Claude 窗口", self.raise_claude)
        link = m.addMenu("🔗 状态联动(二选一)")
        ca = link.addAction("Claude Code")
        ca.setCheckable(True); ca.setChecked(self.hooks_installed())
        ca.triggered.connect(lambda on: self.setup_claude_hooks() if on else self.remove_claude_hooks())
        if self.codex_installed():
            xa = link.addAction("Codex")
            xa.setCheckable(True); xa.setChecked(self.codex_bound())
            xa.triggered.connect(lambda on: self.setup_codex_notify() if on else self.remove_codex_notify())
        else:
            na = link.addAction("Codex(未检测到)"); na.setEnabled(False)
        m.addSeparator()
        m.addAction("🍚 喂食", self.feed)
        m.addAction("🎮 石头剪刀布", self.play_rps)
        m.addAction("😊 记录心情", self.log_mood)
        m.addSeparator()

        focus = m.addMenu("🍅 专注计时")
        for mins in (15, 25, 45):
            focus.addAction(f"{mins} 分钟", lambda _=False, x=mins: self.start_focus(x))
        if self.focus_end:
            focus.addAction("⏹ 停止专注", self.stop_focus)

        rem = m.addMenu("⏰ 提醒")
        rem.addAction("添加提醒…", self.add_reminder)
        wa = rem.addAction("💧 喝水提醒")
        wa.setCheckable(True); wa.setChecked(self.data.get("water_enabled", True))
        wa.triggered.connect(self.toggle_water)

        mu = m.addMenu("🎵 音乐")
        mu.addAction("📂 选择音乐文件夹…", self.choose_music)
        mu.addAction("▶/⏸ 播放/暂停", self.player.toggle)
        vis = mu.addAction("显示播放器")
        vis.setCheckable(True); vis.setChecked(self.player.isVisible())
        vis.triggered.connect(self.toggle_player)

        sc = m.addMenu("🚀 快捷启动")
        for name, cmd in self.data.get("shortcuts", {}).items():
            sc.addAction(name, lambda _=False, c=cmd: self.run_shortcut(c))

        skin = m.addMenu("👗 换衣服")
        for oid, o in OUTFITS.items():
            a = skin.addAction(o["name"])
            a.setCheckable(True); a.setChecked(oid == self.outfit)
            a.triggered.connect(lambda _=False, x=oid: self.switch_outfit(x))
        skin.addSeparator()
        auto = skin.addAction("⏱ 定时自动换装")
        auto.setCheckable(True); auto.setChecked(self.data.get("auto_outfit", False))
        auto.triggered.connect(self.toggle_auto_outfit)
        iv = skin.addMenu("换装间隔")
        for mins in (10, 30, 60, 120):
            a = iv.addAction(f"{mins} 分钟"); a.setCheckable(True)
            a.setChecked(self.data.get("auto_outfit_min") == mins)
            a.triggered.connect(lambda _=False, x=mins: self.set_cfg("auto_outfit_min", x))

        sz = m.addMenu("📏 大小")
        for label, val in (("小 75%", 0.75), ("标准 100%", 1.0), ("大 125%", 1.25), ("超大 150%", 1.5)):
            a = sz.addAction(label); a.setCheckable(True)
            a.setChecked(abs(self.scale - val) < 0.01)
            a.triggered.connect(lambda _=False, v=val: self.set_scale(v))
        bl = m.addMenu("💬 对话框行数")
        for n in (1, 3, 5, 10):
            a = bl.addAction(f"{n} 行"); a.setCheckable(True)
            a.setChecked(int(self.data.get("banner_lines", 1)) == n)
            a.triggered.connect(lambda _=False, x=n: self.set_cfg("banner_lines", x))

        cfg = m.addMenu("⚙️ 设置")
        sm = cfg.addMenu("发送方式")
        for key, label in (("current", "键入当前会话"), ("new", "新终端启动")):
            a = sm.addAction(label); a.setCheckable(True)
            a.setChecked(self.data.get("send_mode") == key)
            a.triggered.connect(lambda _=False, k=key: self.set_cfg("send_mode", k))
        ta = cfg.addMenu("终端应用")
        for label, appname in (("Terminal", "Terminal"), ("iTerm2", "iTerm"),
                               ("VS Code", "Visual Studio Code")):
            a = ta.addAction(label); a.setCheckable(True)
            a.setChecked(self.data.get("terminal_app") == appname)
            a.triggered.connect(lambda _=False, x=appname: self.set_cfg("terminal_app", x))

        m.addSeparator()
        m.addAction("📊 属性详情", self.show_stats)
        m.addAction("退出", self.quit_app)
        m.exec(e.globalPos())
        self.timer.start(base.FRAME_MS)   # 菜单关闭后恢复动画

    def set_cfg(self, key, val):
        self.data[key] = val; self.save()
        self.speak(f"{key} = {val}", 2)

    def set_scale(self, s):
        self.scale = float(s); self.data["pet_scale"] = float(s); self.save()
        self.update_mask(); self.update()
        self.speak(f"大小 {int(s * 100)}%", 2)

    # ---------- 音乐 ----------
    def choose_music(self):
        folder = QtWidgets.QFileDialog.getExistingDirectory(self, "选择音乐文件夹",
                                                            self.data.get("music_folder") or str(Path.home()))
        if not folder:
            return
        n = self.player.load_folder(folder)
        self.data["music_folder"] = folder; self.save()
        if n:
            self.player.place_near(self); self.player.show(); self.player.play_index(0)
            self.speak(f"找到 {n} 首,开播啦 🎵", 4)
        else:
            self.speak("这个文件夹没找到音乐文件", 4)

    def toggle_player(self, checked=None):
        if self.player.isVisible():
            self.player.hide()
        else:
            self.player.place_near(self); self.player.show()

    def toggle_auto_outfit(self, checked):
        self.data["auto_outfit"] = checked; self.last_outfit_change = time.time(); self.save()
        self.speak("定时换装已" + (f"开启(每{self.data.get('auto_outfit_min',30)}分钟)👗" if checked else "关闭"), 4)

    # ---------- Claude Code 一键接入 ----------
    @staticmethod
    def _hook_python():
        exe = sys.executable
        if os.path.basename(exe).lower().startswith("python"):
            return exe
        return shutil.which("python3") or "python3"

    def hooks_installed(self):
        try:
            data = json.loads(CLAUDE_SETTINGS.read_text())
        except Exception:
            return False
        for entries in data.get("hooks", {}).values():
            for e in entries if isinstance(entries, list) else []:
                for h in e.get("hooks", []):
                    if HOOK_TAG in h.get("command", ""):
                        return True
        return False

    def setup_claude_hooks(self):
        # 写助手脚本(解析事件 -> 状态/活动/项目名)
        try:
            STATE_DIR.mkdir(parents=True, exist_ok=True)
            CLAUDE_HOOK_HELPER.write_text(HOOK_HELPER_SRC)
            os.chmod(CLAUDE_HOOK_HELPER, 0o755)
        except Exception as ex:
            self.speak(f"写助手脚本失败: {ex}", 5); return
        py = self._hook_python()
        try:
            data = json.loads(CLAUDE_SETTINGS.read_text()) if CLAUDE_SETTINGS.exists() else {}
        except Exception:
            data = {}
        if CLAUDE_SETTINGS.exists():
            try:
                (CLAUDE_SETTINGS.parent / "settings.json.springfieldpet.bak").write_text(
                    CLAUDE_SETTINGS.read_text())
            except Exception:
                pass
        hooks = data.setdefault("hooks", {})
        added = 0
        for event, _state, matcher in HOOK_EVENTS:
            cmd = f"{shlex.quote(py)} {shlex.quote(str(CLAUDE_HOOK_HELPER))} {event}"
            entries = hooks.setdefault(event, [])
            present = any(HOOK_TAG in h.get("command", "")
                          for e in entries if isinstance(e, dict)
                          for h in e.get("hooks", []))
            if not present:
                entry = {"hooks": [{"type": "command", "command": cmd}]}
                if matcher:
                    entry["matcher"] = matcher
                entries.append(entry); added += 1
        try:
            CLAUDE_SETTINGS.parent.mkdir(parents=True, exist_ok=True)
            CLAUDE_SETTINGS.write_text(json.dumps(data, ensure_ascii=False, indent=2))
        except Exception as ex:
            self.speak(f"写入失败: {ex}", 5); return
        if added:
            self.speak(f"已接入 Claude Code(+{added})!头顶会显示项目+活动。新开会话生效 🔗", 8,
                       notify=True, title="Claude 联动已开启")
        else:
            self.speak("已经接入过啦 🔗", 4)

    def remove_claude_hooks(self):
        try:
            data = json.loads(CLAUDE_SETTINGS.read_text())
        except Exception:
            self.speak("没有可断开的配置", 3); return
        for event, entries in list(data.get("hooks", {}).items()):
            data["hooks"][event] = [
                e for e in entries
                if not any(HOOK_TAG in h.get("command", "") for h in e.get("hooks", []))]
            if not data["hooks"][event]:
                del data["hooks"][event]
        try:
            CLAUDE_SETTINGS.write_text(json.dumps(data, ensure_ascii=False, indent=2))
            self.speak("已断开 Claude 联动(新开会话生效)", 5)
        except Exception as ex:
            self.speak(f"写入失败: {ex}", 5)

    # ---------- Codex 一键接入 ----------
    def codex_installed(self):
        return CODEX_CONFIG.exists()

    def codex_bound(self):
        try:
            return "codex_notify.sh" in CODEX_CONFIG.read_text()
        except Exception:
            return False

    def setup_codex_notify(self):
        if not CODEX_CONFIG.exists():
            self.speak("没找到 Codex 配置(~/.codex/config.toml)", 5); return
        text = CODEX_CONFIG.read_text()
        try:
            (CODEX_CONFIG.parent / "config.toml.springfieldpet.bak").write_text(text)
        except Exception:
            pass
        # 提取原有 notify 数组(非本项目的)以便串联转发
        m = re.search(r'(?m)^\s*notify\s*=\s*(\[[^\n]*\])', text)
        orig = []
        if m:
            try:
                orig = json.loads(m.group(1))
            except Exception:
                orig = []
        if orig and "codex_notify.sh" not in " ".join(map(str, orig)):
            quoted = " ".join(shlex.quote(str(x)) for x in orig)
            CODEX_ORIG.write_text(f"ORIG_NOTIFY=({quoted})\n")
        # 写包装脚本:记 Codex 状态(独立文件,横幅区分 Claude/Codex)+ 转发原 notify
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        py = self._hook_python()
        CODEX_WRAPPER.write_text(
            "#!/bin/bash\n"
            "mkdir -p ~/.springfield_pet\n"
            f'D=~/.springfield_pet\n'
            'echo done > "$D/codex_state"\n'
            # 用 python 从 notify JSON(最后一个参数)提取最后消息作为结果开头
            f'{shlex.quote(py)} - "$@" <<\'PYEOF\' 2>/dev/null || echo 回合完成 > "$D/codex_activity"\n'
            "import sys, json, os\n"
            "from pathlib import Path\n"
            "D = Path.home()/'.springfield_pet'\n"
            "try: d = json.loads(sys.argv[-1])\n"
            "except Exception: d = {}\n"
            "msg = d.get('last-assistant-message') or d.get('last_assistant_message') or ''\n"
            "msg = ' '.join(str(msg).split())\n"
            "(D/'codex_activity').write_text(('完成:'+msg[:60]) if msg else '回合完成')\n"
            "cwd = d.get('cwd') or ''\n"
            "(D/'codex_project').write_text(os.path.basename(str(cwd).rstrip('/')) or 'Codex')\n"
            "PYEOF\n"
            f'SRC="{CODEX_ORIG}"\n'
            'if [ -f "$SRC" ]; then source "$SRC"; "${ORIG_NOTIFY[@]}" "$@" 2>/dev/null; fi\n')
        os.chmod(CODEX_WRAPPER, 0o755)
        new_line = f'notify = ["bash", "{CODEX_WRAPPER}"]'
        if re.search(r'(?m)^\s*notify\s*=', text):
            text = re.sub(r'(?m)^\s*notify\s*=\s*\[[^\n]*\]', new_line, text, count=1)
        else:
            text = new_line + "\n" + text
        try:
            CODEX_CONFIG.write_text(text)
            self.speak("已接入 Codex(跑完回合会庆祝)!已保留你的 Computer Use 🔗", 8,
                       notify=True, title="Codex 联动已开启")
        except Exception as ex:
            self.speak(f"写入失败: {ex}", 5)

    def remove_codex_notify(self):
        if not CODEX_CONFIG.exists():
            return
        text = CODEX_CONFIG.read_text()
        orig_line = None
        if CODEX_ORIG.exists():
            mm = re.search(r"ORIG_NOTIFY=\((.*)\)", CODEX_ORIG.read_text())
            if mm:
                parts = shlex.split(mm.group(1))
                orig_line = "notify = [" + ", ".join(json.dumps(p) for p in parts) + "]"
        if orig_line:
            text = re.sub(r'(?m)^\s*notify\s*=\s*\[[^\n]*\]', orig_line, text, count=1)
        else:
            text = re.sub(r'(?m)^\s*notify\s*=\s*\[[^\n]*\]\n?', "", text, count=1)
        try:
            CODEX_CONFIG.write_text(text)
            self.speak("已断开 Codex 联动(恢复原 notify)", 5)
        except Exception as ex:
            self.speak(f"写入失败: {ex}", 5)

    # ---------- 功能实现 ----------
    def feed(self):
        self.data["stats"]["hunger"] = min(100, self.data["stats"]["hunger"] + 25)
        self.add_xp(3); self.speak("好吃!谢谢~ 🍚", 3); self.bounce()

    def play_rps(self):
        opts = ["石头", "剪刀", "布"]
        btn = QtWidgets.QMessageBox(self)
        btn.setWindowTitle("石头剪刀布"); btn.setText("出什么?")
        bs = [btn.addButton(o, QtWidgets.QMessageBox.ActionRole) for o in opts]
        btn.exec()
        clicked = btn.clickedButton()
        if clicked not in bs:
            return
        me = opts.index(clicked.text()); ai = random.randint(0, 2)
        beats = {0: 1, 1: 2, 2: 0}
        if me == ai:
            res = "平局!"
        elif beats[me] == ai:
            res = "你赢啦 🎉"; self.add_xp(8); self.data["stats"]["happiness"] = min(100, self.data["stats"]["happiness"] + 8)
        else:
            res = "我赢咯~ 😝"; self.add_xp(2)
        self.speak(f"我出{opts[ai]},{res}", 4)

    def log_mood(self):
        moods = ["😀 很好", "🙂 还行", "😐 一般", "😟 有点累", "😢 不太好"]
        item, ok = QtWidgets.QInputDialog.getItem(self, "记录心情", "现在感觉怎么样?", moods, 0, False)
        if ok:
            self.data["mood_log"].append({"mood": item, "at": time.time()})
            self.save(); self.add_xp(2); self.speak("记下啦~ 照顾好自己 💛", 3)

    def start_focus(self, mins):
        self.focus_end = time.time() + mins * 60
        self.external_state = "working"
        self.set_anim("inspect", fallbacks=("thinking", "wait"))
        self.speak(f"开始专注 {mins} 分钟,加油!🍅", 4, notify=True, title="专注开始")

    def stop_focus(self):
        self.focus_end = 0; self.external_state = None
        self.speak("专注已停止", 3)

    def add_reminder(self):
        text, ok = QtWidgets.QInputDialog.getText(self, "添加提醒", "提醒内容:")
        if not ok or not text.strip():
            return
        mins, ok = QtWidgets.QInputDialog.getInt(self, "添加提醒", "多少分钟后?", 10, 1, 1440)
        if not ok:
            return
        self.data["reminders"].append({"text": text.strip(), "at": time.time() + mins * 60})
        self.save(); self.speak(f"好的,{mins}分钟后提醒你", 3)

    def toggle_water(self, checked):
        self.data["water_enabled"] = checked; self.last_water = time.time(); self.save()
        self.speak("喝水提醒已" + ("开启 💧" if checked else "关闭"), 3)

    def run_shortcut(self, cmd):
        try:
            subprocess.Popen(cmd, shell=True); self.speak("启动中… 🚀", 2)
        except Exception as ex:
            self.speak(f"失败: {ex}", 3)

    def show_stats(self):
        st = self.data["stats"]
        recent = self.data["mood_log"][-5:]
        moods = "\n".join(time.strftime("%m-%d %H:%M ", time.localtime(m["at"])) + m["mood"] for m in recent) or "(暂无)"
        QtWidgets.QMessageBox.information(self, "春田 · 属性",
            f"等级: Lv.{st['level']}   经验: {st['xp']}/{st['level']*100}\n"
            f"心情 ♥: {int(st['happiness'])}/100\n饱食 🍚: {int(st['hunger'])}/100\n"
            f"精力 ⚡: {int(st['energy'])}/100\n\n最近心情:\n{moods}")

    def switch_skin(self, skin):
        super().switch_skin(skin)
        self.speak(f"换上「{base.SKIN_NAMES.get(skin, skin)}」啦~", 3)

    def quit_app(self):
        self.save(); QtWidgets.QApplication.quit()

    def closeEvent(self, e):
        self.save(); super().closeEvent(e)


def main():
    app = QtWidgets.QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(True)
    c = Companion(); c.show(); c.raise_(); c.update_mask()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
