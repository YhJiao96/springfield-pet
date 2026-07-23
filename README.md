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
  <img src="docs/demo_skins.gif" width="680" alt="默认 / 女巫 / 红斗篷 / 礼服 / 泳装">
</p>

## ✨ 功能

- **动画桌宠**：待机 / 走动 / 卖萌 / 坐躺休息，透明背景、始终置顶、按脚底锚点渲染不跳。
- **5 套衣服**：默认水手服 / 女巫装 / 红斗篷 / 蓝礼服 / 泳装，每套含「战斗 + 休息」两套动作；支持定时自动换装。
- **交互**：拖动、单击摸摸、**双击弹出头顶输入框**发指令(可选发给 Claude / Codex)、右键全功能菜单、悬浮显示状态栏、大小 75–150%。
- **Claude / Codex 状态联动**：**可同时监控两个 AI**,头顶各一个带图标的对话框(🟠Claude 橙花 / ⚫Codex 黑圆六角星),显示「项目名 · 当前活动」+ 转圈；开工→举放大镜研究,需要授权/确认 & 跑完 → **持续提醒直到你理会**。右上角玻璃标签一键收起/展开。
  Codex 走**官方 lifecycle hooks**,是**实时**的:提交任务、调用工具、等你批准、本轮结束都会立刻反映;**多个 Codex 会话同时跑也不会互相覆盖**,等你批准的那个会被优先顶到前面。
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
│   ├── pet.py                # 动画引擎(加载/渲染/拖动)
│   ├── companion.py          # 伴侣功能 + Claude/Codex 联动 + 播放器
│   └── codex_status.py       # Codex hooks 协议/多会话聚合/hooks.json 合并(纯标准库)
├── tests/                    # python3 -m unittest discover -s tests -v
├── assets/pet_assets/        # 透明帧序列 + manifest.json
├── build/                    # 图标 + PyInstaller 配置 + 打包脚本
└── docs/
```

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
