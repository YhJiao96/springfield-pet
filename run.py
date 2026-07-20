#!/usr/bin/env python3
"""开发运行入口:python run.py"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "src"))

from companion import main  # noqa: E402

if __name__ == "__main__":
    main()
