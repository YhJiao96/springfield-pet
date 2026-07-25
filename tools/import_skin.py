#!/usr/bin/env python3
"""命令行入口薄封装:真正的实现在 src/import_skin.py(这样也能打进 .app)。"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from import_skin import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
