#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""LWSync 入口（与原 sync_app.py 的 GUI/CLI 行为一致）。

用法：
    python main.py                       # 图形界面
    python main.py sync [--date YYYY-MM-DD] [--days 7] [--dry-run] [--csv out.csv]
    python main.py watch --interval 7200
    python main.py test | config | install-task --hours 2 | uninstall-task
"""
import sys

from lw_sync.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
