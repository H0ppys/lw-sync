"""config.ini 读取与写回（拆分自 sync_app.py 第 143-177 行）"""
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
from .http import configure_ssl  # noqa: F401
from .logging_util import log  # noqa: F401
from .paths import DEFAULT_CONFIG, config_path  # noqa: F401




def load_config() -> configparser.ConfigParser:
    cp = configparser.ConfigParser()
    cp.optionxform = str  # type: ignore[assignment]
    path = config_path()
    if not os.path.exists(path):
        for section, values in DEFAULT_CONFIG.items():
            cp.add_section(section)
            for key, val in values.items():
                cp.set(section, key, val)
        save_config(cp)
        log(f"已生成配置文件：{path}")
    cp.read(path, encoding="utf-8-sig")
    changed = False
    for section, values in DEFAULT_CONFIG.items():
        if not cp.has_section(section):
            cp.add_section(section)
            changed = True
        for key, val in values.items():
            if not cp.has_option(section, key):
                cp.set(section, key, val)
                changed = True
    if cp.get("fields", "user", fallback="") == "用户账号":
        cp.set("fields", "user", "采集员")
        changed = True
    if changed:
        save_config(cp)
    configure_ssl(cp)
    return cp


def save_config(cp: configparser.ConfigParser) -> None:
    with open(config_path(), "w", encoding="utf-8") as f:
        cp.write(f)
