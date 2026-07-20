# 🎀 Springfield Pet · 春田桌宠

一只陪你写代码的桌面宠物 —— 以《少女前线》春田 (M1903) 的 Q 版形象为基础，
基于 **PySide6** 的跨平台桌面伴侣，并能**联动 Claude Code / Codex 的运行状态**。

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

## ✨ 功能

- **动画桌宠**：待机 / 走动 / 卖萌 / 坐躺休息，透明背景、始终置顶、按脚底锚点渲染不跳。
- **5 套衣服**：默认水手服 / 女巫装 / 红斗篷 / 蓝礼服 / 泳装，每套含「战斗 + 休息」两套动作；支持定时自动换装。
- **交互**：拖动、单击摸摸、**双击弹出头顶输入框**给 Claude 发指令、右键全功能菜单、悬浮显示状态栏。
- **Claude Code 状态联动**：Claude 开工 → 举放大镜盯着；需要确认 → 警戒+通知；跑完 → 庆祝并**持续提醒直到你理会**。
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

## 🔗 联动 Claude Code 状态

在 `~/.claude/settings.json` 加入 hooks，让 Claude 各事件把状态写进一个文件，桌宠监听并反应：

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

> hooks 在**会话启动时加载**，改完需**新开一个 Claude Code 会话**才生效。

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
│   └── companion.py          # 伴侣功能 + Claude 联动 + 播放器
├── assets/pet_assets/        # 透明帧序列 + manifest.json
├── build/                    # 图标 + PyInstaller 配置 + 打包脚本
└── docs/
```

## 📜 许可

- **源代码**：[MIT](LICENSE)
- **角色美术素材**：版权归《少女前线》/ 散爆网络，仅供学习非商业使用，见 [ASSETS_NOTICE.md](ASSETS_NOTICE.md)。
