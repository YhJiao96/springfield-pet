#!/usr/bin/env python3
"""GIF 批量导入皮肤的单元测试。全部走 tempfile,不碰真实 assets。"""
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

try:
    from PIL import Image
except ImportError:                                  # pragma: no cover
    Image = None

import import_skin as imp  # noqa: E402


def solid(size=(40, 40), box=None, color=(255, 0, 0, 255), bg=(0, 0, 0, 0)):
    """造一张 RGBA 图,box 区域填色。"""
    im = Image.new("RGBA", size, bg)
    if box:
        im.paste(color, box)
    return im


def write_gif(path, frames, durations, transparent=True):
    conv = [f.convert("P", palette=Image.ADAPTIVE) for f in frames]
    kw = dict(save_all=True, append_images=conv[1:], duration=durations, loop=0, disposal=2)
    if transparent:
        kw["transparency"] = 0
    conv[0].save(path, format="GIF", **kw)


@unittest.skipIf(Image is None, "需要 Pillow")
class TestSlotNaming(unittest.TestCase):

    def test_exact_slots(self):
        for slot in imp.SLOTS:
            self.assertEqual(imp.slot_for_filename(f"{slot}.gif"), slot)

    def test_aliases(self):
        cases = {"idle.gif": "wait", "walk.gif": "move", "run.gif": "move",
                 "happy.gif": "victory", "sleep.gif": "lying", "think.gif": "thinking",
                 "click.gif": "attack", "hurt.gif": "die", "待机.gif": "wait",
                 "走路.gif": "move", "庆祝.gif": "victory"}
        for name, slot in cases.items():
            with self.subTest(name=name):
                self.assertEqual(imp.slot_for_filename(name), slot)

    def test_case_and_separators(self):
        for name in ("WAIT.GIF", "Wait.gif", "wait-loop.gif", "wait_2.gif", "01_wait.gif"):
            with self.subTest(name=name):
                self.assertEqual(imp.slot_for_filename(name), "wait")

    def test_unknown(self):
        for name in ("random.gif", "readme.txt", "背景.gif"):
            with self.subTest(name=name):
                self.assertIsNone(imp.slot_for_filename(name))


@unittest.skipIf(Image is None, "需要 Pillow")
class TestResample(unittest.TestCase):
    """GIF 每帧时长不一,必须按时长补帧到固定 fps,否则动作速度全错。"""

    def test_uniform_100ms_to_25fps(self):
        frames = [(solid(), 100) for _ in range(4)]      # 4 帧 × 100ms = 400ms
        out = imp.resample_to_fps(frames, 25)
        self.assertEqual(len(out), 10)                   # 400ms @25fps = 10 帧

    def test_mixed_durations(self):
        frames = [(solid(), d) for d in (100, 40, 200, 40)]   # 380ms
        out = imp.resample_to_fps(frames, 25)
        self.assertEqual(len(out), round(380 / 40))

    def test_already_40ms_is_one_to_one(self):
        frames = [(solid(), 40) for _ in range(7)]
        self.assertEqual(len(imp.resample_to_fps(frames, 25)), 7)

    def test_zero_duration_treated_as_100ms(self):
        """GIF 里 duration=0 的帧,浏览器按 100ms 处理,这里保持一致。"""
        frames = [(solid(), 0), (solid(), 100)]
        self.assertEqual(len(imp.resample_to_fps(frames, 25)), 5)

    def test_no_durations_passthrough(self):
        frames = [(solid(), 0) for _ in range(5)]
        frames = [(f, None) for f, _ in frames]
        frames = [(f, 0) for f, _ in frames]
        # 全 0 且没给 source_fps -> 原样返回
        out = imp.resample_to_fps([(solid(), 0) for _ in range(5)], 25, source_fps=None)
        self.assertEqual(len(out), 5)

    def test_source_fps_upsamples(self):
        """PNG 序列没有时长:给了 source_fps 就按它换算。"""
        out = imp.resample_to_fps([(solid(), 0) for _ in range(5)], 25, source_fps=10)
        self.assertEqual(len(out), 12)          # 5/10s = 500ms -> 12.5 -> 12

    def test_never_returns_empty(self):
        self.assertEqual(len(imp.resample_to_fps([(solid(), 1)], 25)), 1)

    def test_empty_input(self):
        self.assertEqual(imp.resample_to_fps([], 25), [])


@unittest.skipIf(Image is None, "需要 Pillow")
class TestAnchor(unittest.TestCase):
    """锚点决定切换动作时脚会不会跳。"""

    def test_bottom_center_of_centered_figure(self):
        im = solid((100, 100), (40, 20, 60, 80))       # x 40..60, y 20..80
        x, y = imp.compute_anchor([im])
        self.assertAlmostEqual(x, 50.0, delta=1.0)
        self.assertAlmostEqual(y, 80.0, delta=0.5)

    def test_anchor_follows_feet_not_overall_bbox(self):
        """身体前倾(上半身伸出去)时,锚点该跟着脚走,而不是被整体包围盒拉偏。"""
        im = Image.new("RGBA", (100, 100), (0, 0, 0, 0))
        im.paste((255, 0, 0, 255), (40, 60, 60, 90))   # 脚:x 40..60
        im.paste((255, 0, 0, 255), (40, 20, 95, 40))   # 上半身甩到右边 x 40..95
        x, y = imp.compute_anchor([im])
        self.assertAlmostEqual(x, 50.0, delta=2.0)     # 跟脚,不是 (40+95)/2=67.5
        self.assertAlmostEqual(y, 90.0, delta=0.5)

    def test_averages_across_frames(self):
        a = solid((100, 100), (40, 20, 60, 80))
        b = solid((100, 100), (44, 20, 64, 80))
        x, _y = imp.compute_anchor([a, b])
        self.assertAlmostEqual(x, 52.0, delta=1.0)

    def test_fully_transparent(self):
        x, y = imp.compute_anchor([Image.new("RGBA", (20, 30), (0, 0, 0, 0))])
        self.assertEqual([x, y], [10.0, 30.0])

    def test_empty(self):
        self.assertEqual(imp.compute_anchor([]), [0.0, 0.0])


@unittest.skipIf(Image is None, "需要 Pillow")
class TestAlphaAndCrop(unittest.TestCase):

    def test_has_alpha(self):
        self.assertTrue(imp.has_alpha([solid((10, 10), (2, 2, 5, 5))]))
        self.assertFalse(imp.has_alpha([Image.new("RGBA", (10, 10), (1, 2, 3, 255))]))

    def test_key_out_background(self):
        im = Image.new("RGBA", (10, 10), (255, 255, 255, 255))
        im.paste((10, 20, 30, 255), (3, 3, 7, 7))
        out = imp.key_out_background(im, tolerance=10)
        self.assertEqual(out.getpixel((0, 0))[3], 0)      # 角落被抠掉
        self.assertEqual(out.getpixel((5, 5))[3], 255)    # 主体保留

    def test_key_tolerance_matters(self):
        im = Image.new("RGBA", (6, 6), (250, 250, 250, 255))
        im.paste((240, 240, 240, 255), (2, 2, 4, 4))      # 和背景很接近
        loose = imp.key_out_background(im.copy(), tolerance=40)
        tight = imp.key_out_background(im.copy(), tolerance=2)
        self.assertEqual(loose.getpixel((3, 3))[3], 0)    # 容差大 -> 一起抠掉
        self.assertEqual(tight.getpixel((3, 3))[3], 255)  # 容差小 -> 保留

    def test_union_bbox_covers_all_frames(self):
        a = solid((50, 50), (10, 10, 20, 20))
        b = solid((50, 50), (30, 30, 40, 40))
        self.assertEqual(imp.union_bbox([a, b]), (10, 10, 40, 40))

    def test_union_bbox_all_transparent(self):
        self.assertIsNone(imp.union_bbox([Image.new("RGBA", (5, 5), (0, 0, 0, 0))]))

    def test_fit_height_scales_down_only(self):
        big = [Image.new("RGBA", (200, 400), (0, 0, 0, 0))]
        self.assertEqual(imp.fit_height(big, 320)[0].size, (160, 320))
        small = [Image.new("RGBA", (20, 30), (0, 0, 0, 0))]
        self.assertEqual(imp.fit_height(small, 320)[0].size, (20, 30))


@unittest.skipIf(Image is None, "需要 Pillow")
class TestManifestMerge(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "manifest.json"

    def test_preserves_existing_skins(self):
        self.path.write_text(json.dumps({
            "fps": 25,
            "skins": {"M1903": {"animations": {"wait": {"frames": 33}}}},
        }), encoding="utf-8")
        imp.merge_manifest(self.path, "mychar", {"wait": {"frames": 5}}, "我的角色", 25)
        data = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertIn("M1903", data["skins"])                     # 原有皮肤没丢
        self.assertEqual(data["skins"]["M1903"]["animations"]["wait"]["frames"], 33)
        self.assertTrue(data["skins"]["mychar"]["custom"])
        self.assertEqual(data["skins"]["mychar"]["display_name"], "我的角色")
        self.assertEqual(data["fps"], 25)

    def test_creates_when_missing(self):
        imp.merge_manifest(self.path, "a", {"wait": {"frames": 1}}, None, 25)
        self.assertTrue(self.path.exists())
        self.assertNotIn("display_name", json.loads(self.path.read_text())["skins"]["a"])

    def test_reimport_replaces_only_that_skin(self):
        imp.merge_manifest(self.path, "a", {"wait": {"frames": 1}}, None, 25)
        imp.merge_manifest(self.path, "b", {"wait": {"frames": 2}}, None, 25)
        imp.merge_manifest(self.path, "a", {"wait": {"frames": 9}}, None, 25)
        data = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertEqual(data["skins"]["a"]["animations"]["wait"]["frames"], 9)
        self.assertEqual(data["skins"]["b"]["animations"]["wait"]["frames"], 2)

    def test_no_temp_file_left(self):
        imp.merge_manifest(self.path, "a", {"wait": {"frames": 1}}, None, 25)
        self.assertEqual([p.name for p in self.path.parent.iterdir()], ["manifest.json"])

    def test_build_entry_loop_defaults(self):
        w = imp.build_entry("wait", 10, (50, 60), [25.0, 60.0], "sk")
        v = imp.build_entry("victory", 10, (50, 60), [25.0, 60.0], "sk")
        self.assertTrue(w["loop"])
        self.assertFalse(v["loop"])
        self.assertEqual(w["frames_dir"], "sk/wait/")
        self.assertEqual(w["suggested_state"], "idle")

    def test_build_entry_loop_override(self):
        self.assertFalse(imp.build_entry("wait", 1, (2, 2), [1, 2], "sk", loop=False)["loop"])


@unittest.skipIf(Image is None, "需要 Pillow")
class TestCollectInputs(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)

    def touch(self, name):
        p = self.dir / name
        if p.suffix:
            write_gif(p, [solid((8, 8), (2, 2, 6, 6))], [100])
        else:
            p.mkdir()
        return p

    def test_picks_known_reports_unknown(self):
        self.touch("wait.gif"); self.touch("walk.gif"); self.touch("random.gif")
        (self.dir / "notes.txt").write_text("x")
        found, unknown = imp.collect_inputs(self.dir)
        self.assertEqual(sorted(s for _p, s in found), ["move", "wait"])
        self.assertIn("random.gif", unknown)
        self.assertNotIn("notes.txt", unknown)          # 非素材后缀直接忽略

    def test_duplicate_slot_kept_once(self):
        self.touch("wait.gif"); self.touch("idle.gif")   # 都映射到 wait
        found, unknown = imp.collect_inputs(self.dir)
        self.assertEqual(len(found), 1)
        self.assertTrue(any("已被占用" in u for u in unknown))

    def test_hidden_files_ignored(self):
        self.touch("wait.gif"); (self.dir / ".DS_Store").write_text("x")
        found, unknown = imp.collect_inputs(self.dir)
        self.assertEqual(len(found), 1)
        self.assertEqual(unknown, [])


@unittest.skipIf(Image is None, "需要 Pillow")
class TestEndToEnd(unittest.TestCase):
    """整条流水线:GIF 目录 -> 帧 + manifest。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.src = Path(self.tmp.name) / "gifs"; self.src.mkdir()
        self.assets = Path(self.tmp.name) / "pet_assets"; self.assets.mkdir()

    def make(self, name, n=4, durations=None, transparent=True, size=(60, 60)):
        frames = [solid(size, (20 + i, 25, 40 + i, 50)) for i in range(n)]
        write_gif(self.src / name, frames, durations or [100] * n, transparent)

    def run_cli(self, *extra):
        return imp.main([str(self.src), "--name", "mychar", "--display", "我的角色",
                         "--assets", str(self.assets), *extra])

    def test_full_import(self):
        self.make("wait.gif"); self.make("walk.gif"); self.make("happy.gif")
        self.assertEqual(self.run_cli(), 0)
        data = json.loads((self.assets / "manifest.json").read_text(encoding="utf-8"))
        anims = data["skins"]["mychar"]["animations"]
        self.assertEqual(sorted(anims), ["move", "victory", "wait"])
        for slot, meta in anims.items():
            d = self.assets / "mychar" / slot
            pngs = sorted(d.glob("frame_*.png"))
            self.assertEqual(len(pngs), meta["frames"], slot)
            self.assertEqual(Image.open(pngs[0]).size, tuple(meta["size"]), slot)
            self.assertTrue(0 <= meta["anchor"][0] <= meta["size"][0])
            self.assertTrue(0 <= meta["anchor"][1] <= meta["size"][1])
        self.assertTrue(anims["wait"]["loop"])
        self.assertFalse(anims["victory"]["loop"])

    def test_frames_are_cropped_to_content(self):
        """60x60 的画布里只有一小块内容,导出应被裁到内容大小。"""
        self.make("wait.gif", size=(60, 60))
        self.run_cli()
        meta = json.loads((self.assets / "manifest.json").read_text())["skins"]["mychar"]["animations"]["wait"]
        self.assertLess(meta["size"][0], 60)
        self.assertLess(meta["size"][1], 60)

    def test_resampled_frame_count(self):
        self.make("wait.gif", n=4, durations=[100, 100, 100, 100])   # 400ms
        self.run_cli()
        meta = json.loads((self.assets / "manifest.json").read_text())["skins"]["mychar"]["animations"]["wait"]
        self.assertEqual(meta["frames"], 10)                         # 400ms @25fps

    def test_dry_run_writes_nothing(self):
        self.make("wait.gif")
        self.run_cli("--dry-run")
        self.assertFalse((self.assets / "manifest.json").exists())
        self.assertFalse((self.assets / "mychar").exists())

    def test_opaque_gif_gets_background_keyed(self):
        self.make("wait.gif", transparent=False)
        self.run_cli()
        d = self.assets / "mychar" / "wait"
        first = Image.open(sorted(d.glob("frame_*.png"))[0])
        self.assertLess(first.getchannel("A").getextrema()[0], 255)   # 有透明像素了

    def test_reimport_needs_force(self):
        self.make("wait.gif")
        self.run_cli()
        with self.assertRaises(SystemExit):
            self.run_cli()
        self.assertEqual(self.run_cli("--force"), 0)

    def test_bad_skin_name_rejected(self):
        self.make("wait.gif")
        with self.assertRaises(SystemExit):
            imp.main([str(self.src), "--name", "../evil", "--assets", str(self.assets)])

    def test_no_recognisable_files(self):
        self.make("random.gif")
        with self.assertRaises(SystemExit):
            self.run_cli()

    def test_reimport_shrinks_frame_dir(self):
        """重导入帧数变少时,旧的多余帧必须被清掉,否则会多播几帧。"""
        self.make("wait.gif", n=8)
        self.run_cli()
        n_before = len(list((self.assets / "mychar" / "wait").glob("*.png")))
        self.make("wait.gif", n=2)
        self.run_cli("--force")
        n_after = len(list((self.assets / "mychar" / "wait").glob("*.png")))
        self.assertLess(n_after, n_before)


@unittest.skipIf(Image is None, "需要 Pillow")
class TestRunImport(unittest.TestCase):
    """run_import():GUI 和 CLI 共用的编程接口。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.src = Path(self.tmp.name) / "gifs"; self.src.mkdir()
        self.assets = Path(self.tmp.name) / "skins"

    def make(self, name, n=4):
        frames = [solid((60, 60), (20 + i, 25, 40 + i, 50)) for i in range(n)]
        write_gif(self.src / name, frames, [100] * n)

    def test_returns_result_dict(self):
        self.make("wait.gif"); self.make("walk.gif")
        res = imp.run_import(self.src, "mychar", self.assets, display="我的")
        self.assertEqual(res["skin"], "mychar")
        self.assertEqual(sorted(res["animations"]), ["move", "wait"])
        self.assertFalse(res["no_wait"])
        self.assertTrue((self.assets / "mychar" / "wait").exists())
        data = json.loads((self.assets / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(data["skins"]["mychar"]["display_name"], "我的")

    def test_no_wait_flag(self):
        self.make("walk.gif")
        self.assertTrue(imp.run_import(self.src, "c", self.assets)["no_wait"])

    def test_bad_name_raises_valueerror(self):
        self.make("wait.gif")
        with self.assertRaises(ValueError):
            imp.run_import(self.src, "../evil", self.assets)

    def test_empty_dir_raises(self):
        self.make("random.gif")
        with self.assertRaises(ValueError):
            imp.run_import(self.src, "c", self.assets)

    def test_dry_run_writes_nothing(self):
        self.make("wait.gif")
        imp.run_import(self.src, "c", self.assets, dry_run=True)
        self.assertFalse(self.assets.exists())

    def test_force_false_rejects_existing(self):
        self.make("wait.gif")
        imp.run_import(self.src, "c", self.assets)
        with self.assertRaises(ValueError):
            imp.run_import(self.src, "c", self.assets, force=False)
        # force=True 默认允许覆盖
        self.assertEqual(imp.run_import(self.src, "c", self.assets)["skin"], "c")


class TestLoadManifest(unittest.TestCase):
    """pet.load_manifest():合并内置 + 外部导入皮肤,各记素材根。"""

    def setUp(self):
        import os
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        import pet
        self.pet = pet
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        base = Path(self.tmp.name)
        self.builtin = base / "pet_assets"; self.builtin.mkdir()
        self.external = base / "skins"; self.external.mkdir()
        (self.builtin / "manifest.json").write_text(json.dumps({
            "fps": 25, "skins": {"M1903": {"animations": {"wait": {"frames": 33}}}},
        }), encoding="utf-8")
        self._old_assets, self._old_ext = pet.ASSETS, pet.EXTERNAL_SKINS
        pet.ASSETS, pet.EXTERNAL_SKINS = self.builtin, self.external
        self.addCleanup(self._restore)

    def _restore(self):
        self.pet.ASSETS, self.pet.EXTERNAL_SKINS = self._old_assets, self._old_ext

    def test_builtin_only_when_no_external(self):
        m = self.pet.load_manifest()
        self.assertEqual(list(m["skins"]), ["M1903"])
        self.assertEqual(m["skins"]["M1903"]["_root"], str(self.builtin))

    def test_external_merged_and_marked_custom(self):
        (self.external / "manifest.json").write_text(json.dumps({
            "skins": {"mychar": {"animations": {"wait": {"frames": 5}}, "display_name": "我的"}},
        }), encoding="utf-8")
        m = self.pet.load_manifest()
        self.assertEqual(sorted(m["skins"]), ["M1903", "mychar"])
        self.assertEqual(m["skins"]["mychar"]["_root"], str(self.external))
        self.assertTrue(m["skins"]["mychar"]["custom"])
        self.assertEqual(m["skins"]["M1903"]["_root"], str(self.builtin))   # 内置根不变

    def test_corrupt_external_ignored(self):
        (self.external / "manifest.json").write_text("}{ broken", encoding="utf-8")
        m = self.pet.load_manifest()
        self.assertEqual(list(m["skins"]), ["M1903"])       # 坏的外部文件不影响内置

    def test_external_entry_without_animations_skipped(self):
        (self.external / "manifest.json").write_text(json.dumps({
            "skins": {"bad": {"display_name": "缺动画"}, "good": {"animations": {"wait": {}}}},
        }), encoding="utf-8")
        m = self.pet.load_manifest()
        self.assertIn("good", m["skins"])
        self.assertNotIn("bad", m["skins"])


class TestAppIntegration(unittest.TestCase):
    """companion.custom_outfits():导入的皮肤要能出现在换衣服菜单。"""

    def setUp(self):
        import os
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

    def test_custom_outfits_picked_up(self):
        import companion
        manifest = {"skins": {
            "M1903": {"animations": {}},
            "mychar": {"animations": {}, "custom": True, "display_name": "我的角色"},
            "bare": {"animations": {}, "custom": True},
        }}
        out = companion.custom_outfits(manifest)
        self.assertEqual(sorted(out), ["custom:bare", "custom:mychar"])
        self.assertEqual(out["custom:mychar"]["name"], "我的角色")
        self.assertEqual(out["custom:bare"]["name"], "bare")       # 没 display_name 用 id
        self.assertEqual(out["custom:mychar"]["combat"], "mychar")
        self.assertIsNone(out["custom:mychar"]["rest"])            # 单套动作集

    def test_builtin_skins_not_treated_as_custom(self):
        import companion
        self.assertEqual(companion.custom_outfits(
            {"skins": {"M1903": {"animations": {}}}}), {})

    def test_tolerates_garbage(self):
        import companion
        for m in ({}, {"skins": None}, {"skins": {"x": "nope"}}, {"skins": {"y": {}}}):
            with self.subTest(m=m):
                self.assertEqual(companion.custom_outfits(m), {})


if __name__ == "__main__":
    unittest.main()
