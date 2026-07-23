#!/usr/bin/env python3
"""Codex Hook helper + 多会话聚合的单元测试。

全部走 tempfile,不碰真实的 ~/.codex 和 ~/.springfield_pet。
"""
import io
import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import codex_status as cxs  # noqa: E402


class HelperTestBase(unittest.TestCase):
    """每个测试一个临时 ~/.springfield_pet,helper 通过环境变量注入路径。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self._old_env = os.environ.get("SPRINGFIELD_PET_DIR")
        os.environ["SPRINGFIELD_PET_DIR"] = self.tmp.name
        self.addCleanup(self._restore_env)
        self.helper = cxs.load_helper_module()
        self.sessions = Path(self.tmp.name) / "codex_sessions"

    def _restore_env(self):
        if self._old_env is None:
            os.environ.pop("SPRINGFIELD_PET_DIR", None)
        else:
            os.environ["SPRINGFIELD_PET_DIR"] = self._old_env

    def fire(self, payload, argv=None):
        """模拟 Codex 调用 hook:把 JSON pipe 给 helper。"""
        raw = payload if isinstance(payload, str) else json.dumps(payload)
        rc = self.helper.main(argv or [], io.StringIO(raw))
        self.assertEqual(rc, 0, "helper 必须始终 exit 0,不能打扰 Codex")
        return rc

    def record(self, session_id="s1"):
        path = self.sessions / (self.helper.safe_session_id(session_id) + ".json")
        return json.loads(path.read_text(encoding="utf-8"))


class TestEventMapping(HelperTestBase):
    """六种 Hook 事件的状态映射。"""

    CASES = [
        ("SessionStart", "idle", "Codex 会话已就绪"),
        ("UserPromptSubmit", "working", "正在理解新任务"),
        ("Stop", "done", "本轮任务已完成"),
    ]

    def test_simple_events(self):
        for event, state, activity in self.CASES:
            with self.subTest(event=event):
                self.fire({"hook_event_name": event, "session_id": "s1"})
                rec = self.record()
                self.assertEqual(rec["state"], state)
                self.assertEqual(rec["activity"], activity)
                self.assertEqual(rec["event"], event)
                self.assertEqual(rec["schema_version"], 2)
                self.assertEqual(rec["source"], "codex-hooks")

    def test_pre_tool_use_working(self):
        self.fire({"hook_event_name": "PreToolUse", "session_id": "s1",
                   "tool_name": "exec_command"})
        rec = self.record()
        self.assertEqual(rec["state"], "working")
        self.assertEqual(rec["activity"], "正在运行命令")
        self.assertEqual(rec["tool_name"], "exec_command")

    def test_post_tool_use_working(self):
        self.fire({"hook_event_name": "PostToolUse", "session_id": "s1",
                   "tool_name": "apply_patch"})
        rec = self.record()
        self.assertEqual(rec["state"], "working")
        self.assertEqual(rec["activity"], "已完成:修改文件")

    def test_permission_request_waiting(self):
        self.fire({"hook_event_name": "PermissionRequest", "session_id": "s1",
                   "tool_name": "Bash"})
        rec = self.record()
        self.assertEqual(rec["state"], "waiting")
        self.assertEqual(rec["activity"], "等待批准:运行命令")

    def test_tool_action_table(self):
        cases = {
            "Bash": "运行命令", "exec_command": "运行命令",
            "apply_patch": "修改文件", "Edit": "修改文件", "Write": "修改文件",
            "read_file": "读取文件", "Read": "读取文件",
            "WebSearch": "搜索资料", "update_plan": "更新计划",
            "Agent": "协调子任务", "spawn_agent": "协调子任务",
            "mcp__figma__get_file": "使用外部工具",
            "": "使用工具",
        }
        for tool, expect in cases.items():
            with self.subTest(tool=tool):
                self.assertEqual(self.helper.tool_action(tool), expect)

    def test_unknown_tool_keeps_name_only(self):
        self.assertEqual(self.helper.tool_action("weird_tool"), "使用 weird_tool")

    def test_event_name_from_argv_fallback(self):
        """stdin 里没有 hook_event_name 时,退回命令行参数。"""
        self.fire({"session_id": "s1"}, argv=["UserPromptSubmit"])
        self.assertEqual(self.record()["state"], "working")


class TestRobustness(HelperTestBase):
    """字段缺失 / stdin 非法 / 未知事件都不能崩。"""

    def test_invalid_json_stdin(self):
        self.fire("{not json at all")
        self.assertFalse(list(self.sessions.glob("*.json")),
                         "无法识别的输入不应写出状态文件")

    def test_empty_stdin(self):
        self.fire("")
        self.assertFalse(list(self.sessions.glob("*.json")))

    def test_non_dict_json(self):
        self.fire("[1, 2, 3]")
        self.assertFalse(list(self.sessions.glob("*.json")))

    def test_missing_all_optional_fields(self):
        self.fire({"hook_event_name": "Stop"})
        rec = self.record("")          # session_id 缺失 -> "session"
        self.assertEqual(rec["state"], "done")
        self.assertEqual(rec["project"], "Codex")
        self.assertEqual(rec["cwd"], "")
        self.assertEqual(rec["model"], "")

    def test_unknown_event_keeps_old_state(self):
        self.fire({"hook_event_name": "UserPromptSubmit", "session_id": "s1"})
        before = self.record()
        self.fire({"hook_event_name": "SomeFutureEvent", "session_id": "s1"})
        self.assertEqual(self.record(), before, "未知事件应被忽略,状态原样保留")

    def test_weird_field_types_do_not_crash(self):
        self.fire({"hook_event_name": "PreToolUse", "session_id": 12345,
                   "cwd": {"unexpected": "dict"}, "tool_name": ["a", "b"],
                   "model": None, "turn_id": 7})
        rec = self.record("12345")
        self.assertEqual(rec["state"], "working")
        self.assertEqual(rec["cwd"], "")
        self.assertEqual(rec["turn_id"], "7")

    def test_tool_name_alternate_keys(self):
        for payload in ({"tool": "Bash"}, {"name": "Bash"},
                        {"tool": {"name": "Bash"}}):
            with self.subTest(payload=payload):
                self.assertEqual(self.helper.tool_name(payload), "Bash")


class TestSessionIdSanitising(HelperTestBase):
    """session_id 只能用来拼安全文件名,不许目录穿透。"""

    def test_path_traversal_blocked(self):
        evil = "../../../../etc/passwd"
        safe = self.helper.safe_session_id(evil)
        self.assertNotIn("/", safe)
        self.assertNotIn("\\", safe)
        self.assertFalse(safe.startswith("."))
        self.fire({"hook_event_name": "Stop", "session_id": evil})
        written = list(self.sessions.glob("*.json"))
        self.assertEqual(len(written), 1)
        self.assertEqual(written[0].parent, self.sessions)

    def test_dot_ids(self):
        for sid in ("..", ".", "", None, "///"):
            with self.subTest(sid=sid):
                safe = self.helper.safe_session_id(sid)
                self.assertTrue(safe)
                self.assertFalse(safe.startswith("."))
                self.assertNotIn("/", safe)

    def test_length_capped(self):
        self.assertLessEqual(len(self.helper.safe_session_id("x" * 500)), 120)

    def test_normal_uuid_preserved(self):
        sid = "01937c2e-9f4a-7bb1-9d0e-2f8f2b7a4c11"
        self.assertEqual(self.helper.safe_session_id(sid), sid)


class TestAtomicWriteAndSequence(HelperTestBase):

    def test_sequence_increments(self):
        for expected in (1, 2, 3):
            self.fire({"hook_event_name": "PreToolUse", "session_id": "s1",
                       "tool_name": "Bash"})
            self.assertEqual(self.record()["sequence"], expected)

    def test_corrupt_previous_restarts_at_one(self):
        self.sessions.mkdir(parents=True, exist_ok=True)
        (self.sessions / "s1.json").write_text("{{{ broken", encoding="utf-8")
        self.fire({"hook_event_name": "Stop", "session_id": "s1"})
        self.assertEqual(self.record()["sequence"], 1)

    def test_written_json_is_complete(self):
        self.fire({"hook_event_name": "Stop", "session_id": "s1"})
        rec = self.record()
        for key in ("schema_version", "source", "session_id", "turn_id", "state",
                    "event", "project", "cwd", "model", "tool_name", "activity",
                    "updated_at", "sequence"):
            self.assertIn(key, rec)
        self.assertIsInstance(rec["updated_at"], float)

    def test_no_temp_files_left_behind(self):
        self.fire({"hook_event_name": "Stop", "session_id": "s1"})
        leftovers = [p.name for p in self.sessions.iterdir()
                     if p.name.endswith(".tmp")]
        self.assertEqual(leftovers, [])

    def test_sessions_are_independent(self):
        self.fire({"hook_event_name": "UserPromptSubmit", "session_id": "a"})
        self.fire({"hook_event_name": "PermissionRequest", "session_id": "b"})
        self.assertEqual(self.record("a")["state"], "working")
        self.assertEqual(self.record("b")["state"], "waiting")


class TestPrivacy(HelperTestBase):
    """状态文件里不能出现 prompt / 完整命令 / 工具输出 / 密钥。"""

    SECRET = "sk-super-secret-token-do-not-leak"

    def test_no_secrets_written(self):
        self.fire({
            "hook_event_name": "PreToolUse",
            "session_id": "s1",
            "tool_name": "Bash",
            "tool_input": {"command": f"curl -H 'Auth: {self.SECRET}' https://x.dev"},
            "prompt": f"我的 API key 是 {self.SECRET},帮我调接口",
            "tool_output": "机密输出" * 50,
            "env": {"OPENAI_API_KEY": self.SECRET},
        })
        blob = (self.sessions / "s1.json").read_text(encoding="utf-8")
        for leak in (self.SECRET, "curl", "机密输出", "API key"):
            self.assertNotIn(leak, blob)

    def test_post_tool_use_drops_output(self):
        self.fire({"hook_event_name": "PostToolUse", "session_id": "s1",
                   "tool_name": "Bash", "tool_output": "非常长的输出内容 xyzzy"})
        self.assertNotIn("xyzzy", (self.sessions / "s1.json").read_text(encoding="utf-8"))

    def test_activity_length_capped(self):
        self.fire({"hook_event_name": "PreToolUse", "session_id": "s1",
                   "tool_name": "T" * 400})
        self.assertLessEqual(len(self.record()["activity"]), 100)

    def test_activity_has_no_newlines(self):
        self.fire({"hook_event_name": "PreToolUse", "session_id": "s1",
                   "tool_name": "we\nird\tname\r\n"})
        act = self.record()["activity"]
        for ch in ("\n", "\r", "\t"):
            self.assertNotIn(ch, act)

    def test_clean_strips_control_chars(self):
        self.assertEqual(self.helper.clean("a\x00b\x07c"), "a b c")


class TestAggregation(unittest.TestCase):
    """多 session 优先级 / 超时 / 损坏文件。"""

    NOW = 1_700_000_000.0

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)

    def write(self, name, state, age=0.0, sequence=1, **extra):
        rec = {
            "schema_version": 2, "source": "codex-hooks", "session_id": name,
            "turn_id": "", "state": state, "event": "Stop", "project": name,
            "cwd": f"/tmp/{name}", "model": "", "tool_name": "",
            "activity": state, "updated_at": self.NOW - age, "sequence": sequence,
        }
        rec.update(extra)
        (self.dir / f"{name}.json").write_text(json.dumps(rec), encoding="utf-8")
        return rec

    def select(self):
        return cxs.select_codex_session(self.dir, self.NOW)

    def test_empty_dir(self):
        self.assertIsNone(self.select())

    def test_missing_dir(self):
        self.assertIsNone(cxs.select_codex_session(self.dir / "nope", self.NOW))

    def test_waiting_beats_working(self):
        self.write("a", "working", age=0)
        self.write("b", "waiting", age=120)
        self.assertEqual(self.select()["session_id"], "b")

    def test_working_beats_recent_done(self):
        self.write("a", "done", age=1)
        self.write("b", "working", age=200)
        self.assertEqual(self.select()["session_id"], "b")

    def test_recent_done_beats_idle(self):
        self.write("a", "idle", age=0)
        self.write("b", "done", age=5)
        self.assertEqual(self.select()["session_id"], "b")

    def test_same_rank_picks_newest(self):
        self.write("a", "working", age=300)
        self.write("b", "working", age=5)
        self.assertEqual(self.select()["session_id"], "b")

    def test_working_goes_stale_after_30min(self):
        self.write("a", "working", age=cxs.WORKING_STALE_SEC + 1)
        self.assertEqual(self.select()["effective_state"], "idle")

    def test_working_still_alive_just_under_30min(self):
        self.write("a", "working", age=cxs.WORKING_STALE_SEC - 1)
        self.assertEqual(self.select()["effective_state"], "working")

    def test_waiting_survives_15s(self):
        self.write("a", "waiting", age=60)
        self.assertEqual(self.select()["effective_state"], "waiting")

    def test_waiting_survives_hours(self):
        self.write("a", "waiting", age=6 * 3600)
        self.assertEqual(self.select()["effective_state"], "waiting")

    def test_done_expires_after_15s(self):
        self.write("a", "done", age=cxs.TERMINAL_SHOW_SEC + 1)
        self.assertEqual(self.select()["effective_state"], "idle")

    def test_failed_expires_after_15s(self):
        self.write("a", "failed", age=cxs.TERMINAL_SHOW_SEC + 1)
        self.assertEqual(self.select()["effective_state"], "idle")

    def test_stale_working_loses_to_fresh_idle(self):
        self.write("a", "working", age=cxs.WORKING_STALE_SEC + 10)
        self.write("b", "idle", age=1)
        self.assertEqual(self.select()["session_id"], "b")

    def test_old_files_ignored(self):
        self.write("a", "waiting", age=cxs.MAX_AGE_SEC + 10)
        self.assertIsNone(self.select())

    def test_future_files_ignored(self):
        self.write("a", "waiting", age=-(cxs.FUTURE_SKEW_SEC + 10))
        self.assertIsNone(self.select())

    def test_small_clock_skew_tolerated(self):
        self.write("a", "working", age=-5)
        self.assertIsNotNone(self.select())

    def test_wrong_schema_ignored(self):
        self.write("a", "waiting", schema_version=1)
        self.assertIsNone(self.select())

    def test_corrupt_file_does_not_break_others(self):
        (self.dir / "broken.json").write_text("}{ nope", encoding="utf-8")
        (self.dir / "empty.json").write_text("", encoding="utf-8")
        (self.dir / "list.json").write_text("[]", encoding="utf-8")
        self.write("good", "waiting", age=1)
        picked = self.select()
        self.assertIsNotNone(picked)
        self.assertEqual(picked["session_id"], "good")

    def test_non_json_files_skipped(self):
        (self.dir / "notes.txt").write_text("hello", encoding="utf-8")
        self.write("good", "working", age=1)
        self.assertEqual(self.select()["session_id"], "good")

    def test_change_key_tracks_sequence(self):
        self.write("a", "done", age=1, sequence=4)
        first = cxs.session_change_key(self.select())
        self.write("a", "done", age=1, sequence=5)
        self.assertNotEqual(first, cxs.session_change_key(self.select()))

    def test_change_key_stable_when_nothing_changes(self):
        self.write("a", "working", age=1, sequence=4)
        self.assertEqual(cxs.session_change_key(self.select()),
                         cxs.session_change_key(self.select()))

    def test_change_key_none_for_no_session(self):
        self.assertIsNone(cxs.session_change_key(None))

    def test_activity_shown_while_state_is_live(self):
        self.write("a", "working", age=1, activity="正在运行命令")
        self.assertEqual(cxs.display_activity(self.select()), "正在运行命令")

    def test_activity_dropped_once_done_expired(self):
        """done 展示满 15 秒后,横幅不该还挂着"本轮任务已完成"。"""
        self.write("a", "done", age=cxs.TERMINAL_SHOW_SEC + 1, activity="本轮任务已完成")
        picked = self.select()
        self.assertEqual(picked["effective_state"], "idle")
        self.assertEqual(cxs.display_activity(picked), "")

    def test_activity_dropped_once_working_stale(self):
        self.write("a", "working", age=cxs.WORKING_STALE_SEC + 1, activity="正在运行命令")
        self.assertEqual(cxs.display_activity(self.select()), "")

    def test_display_activity_of_none(self):
        self.assertEqual(cxs.display_activity(None), "")


class TestEndToEndTurn(HelperTestBase):
    """helper 写 -> 聚合器读,完整走一轮。"""

    def test_full_turn(self):
        now = time.time()
        self.fire({"hook_event_name": "SessionStart", "session_id": "s1",
                   "cwd": "/Users/me/projects/my-app", "model": "gpt-5"})
        picked = cxs.select_codex_session(self.sessions, now)
        self.assertEqual(picked["effective_state"], "idle")
        self.assertEqual(picked["project"], "my-app")
        self.assertEqual(picked["model"], "gpt-5")

        self.fire({"hook_event_name": "UserPromptSubmit", "session_id": "s1",
                   "cwd": "/Users/me/projects/my-app"})
        self.assertEqual(cxs.select_codex_session(self.sessions, now)["effective_state"],
                         "working")

        self.fire({"hook_event_name": "PermissionRequest", "session_id": "s1",
                   "tool_name": "Bash", "cwd": "/Users/me/projects/my-app"})
        picked = cxs.select_codex_session(self.sessions, now)
        self.assertEqual(picked["effective_state"], "waiting")
        self.assertEqual(picked["activity"], "等待批准:运行命令")

        self.fire({"hook_event_name": "Stop", "session_id": "s1",
                   "cwd": "/Users/me/projects/my-app"})
        picked = cxs.select_codex_session(self.sessions, now)
        self.assertEqual(picked["effective_state"], "done")
        self.assertEqual(picked["sequence"], 4)

    def test_two_concurrent_sessions_waiting_wins(self):
        now = time.time()
        self.fire({"hook_event_name": "UserPromptSubmit", "session_id": "busy",
                   "cwd": "/tmp/busy"})
        self.fire({"hook_event_name": "PermissionRequest", "session_id": "asking",
                   "cwd": "/tmp/asking", "tool_name": "apply_patch"})
        picked = cxs.select_codex_session(self.sessions, now)
        self.assertEqual(picked["project"], "asking")
        self.assertEqual(picked["effective_state"], "waiting")


if __name__ == "__main__":
    unittest.main()
