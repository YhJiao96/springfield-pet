#!/usr/bin/env python3
"""把一堆动作 GIF 批量导入成一套新皮肤。

用法::

    python3 tools/import_skin.py <GIF目录> --name mychar --display "我的角色"

目录里一个文件 = 一个动作,文件名就是动作名(大小写无所谓,支持常见别名)::

    my_gifs/
      wait.gif        待机(必需)
      move.gif        走路
      victory.gif     庆祝
      thinking.gif    思考
      ...

也吃 APNG / WebP / PNG 序列目录。产出::

    assets/pet_assets/<name>/<动作>/frame_0000.png ...
    assets/pet_assets/manifest.json   (合并进去,不覆盖别人)

三件容易被忽略但必须做对的事:

1. **重采样到 25fps**。GIF 每帧时长可以不一样(常见 100ms/40ms 混排),而桌宠
   是固定 25fps 播放。不按时长补帧的话动作速度全错。
2. **脚底锚点**。桌宠按锚点渲染,切换动作时脚才不会跳。这里用"不透明像素
   最底部一小条的水平中心"当锚点 x —— 比整体包围盒中心更贴近脚的位置,
   角色前倾/挥手时不会左右漂。
3. **裁掉透明边**。GIF 往往留一大圈空白,不裁的话锚点算不准、体积也浪费。
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
import types
from pathlib import Path

#: 普通用户/打包版导入的皮肤默认写这里 —— .app 启动时会扫描它。
#: 开发者想把皮肤放进仓库,用 --assets 指到 assets/pet_assets。
EXTERNAL_SKINS_DIR = Path.home() / ".springfield_pet" / "skins"

try:
    from PIL import Image
except ImportError:                                    # pragma: no cover
    sys.exit("需要 Pillow:  pip install Pillow")

DEFAULT_FPS = 25
DEFAULT_MAX_HEIGHT = 320          # 和内置皮肤(~280px)一个量级
DEFAULT_FOOT_BAND = 0.12          # 取底部 12% 当"脚"来定锚点 x
DEFAULT_KEY_TOLERANCE = 24        # 无 alpha 时按角落色抠背景的容差

SUPPORTED_SUFFIXES = {".gif", ".png", ".apng", ".webp"}

#: 动作槽 -> (是否循环, suggested_state);跟内置 manifest 的约定保持一致
SLOTS = {
    "wait":        (True,  "idle"),
    "move":        (True,  "walk"),
    "thinking":    (True,  "thinking/working"),
    "inspect":     (True,  "thinking/inspect"),
    "sit":         (True,  "sit"),
    "lying":       (True,  "sleep"),
    "pick":        (True,  "busy/pick"),
    "victoryloop": (True,  "success_idle"),
    "victory":     (False, "success_intro"),
    "attack":      (False, "click_react"),
    "spine":       (False, "skill/thinking"),
    "die":         (False, "error/hurt"),
}

#: 文件名别名 -> 动作槽
ALIASES = {
    "idle": "wait", "stand": "wait", "default": "wait", "待机": "wait",
    "walk": "move", "run": "move", "走": "move", "走路": "move",
    "happy": "victory", "win": "victory", "celebrate": "victory", "庆祝": "victory",
    "think": "thinking", "working": "thinking", "思考": "thinking",
    "search": "inspect", "研究": "inspect",
    "click": "attack", "poke": "attack", "点击": "attack",
    "drag": "pick", "拖动": "pick",
    "sleep": "lying", "睡": "lying", "躺": "lying",
    "坐": "sit",
    "hurt": "die", "error": "die", "受伤": "die", "death": "die", "dead": "die", "死": "die",
    "skill": "spine",
}


# ----------------------------------------------------------------- 纯函数

def slot_for_filename(filename: str):
    """文件名 -> 动作槽名;认不出来返回 None。"""
    stem = Path(filename).stem.strip().lower()
    stem = re.sub(r"^\d+[-_. ]*", "", stem)        # 允许 "01_wait.gif" 这种排序前缀
    stem = re.sub(r"[-_. ]+", "", stem)
    if stem in SLOTS:
        return stem
    if stem in ALIASES:
        return ALIASES[stem]
    for alias, slot in ALIASES.items():            # 允许 "walk_loop" / "wait2"
        if stem.startswith(alias):
            return slot
    for slot in SLOTS:
        if stem.startswith(slot):
            return slot
    return None


def load_frames(path: Path):
    """读出 [(RGBA 图, 该帧时长毫秒), ...]。GIF/APNG/WebP 都走这里。"""
    out = []
    with Image.open(path) as im:
        n = getattr(im, "n_frames", 1)
        for i in range(n):
            im.seek(i)
            # 先转 RGBA 再 copy —— GIF 的局部更新帧由 Pillow 负责合成
            frame = im.convert("RGBA").copy()
            duration = im.info.get("duration") or 0
            out.append((frame, int(duration)))
    if not out:
        raise ValueError(f"{path.name}: 一帧都没读出来")
    return out


def load_frames_from_dir(folder: Path):
    """PNG 序列目录 -> [(图, 0), ...],时长按 0 处理(即按源 fps 等距)。"""
    files = sorted(p for p in folder.iterdir()
                   if p.suffix.lower() == ".png" and not p.name.startswith("."))
    if not files:
        raise ValueError(f"{folder.name}/ 里没有 PNG")
    return [(Image.open(p).convert("RGBA"), 0) for p in files]


def resample_to_fps(frames, target_fps: int = DEFAULT_FPS, source_fps: float | None = None):
    """按每帧时长把序列重采样到固定 fps。

    时长缺失或为 0 的(PNG 序列/坏 GIF)按 ``source_fps`` 等距处理,
    ``source_fps`` 也没给就认为本来就是 target_fps,原样返回。
    """
    if not frames:
        return []
    step_ms = 1000.0 / target_fps
    durations = [d for _img, d in frames]
    if not any(durations):
        if source_fps and abs(source_fps - target_fps) > 1e-6:
            per = 1000.0 / source_fps
            durations = [per] * len(frames)
        else:
            return [img for img, _d in frames]
    # 时长为 0 的帧(GIF 里常见)按 100ms 处理,和浏览器的做法一致
    durations = [d if d > 0 else 100 for d in durations]

    out, carry = [], 0.0
    for (img, _d), dur in zip(frames, durations):
        carry += dur
        count = int(round(carry / step_ms))
        if count < 1 and not out:
            count = 1                      # 再短也至少留一帧,别把动作吃没了
        carry -= count * step_ms
        out.extend([img] * count)
    return out or [frames[0][0]]


def has_alpha(images) -> bool:
    """序列里是否真的存在透明像素。"""
    for img in images:
        lo, hi = img.getchannel("A").getextrema()
        if lo < 255:
            return True
    return False


def key_out_background(img: Image.Image, tolerance: int = DEFAULT_KEY_TOLERANCE,
                       key_color=None):
    """把接近角落色的像素抠成透明。只在整段序列都没有 alpha 时才用。"""
    rgba = img.convert("RGBA")
    if key_color is None:
        key_color = rgba.getpixel((0, 0))[:3]
    kr, kg, kb = key_color
    px = rgba.load()
    w, h = rgba.size
    tol2 = tolerance * tolerance * 3
    for y in range(h):
        for x in range(w):
            r, g, b, a = px[x, y]
            if a and (r - kr) ** 2 + (g - kg) ** 2 + (b - kb) ** 2 <= tol2:
                px[x, y] = (r, g, b, 0)
    return rgba


def union_bbox(images):
    """整段序列的不透明区域并集包围盒;全透明返回 None。"""
    box = None
    for img in images:
        b = img.getchannel("A").getbbox()
        if b is None:
            continue
        box = b if box is None else (min(box[0], b[0]), min(box[1], b[1]),
                                     max(box[2], b[2]), max(box[3], b[3]))
    return box


def compute_anchor(images, foot_band: float = DEFAULT_FOOT_BAND):
    """算脚底锚点 ``[x, y]``(相对已裁剪的图)。

    y = 不透明区域底边。
    x = 底部一小条(默认 12% 高)里所有不透明像素的水平中心,逐帧取平均。
    用"脚那一条"而不是整体中心,是为了角色前倾/挥手时锚点不左右漂。
    """
    if not images:
        return [0.0, 0.0]
    w, h = images[0].size
    bottom = 0
    for img in images:
        b = img.getchannel("A").getbbox()
        if b:
            bottom = max(bottom, b[3])
    if bottom <= 0:
        return [w / 2.0, float(h)]
    band = max(1, int(round(h * foot_band)))
    y0 = max(0, bottom - band)

    centers = []
    for img in images:
        alpha = img.getchannel("A").crop((0, y0, w, bottom))
        b = alpha.getbbox()
        if b:
            centers.append((b[0] + b[2]) / 2.0)
    x = sum(centers) / len(centers) if centers else w / 2.0
    return [round(x, 1), round(float(bottom), 1)]


def fit_height(images, max_height: int):
    """整段等比缩放到不超过 max_height。"""
    if not images:
        return images
    w, h = images[0].size
    if h <= max_height:
        return images
    scale = max_height / h
    nw, nh = max(1, int(round(w * scale))), max(1, int(round(h * scale)))
    return [im.resize((nw, nh), Image.LANCZOS) for im in images]


def build_entry(slot: str, count: int, size, anchor, skin: str, loop=None):
    """一条 manifest 动画记录。"""
    default_loop, suggested = SLOTS.get(slot, (True, slot))
    return {
        "frames": count,
        "size": [int(size[0]), int(size[1])],
        "anchor": [float(anchor[0]), float(anchor[1])],
        "loop": bool(default_loop if loop is None else loop),
        "suggested_state": suggested,
        "frames_dir": f"{skin}/{slot}/",
    }


# --------------------------------------------------------------- 处理流程

def process_one(path: Path, slot: str, args, log=print):
    """一个 GIF/序列 -> (帧列表, manifest 记录用的 size/anchor)。"""
    frames = load_frames_from_dir(path) if path.is_dir() else load_frames(path)
    raw_n = len(frames)
    images = resample_to_fps(frames, args.fps, args.source_fps)

    if not has_alpha(images):
        if args.no_key:
            log(f"    ⚠️ {slot}: 整段没有透明通道,又指定了 --no-key,"
                f"背景会是一个实心方块")
        else:
            log(f"    · {slot}: 没有透明通道,按角落色抠背景(容差 {args.key_tolerance})")
            images = [key_out_background(im, args.key_tolerance) for im in images]

    box = union_bbox(images)
    if box is None:
        raise ValueError(f"{slot}: 抠完之后整段全透明,换个 --key-tolerance 试试")
    images = [im.crop(box) for im in images]
    images = fit_height(images, args.max_height)

    anchor = compute_anchor(images, args.foot_band)
    log(f"    {slot:12s} {raw_n:3d} 帧 -> {len(images):3d} 帧 @{args.fps}fps  "
        f"{images[0].size[0]}x{images[0].size[1]}  锚点 {anchor}")
    return images, anchor


def write_frames(images, out_dir: Path):
    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True)
    for i, im in enumerate(images):
        im.save(out_dir / f"frame_{i:04d}.png")


def merge_manifest(manifest_path: Path, skin: str, animations: dict,
                   display: str | None, fps: int):
    """把新皮肤并进 manifest,原有皮肤原样保留;原子写。"""
    if manifest_path.exists():
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
    else:
        data = {"fps": fps, "skins": {}}
    data.setdefault("fps", fps)
    skins = data.setdefault("skins", {})
    entry = {"animations": animations, "custom": True}
    if display:
        entry["display_name"] = display
    skins[skin] = entry
    tmp = manifest_path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(manifest_path)
    return data


def run_import(source, name, assets, display=None, *, fps=DEFAULT_FPS, source_fps=None,
               max_height=DEFAULT_MAX_HEIGHT, foot_band=DEFAULT_FOOT_BAND,
               key_tolerance=DEFAULT_KEY_TOLERANCE, no_key=False,
               force=True, dry_run=False, log=lambda *a: None):
    """编程接口(CLI 和 App 内 GUI 共用)。

    成功返回 ``{"skin", "animations", "unknown", "no_wait"}``;参数或内容有问题
    抛 ``ValueError``(带中文消息,可直接展示给用户)。
    """
    source, assets = Path(source), Path(assets)
    if not source.is_dir():
        raise ValueError(f"找不到目录: {source}")
    if not re.fullmatch(r"[A-Za-z0-9_-]+", str(name)):
        raise ValueError("皮肤 ID 只能用字母/数字/下划线/连字符")

    manifest_path = assets / "manifest.json"
    if not force and manifest_path.exists():
        existing = json.loads(manifest_path.read_text(encoding="utf-8"))
        if name in existing.get("skins", {}):
            raise ValueError(f"皮肤 {name} 已存在(force=False)")

    inputs, unknown = collect_inputs(source)
    if not inputs:
        raise ValueError("目录里没有能识别的动作文件,文件名请用 wait/move/victory…")
    no_wait = not any(slot == "wait" for _p, slot in inputs)

    opts = types.SimpleNamespace(
        fps=fps, source_fps=source_fps, max_height=max_height, foot_band=foot_band,
        key_tolerance=key_tolerance, no_key=no_key)
    animations = {}
    for path, slot in inputs:
        images, anchor = process_one(path, slot, opts, log=log)
        animations[slot] = build_entry(slot, len(images), images[0].size, anchor, name)
        if not dry_run:
            write_frames(images, assets / name / slot)
    if not dry_run:
        merge_manifest(manifest_path, name, animations, display or name, fps)
    return {"skin": name, "animations": animations, "unknown": unknown, "no_wait": no_wait}


def collect_inputs(src: Path):
    """扫目录,返回 [(路径, 动作槽)],并报告认不出来的文件。"""
    found, unknown = [], []
    for p in sorted(src.iterdir()):
        if p.name.startswith("."):
            continue
        if p.is_dir():
            slot = slot_for_filename(p.name)
            (found.append((p, slot)) if slot else unknown.append(p.name))
        elif p.suffix.lower() in SUPPORTED_SUFFIXES:
            slot = slot_for_filename(p.name)
            (found.append((p, slot)) if slot else unknown.append(p.name))
    # 同一个槽被多个文件命中时,只保留第一个
    seen, deduped = set(), []
    for path, slot in found:
        if slot in seen:
            unknown.append(f"{path.name}(槽 {slot} 已被占用,跳过)")
            continue
        seen.add(slot)
        deduped.append((path, slot))
    return deduped, unknown


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="把一堆动作 GIF 批量导入成一套新皮肤",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="文件名就是动作名,支持别名:\n  " +
               "  ".join(sorted(SLOTS)) + "\n别名:\n  " +
               "  ".join(f"{k}->{v}" for k, v in sorted(ALIASES.items())))
    ap.add_argument("source", type=Path, help="放着各动作 GIF 的目录")
    ap.add_argument("--name", required=True, help="皮肤 ID(文件夹名,建议用英文)")
    ap.add_argument("--display", help="菜单里显示的名字,默认同 --name")
    ap.add_argument("--assets", type=Path, default=EXTERNAL_SKINS_DIR,
                    help="写到哪个素材目录(默认 ~/.springfield_pet/skins,.app 能直接读;"
                         "想放进仓库供开发用 assets/pet_assets)")
    ap.add_argument("--fps", type=int, default=DEFAULT_FPS, help=f"目标帧率(默认 {DEFAULT_FPS})")
    ap.add_argument("--source-fps", type=float, default=None,
                    help="源帧率;GIF 自带时长时不用给,PNG 序列建议给")
    ap.add_argument("--max-height", type=int, default=DEFAULT_MAX_HEIGHT,
                    help=f"最大高度,超了等比缩(默认 {DEFAULT_MAX_HEIGHT})")
    ap.add_argument("--foot-band", type=float, default=DEFAULT_FOOT_BAND,
                    help=f"取底部多大比例当'脚'来定锚点 x(默认 {DEFAULT_FOOT_BAND})")
    ap.add_argument("--key-tolerance", type=int, default=DEFAULT_KEY_TOLERANCE,
                    help="无 alpha 时抠角落色的容差")
    ap.add_argument("--no-key", action="store_true", help="即使没有 alpha 也不抠背景")
    ap.add_argument("--force", action="store_true", help="允许覆盖同名皮肤")
    ap.add_argument("--dry-run", action="store_true", help="只分析不写文件")
    args = ap.parse_args(argv)

    # 先探测一遍,把认不出的文件报给用户(run_import 内部只沉默跳过)
    if args.source.is_dir():
        _found, unknown = collect_inputs(args.source)
        for n in unknown:
            print(f"跳过(认不出是哪个动作):{n}")

    print(f"\n导入皮肤 {args.name} -> {args.assets}")
    try:
        res = run_import(args.source, args.name, args.assets, args.display,
                         fps=args.fps, source_fps=args.source_fps, max_height=args.max_height,
                         foot_band=args.foot_band, key_tolerance=args.key_tolerance,
                         no_key=args.no_key, force=args.force, dry_run=args.dry_run, log=print)
    except ValueError as ex:
        ap.error(str(ex))

    if res["no_wait"]:
        print("⚠️  没有 wait(待机)动作 —— 建议补一个 wait.gif")
    if args.dry_run:
        print("\n--dry-run:没写任何文件。manifest 记录会是:")
        print(json.dumps({args.name: {"animations": res["animations"]}},
                         ensure_ascii=False, indent=2))
        return 0

    total = sum(a["frames"] for a in res["animations"].values())
    print(f"\n✅ 完成:{args.assets / args.name}  共 {total} 帧")
    print("   重启桌宠后在右键「👗 换衣服」里就能看到它了")
    return 0


if __name__ == "__main__":
    sys.exit(main())
