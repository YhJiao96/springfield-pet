#!/usr/bin/env python3
"""Codex 实时状态:lifecycle hooks 协议 + 多会话聚合 + hooks.json 合并。

本模块只用标准库,不 import Qt,便于单元测试。分三块:

1. ``CODEX_HOOK_HELPER_SRC``
   自包含的 Hook helper 源码,由桌宠部署到 ``~/.springfield_pet/codex_hook.py``。
   Codex 每次触发 lifecycle hook 时调用它,它从 stdin 读事件 JSON,
   原子写入 ``~/.springfield_pet/codex_sessions/<session>.json``。
   (以字符串内嵌是为了让 PyInstaller 打包后的 .app 也能部署出这个脚本;
   测试用 :func:`load_helper_module` 把它 exec 出来直接测真实逻辑。)

2. 聚合:``select_codex_session()`` — 扫描 session 目录,按优先级挑一个展示。

3. 配置合并:``merge_hook_handlers()`` / ``remove_hook_handlers()`` —
   幂等地把本项目的 handler 并进/摘出 ``~/.codex/hooks.json``,保留他人配置。
"""
from __future__ import annotations

import json
import os
import tempfile
import types
from pathlib import Path

# ---------------------------------------------------------------- 协议常量

SCHEMA_VERSION = 2

#: 用到的 Codex lifecycle 事件
HOOK_EVENTS = (
    "SessionStart",
    "UserPromptSubmit",
    "PreToolUse",
    "PostToolUse",
    "PermissionRequest",
    "Stop",
)

#: handler 命令里包含这个片段 = 本项目装的
HOOK_TAG = ".springfield_pet/codex_hook.py"

HOOK_TIMEOUT = 5
HOOK_STATUS_MESSAGE = "Updating SpringfieldPet"

WORKING_STALE_SEC = 30 * 60     # working 超过 30 分钟没更新 -> 视为 idle
TERMINAL_SHOW_SEC = 15          # done/failed 横幅展示时长
MAX_AGE_SEC = 24 * 3600         # 超过 24 小时的 session 文件直接忽略
FUTURE_SKEW_SEC = 60            # updated_at 超前 60 秒以上视为异常

_RANK = {"waiting": 3, "working": 2, "done": 1, "failed": 1, "idle": 0}


# ------------------------------------------------------------ Hook helper

CODEX_HOOK_HELPER_SRC = r'''#!/usr/bin/env python3
"""SpringfieldPet · Codex lifecycle hook helper(自动生成,请勿手改)。

从 stdin 读 hook 事件 JSON,原子写入单个 session 的状态文件。
只用标准库、不联网、不写 stdout,失败也只记日志并 exit 0,绝不打扰 Codex。
永远不写入 prompt / 完整命令 / 工具输出 / 环境变量 / 密钥。
"""
import json
import os
import re
import sys
import tempfile
import time

SCHEMA_VERSION = 2
MAX_ACTIVITY = 100


def state_dir():
    # 允许注入,便于测试;正常情况下就是 ~/.springfield_pet
    return os.environ.get("SPRINGFIELD_PET_DIR") or os.path.join(
        os.path.expanduser("~"), ".springfield_pet")


def session_dir():
    return os.path.join(state_dir(), "codex_sessions")


def log_error(msg):
    try:
        p = os.path.join(state_dir(), "codex_hook_errors.log")
        os.makedirs(os.path.dirname(p), exist_ok=True)
        if os.path.exists(p) and os.path.getsize(p) > 256 * 1024:
            os.remove(p)
        with open(p, "a", encoding="utf-8") as f:
            f.write("%.0f %s\n" % (time.time(), str(msg)[:500]))
    except Exception:
        pass


def safe_session_id(sid):
    """把 session_id 变成安全文件名:挡掉 / \\ .. 和其他危险字符。"""
    s = re.sub(r"[^A-Za-z0-9_.-]", "_", str(sid or ""))
    s = s.lstrip(".")           # "." / ".." / 隐藏文件都变成空
    s = s[:120]
    return s or "session"


def clean(text, limit=MAX_ACTIVITY):
    """去掉换行/控制字符并截断,保证长度不超过 limit。"""
    s = "".join(c if (c >= " " and c != "\x7f") else " " for c in str(text or ""))
    s = " ".join(s.split())
    if len(s) > limit:
        s = s[:max(1, limit - 1)] + "…"
    return s


def tool_name(data):
    """容错地取工具名:字段名随版本变化,取不到就返回空。"""
    for key in ("tool_name", "tool", "name"):
        v = data.get(key)
        if isinstance(v, str) and v.strip():
            return v.strip()
        if isinstance(v, dict):
            for k2 in ("name", "tool_name"):
                v2 = v.get(k2)
                if isinstance(v2, str) and v2.strip():
                    return v2.strip()
    return ""


# (工具名小写候选, 安全的中文动作短语) —— 只看名字,绝不看参数
TOOL_ACTIONS = (
    (("bash", "exec_command", "shell", "run_command", "local_shell"), "运行命令"),
    (("apply_patch", "edit", "write", "str_replace", "notebookedit",
      "create_file", "multiedit"), "修改文件"),
    (("read_file", "read", "view", "cat", "view_image"), "读取文件"),
    (("websearch", "web_search", "browser_search", "search"), "搜索资料"),
    (("update_plan", "todowrite"), "更新计划"),
    (("agent", "spawn_agent", "task", "subagent"), "协调子任务"),
)


def tool_action(name):
    """由工具名生成一段安全、简短的动作描述(名词短语)。"""
    low = str(name or "").strip().lower()
    if not low:
        return "使用工具"
    if low.startswith("mcp__") or low.startswith("mcp."):
        return "使用外部工具"
    for keys, action in TOOL_ACTIONS:
        if low in keys:
            return action
    return "使用 " + clean(name, 24)


def map_event(event, data):
    """事件 -> (state, activity)。未知事件返回 (None, None) 表示忽略。"""
    if event == "SessionStart":
        return "idle", "Codex 会话已就绪"
    if event == "UserPromptSubmit":
        return "working", "正在理解新任务"
    if event == "PreToolUse":
        return "working", "正在" + tool_action(tool_name(data))
    if event == "PostToolUse":
        return "working", "已完成:" + tool_action(tool_name(data))
    if event == "PermissionRequest":
        return "waiting", "等待批准:" + tool_action(tool_name(data))
    if event == "Stop":
        return "done", "本轮任务已完成"
    return None, None


def read_prev(path):
    try:
        with open(path, encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}          # 文件损坏/不存在 -> 从头开始,不报错


def next_sequence(prev):
    try:
        n = int(prev.get("sequence", 0))
    except Exception:
        n = 0
    return n + 1 if n >= 0 else 1


def atomic_write_json(path, payload):
    """同目录临时文件 + fsync + os.replace,读者永远看不到半截文件。"""
    d = os.path.dirname(path) or "."
    os.makedirs(d, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=d, prefix=".codex-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except Exception:
            pass
        raise


def build_record(event, data, prev):
    state, activity = map_event(event, data)
    if state is None:
        return None
    cwd = data.get("cwd") or ""
    if not isinstance(cwd, str):
        cwd = ""
    project = os.path.basename(cwd.rstrip("/\\")) or "Codex"
    return {
        "schema_version": SCHEMA_VERSION,
        "source": "codex-hooks",
        "session_id": clean(data.get("session_id") or "", 80),
        "turn_id": clean(data.get("turn_id") or "", 80),
        "state": state,
        "event": event,
        "project": clean(project, 40),
        "cwd": cwd[:300],
        "model": clean(data.get("model") or "", 40),
        "tool_name": clean(tool_name(data), 40),
        "activity": clean(activity, MAX_ACTIVITY),
        "updated_at": time.time(),
        "sequence": next_sequence(prev),
    }


def main(argv=None, stream=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    try:
        raw = (sys.stdin if stream is None else stream).read()
    except Exception:
        raw = ""
    try:
        data = json.loads(raw) if str(raw).strip() else {}
    except Exception:
        data = {}
    if not isinstance(data, dict):
        data = {}
    # 优先用 stdin 里的事件名;取不到就退回命令行参数
    event = str(data.get("hook_event_name") or (argv[0] if argv else "") or "").strip()
    try:
        path = os.path.join(session_dir(),
                            safe_session_id(data.get("session_id")) + ".json")
        rec = build_record(event, data, read_prev(path))
        if rec is not None:            # 未知事件 -> 什么都不写,保持旧状态
            atomic_write_json(path, rec)
    except Exception as ex:
        log_error("%s: %s" % (event, ex))
    return 0


if __name__ == "__main__":
    sys.exit(main())
'''


def load_helper_module(name: str = "springfield_codex_hook") -> types.ModuleType:
    """把内嵌的 helper 源码 exec 成模块 —— 测试用它直接测真实部署的代码。"""
    mod = types.ModuleType(name)
    mod.__file__ = "<CODEX_HOOK_HELPER_SRC>"
    exec(compile(CODEX_HOOK_HELPER_SRC, mod.__file__, "exec"), mod.__dict__)
    return mod


# --------------------------------------------------------------- 多会话聚合

def _num(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def read_session_record(path, now: float):
    """读一个 session JSON;不合法/过期返回 None(绝不抛异常)。"""
    try:
        with open(path, encoding="utf-8") as f:
            rec = json.load(f)
    except Exception:
        return None
    if not isinstance(rec, dict):
        return None
    if rec.get("schema_version") != SCHEMA_VERSION:
        return None
    updated = _num(rec.get("updated_at"), -1.0)
    if updated < 0:
        return None
    if updated > now + FUTURE_SKEW_SEC:     # 时钟异常的文件
        return None
    if now - updated > MAX_AGE_SEC:         # 24 小时前的残留
        return None
    return rec


def effective_state(rec, now: float) -> str:
    """把记录里的原始 state 按超时规则折算成当前该显示的状态。"""
    state = rec.get("state")
    age = now - _num(rec.get("updated_at"), now)
    if state == "waiting":
        return "waiting"                    # 等待授权不会因为 15 秒就消失
    if state == "working":
        # Codex App 异常退出后不该让桌宠永远在"工作"
        return "working" if age <= WORKING_STALE_SEC else "idle"
    if state in ("done", "failed"):
        return state if age <= TERMINAL_SHOW_SEC else "idle"
    return "idle"


def iter_session_records(session_dir, now: float):
    """扫描目录下所有有效 session,附加 ``effective_state``。"""
    out = []
    try:
        entries = sorted(Path(session_dir).glob("*.json"))
    except Exception:
        return out
    for path in entries:
        rec = read_session_record(path, now)
        if rec is None:
            continue                        # 损坏的文件不影响其他 session
        rec = dict(rec)
        rec["effective_state"] = effective_state(rec, now)
        rec["path"] = str(path)
        out.append(rec)
    return out


def select_codex_session(session_dir, now: float):
    """挑出该展示的那个 session:waiting > working > 新鲜 done/failed > idle。"""
    records = iter_session_records(session_dir, now)
    if not records:
        return None
    return max(records, key=lambda r: (_RANK.get(r["effective_state"], 0),
                                       _num(r.get("updated_at"))))


def display_activity(rec) -> str:
    """横幅该显示的活动文案。

    状态已经超时的记录(done 展示满 15 秒、working 陈旧超过 30 分钟)不该
    继续挂着旧文案 —— 此时回到空文案,由调用方显示"待命中"。
    """
    if not rec:
        return ""
    if rec.get("effective_state") != rec.get("state"):
        return ""
    return rec.get("activity") or ""


def session_change_key(rec):
    """(session_id, sequence, effective_state) —— 用来判断"真的变了"。"""
    if not rec:
        return None
    return (rec.get("session_id", ""), rec.get("sequence", 0),
            rec.get("effective_state", "idle"))


# ------------------------------------------------------- hooks.json 读写合并

def read_json_file(path):
    """读 JSON 配置。文件不存在返回 {};内容非法抛 ValueError(调用方须中止)。"""
    p = Path(path)
    if not p.exists():
        return {}
    text = p.read_text(encoding="utf-8")
    if not text.strip():
        return {}
    data = json.loads(text)                 # 非法 JSON -> JSONDecodeError(ValueError)
    if not isinstance(data, dict):
        raise ValueError("hooks 配置顶层必须是 JSON 对象")
    return data


def atomic_write_json(path, payload):
    """同目录临时文件 + fsync + os.replace。"""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(p.parent), prefix=".springfieldpet-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, str(p))
    except Exception:
        try:
            os.unlink(tmp)
        except Exception:
            pass
        raise


def _hooks_dict(cfg):
    hooks = cfg.setdefault("hooks", {})
    if not isinstance(hooks, dict):
        raise ValueError('hooks 配置里的 "hooks" 必须是对象')
    return hooks


def _group_has_tag(group, tag):
    if not isinstance(group, dict):
        return False
    return any(isinstance(h, dict) and tag in str(h.get("command", ""))
               for h in (group.get("hooks") or []))


def hooks_config_has_helper(cfg, tag: str = HOOK_TAG) -> bool:
    """配置里是否已经有本项目的 handler。"""
    if not isinstance(cfg, dict):
        return False
    hooks = cfg.get("hooks")
    if not isinstance(hooks, dict):
        return False
    for entries in hooks.values():
        if isinstance(entries, list) and any(_group_has_tag(g, tag) for g in entries):
            return True
    return False


def merge_hook_handlers(cfg, command_for_event, events=HOOK_EVENTS, tag: str = HOOK_TAG,
                        timeout: int = HOOK_TIMEOUT,
                        status_message: str = HOOK_STATUS_MESSAGE) -> int:
    """把本项目 handler 幂等地并进 cfg(原地修改),返回新增数量。

    ``command_for_event`` 可以是字符串,也可以是 ``event -> command`` 的函数。
    已有的其他 hook、matcher group、未知字段全部原样保留。
    """
    hooks = _hooks_dict(cfg)
    added = 0
    for event in events:
        entries = hooks.setdefault(event, [])
        if not isinstance(entries, list):
            raise ValueError(f'hooks["{event}"] 必须是数组')
        if any(_group_has_tag(g, tag) for g in entries):
            continue                        # 幂等:重复安装不重复添加
        command = (command_for_event(event) if callable(command_for_event)
                   else command_for_event)
        entries.append({"hooks": [{
            "type": "command",
            "command": command,
            "timeout": timeout,
            "statusMessage": status_message,
        }]})
        added += 1
    return added


def remove_hook_handlers(cfg, tag: str = HOOK_TAG) -> int:
    """只摘掉本项目的 handler(原地修改),返回移除数量。"""
    if not isinstance(cfg, dict):
        return 0
    hooks = cfg.get("hooks")
    if not isinstance(hooks, dict):
        return 0
    removed = 0
    for event, entries in list(hooks.items()):
        if not isinstance(entries, list):
            continue
        kept_groups = []
        for group in entries:
            if not _group_has_tag(group, tag):
                kept_groups.append(group)
                continue
            handlers = group.get("hooks") or []
            kept = [h for h in handlers
                    if not (isinstance(h, dict) and tag in str(h.get("command", "")))]
            removed += len(handlers) - len(kept)
            if kept:
                group["hooks"] = kept       # 组里还有别人的 handler -> 保留该组
                kept_groups.append(group)
            # 否则:这个 group 本来就只有我们,连组一起丢掉
        if len(kept_groups) != len(entries):
            if kept_groups:
                hooks[event] = kept_groups
            else:
                del hooks[event]            # 只删因此变空的事件键
    return removed
