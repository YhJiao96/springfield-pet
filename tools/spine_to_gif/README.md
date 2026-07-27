# Spine 素材 → GIF / 桌宠皮肤

把 **Spine 骨骼动画素材**(`.skel`/`.json` + `.atlas` + `.png`)渲染成透明 GIF,
或直接变成一套春田桌宠皮肤。《少女前线》的 Q 版人形就是 Spine 格式。

> ⚠️ **素材需你自己提供**。本工具不含、也不下载任何游戏素材,渲染全程在本地进行,
> 不上传任何东西。请只对**你有权使用**的素材运行。

## 依赖(首次一次性)

```bash
pip install playwright Pillow
python3 -m playwright install chromium      # 下载无头 Chromium(~150MB)
```

`pixi.js` / `pixi-spine`(浏览器版 JS)会在首次运行时自动下载到
`~/.springfield_pet/spine_tools/`,不进仓库。

先自检依赖:

```bash
python3 tools/spine_to_gif/spine_to_gif.py --check .
```

## 用法

一套素材放一个目录(`.skel` 和 `.atlas` 通常同名):

```
M1903/
  M1903.skel      # 或 .json
  M1903.atlas
  M1903.png       # 图集(可能多张,atlas 里引用)
```

**导出每个动画一个 GIF**(默认写到 `素材目录/_gif_out/`):

```bash
python3 tools/spine_to_gif/spine_to_gif.py path/to/M1903
```

**直接变成桌宠皮肤**(渲染 + 导入一步到位):

```bash
python3 tools/spine_to_gif/spine_to_gif.py path/to/M1903 \
    --to-skin m1903 --display "春田 · 自渲染"
# 重启桌宠 → 右键「👗 换衣服 → 我导入的」
```

常用选项:

| 选项 | 说明 |
|---|---|
| `--only idle walk`  | 只渲这些动画 |
| `--fps 25`          | 目标帧率(默认 25) |
| `--height 280`      | 渲染目标高度 |
| `--frames`          | 另存 PNG 帧序列(保留完整透明,可喂给 `import_skin.py`) |
| `--out DIR`         | 指定输出目录 |
| `--to-skin ID`      | 渲染并导入成桌宠皮肤 |

## 它替你处理好的事

- **逐帧 seek + 固定帧率**:按 `--fps` 均匀采样动画时间轴,不受源动画时长影响。
- **统一画布 + 脚底锚点**:所有动画共用一个画布(以 setup-pose 包围盒为基准、
  四周留余量),渲染后按像素裁剪;`--to-skin` 时复用 `import_skin` 的脚底锚点逻辑,
  切换动作脚不跳。
- **透明背景**:pixi 透明画布渲染,导出带完整 alpha 的 PNG(GIF 因格式限制是 1bit
  透明,想要完整 alpha 用 `--frames`)。

## 动画名映射(--to-skin)

spine 动画名会映射到桌宠动作槽:`idle→wait`、`walk/run→move`、`死/death→die` 等
(见 `tools/import_skin.py --help` 的完整别名表)。**桌宠没有对应动作的动画会被
跳过**(但 GIF 输出仍是全部动画)——那些可以先导出 GIF,再用
`import_skin.py` 按 `wait/move/victory…` 命名手动导入。

## 已知范围

- 目前一次处理**一套**素材(一个角色一套皮肤);批量遍历整个素材库是下一步。
- 渲染质量取决于 `pixi-spine` 对该 Spine 版本的支持(已验证 Spine 3.8 二进制 `.skel`;
  pixi-spine 4.x 同时支持 3.8 / 4.0 / 4.1)。
