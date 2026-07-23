#!/usr/bin/env python3
"""~/.codex/hooks.json 的合并 / 幂等 / 卸载 / 保护他人配置。

全部走 tempfile,不碰真实的 ~/.codex。
"""
import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import codex_status as cxs  # noqa: E402

HELPER_CMD = "/usr/bin/python3 /Users/me/.springfield_pet/codex_hook.py"

OTHER_HOOK = {
    "hooks": [{"type": "command", "command": "/opt/other-tool/notify.sh",
               "timeout": 3}]
}


def helper_cmd(event):
    return f"{HELPER_CMD} {event}"


class TestMerge(unittest.TestCase):

    def test_merge_into_empty_config(self):
        cfg = {}
        added = cxs.merge_hook_handlers(cfg, helper_cmd)
        self.assertEqual(added, len(cxs.HOOK_EVENTS))
        self.assertEqual(sorted(cfg["hooks"]), sorted(cxs.HOOK_EVENTS))
        for event in cxs.HOOK_EVENTS:
            handler = cfg["hooks"][event][0]["hooks"][0]
            self.assertEqual(handler["type"], "command")
            self.assertIn(cxs.HOOK_TAG, handler["command"])
            self.assertEqual(handler["timeout"], cxs.HOOK_TIMEOUT)
            self.assertEqual(handler["statusMessage"], cxs.HOOK_STATUS_MESSAGE)

    def test_no_matcher_key_emitted(self):
        """Codex 的这些事件不都支持 matcher,不要伪造 "*"。"""
        cfg = {}
        cxs.merge_hook_handlers(cfg, helper_cmd)
        for event in cxs.HOOK_EVENTS:
            self.assertNotIn("matcher", cfg["hooks"][event][0])

    def test_accepts_plain_string_command(self):
        cfg = {}
        cxs.merge_hook_handlers(cfg, HELPER_CMD)
        self.assertEqual(cfg["hooks"]["Stop"][0]["hooks"][0]["command"], HELPER_CMD)

    def test_preserves_existing_hooks(self):
        cfg = {
            "description": "Local lifecycle hooks",
            "hooks": {
                "Stop": [copy.deepcopy(OTHER_HOOK)],
                "SomeOtherEvent": [copy.deepcopy(OTHER_HOOK)],
            },
            "unknownTopLevelField": {"keep": "me"},
        }
        cxs.merge_hook_handlers(cfg, helper_cmd)
        self.assertEqual(cfg["description"], "Local lifecycle hooks")
        self.assertEqual(cfg["unknownTopLevelField"], {"keep": "me"})
        self.assertEqual(cfg["hooks"]["SomeOtherEvent"], [OTHER_HOOK])
        stop = cfg["hooks"]["Stop"]
        self.assertEqual(len(stop), 2)
        self.assertEqual(stop[0], OTHER_HOOK)          # 别人的排在前面且未被改动
        self.assertIn(cxs.HOOK_TAG, stop[1]["hooks"][0]["command"])

    def test_preserves_matcher_groups_of_others(self):
        cfg = {"hooks": {"PreToolUse": [
            {"matcher": "Bash", "hooks": [{"type": "command", "command": "x.sh"}]}]}}
        cxs.merge_hook_handlers(cfg, helper_cmd)
        self.assertEqual(cfg["hooks"]["PreToolUse"][0]["matcher"], "Bash")

    def test_idempotent(self):
        cfg = {}
        first = cxs.merge_hook_handlers(cfg, helper_cmd)
        snapshot = copy.deepcopy(cfg)
        second = cxs.merge_hook_handlers(cfg, helper_cmd)
        third = cxs.merge_hook_handlers(cfg, helper_cmd)
        self.assertEqual(first, len(cxs.HOOK_EVENTS))
        self.assertEqual((second, third), (0, 0))
        self.assertEqual(cfg, snapshot)

    def test_partial_install_tops_up(self):
        """只装了一半(例如上次被中断)时,补齐剩下的。"""
        cfg = {}
        cxs.merge_hook_handlers(cfg, helper_cmd, events=("Stop",))
        added = cxs.merge_hook_handlers(cfg, helper_cmd)
        self.assertEqual(added, len(cxs.HOOK_EVENTS) - 1)
        self.assertEqual(len(cfg["hooks"]["Stop"]), 1)

    def test_command_updates_are_not_duplicated(self):
        """helper 路径不变时,即使 python 解释器换了也不重复添加。"""
        cfg = {}
        cxs.merge_hook_handlers(cfg, lambda e: f"/usr/bin/python3 {cxs.HOOK_TAG} {e}")
        added = cxs.merge_hook_handlers(cfg, lambda e: f"/opt/py/python3 {cxs.HOOK_TAG} {e}")
        self.assertEqual(added, 0)

    def test_rejects_non_dict_hooks(self):
        with self.assertRaises(ValueError):
            cxs.merge_hook_handlers({"hooks": "nope"}, helper_cmd)

    def test_rejects_non_list_event(self):
        with self.assertRaises(ValueError):
            cxs.merge_hook_handlers({"hooks": {"Stop": "nope"}}, helper_cmd)


class TestDetection(unittest.TestCase):

    def test_detects_installed(self):
        cfg = {}
        cxs.merge_hook_handlers(cfg, helper_cmd)
        self.assertTrue(cxs.hooks_config_has_helper(cfg))

    def test_not_detected_when_absent(self):
        self.assertFalse(cxs.hooks_config_has_helper({}))
        self.assertFalse(cxs.hooks_config_has_helper({"hooks": {}}))
        self.assertFalse(cxs.hooks_config_has_helper(
            {"hooks": {"Stop": [copy.deepcopy(OTHER_HOOK)]}}))

    def test_tolerates_garbage(self):
        for cfg in (None, [], "x", {"hooks": "x"}, {"hooks": {"Stop": "x"}},
                    {"hooks": {"Stop": ["x", 1, None]}}):
            with self.subTest(cfg=cfg):
                self.assertFalse(cxs.hooks_config_has_helper(cfg))


class TestRemove(unittest.TestCase):

    def test_removes_only_our_handlers(self):
        cfg = {
            "description": "keep",
            "hooks": {
                "Stop": [copy.deepcopy(OTHER_HOOK)],
                "SomeOtherEvent": [copy.deepcopy(OTHER_HOOK)],
            },
        }
        cxs.merge_hook_handlers(cfg, helper_cmd)
        removed = cxs.remove_hook_handlers(cfg)
        self.assertEqual(removed, len(cxs.HOOK_EVENTS))
        self.assertFalse(cxs.hooks_config_has_helper(cfg))
        self.assertEqual(cfg["description"], "keep")
        self.assertEqual(cfg["hooks"]["Stop"], [OTHER_HOOK])
        self.assertEqual(cfg["hooks"]["SomeOtherEvent"], [OTHER_HOOK])

    def test_drops_events_that_became_empty(self):
        cfg = {}
        cxs.merge_hook_handlers(cfg, helper_cmd)
        cxs.remove_hook_handlers(cfg)
        self.assertEqual(cfg["hooks"], {})

    def test_keeps_shared_group_with_other_handlers(self):
        """同一 group 里混着别人的 handler 时,只摘我们那条,组保留。"""
        cfg = {"hooks": {"Stop": [{"hooks": [
            {"type": "command", "command": "/opt/other-tool/notify.sh"},
            {"type": "command", "command": f"/usr/bin/python3 {cxs.HOOK_TAG}"},
        ]}]}}
        removed = cxs.remove_hook_handlers(cfg)
        self.assertEqual(removed, 1)
        group = cfg["hooks"]["Stop"][0]
        self.assertEqual(len(group["hooks"]), 1)
        self.assertEqual(group["hooks"][0]["command"], "/opt/other-tool/notify.sh")

    def test_preserves_unknown_group_fields(self):
        cfg = {"hooks": {"PreToolUse": [{
            "matcher": "Bash",
            "note": "someone else's field",
            "hooks": [
                {"type": "command", "command": "keep.sh"},
                {"type": "command", "command": f"python3 {cxs.HOOK_TAG}"},
            ],
        }]}}
        cxs.remove_hook_handlers(cfg)
        group = cfg["hooks"]["PreToolUse"][0]
        self.assertEqual(group["matcher"], "Bash")
        self.assertEqual(group["note"], "someone else's field")

    def test_remove_is_idempotent(self):
        cfg = {"hooks": {"Stop": [copy.deepcopy(OTHER_HOOK)]}}
        self.assertEqual(cxs.remove_hook_handlers(cfg), 0)
        self.assertEqual(cfg["hooks"]["Stop"], [OTHER_HOOK])

    def test_tolerates_garbage(self):
        for cfg in (None, [], {"hooks": "x"}, {"hooks": {"Stop": "x"}}):
            with self.subTest(cfg=cfg):
                self.assertEqual(cxs.remove_hook_handlers(cfg), 0)

    def test_install_remove_roundtrip_restores_original(self):
        original = {
            "description": "Local lifecycle hooks",
            "hooks": {"Stop": [copy.deepcopy(OTHER_HOOK)]},
        }
        cfg = copy.deepcopy(original)
        cxs.merge_hook_handlers(cfg, helper_cmd)
        cxs.remove_hook_handlers(cfg)
        self.assertEqual(cfg, original)


class TestFileIO(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "hooks.json"

    def test_missing_file_reads_as_empty(self):
        self.assertEqual(cxs.read_json_file(self.path), {})

    def test_blank_file_reads_as_empty(self):
        self.path.write_text("   \n", encoding="utf-8")
        self.assertEqual(cxs.read_json_file(self.path), {})

    def test_invalid_json_raises_so_install_aborts(self):
        self.path.write_text("{ not json", encoding="utf-8")
        with self.assertRaises(ValueError):
            cxs.read_json_file(self.path)

    def test_non_object_json_raises(self):
        self.path.write_text("[1,2,3]", encoding="utf-8")
        with self.assertRaises(ValueError):
            cxs.read_json_file(self.path)

    def test_invalid_file_is_never_overwritten(self):
        """安装流程:读失败就抛,原文件必须原样留着。"""
        raw = "{ not json"
        self.path.write_text(raw, encoding="utf-8")
        try:
            cfg = cxs.read_json_file(self.path)
            cxs.merge_hook_handlers(cfg, helper_cmd)
            cxs.atomic_write_json(self.path, cfg)
        except ValueError:
            pass
        self.assertEqual(self.path.read_text(encoding="utf-8"), raw)

    def test_atomic_write_roundtrip(self):
        cfg = {}
        cxs.merge_hook_handlers(cfg, helper_cmd)
        cxs.atomic_write_json(self.path, cfg)
        self.assertEqual(json.loads(self.path.read_text(encoding="utf-8")), cfg)
        self.assertTrue(cxs.hooks_config_has_helper(cxs.read_json_file(self.path)))

    def test_atomic_write_leaves_no_temp_files(self):
        cxs.atomic_write_json(self.path, {"a": 1})
        self.assertEqual([p.name for p in Path(self.tmp.name).iterdir()],
                         ["hooks.json"])

    def test_unicode_preserved(self):
        cxs.atomic_write_json(self.path, {"活动": "正在运行命令"})
        self.assertIn("正在运行命令", self.path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
