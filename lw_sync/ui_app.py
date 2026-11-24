"""主窗口（状态区、控制区、日志区）（拆分自 sync_app.py 第 758-1077 行）"""
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
from .lark import AuthRequired, LarkCli, prefer_exe_path  # noqa: F401
from .lightwheel import LightwheelClient, LoginRequired  # noqa: F401
from .logging_util import log  # noqa: F401
from .paths import VERSION, log_dir  # noqa: F401
from .pipeline import sync  # noqa: F401
from .tasks import install_task, next_run_text, remove_task  # noqa: F401
from .ui_datepicker import DatePicker  # noqa: F401
from .ui_dialogs import LwLoginDialog, ReauthDialog, SettingsDialog  # noqa: F401




# --------------------------------------------------------------------------
# 图形界面
# --------------------------------------------------------------------------
class App:
    def __init__(self, root: tk.Tk, cp: configparser.ConfigParser):
        self.root = root
        self.cp = cp
        self.q: queue.Queue[str] = queue.Queue()
        self.busy = False

        root.title(f"作业记录同步 v{VERSION}")
        root.geometry("760x540")
        root.minsize(700, 480)

        style = ttk.Style()
        try:
            style.theme_use("vista")
        except tk.TclError:
            pass

        main = ttk.Frame(root, padding=12)
        main.pack(fill="both", expand=True)

        status = ttk.LabelFrame(main, text="状态", padding=10)
        status.pack(fill="x")
        lw_row = ttk.Frame(status)
        lw_row.pack(anchor="w", fill="x")
        self.lw_status = ttk.Label(lw_row, text="光轮账号：检查中…")
        self.lw_status.pack(side="left")
        ttk.Button(lw_row, text="登录", width=6, command=self.lw_login).pack(side="left", padx=8)
        self.fs_status = ttk.Label(status, text="飞书授权：检查中…")
        self.fs_status.pack(anchor="w")
        self.last_status = ttk.Label(status, text="上次同步：—")
        self.last_status.pack(anchor="w")

        bar = ttk.Frame(main, padding=(0, 10))
        bar.pack(fill="x")
        ttk.Label(bar, text="采集完成日期：").pack(side="left")
        self._date_touched = False
        self.date_var = tk.StringVar(value=dt.date.today().strftime("%Y-%m-%d"))
        self.date_label = ttk.Label(bar, textvariable=self.date_var, width=14, anchor="center", relief="solid", padding=(4, 2))
        self.date_label.pack(side="left")
        ttk.Button(bar, text="📅 选日期", command=self.pick_date).pack(side="left", padx=(6, 0))
        ttk.Label(bar, text="范围：").pack(side="left", padx=(10, 2))
        self.scope_var = tk.StringVar(value=self._scope_label())
        self.scope_combo = ttk.Combobox(
            bar, textvariable=self.scope_var, state="readonly", width=9,
            values=["仅当天", "最近3天", "最近7天", "最近14天", "最近30天"],
        )
        self.scope_combo.pack(side="left")
        self.scope_combo.bind("<<ComboboxSelected>>", self._on_scope_change)
        # 跨天后自动跟随"今天"（用日历选过日期则不再跟随）
        self.root.after(60000, self._follow_today)
        self.sync_btn = ttk.Button(bar, text="一键同步", command=lambda: self.start_sync(False))
        self.sync_btn.pack(side="left", padx=6)
        self.preview_btn = ttk.Button(bar, text="预览", command=lambda: self.start_sync(True))
        self.preview_btn.pack(side="left")
        ttk.Button(bar, text="重新授权飞书", command=self.reauth).pack(side="left", padx=6)
        ttk.Button(bar, text="设置", command=self.settings).pack(side="left")
        ttk.Button(bar, text="打开日志", command=self.open_logs).pack(side="left", padx=6)

        auto = ttk.Frame(main)
        auto.pack(fill="x", pady=(0, 6))
        ttk.Label(auto, text="自动同步：").pack(side="left")
        self.auto_var = tk.StringVar(value=self._auto_label())
        self.auto_combo = ttk.Combobox(
            auto, textvariable=self.auto_var, state="readonly", width=10,
            values=["关闭", "每小时", "每2小时", "每4小时", "每6小时"],
        )
        self.auto_combo.pack(side="left")
        self.auto_combo.bind("<<ComboboxSelected>>", self.on_auto_change)
        self.auto_status = ttk.Label(auto, text="", foreground="#666")
        self.auto_status.pack(side="left", padx=10)
        self.refresh_task_status()
        self.root.after(30000, self._tick_task)

        box = ttk.LabelFrame(main, text="运行日志", padding=6)
        box.pack(fill="both", expand=True)
        self.text = tk.Text(box, height=16, wrap="word", state="disabled")
        sb = ttk.Scrollbar(box, command=self.text.yview)
        self.text.configure(yscrollcommand=sb.set)
        self.text.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")

        self._log_path = os.path.join(log_dir(), f"sync-{dt.date.today():%Y%m%d}.log")
        try:
            self._log_pos = os.path.getsize(self._log_path)
        except OSError:
            self._log_pos = 0
        self._log_partial = ""
        self.root.after(400, self._tail_log)
        log("界面已启动")
        self.refresh_status()

    def _after(self, fn: Callable[[], None]) -> None:
        """线程安全地把回调排到界面线程；窗口已关闭时忽略。"""
        try:
            self.root.after(0, fn)
        except Exception:  # noqa: BLE001
            pass

    # ---- 日志 ----
    def write_log(self, msg: str) -> None:
        log(msg)

    def _append_line(self, line: str) -> None:
        self.text.configure(state="normal")
        self.text.insert("end", line + "\n")
        try:
            if int(self.text.index("end-1c").split(".")[0]) > 2000:
                self.text.delete("1.0", "500.0")
        except Exception:  # noqa: BLE001
            pass
        self.text.see("end")
        self.text.configure(state="disabled")

    def _tail_log(self) -> None:
        """跟随日志文件：本程序和计划任务的每一条日志都会实时出现在日志栏。"""
        try:
            path = os.path.join(log_dir(), f"sync-{dt.date.today():%Y%m%d}.log")
            if self._log_path != path:
                self._log_path = path
                self._log_pos = 0  # 跨天换文件，从头读
                self._log_partial = ""
            if os.path.exists(path):
                size = os.path.getsize(path)
                if size < self._log_pos:
                    self._log_pos = 0
                if size > self._log_pos:
                    with open(path, "r", encoding="utf-8", errors="replace") as f:
                        f.seek(self._log_pos)
                        data = f.read()
                        self._log_pos = f.tell()
                    data = self._log_partial + data
                    lines = data.split("\n")
                    self._log_partial = lines.pop() if lines else ""
                    for line in lines:
                        if line.strip():
                            self._append_line(line)
        except Exception:  # noqa: BLE001
            pass
        self.root.after(500, self._tail_log)

    # ---- 状态 ----
    def refresh_status(self) -> None:
        def work() -> None:
            cp = self.cp
            try:
                lw = LightwheelClient(cp)
                lw.login()
                self._after(lambda: self.lw_status.configure(text=f"光轮账号：{lw.username} ✅", foreground="#1a7f37"))
            except LoginRequired as e:
                self._after(lambda e=e: self.lw_status.configure(text=f"光轮账号：未登录（{str(e)[:30]}）", foreground="#c62828"))
            except Exception as e:  # noqa: BLE001
                self._after(lambda e=e: self.lw_status.configure(text=f"光轮账号：未登录（{str(e)[:40]}）", foreground="#c62828"))
            try:
                lark = LarkCli(cp)
                if not lark.app_configured():
                    self._after(lambda: self.fs_status.configure(text="飞书授权：未配置应用（请在设置中填写 App ID/Secret）", foreground="#c62828"))
                elif lark.is_authorized():
                    self._after(lambda: self.fs_status.configure(text="飞书授权：已授权 ✅", foreground="#1a7f37"))
                else:
                    self._after(lambda: self.fs_status.configure(text="飞书授权：已过期，请点击「重新授权飞书」", foreground="#c62828"))
            except Exception as e:  # noqa: BLE001
                self._after(lambda e=e: self.fs_status.configure(text=f"飞书授权：异常（{str(e)[:40]}）", foreground="#c62828"))

        threading.Thread(target=work, daemon=True).start()

    # ---- 定时任务 ----
    def _auto_label(self) -> str:
        try:
            sec = int(self.cp.get("options", "interval_seconds", fallback="3600"))
        except ValueError:
            sec = 3600
        mapping = {3600: "每小时", 7200: "每2小时", 14400: "每4小时", 21600: "每6小时"}
        return mapping.get(sec, "关闭")

    def refresh_task_status(self) -> None:
        def work() -> None:
            text = next_run_text(self.cp)
            self._after(lambda: self.auto_status.configure(text=text))

        threading.Thread(target=work, daemon=True).start()

    def _tick_task(self) -> None:
        self.refresh_task_status()
        self.root.after(30000, self._tick_task)

    def on_auto_change(self, _event: object = None) -> None:
        label = self.auto_var.get()
        log(f"自动同步设置：{label}")
        seconds = {"每小时": 3600, "每2小时": 7200, "每4小时": 14400, "每6小时": 21600}.get(label)

        def work() -> None:
            try:
                msg = remove_task(self.cp) if seconds is None else install_task(self.cp, seconds)
                self._after(lambda: self.auto_status.configure(text=msg))
                self._after(self.refresh_task_status)
            except Exception as e:  # noqa: BLE001
                self._after(lambda e=e: messagebox.showerror("设置失败", str(e)[:300]))

        threading.Thread(target=work, daemon=True).start()

    def _scope_label(self) -> str:
        try:
            d = int(self.cp.get("options", "sync_days", fallback="7"))
        except ValueError:
            d = 7
        return {1: "仅当天", 3: "最近3天", 7: "最近7天", 14: "最近14天", 30: "最近30天"}.get(d, f"最近{d}天")

    def _on_scope_change(self, _event: object = None) -> None:
        days = {"仅当天": 1, "最近3天": 3, "最近7天": 7, "最近14天": 14, "最近30天": 30}.get(self.scope_var.get(), 7)
        self.cp.set("options", "sync_days", str(days))
        save_config(self.cp)
        log(f"同步范围：{self.scope_var.get()}（{days} 天）")

    # ---- 日期选择 ----
    def _follow_today(self) -> None:
        if not self._date_touched:
            self.date_var.set(dt.date.today().strftime("%Y-%m-%d"))
        self.root.after(60000, self._follow_today)

    def pick_date(self) -> None:
        log("点击「选日期」")
        DatePicker(self.root, self.date_var.get(), self._on_date_picked)

    def _on_date_picked(self, value: str) -> None:
        self.date_var.set(value)
        self._date_touched = True
        log(f"已选择日期：{value}")

    # ---- 同步 ----
    def start_sync(self, dry: bool) -> None:
        if self.busy:
            return
        date = self.date_var.get().strip()
        try:
            dt.datetime.strptime(date, "%Y-%m-%d")
        except ValueError:
            messagebox.showerror("日期格式错误", "请按 2026-11-21 的格式填写日期")
            return
        self.busy = True
        days = {"仅当天": 1, "最近3天": 3, "最近7天": 7, "最近14天": 14, "最近30天": 30}.get(self.scope_var.get(), 7)
        log(f"点击「{'预览' if dry else '一键同步'}」：截止 {date}，共 {days} 天")
        for b in (self.sync_btn, self.preview_btn):
            b.configure(state="disabled")
        self.write_log(f"开始{'预览' if dry else '同步'}：截止 {date}，共 {days} 天")

        def work() -> None:
            try:
                n = sync(self.cp, date, dry_run=dry, days=days)
                self._after(lambda: self.last_status.configure(text=f"上次同步：{dt.datetime.now():%H:%M:%S} 成功，{days} 天共 {n} 条"))
                self._after(self.refresh_task_status)
                self._after(lambda: messagebox.showinfo("完成", f"已{'预览' if dry else '同步'} {n} 条记录"))
            except AuthRequired as e:
                log(f"需要飞书授权：{e}", "ERROR")
                self._after(lambda e=e: self._need_auth(str(e)))
            except LoginRequired as e:
                log(f"需要光轮登录：{e}", "ERROR")
                self._after(lambda e=e: self._need_lw_login(str(e)))
            except Exception as e:  # noqa: BLE001
                log(f"同步失败：{e}", "ERROR")
                if "未找到 lark-cli" in str(e):
                    self._after(lambda e=e: self._ask_locate_cli(str(e)))
                else:
                    self._after(lambda e=e: messagebox.showerror("失败", str(e)[:500]))
            finally:
                self.busy = False
                self._after(lambda: [b.configure(state="normal") for b in (self.sync_btn, self.preview_btn)])
                self._after(self.refresh_status)

        threading.Thread(target=work, daemon=True).start()

    def _need_auth(self, msg: str) -> None:
        if messagebox.askyesno("需要重新授权", f"{msg}\n\n现在打开飞书授权窗口？"):
            self.reauth()

    def _ask_locate_cli(self, msg: str) -> None:
        if not messagebox.askyesno("未找到 lark-cli", f"{msg}\n\n是否手动选择 lark-cli.exe？"):
            return
        from tkinter import filedialog

        path = filedialog.askopenfilename(
            title="请选择 lark-cli.exe",
            filetypes=[("lark-cli", "lark-cli.exe"), ("可执行文件", "*.exe"), ("所有文件", "*.*")],
        )
        if path:
            path = prefer_exe_path(path)
            self.cp.set("feishu", "lark_cli", path)
            save_config(self.cp)
            log(f"已指定 lark-cli 路径：{path}")
            self.refresh_status()

    def lw_login(self) -> None:
        log("点击「登录」")
        LwLoginDialog(self.root, self.cp, on_done=self.refresh_status)

    def _need_lw_login(self, msg: str) -> None:
        if messagebox.askyesno("光轮账号需要登录", f"{msg}\n\n是否打开光轮网站登录页？"):
            webbrowser.open(LwLoginDialog.SITE)
            self.lw_login()

    # ---- 重新授权 ----
    def reauth(self) -> None:
        log("点击「重新授权飞书」")
        ReauthDialog(self.root, self.cp, on_done=self.refresh_status)

    # ---- 设置 ----
    def settings(self) -> None:
        log("点击「设置」")
        SettingsDialog(self.root, self.cp)

    def open_logs(self) -> None:
        log(f"点击「打开日志」：{log_dir()}")
        try:
            os.startfile(log_dir())
        except Exception:  # noqa: BLE001
            pass
