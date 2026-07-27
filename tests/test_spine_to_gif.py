#!/usr/bin/env python3
"""spine_to_gif 的单元测试。

纯函数(找素材/裁剪)全测;真实 Spine 渲染需要 chromium + 联网,做成一个可选的
集成测试,只有设了 SPINE_SAMPLE 环境变量指向一套素材时才跑。
"""
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools" / "spine_to_gif"))
sys.path.insert(0, str(ROOT / "src"))

try:
    from PIL import Image
except ImportError:                                  # pragma: no cover
    Image = None

import spine_to_gif as stg  # noqa: E402


def solid(size, box, color=(200, 30, 30, 255)):
    im = Image.new("RGBA", size, (0, 0, 0, 0))
    if box:
        im.paste(color, box)
    return im


@unittest.skipIf(Image is None, "需要 Pillow")
class TestFindSpineFiles(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.d = Path(self.tmp.name)

    def _atlas(self, name, png="tex.png"):
        (self.d / name).write_text(f"\n{png}\nsize: 64,64\nformat: RGBA8888\n")

    def _png(self, name="tex.png"):
        Image.new("RGBA", (8, 8)).save(self.d / name)

    def test_binary_skel_same_name_atlas(self):
        (self.d / "M1903.skel").write_bytes(b"\x00spine")
        self._atlas("M1903.atlas"); self._png()
        skel, atlas, is_bin = stg.find_spine_files(self.d)
        self.assertEqual(skel.name, "M1903.skel")
        self.assertEqual(atlas.name, "M1903.atlas")
        self.assertTrue(is_bin)

    def test_json_skeleton(self):
        (self.d / "hero.json").write_text("{}")
        self._atlas("hero.atlas"); self._png()
        skel, atlas, is_bin = stg.find_spine_files(self.d)
        self.assertEqual(skel.suffix, ".json")
        self.assertFalse(is_bin)

    def test_prefers_skel_with_matching_atlas(self):
        (self.d / "a.skel").write_bytes(b"x")
        (self.d / "b.skel").write_bytes(b"x")
        self._atlas("b.atlas"); self._png()
        skel, atlas, _ = stg.find_spine_files(self.d)
        self.assertEqual(skel.name, "b.skel")          # 选有同名 atlas 的

    def test_mismatched_names_still_pairs(self):
        (self.d / "spineboy-pro.skel").write_bytes(b"x")
        self._atlas("spineboy-pma.atlas"); self._png()
        skel, atlas, _ = stg.find_spine_files(self.d)
        self.assertEqual(atlas.name, "spineboy-pma.atlas")

    def test_missing_skel(self):
        self._atlas("x.atlas"); self._png()
        with self.assertRaises(ValueError):
            stg.find_spine_files(self.d)

    def test_missing_atlas(self):
        (self.d / "x.skel").write_bytes(b"x")
        with self.assertRaises(ValueError):
            stg.find_spine_files(self.d)

    def test_missing_png_referenced_by_atlas(self):
        (self.d / "x.skel").write_bytes(b"x")
        self._atlas("x.atlas", png="nope.png")         # 引用了不存在的 png
        with self.assertRaises(ValueError):
            stg.find_spine_files(self.d)

    def test_manifest_json_not_treated_as_skeleton(self):
        (self.d / "manifest.json").write_text("{}")
        (self.d / "real.skel").write_bytes(b"x")
        self._atlas("real.atlas"); self._png()
        skel, _a, _b = stg.find_spine_files(self.d)
        self.assertEqual(skel.name, "real.skel")

    def test_pass_skel_file_directly(self):
        (self.d / "c.skel").write_bytes(b"x")
        self._atlas("c.atlas"); self._png()
        skel, atlas, _ = stg.find_spine_files(self.d / "c.skel")
        self.assertEqual(skel.name, "c.skel")


@unittest.skipIf(Image is None, "需要 Pillow")
class TestCrop(unittest.TestCase):

    def test_crops_to_union_of_all_frames(self):
        frames = [solid((100, 100), (40, 40, 50, 60)),
                  solid((100, 100), (45, 30, 55, 70))]
        out = stg._crop_to_content(frames, pad=0)
        # union: x 40..55, y 30..70 -> 15x40
        self.assertEqual(out[0].size, (15, 40))
        self.assertEqual(out[0].size, out[1].size)     # 所有帧裁成同尺寸

    def test_pad_applied_and_clamped(self):
        frames = [solid((100, 100), (10, 10, 20, 20))]
        out = stg._crop_to_content(frames, pad=5)
        self.assertEqual(out[0].size, (20, 20))        # (5..25) 两边各+5

    def test_all_transparent_returned_asis(self):
        frames = [Image.new("RGBA", (30, 30), (0, 0, 0, 0))]
        out = stg._crop_to_content(frames)
        self.assertEqual(out[0].size, (30, 30))


@unittest.skipIf(Image is None, "需要 Pillow")
class TestVendorAndSave(unittest.TestCase):

    def test_save_gifs_multiframe(self):
        frames = [solid((60, 60), (20, 20, 40, 50), color=(i * 20, 30, 30, 255))
                  for i in range(1, 5)]
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        out = Path(tmp.name)
        stg.save_gifs({"idle": frames}, out, log=lambda *a: None)
        from PIL import ImageSequence
        im = Image.open(out / "idle.gif")
        n = sum(1 for _ in ImageSequence.Iterator(im))
        self.assertEqual(n, 4)                         # 4 帧都在,没被合并

    def test_save_frames_writes_png_sequence(self):
        frames = [solid((40, 40), (10, 10, 20, 20)) for _ in range(3)]
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        out = Path(tmp.name)
        stg.save_frames({"wait": frames}, out, log=lambda *a: None)
        self.assertEqual(len(list((out / "wait").glob("frame_*.png"))), 3)


class TestIntegrationRender(unittest.TestCase):
    """真实渲染:仅当 SPINE_SAMPLE=<素材目录> 且 chromium 就绪时才跑。"""

    def setUp(self):
        self.sample = os.environ.get("SPINE_SAMPLE")
        if not self.sample:
            self.skipTest("未设 SPINE_SAMPLE,跳过真实渲染集成测试")
        ok, _ = stg.chromium_ready()
        if not ok:
            self.skipTest("chromium 未就绪")

    def test_render_produces_animated_frames(self):
        import numpy as np
        skel, atlas, _ = stg.find_spine_files(Path(self.sample))
        fb, meta = stg.render_spine(skel, atlas, log=lambda *a: None)
        self.assertTrue(fb, "没渲出任何动画")
        name = max(fb, key=lambda k: len(fb[k]))     # 取帧最多的动画(避开极短的)
        frames = fb[name]
        self.assertGreater(len(frames), 1)
        # 相邻帧应有变化(动画真的在动)
        changed = sum(1 for i in range(1, len(frames))
                      if not np.array_equal(np.array(frames[i]), np.array(frames[i - 1])))
        self.assertGreater(changed, 0, "所有帧相同 —— 动画没推进")
        # 透明背景
        self.assertEqual(frames[0].getchannel("A").getextrema()[0], 0)


if __name__ == "__main__":
    unittest.main()
