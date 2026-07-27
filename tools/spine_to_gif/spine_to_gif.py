#!/usr/bin/env python3
"""把一套 Spine 素材(.skel/.json + .atlas + .png)渲染成透明 GIF / 帧序列。

用于把《少女前线》这类 **Spine 骨骼动画** 素材转成桌宠能用的帧。
素材需**你自己提供**(本工具不含任何游戏素材);渲染在本地进行,不上传。

    python3 tools/spine_to_gif/spine_to_gif.py <素材目录>
    python3 tools/spine_to_gif/spine_to_gif.py <素材目录> --to-skin mychar   # 直接变桌宠皮肤

一套素材通常长这样(skel 和 atlas 同名)::

    M1903/
      M1903.skel      # 或 .json —— 骨骼动画
      M1903.atlas     # 图集描述
      M1903.png       # 图集(可能多张)

渲染走 pixi-spine + 无头 Chromium(playwright)。首次运行会:
  1. 下载 pixi.js / pixi-spine 的浏览器版 JS 到 ~/.springfield_pet/spine_tools/
  2. 需要 Chromium —— 没有的话按提示跑一次 `python3 -m playwright install chromium`

产出(默认写到 <素材目录>/_gif_out/):
  - 每个动画一个透明 GIF
  - --frames 另存 PNG 帧序列(保留完整透明,可喂给 import_skin)
  - --to-skin NAME 直接渲染并导入成一套桌宠皮肤(内部复用 import_skin)
"""
from __future__ import annotations

import argparse
import base64
import functools
import http.server
import re
import shutil
import socketserver
import sys
import threading
import urllib.request
from pathlib import Path

try:
    from PIL import Image
except ImportError:                                    # pragma: no cover
    sys.exit("需要 Pillow:  pip install Pillow")

HERE = Path(__file__).resolve().parent
TOOLS_DIR = Path.home() / ".springfield_pet" / "spine_tools"

# 浏览器版 JS(MIT);首次运行下载到 TOOLS_DIR,不进仓库。
VENDOR_JS = {
    "pixi.min.js": "https://unpkg.com/pixi.js@7.4.2/dist/pixi.min.js",
    "pixi-spine.js": "https://unpkg.com/pixi-spine@4.0.4/dist/pixi-spine.js",
}

DEFAULT_FPS = 25
DEFAULT_HEIGHT = 280          # 渲染目标高度(和内置皮肤一个量级)
DEFAULT_PAD = 12
MEASURE_SAMPLES = 6           # 每个动画采样几个时间点求 union 包围盒


# ------------------------------------------------------------ 依赖准备

def ensure_vendor_js(log=print):
    """确保 pixi / pixi-spine 就绪;缺了就下载。返回它们所在目录。"""
    TOOLS_DIR.mkdir(parents=True, exist_ok=True)
    for name, url in VENDOR_JS.items():
        dst = TOOLS_DIR / name
        if dst.exists() and dst.stat().st_size > 1000:
            continue
        log(f"  下载 {name} …")
        try:
            with urllib.request.urlopen(url, timeout=60) as r:
                dst.write_bytes(r.read())
        except Exception as ex:
            raise SystemExit(f"下载 {name} 失败({url}): {ex}\n"
                             f"可手动下载放到 {dst}")
    return TOOLS_DIR


def chromium_ready():
    """playwright 的 chromium 装了没。"""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return False, "缺少 playwright:  pip install playwright"
    try:
        with sync_playwright() as p:
            exe = p.chromium.executable_path
            return (Path(exe).exists(), None) if exe else (False, "chromium 未安装")
    except Exception as ex:
        return False, str(ex)


# ------------------------------------------------------------ 定位素材

SKEL_SUFFIXES = (".skel", ".json")


def find_spine_files(src: Path):
    """在目录里找一套 spine 素材,返回 (skel, atlas, is_binary)。

    优先 skel 与 atlas 同名;否则取目录里唯一的一个。找不到抛 ValueError。
    """
    if src.is_file():
        skel = src
        src = src.parent
    else:
        skels = [p for p in sorted(src.iterdir())
                 if p.suffix.lower() in SKEL_SUFFIXES and p.name != "manifest.json"]
        if not skels:
            raise ValueError(f"{src} 里没有 .skel/.json 骨骼文件")
        # 优先有同名 atlas 的
        skel = next((s for s in skels if (src / (s.stem + ".atlas")).exists()), skels[0])

    atlases = [p for p in sorted(src.iterdir()) if p.suffix.lower() == ".atlas"]
    if not atlases:
        raise ValueError(f"{src} 里没有 .atlas 图集文件")
    atlas = src / (skel.stem + ".atlas")
    if not atlas.exists():
        atlas = atlases[0]

    # atlas 引用的 png 是否都在
    missing = [ln.strip() for ln in atlas.read_text(errors="ignore").splitlines()
               if ln.strip().lower().endswith(".png") and not (src / ln.strip()).exists()]
    if missing:
        raise ValueError(f"{atlas.name} 引用的图集缺失: {', '.join(missing)}")

    return skel, atlas, skel.suffix.lower() == ".skel"


# ------------------------------------------------------------ 渲染

class _QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a):        # 别把每个请求都打到控制台
        pass


class _Server:
    """临时 http server —— Assets.load 需要 http(file:// 的 fetch 被 CORS 挡)。"""

    def __init__(self, root: Path):
        handler = functools.partial(_QuietHandler, directory=str(root))
        self.httpd = socketserver.TCPServer(("127.0.0.1", 0), handler)
        self.port = self.httpd.server_address[1]
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    @property
    def base(self):
        return f"http://127.0.0.1:{self.port}"

    def close(self):
        self.httpd.shutdown()


CANVAS_MARGIN = 0.35          # setup-pose 包围盒四周各留这么多余量,容纳跳跃/移动


def render_spine(skel: Path, atlas: Path, *, fps=DEFAULT_FPS, height=DEFAULT_HEIGHT,
                 margin=CANVAS_MARGIN, only=None, log=print):
    """渲染所有动画。返回 {anim_name: [PIL.Image(RGBA), ...]} 和元信息。"""
    from playwright.sync_api import sync_playwright

    vendor = ensure_vendor_js(log)
    work = Path(TOOLS_DIR) / "_render_work"
    if work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True)
    # server 根:harness + JS + 素材(atlas 引用的 png 一并 copy)
    shutil.copy(HERE / "harness.html", work / "harness.html")
    for name in VENDOR_JS:
        shutil.copy(vendor / name, work / name)
    shutil.copy(skel, work / skel.name)
    shutil.copy(atlas, work / atlas.name)
    for ln in atlas.read_text(errors="ignore").splitlines():
        if ln.strip().lower().endswith(".png"):
            shutil.copy(skel.parent / ln.strip(), work / ln.strip())

    server = _Server(work)
    frames_by_anim, meta = {}, {}
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1024, "height": 1024})
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.goto(f"{server.base}/harness.html")

            info = page.evaluate("async ([s,a]) => await window.spineLoad(s,a)",
                                 [f"{server.base}/{skel.name}", f"{server.base}/{atlas.name}"])
            if "error" in info:
                raise SystemExit(f"加载 spine 失败:\n{info['error']}\n"
                                 + ("\n".join(errors) if errors else ""))
            meta = {"version": info["version"], "pixi": info["pixi"]}
            animations = info["animations"]
            if only:
                want = set(only)
                animations = [a for a in animations if a["name"] in want]
                if not animations:
                    raise SystemExit(f"没有名为 {only} 的动画;可选:"
                                     + ", ".join(a["name"] for a in info["animations"]))
            log(f"  spine {info['version']} / pixi {info['pixi']} · "
                f"{len(animations)} 个动画")

            # 固定画布 = setup-pose 包围盒 + 四周余量,所有动画共用(切换不跳);
            # 多余留白最后按像素裁掉,越界的移动动作靠余量兜住。
            b = info["bounds"]
            if b["width"] <= 0 or b["height"] <= 0:
                raise SystemExit("setup-pose 包围盒无效(素材可能损坏)")
            scale = height / b["height"]
            cx, cy = b["x"] + b["width"] / 2, b["y"] + b["height"] / 2
            w = int(round(b["width"] * scale * (1 + 2 * margin)))
            h = int(round(b["height"] * scale * (1 + 2 * margin)))
            ox = w / 2 - cx * scale
            oy = h / 2 - cy * scale
            setup = page.evaluate("([w,h,s,ox,oy]) => window.spineSetup(w,h,s,ox,oy)",
                                  [w, h, scale, ox, oy])
            if "error" in setup:
                raise SystemExit(f"建画布失败: {setup['error']}")
            meta["canvas"] = [w, h]

            for a in animations:
                dur = a["duration"] or 0.0
                n = max(1, round(dur * fps))
                frames = []
                for i in range(n):
                    data = page.evaluate("([n,t]) => window.spineFrame(n,t)",
                                         [a["name"], i / fps])
                    if isinstance(data, str) and data.startswith("ERR:"):
                        raise SystemExit(f"渲染 {a['name']} 第 {i} 帧失败:\n{data[4:]}")
                    raw = base64.b64decode(re.sub("^data:image/png;base64,", "", data))
                    import io
                    frames.append(Image.open(io.BytesIO(raw)).convert("RGBA"))
                frames_by_anim[a["name"]] = frames
                log(f"    {a['name']:16s} {dur:5.2f}s -> {n:3d} 帧")
            browser.close()
    finally:
        server.close()
    return frames_by_anim, meta


# ------------------------------------------------------------ 输出

def _crop_to_content(frames, pad=2):
    """把一个动画的所有帧裁到它们不透明区域的并集(去掉固定画布的多余留白)。"""
    box = None
    for f in frames:
        b = f.getchannel("A").getbbox()
        if b:
            box = b if box is None else (min(box[0], b[0]), min(box[1], b[1]),
                                         max(box[2], b[2]), max(box[3], b[3]))
    if box is None:
        return frames
    w, h = frames[0].size
    box = (max(0, box[0] - pad), max(0, box[1] - pad),
           min(w, box[2] + pad), min(h, box[3] + pad))
    return [f.crop(box) for f in frames]


def save_gifs(frames_by_anim, out_dir: Path, fps=DEFAULT_FPS, log=print):
    out_dir.mkdir(parents=True, exist_ok=True)
    dur_ms = int(round(1000 / fps))
    for name, frames in frames_by_anim.items():
        frames = _crop_to_content(frames)
        # GIF 只有 1bit 透明:把接近全透的像素设为透明索引
        path = out_dir / f"{name}.gif"
        conv = []
        for f in frames:
            alpha = f.getchannel("A")
            p = f.convert("RGB").convert("P", palette=Image.ADAPTIVE, colors=255)
            p.paste(255, mask=alpha.point(lambda a: 255 if a < 128 else 0))
            p.info["transparency"] = 255
            conv.append(p)
        conv[0].save(path, format="GIF", save_all=True, append_images=conv[1:],
                     duration=dur_ms, loop=0, transparency=255, disposal=2, optimize=False)
        log(f"    {path.name}")


def save_frames(frames_by_anim, out_dir: Path, log=print):
    for name, frames in frames_by_anim.items():
        d = out_dir / name
        d.mkdir(parents=True, exist_ok=True)
        for i, f in enumerate(frames):
            f.save(d / f"frame_{i:04d}.png")
    log(f"    帧序列 -> {out_dir}")


def to_skin(frames_by_anim, skin_name, display, fps=DEFAULT_FPS, log=print):
    """把渲染帧直接导入成一套桌宠皮肤(复用 import_skin 的裁剪/锚点/manifest)。

    spine 动画名映射到桌宠动作槽(wait/move/victory…);认不出对应动作的动画
    桌宠播不了,会跳过(但 GIF 输出仍是全部动画)。
    """
    sys.path.insert(0, str(HERE.parent.parent / "src"))
    import import_skin as imp
    tmp = Path(TOOLS_DIR) / "_to_skin_frames"
    if tmp.exists():
        shutil.rmtree(tmp)
    used, skipped = {}, []          # slot -> spine 动画名(同槽先到先得)
    for name, frames in frames_by_anim.items():
        slot = imp.slot_for_filename(name)
        if not slot or slot in used:
            skipped.append(name)
            continue
        used[slot] = name
        d = tmp / slot
        d.mkdir(parents=True, exist_ok=True)
        for i, f in enumerate(frames):
            f.save(d / f"frame_{i:04d}.png")
    if not used:
        raise SystemExit("没有能映射到桌宠动作的动画名;可改用 GIF 输出后再用 "
                         "import_skin.py(文件名用 wait/move/victory…)手动导入")
    for slot, name in sorted(used.items()):
        log(f"    {name} -> {slot}")
    if skipped:
        log(f"  桌宠没有对应动作、已跳过(GIF 仍会全导出):{', '.join(skipped)}")
    res = imp.run_import(tmp, skin_name, imp.EXTERNAL_SKINS_DIR, display=display,
                         fps=fps, force=True, log=lambda *a: None)
    log(f"  已导入皮肤「{display}」:{sorted(res['animations'])}")
    return res


# ------------------------------------------------------------ CLI

def main(argv=None):
    ap = argparse.ArgumentParser(
        description="把一套 Spine 素材渲染成透明 GIF / 桌宠皮肤",
        formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
    ap.add_argument("source", type=Path, help="放一套 spine 素材的目录(或 .skel/.json 文件)")
    ap.add_argument("--out", type=Path, help="输出目录(默认 <素材>/_gif_out)")
    ap.add_argument("--fps", type=int, default=DEFAULT_FPS)
    ap.add_argument("--height", type=int, default=DEFAULT_HEIGHT, help="渲染目标高度")
    ap.add_argument("--only", nargs="+", help="只渲这些动画名")
    ap.add_argument("--frames", action="store_true", help="另存 PNG 帧序列")
    ap.add_argument("--to-skin", metavar="ID", help="直接导入成桌宠皮肤(皮肤 ID)")
    ap.add_argument("--display", help="皮肤显示名(配合 --to-skin)")
    ap.add_argument("--check", action="store_true", help="只检查依赖是否就绪")
    args = ap.parse_args(argv)

    ok, msg = chromium_ready()
    if args.check:
        print("chromium:", "就绪 ✅" if ok else f"未就绪 ❌ {msg}")
        try:
            ensure_vendor_js(); print("pixi/pixi-spine: 就绪 ✅")
        except SystemExit as e:
            print("pixi/pixi-spine:", e)
        return 0
    if not ok:
        ap.error(f"Chromium 未就绪:{msg}\n请先运行:  python3 -m playwright install chromium")
    if not args.source.exists():
        ap.error(f"找不到:{args.source}")

    try:
        skel, atlas, is_bin = find_spine_files(
            args.source if args.source.is_dir() else args.source)
    except ValueError as e:
        ap.error(str(e))
    print(f"素材:{skel.name} + {atlas.name}({'二进制' if is_bin else 'JSON'})")

    frames_by_anim, meta = render_spine(
        skel, atlas, fps=args.fps, height=args.height, only=args.only)
    total = sum(len(f) for f in frames_by_anim.values())
    print(f"渲染完成:{len(frames_by_anim)} 个动画 / {total} 帧,画布 {meta['canvas']}")

    if args.to_skin:
        to_skin(frames_by_anim, args.to_skin, args.display or args.to_skin, fps=args.fps)
        print("重启桌宠 → 右键「👗 换衣服」就能看到它")
        return 0

    out = args.out or (skel.parent / "_gif_out")
    print(f"\n导出 GIF -> {out}")
    save_gifs(frames_by_anim, out, fps=args.fps)
    if args.frames:
        save_frames(frames_by_anim, out / "_frames")
    print("✅ 完成。这些 GIF/帧可直接用 tools/import_skin.py 导入成桌宠皮肤")
    return 0


if __name__ == "__main__":
    sys.exit(main())
