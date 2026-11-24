"""argparse 入口与命令分发（拆分自 sync_app.py 第 1565-1649 行）"""
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
from .config import load_config  # noqa: F401
from .gui import run_gui  # noqa: F401
from .lark import AuthRequired  # noqa: F401
from .lightwheel import LoginRequired  # noqa: F401
from .logging_util import log, setup_console  # noqa: F401
from .paths import APP_NAME, VERSION  # noqa: F401
from .pipeline import sync  # noqa: F401
from .tasks import cmd_config, cmd_test, cmd_watch, install_task, remove_task  # noqa: F401




def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog=APP_NAME, description="作业记录同步工具")
    p.add_argument("--version", action="version", version=f"{APP_NAME} {VERSION}")
    sub = p.add_subparsers(dest="cmd")

    s = sub.add_parser("sync", help="同步一次")
    s.add_argument("--date", help="采集完成日期，默认当天，如 2026-11-21")
    s.add_argument("--dry-run", action="store_true", help="只拉取并打印，不写入飞书")
    s.add_argument("--csv", help="同时导出 CSV 到指定路径")
    s.add_argument("--days", type=int, help="同步最近 N 天（含当天），默认取配置 sync_days=7")

    w = sub.add_parser("watch", help="常驻定时同步")
    w.add_argument("--interval", type=int, help="间隔秒数，默认 3600")

    sub.add_parser("gui", help="打开图形界面")
    sub.add_parser("test", help="测试光轮/飞书连通性")
    sub.add_parser("config", help="修改配置")
    it = sub.add_parser("install-task", help="注册 Windows 计划任务")
    it.add_argument("--hours", type=float, help="同步间隔小时数，默认取配置（1）")
    sub.add_parser("uninstall-task", help="删除 Windows 计划任务")
    return p


def main(argv: list[str] | None = None) -> int:
    setup_console()
    cp = load_config()
    argv = list(sys.argv[1:] if argv is None else argv)

    windowed = sys.stdout is None
    if not argv:
        if windowed:
            run_gui(cp)
            return 0
        try:
            sync(cp)
        except AuthRequired as e:
            log(f"需要授权：{e}", "ERROR")
            return 2
        except LoginRequired as e:
            log(f"需要登录光轮账号：{e}", "ERROR")
            return 2
        except Exception as e:  # noqa: BLE001
            log(f"同步失败：{e}", "ERROR")
            if sys.stdin and sys.stdin.isatty():
                input("\n按回车键退出...")
            return 1
        if sys.stdin and sys.stdin.isatty():
            input("\n同步完成，按回车键退出...")
        return 0

    args = build_parser().parse_args(argv)
    try:
        if args.cmd == "gui":
            run_gui(cp)
        elif args.cmd == "sync":
            sync(cp, args.date, args.dry_run, args.csv, args.days)
        elif args.cmd == "watch":
            cmd_watch(cp, args.interval)
        elif args.cmd == "test":
            cmd_test(cp)
        elif args.cmd == "config":
            cmd_config(cp)
        elif args.cmd == "install-task":
            seconds = int(args.hours * 3600) if getattr(args, "hours", None) else None
            print(install_task(cp, seconds))
        elif args.cmd == "uninstall-task":
            print(remove_task(cp))
        else:
            build_parser().print_help()
    except KeyboardInterrupt:
        log("已中断")
        return 130
    except AuthRequired as e:
        log(f"需要授权：{e}", "ERROR")
        return 2
    except Exception as e:  # noqa: BLE001
        log(f"执行失败：{e}", "ERROR")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
