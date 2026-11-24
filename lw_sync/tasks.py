"""配置/自检子命令与 Windows 计划任务管理（拆分自 sync_app.py 第 1442-1564 行）"""
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
from .config import save_config  # noqa: F401
from .lark import LarkCli  # noqa: F401
from .lightwheel import LightwheelClient  # noqa: F401
from .logging_util import log  # noqa: F401
from .paths import CREATE_NO_WINDOW, TASK_NAME_DEFAULT, app_dir, config_path  # noqa: F401
from .pipeline import sync  # noqa: F401




# --------------------------------------------------------------------------
# 命令行
# --------------------------------------------------------------------------
def cmd_config(cp: configparser.ConfigParser) -> None:
    print(f"配置文件：{config_path()}")
    for section in ("lightwheel", "feishu"):
        print(f"\n[{section}]")
        for key, val in list(cp.items(section)):
            new = input(f"  {key} [{val}]: ").strip()
            if new:
                cp.set(section, key, new)
    save_config(cp)
    log("配置已保存")


def cmd_test(cp: configparser.ConfigParser) -> None:
    lw = LightwheelClient(cp)
    lw.login()
    rows = lw.fetch_collectors(dt.date.today().strftime("%Y-%m-%d"))
    print(f"光轮平台：正常，今日采集员记录 {len(rows)} 条")

    lark = LarkCli(cp)
    if not lark.ensure_app_configured():
        print("飞书：未配置应用凭证")
        return
    if not lark.is_authorized():
        print("飞书：授权已过期，请运行 gui 或执行 lark-cli auth login")
        return
    records, columns = lark.export_records()
    print(f"飞书：正常，现有 {len(records)} 条记录")
    for k in ("date", "user", "parent_duration", "sub_duration", "inspected_duration", "passed_duration", "pass_rate"):
        name = cp.get("fields", k)
        meta = columns.get(name, {})
        print(f"  {'OK ' if name in columns else '缺失'} {k:<20} -> {name} ({meta.get('field_type', '?')})")


def task_exe() -> str:
    exe = os.path.join(app_dir(), "LWSync.exe")
    if os.path.exists(exe):
        return exe
    if getattr(sys, "frozen", False):
        return sys.executable
    raise RuntimeError("未找到 LWSync.exe，请用便携版目录里的 LWSync.exe 设置自动同步")


def install_task(cp: configparser.ConfigParser, seconds: int | None = None) -> str:
    if os.name != "nt":
        raise RuntimeError("仅支持 Windows")
    seconds = seconds or int(cp.get("options", "interval_seconds", fallback="3600"))
    minutes = max(1, int(seconds) // 60)
    task = cp.get("options", "task_name", fallback=TASK_NAME_DEFAULT)
    exe = task_exe()
    subprocess.run(
        ["schtasks", "/Create", "/F", "/TN", task, "/TR", f'"{exe}" sync', "/SC", "MINUTE", "/MO", str(minutes), "/RL", "LIMITED"],
        check=True,
        creationflags=CREATE_NO_WINDOW,
    )
    cp.set("options", "interval_seconds", str(seconds))
    save_config(cp)
    msg = f"已设置自动同步：每 {minutes} 分钟一次（计划任务 {task}）"
    log(msg)
    return msg


def remove_task(cp: configparser.ConfigParser) -> str:
    task = cp.get("options", "task_name", fallback=TASK_NAME_DEFAULT)
    subprocess.run(["schtasks", "/Delete", "/F", "/TN", task], check=False, creationflags=CREATE_NO_WINDOW)
    msg = f"已关闭自动同步（删除计划任务 {task}）"
    log(msg)
    return msg


def task_query(cp: configparser.ConfigParser) -> str:
    if os.name != "nt":
        return ""
    task = cp.get("options", "task_name", fallback=TASK_NAME_DEFAULT)
    try:
        p = subprocess.run(["schtasks", "/Query", "/TN", task, "/FO", "LIST"], capture_output=True, creationflags=CREATE_NO_WINDOW)
        out = p.stdout.decode("gbk", "replace")
        if p.returncode != 0:
            return "未启用"
        for line in out.splitlines():
            if "Next Run Time" in line or "下次运行时间" in line:
                return line.split(":", 1)[-1].strip()
        return "已启用"
    except Exception:  # noqa: BLE001
        return ""


def next_run_text(cp: configparser.ConfigParser) -> str:
    raw = task_query(cp)
    if not raw or raw == "未启用":
        return "当前未启用自动同步"
    when = None
    for fmt in ("%Y/%m/%d %H:%M:%S", "%Y-%m-%d %H:%M:%S", "%m/%d/%Y %I:%M:%S %p", "%Y/%m/%d %H:%M"):
        try:
            when = dt.datetime.strptime(raw, fmt)
            break
        except ValueError:
            continue
    if when is None:
        return f"下次运行：{raw}"
    delta = (when - dt.datetime.now()).total_seconds()
    if delta <= 0:
        return f"下次运行：{when:%Y/%m/%d %H:%M}（即将运行）"
    minutes = int(delta // 60)
    h, m = divmod(minutes, 60)
    remain = f"{h} 小时 {m} 分" if h else f"{m} 分"
    return f"下次运行：{when:%Y/%m/%d %H:%M}（约 {remain}后）"


def cmd_watch(cp: configparser.ConfigParser, interval: int | None = None) -> None:
    interval = interval or int(cp.get("options", "interval_seconds", fallback="3600"))
    log(f"进入常驻模式，每 {interval} 秒同步一次（Ctrl+C 退出）")
    while True:
        started = time.time()
        try:
            sync(cp)
        except Exception as e:  # noqa: BLE001
            log(f"同步失败：{e}", "ERROR")
        time.sleep(max(5, interval - (time.time() - started)))
