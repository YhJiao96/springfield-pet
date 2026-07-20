#!/usr/bin/env python3
"""春田桌宠 — Springfield desktop pet.

用 pet_assets/ 里的透明帧序列驱动。功能:
  - 自主行为:待机 / 走动 / 思考(气泡) / 偶尔卖萌 / 重伤皮会坐下躺下
  - 左键按住拖动:小人被"拎起"跟着鼠标(有 pick 的皮肤用 pick)
  - 右键菜单:切换 10 套皮肤 + 退出
  - 按脚底锚点渲染,切换状态时脚不乱跳

运行: python3 pet.py
"""
from __future__ import annotations

import json
import os
import random
import sys
from pathlib import Path

from PySide6 import QtCore, QtGui, QtWidgets

def _asset_root():
    # PyInstaller 打包后素材在 _MEIPASS/pet_assets;开发时在 repo/assets/pet_assets
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", ".")) / "pet_assets"
    here = Path(__file__).resolve().parent
    for cand in (here.parent / "assets" / "pet_assets", here.parent / "pet_assets"):
        if (cand / "manifest.json").exists():
            return cand
    return here.parent / "assets" / "pet_assets"


ASSETS = _asset_root()
FPS = 25
FRAME_MS = int(1000 / FPS)

# 窗口足够大以容纳最大姿势;脚底锚点固定在窗内这个点
WIN_W, WIN_H = 520, 520
ANCHOR_WX, ANCHOR_WY = 260, 360

DEFAULT_SKIN = "M1903"
NATIVE_MOVE_FACES_RIGHT = True   # move 原生朝右;朝左时水平翻转

# 皮肤中文名
SKIN_NAMES = {
    "M1903": "春田 · 默认",
    "M1903_5": "春田 · 皮肤5",
    "M1903_302": "春田 · 皮肤302",
    "M1903_802": "春田 · 蓝礼服",
    "M1903_1107": "春田 · 泳装",
    "RM1903": "春田 · 重伤",
    "RM1903_5": "春田 · 重伤5",
    "RM1903_302": "春田 · 重伤·红斗篷",
    "RM1903_1107": "春田 · 重伤·泳装",
    "RM1903_802": "春田 · 重伤·礼服",
}


class Anim:
    """一个动画:一串 QPixmap + 锚点 + 是否循环。"""

    def __init__(self, name, frames, anchor, loop):
        self.name = name
        self.frames = frames          # list[QPixmap]
        self.anchor = anchor          # [ax, ay] in frame pixels
        self.loop = loop

    def flipped(self):
        flip = [f.transformed(QtGui.QTransform().scale(-1, 1),
                              QtCore.Qt.SmoothTransformation) for f in self.frames]
        w = self.frames[0].width()
        return Anim(self.name + "_flip", flip, [w - self.anchor[0], self.anchor[1]], self.loop)


def load_skin(skin, manifest):
    """加载一套皮肤的全部动画为内存中的 QPixmap。"""
    anims = {}
    entry = manifest["skins"][skin]["animations"]
    for name, meta in entry.items():
        adir = ASSETS / skin / name
        files = sorted(adir.glob("frame_*.png"))
        if not files:
            continue
        frames = [QtGui.QPixmap(str(f)) for f in files]
        anims[name] = Anim(name, frames, meta["anchor"], meta.get("loop", True))
    return anims


class Pet(QtWidgets.QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowFlags(
            QtCore.Qt.FramelessWindowHint
            | QtCore.Qt.WindowStaysOnTopHint)
        self.setAttribute(QtCore.Qt.WA_TranslucentBackground)
        self.resize(WIN_W, WIN_H)

        self.manifest = json.load(open(ASSETS / "manifest.json"))
        self.skin = DEFAULT_SKIN
        self.anims = load_skin(self.skin, self.manifest)

        self.cur = None          # 当前 Anim
        self.frame_i = 0
        self.facing_right = True
        self.scale = 1.0         # 整体缩放

        # 拖动
        self.dragging = False
        self.drag_offset = QtCore.QPoint()

        # 自主行为
        self.state = "idle"
        self.walk_target = None
        self.dwell = 0           # 剩余待机计时(帧)

        # 定位到屏幕底部中间偏右
        screen = QtWidgets.QApplication.primaryScreen().availableGeometry()
        self.move(screen.center().x() - WIN_W // 2,
                  screen.bottom() - WIN_H + 40)

        self.set_anim("wait")
        self.timer = QtCore.QTimer(self)
        self.timer.timeout.connect(self.tick)
        self.timer.start(FRAME_MS)

    # ---------- 动画控制 ----------
    def pick_anim(self, name, fallbacks=()):
        for n in (name, *fallbacks):
            if n in self.anims:
                return self.anims[n]
        return self.anims.get("wait")

    def set_anim(self, name, facing_right=None, fallbacks=()):
        if facing_right is not None:
            self.facing_right = facing_right
        base = self.pick_anim(name, fallbacks)
        if base is None:
            return
        # move 按朝向翻转
        need_flip = (not self.facing_right) if NATIVE_MOVE_FACES_RIGHT else self.facing_right
        self.cur = base.flipped() if (need_flip and name == "move") else base
        self.frame_i = 0

    # ---------- 主循环 ----------
    def tick(self):
        if not self.cur:
            return
        if not self.dragging:
            self.behave()
        self.frame_i += 1
        if self.frame_i >= len(self.cur.frames):
            if self.cur.loop:
                self.frame_i = 0
            else:
                self.frame_i = len(self.cur.frames) - 1
                if not self.dragging:
                    self.on_oneshot_done()
        self.update()

    def on_oneshot_done(self):
        # 一次性动画播完 -> 回待机
        self.state = "idle"
        self.dwell = random.randint(40, 110)
        self.set_anim("wait")

    def behave(self):
        if self.state == "walk":
            self.step_walk()
            return
        # idle:倒计时结束后随机挑个新行为
        self.dwell -= 1
        if self.dwell > 0:
            return
        self.choose_action()

    def choose_action(self):
        is_damaged = self.skin.startswith("R")
        actions = ["walk", "think", "wait", "wait"]
        if is_damaged:
            actions += ["sit", "lying", "pick"]
        else:
            actions += ["victory", "attack"]
            if "spine" in self.anims:
                actions += ["spine"]
        choice = random.choice(actions)

        if choice == "walk":
            screen = QtWidgets.QApplication.primaryScreen().availableGeometry()
            self.walk_target = random.randint(screen.left() + 40,
                                              screen.right() - WIN_W - 40 + ANCHOR_WX)
            self.state = "walk"
            self.facing_right = self.walk_target > self.x()
            self.set_anim("move")
        elif choice in ("wait",):
            self.state = "idle"
            self.dwell = random.randint(60, 160)
            self.set_anim("wait")
        else:
            # 一次性/短循环表演
            self.state = "perform"
            self.set_anim(choice, fallbacks=("wait",))
            if self.cur and self.cur.loop:
                # 循环类(think/sit/lying)给个时长后回待机
                QtCore.QTimer.singleShot(random.randint(2500, 5000), self.end_perform)

    def end_perform(self):
        if self.state == "perform" and not self.dragging:
            self.on_oneshot_done()

    def step_walk(self):
        speed = 3
        x = self.x()
        if abs(x - self.walk_target) <= speed:
            self.state = "idle"
            self.dwell = random.randint(40, 120)
            self.set_anim("wait")
            return
        nx = x + (speed if self.walk_target > x else -speed)
        self.move(nx, self.y())

    # ---------- 渲染 ----------
    def paintEvent(self, _):
        if not self.cur:
            return
        pm = self.cur.frames[self.frame_i]
        s = self.scale
        ax, ay = self.cur.anchor
        if s != 1.0:
            pm = pm.scaled(max(1, int(pm.width() * s)), max(1, int(pm.height() * s)),
                           QtCore.Qt.KeepAspectRatio, QtCore.Qt.SmoothTransformation)
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.SmoothPixmapTransform)
        p.drawPixmap(int(ANCHOR_WX - ax * s), int(ANCHOR_WY - ay * s), pm)
        p.end()

    # ---------- 交互 ----------
    def opaque_at(self, pos):
        """命中测试:该点是否落在小人不透明像素上。"""
        if not self.cur:
            return False
        pm = self.cur.frames[self.frame_i]
        ax, ay = self.cur.anchor
        fx = pos.x() - int(ANCHOR_WX - ax)
        fy = pos.y() - int(ANCHOR_WY - ay)
        if 0 <= fx < pm.width() and 0 <= fy < pm.height():
            return QtGui.QColor(pm.toImage().pixel(fx, fy)).alpha() > 30
        return False

    def mousePressEvent(self, e):
        if e.button() == QtCore.Qt.LeftButton and self.opaque_at(e.position().toPoint()):
            self.dragging = True
            self.drag_offset = e.globalPosition().toPoint() - self.frameGeometry().topLeft()
            self.state = "drag"
            # 被拎起:有 pick 用 pick,否则用 wait
            self.set_anim("pick", fallbacks=("thinking", "wait"))
            e.accept()

    def mouseMoveEvent(self, e):
        if self.dragging:
            self.move(e.globalPosition().toPoint() - self.drag_offset)
            e.accept()

    def mouseReleaseEvent(self, e):
        if self.dragging and e.button() == QtCore.Qt.LeftButton:
            self.dragging = False
            self.state = "idle"
            self.dwell = random.randint(30, 80)
            self.set_anim("wait")
            e.accept()

    def mouseDoubleClickEvent(self, e):
        # 双击卖个萌
        if self.opaque_at(e.position().toPoint()):
            self.state = "perform"
            self.set_anim("victory" if not self.skin.startswith("R") else "pick",
                          fallbacks=("thinking", "wait"))

    def contextMenuEvent(self, e):
        menu = QtWidgets.QMenu(self)
        skin_menu = menu.addMenu("换皮肤")
        for sk in self.manifest["skins"]:
            act = skin_menu.addAction(SKIN_NAMES.get(sk, sk))
            act.setCheckable(True)
            act.setChecked(sk == self.skin)
            act.triggered.connect(lambda _=False, s=sk: self.switch_skin(s))
        menu.addSeparator()
        menu.addAction("退出", QtWidgets.QApplication.quit)
        menu.exec(e.globalPos())

    def switch_skin(self, skin):
        if skin == self.skin:
            return
        self.skin = skin
        self.anims = load_skin(skin, self.manifest)
        self.state = "idle"
        self.dwell = random.randint(30, 80)
        self.set_anim("wait")


def main():
    app = QtWidgets.QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(True)
    pet = Pet()
    pet.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
