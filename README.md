# 🎀 Springfield Pet · 春田桌宠

一只陪你写代码的桌面宠物 —— 以《少女前线》春田 (M1903) 的 Q 版形象为基础，
基于 **PySide6** 的跨平台桌面伴侣，能**同时联动 Claude Code 与 Codex 的运行状态**，
在头顶显示各自的「项目名 · 当前活动」对话框。

<p align="center">
  <img src="docs/icon-candidates/ic_pixel_mild.png" width="140" alt="Springfield Pet icon">
</p>

---

> ## ⚠️ 素材版权声明 / Asset Copyright Notice
>
> **本作所使用的像素小人素材及角色形象（春田 / Springfield / M1903）版权，均归
> 上海散爆网络科技有限公司 / 云母组（MICA Team / SUNBORN Network）所有。**
>
> - 这些素材**仅供个人学习、研究与非商业用途**，本项目不主张任何版权、不用于任何商业目的。
> - 素材来源：从《少女前线》游戏客户端解包出的 Spine 骨骼资源，经渲染为透明帧序列。
>   建议有条件的使用者**自行从游戏客户端提取**对应素材。
> - **若版权方（散爆网络 / 云母组）提出要求，本项目将立即删除全部相关素材。**
>
> The chibi character art of *Springfield / M1903* used here is copyright of
> **SUNBORN Network / MICA Team** (*Girls' Frontline*), provided for personal,
> non-commercial study only. Assets were extracted from the game client's Spine
> resources. **They will be removed immediately upon the rights holder's request.**
> See [`ASSETS_NOTICE.md`](ASSETS_NOTICE.md). The source code is under the MIT license.

---

## 🎬 预览

<p align="center">
  <img src="docs/demo_hero.gif" width="230" alt="待机 / 走动 / 庆祝">
</p>

**5 套换装**（每套含战斗+休息动作，可定时自动切换）：

<p align="center">
  <img src="docs/demo_skins.gif" width="680" alt="制服 / 万圣节 / 圣诞节 / 晚礼服 / 泳装">
</p>

## ✨ 功能

- **动画桌宠**：待机 / 走动 / 卖萌 / 坐躺休息，透明背景、始终置顶、按脚底锚点渲染不跳。
- **5 套官方皮肤**：制服(默认) / 万圣节「古典派女巫」/ 圣诞节「圣善夜的祝福」/ 晚礼服「灯火下的女王」/ 泳装「睡醒的人鱼」，每套含「战斗 + 休息」两套动作；支持定时自动换装。
- **交互**：拖动、单击摸摸、**双击弹出头顶输入框**发指令(可选发给 Claude / Codex)、右键全功能菜单、悬浮显示状态栏、大小 75–150%。
- **Claude / Codex 状态联动**：**可同时监控两个 AI**,头顶各一个带图标的对话框(🟠Claude 橙花 / ⚫Codex 黑圆六角星),显示「项目名 · 当前活动」+ 转圈；开工→举放大镜研究,需要授权/确认 & 跑完 → **持续提醒直到你理会**。右上角玻璃标签一键收起/展开。
  Codex 走**官方 lifecycle hooks**,是**实时**的:提交任务、调用工具、等你批准、本轮结束都会立刻反映;**多个 Codex 会话同时跑也不会互相覆盖**,等你批准的那个会被优先顶到前面。
- **换成你自己的角色**：把动作 GIF 拖进去，或把 **Spine 骨骼素材**（少前 Q 版人形即此格式）本地渲染，一步做成新桌宠；App 内右键即可导入，下载打包版的人也能用。见 [制作你自己的桌宠角色](#-制作你自己的桌宠角色)。
- **OpenPets 风格小工具**：番茄钟专注计时、喝水提醒、自定义提醒、情绪记录、石头剪刀布、快捷启动、虚拟属性(心情/饱食/精力/等级)。
- **迷你音乐播放器**：选文件夹播放，进度/上一首/下一首/播放暂停/循环模式，可拖动悬浮窗。

## 🚀 运行

### 方式一：直接下载打包版（推荐）

到 [Releases](../../releases) 下载对应平台的包：

- **macOS**：`SpringfieldPet.app`，首次运行如被拦截：
  ```bash
  xattr -dr com.apple.quarantine SpringfieldPet.app
  ```
- **Windows**：`SpringfieldPet.exe`，双击即可。

### 方式二：从源码运行

```bash
pip install -r requirements.txt
python run.py
```

## 🔗 联动 Claude Code / Codex 状态

<p align="center">
  <img src="docs/demo_magnifier.gif" width="200" alt="工作时举放大镜研究">
  <br><sub>AI 工作时，春田会举起放大镜「研究」</sub>
</p>

让桌宠跟随 AI 的运行状态自动反应,并在头顶显示「项目名 · 当前活动」。
**Claude Code 与 Codex 可同时接入**(不是二选一),接入哪个就显示哪个对话框。
**装好 App 后照下面做一次即可,之后全自动。**

### 方式一:一键接入(推荐,零配置)

右键 → **「🔗 状态联动(可多选)」** → 勾选 Claude Code 和/或 **Codex 实时状态 Hooks**:

- **Claude Code**:自动把 hooks 合并进 `~/.claude/settings.json`(备份、不覆盖已有配置)。
  经助手脚本解析事件,可显示细粒度活动(读取/搜索/运行 X…)、需要授权、以及完成时的**结论开头**。
- **Codex 实时状态 Hooks**:自动把六个 [lifecycle hooks](https://learn.chatgpt.com/docs/hooks)
  合并进 `~/.codex/hooks.json`(带时间戳备份 + **完整保留其他软件已装的 hook**)。

再点一次即「断开」,只摘掉本项目写入的 handler,别人的配置原样不动。

#### Codex 能实时看到什么

| 时机 | 春田的反应 | 头顶显示 |
|---|---|---|
| 新会话就绪 (`SessionStart`) | 待命 | `Codex 会话已就绪` · |
| 你提交了任务 (`UserPromptSubmit`) | 举放大镜研究 | `正在理解新任务` ⠋ |
| 正在调工具 (`PreToolUse`) | 举放大镜研究 | `正在运行命令 / 修改文件 / 读取文件…` ⠋ |
| 工具跑完 (`PostToolUse`) | 举放大镜研究 | `已完成:修改文件` ⠋ |
| **等你批准** (`PermissionRequest`) | 停下来等 + **持续提醒** | `等待批准:运行命令` 👀 |
| 本轮结束 (`Stop`) | 庆祝一次 + 提醒 | `本轮任务已完成` ✅(显示 15 秒) |

**多会话**:同时开几个 Codex 任务时,等你批准的那个优先展示,其次是正在干活的,
再次是刚跑完的。某个会话的 Codex 意外退出后,它的「工作中」30 分钟后自动作废,
春田不会一直傻转圈。

> ⚠️ **首次接入后必须新开一个 Codex 会话**,并在会话里执行 `/hooks`
> **审查并信任 SpringfieldPet Hooks** —— 未信任的 hook 不会被执行。

#### 隐私

状态只存在**你自己的电脑上**:`~/.springfield_pet/codex_sessions/<session>.json`,
每个会话一个文件。里面**只有**会话 id、项目文件夹名、模型名、工具名和一句
不超过 100 字的中文活动描述。

**不会**写入你的 prompt、完整命令、工具输出、环境变量或任何密钥,也不联网。
断开联动时这些文件会**保留**(方便排查),想清掉直接 `rm -rf ~/.springfield_pet/codex_sessions`。

#### 兼容旧版 notify

早期版本通过 `~/.codex/config.toml` 的 `notify` 接入,只能在**回合结束**时知道「跑完了」。
现在仍兼容:只要还没有任何 hooks 状态文件,春田就退回读旧的 `codex_state`;
一旦 hooks 开始工作,旧文件就被**完全忽略**,不会重复庆祝。
关闭联动时,如果 `notify` 正是本项目装的那个包装脚本,会一并还原你原来的 notify
(比如 Computer Use);不是本项目装的则原样不动。

### 方式二：手动配置

若想自己改，或在 Windows 上，把下面的 hooks 加进 `~/.claude/settings.json`：

```json
{
  "hooks": {
    "UserPromptSubmit": [{ "hooks": [{ "type": "command", "command": "mkdir -p ~/.springfield_pet && echo working > ~/.springfield_pet/claude_state" }] }],
    "PreToolUse":       [{ "matcher": "*", "hooks": [{ "type": "command", "command": "mkdir -p ~/.springfield_pet && echo working > ~/.springfield_pet/claude_state" }] }],
    "Notification":     [{ "hooks": [{ "type": "command", "command": "mkdir -p ~/.springfield_pet && echo waiting > ~/.springfield_pet/claude_state" }] }],
    "Stop":             [{ "hooks": [{ "type": "command", "command": "mkdir -p ~/.springfield_pet && echo done > ~/.springfield_pet/claude_state" }] }],
    "SessionStart":     [{ "hooks": [{ "type": "command", "command": "mkdir -p ~/.springfield_pet && echo idle > ~/.springfield_pet/claude_state" }] }]
  }
}
```

> ⚠️ **无论哪种方式**，hooks 都在 **Claude Code 会话启动时加载**，所以配置后需**新开一个 Claude Code 会话**才生效（旧会话不受影响）。之后你正常用 Claude，桌宠就会自动跟随状态，**无需再手动运行任何东西**。
> Codex 同理：改完 `~/.codex/hooks.json` 要**新开 Codex 会话**并在 `/hooks` 里信任它。

## 🔔 系统通知：点一下唤起对应窗口

macOS 上用 `osascript` 发的通知会被系统算在**「脚本编辑器」**头上——点通知就弹出
脚本编辑器和选文件窗口，很烦。现在通知会**挂在它该属于的 App 名下**：

| 通知 | 图标 | 点一下 |
|---|---|---|
| Claude 需要授权 / 跑完了 | 你设的终端 App | 唤起 Terminal / iTerm2 / VS Code |
| Codex 需要批准 / 跑完了 / 出错了 | Codex | 唤起 Codex 窗口 |
| 喝水 / 提醒 / 专注 / 升级 | 春田自己（仅打包版） | 只是关掉通知 |

嫌吵就右键 → **⚙️ 设置 → 「🔔 系统通知」** 取消勾选，只保留头顶气泡。

> 归属失败（App 没装、没给自动化权限）会自动退回普通通知，**不会因此收不到提醒**。
> 从源码跑的裸 Python 进程没有 App bundle，非 AI 类通知仍归「脚本编辑器」——
> 想要完整体验请用打包好的 `.app`。

## 🎨 制作你自己的桌宠角色

想换成别的角色？看你手上的素材是什么形态，走下面两条路之一。做好的皮肤存在
**`~/.springfield_pet/skins/`**，打包好的 `.app` 启动时会自动扫描，所以**下载 App
的人也能造自己的角色，不用碰源码**。内置素材是只读的，你的导入永远不会覆盖它。

> ⚠️ 请只使用**你有权使用**的素材。角色美术版权归各自权利人；本项目工具不含、
> 也不下载任何游戏素材，一切在你本机进行。若用少前素材，请遵守
> [素材版权声明](#️-素材版权声明--asset-copyright-notice)（个人学习、非商业）。

### 路线 A：手上是动图 / 序列帧 —— 直接导入

一套动作 = 一个文件，**文件名就是动作名**，丢进一个文件夹即可：

```
my_gifs/
  wait.gif        待机（必需）
  walk.gif        走路
  happy.gif       庆祝
  think.gif       思考
  …
```

- **App 里导入（推荐，零命令行）**：右键 → **「👗 换衣服 → 🎨 导入皮肤…」**，
  选文件夹、起名字，几秒就换上了。删除在「👗 换衣服 → 🗑 删除导入的皮肤」。
- **命令行**：`python3 tools/import_skin.py my_gifs --name mychar --display "我的角色"`

支持 **GIF / APNG / 透明 WebP / PNG 序列目录**。它替你处理好三件容易翻车的事：
帧率对齐（按每帧时长重采样到 25fps）、脚底锚点（切换动作脚不跳）、自动裁边 + 抠背景。
`--dry-run` 先看分析不写文件；完整选项见 `--help`。

### 路线 B：手上是 Spine 骨骼素材 —— 先渲染再导入

少前的 Q 版人形、以及很多游戏/[Spine](https://esotericsoftware.com) 项目的素材，是
**骨骼动画**格式：一套三件套 `骨骼(.skel 或 .json) + 图集描述(.atlas) + 图集图(.png)`。
`tools/spine_to_gif/` 把它在本地渲染成帧，一步做成桌宠：

```bash
# 一次性装依赖(约 150MB Chromium)
pip install playwright Pillow
python3 -m playwright install chromium

# 渲染 + 导入成桌宠皮肤,一步到位
python3 tools/spine_to_gif/spine_to_gif.py 素材目录 --to-skin mychar --display "我的角色"
```

跑完重启桌宠，右键「👗 换衣服 → 我导入的」就能选它。也可以只导出 GIF（不加
`--to-skin`，默认写到 `素材目录/_gif_out/`）留着预览或走路线 A。

**用少前 Spine 素材的完整步骤**：

1. 从你的来源拿到某个角色某套皮肤的 Spine 三件套（少前资料库 / Spine 查看类站点
   通常能导出 `.skel`+`.atlas`+`.png`），放进**同一个文件夹**，
   `.skel` 和 `.atlas` **建议同名**（如 `M1903.skel` / `M1903.atlas`）。
2. `python3 tools/spine_to_gif/spine_to_gif.py 那个文件夹 --to-skin m1903 --display "春田"`
3. 工具会自动识别所有动画、逐帧渲染、映射到桌宠动作、算好脚底锚点。
   认不出对应动作的动画会跳过（但 GIF 输出仍是全部）。
4. 重启桌宠 → 换衣服里选它。

细节（帧率、锚点余量、动画名映射、只渲某几个动画等）见
[`tools/spine_to_gif/README.md`](tools/spine_to_gif/README.md)。

### 动作名对照表

文件名 / Spine 动画名会映射到这些**桌宠动作槽**。至少给一个 `wait`；缺的动作会自动
回退到相近的（比如没有 `inspect` 就用 `thinking`）。

| 动作槽 | 可用的文件名 / 别名 | 桌宠什么时候播 |
|---|---|---|
| `wait`     | idle / 待机（**必需**） | 平时待机 |
| `move`     | walk / run / 走路 | 在屏幕上走动 |
| `victory`  | happy / celebrate / 庆祝 | AI 跑完、升级、被喂食 |
| `thinking` | think / working / 思考 | 思考 / 工作中 |
| `inspect`  | search / 研究 | AI 工作时「举放大镜研究」 |
| `spine`    | skill | 需要你确认 / 授权时的等待姿势 |
| `attack`   | click / poke / 点击 | 被单击时的反应 |
| `pick`     | drag / 拖动 | 被鼠标拎起拖动时 |
| `sit` `lying` | sit / 坐、sleep / 睡 / 躺 | 精力低时休息 |
| `die`      | death / hurt / error / 受伤 / 死 | AI 报错 / 失败 |

> 开发者想把皮肤放进仓库随包发布，给 `import_skin.py` 或 `spine_to_gif.py`
> 加 `--assets assets/pet_assets` 即可（默认写用户目录，不进仓库）。

## ⌨️ 把指令键入当前终端（macOS）

「双击 → 输入 prompt」默认会把内容**粘贴进你当前的终端会话**并回车。这需要给应用授权：
**系统设置 › 隐私与安全性 › 辅助功能** 中勾选 `SpringfieldPet`。
（用源码运行的裸 Python 进程往往拿不到该权限，所以推荐用打包好的 `.app`。）
右键菜单 `⚙️ 设置 › 终端应用` 可切换 Terminal / iTerm2 / VS Code。

## 🛠 自行打包

```bash
# macOS -> SpringfieldPet.app
bash build/build_macos.sh

# Windows -> SpringfieldPet.exe
build\build_windows.bat
```

依赖 PyInstaller，图标见 `build/icon.icns` / `build/icon.ico`。

## 📁 结构

```
springfield-pet/
├── run.py                    # 入口
├── src/
│   ├── pet.py                # 动画引擎(加载/渲染/拖动;扫描用户导入的皮肤)
│   ├── companion.py          # 伴侣功能 + Claude/Codex 联动 + 播放器 + 换装/导入
│   ├── codex_status.py       # Codex hooks 协议/多会话聚合/hooks.json 合并(纯标准库)
│   └── import_skin.py        # GIF/序列帧 -> 桌宠皮肤(帧率对齐 + 脚底锚点)
├── tools/
│   ├── import_skin.py        # 上面的命令行入口
│   └── spine_to_gif/         # Spine 骨骼素材 -> GIF/皮肤(pixi-spine + Chromium)
├── tests/                    # python3 -m unittest discover -s tests -v
├── assets/pet_assets/        # 透明帧序列 + manifest.json(内置 10 套)
├── build/                    # 图标 + PyInstaller 配置 + 打包脚本
└── docs/
```

用户导入的皮肤放在 `~/.springfield_pet/skins/`（不进仓库，`.app` 启动时扫描）。

## 🧪 测试

```bash
python3 -m unittest discover -s tests -v
python3 -m py_compile src/*.py
```

测试全部走 `tempfile`，**不会**碰你真实的 `~/.codex` 或 `~/.springfield_pet`，
也不弹通知、不开窗口。

## 📜 许可

- **源代码**：[MIT](LICENSE)
- **角色美术素材**：版权归《少女前线》/ 散爆网络，仅供学习非商业使用，见 [ASSETS_NOTICE.md](ASSETS_NOTICE.md)。
