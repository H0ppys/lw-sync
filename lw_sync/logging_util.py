"""日志汇聚（文件 + 界面回调 + 控制台）（拆分自 sync_app.py 第 98-142 行）"""
from __future__ import annotations

# --- 原文件公共 import（拆分保留） ---
import argparse
import base64
import configparser
import csv
import datetime as dt
import json
import os
import queue
import shutil
import ssl
import subprocess
import sys
import threading
import time
import tkinter as tk
import urllib.error
import urllib.request
import webbrowser
from dataclasses import dataclass
from tkinter import messagebox, ttk
from typing import Any, Callable

# --- 跨模块依赖（拆分自动生成） ---
from .paths import log_dir  # noqa: F401




_LOG_SINKS: list[Callable[[str], None]] = []


def add_log_sink(fn: Callable[[str], None]) -> None:
    """注册日志接收器（界面用它把每条日志同步显示到日志栏）。"""
    _LOG_SINKS.append(fn)


def log(msg: str, level: str = "INFO") -> None:
    ts = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] [{level}] {msg}"
    try:
        if sys.stdout is not None:
            print(line, flush=True)
    except Exception:
        pass
    try:
        with open(os.path.join(log_dir(), f"sync-{dt.date.today():%Y%m%d}.log"), "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        pass
    for sink in list(_LOG_SINKS):
        try:
            sink(line)
        except Exception:
            pass


def setup_console() -> None:
    try:
        if os.name == "nt":
            import ctypes

            ctypes.windll.kernel32.SetConsoleOutputCP(65001)
            ctypes.windll.kernel32.SetConsoleCP(65001)
    except Exception:
        pass
    for stream in (sys.stdout, sys.stderr):
        try:
            if stream is not None:
                stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
