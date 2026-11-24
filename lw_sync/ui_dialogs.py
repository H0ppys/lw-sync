"""重新授权、光轮登录、设置对话框（拆分自 sync_app.py 第 1154-1435 行）"""
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
from .http import configure_ssl, http_json  # noqa: F401
from .lark import LarkCli, prefer_exe_path  # noqa: F401
from .logging_util import log  # noqa: F401
from .paths import app_dir  # noqa: F401




class ReauthDialog:
    def __init__(self, parent: tk.Misc, cp: configparser.ConfigParser, on_done: Callable[[], None] | None = None):
        self.cp = cp
        self.on_done = on_done
        self.win = tk.Toplevel(parent)
        self.win.title("飞书重新授权")
        self.win.geometry("460x600")
        self.win.transient(parent)
        self.win.grab_set()
        self.win.attributes("-topmost", True)
        self.win.after(1200, lambda: self.win.attributes("-topmost", False))
        self.win.lift()
        self.device_code: str | None = None

        pad = ttk.Frame(self.win, padding=14)
        pad.pack(fill="both", expand=True)

        ttk.Label(pad, text="请使用飞书扫码，或在浏览器中打开下面的链接完成授权：", wraplength=420).pack(anchor="w")
        self.url_var = tk.StringVar(value="正在获取授权链接…")
        self.url_entry = ttk.Entry(pad, textvariable=self.url_var, state="readonly")
        self.url_entry.pack(fill="x", pady=8)

        self.qr_label = ttk.Label(pad, text="二维码加载中…")
        self.qr_label.pack(pady=6)

        btns = ttk.Frame(pad)
        btns.pack(fill="x", pady=6)
        self.open_btn = ttk.Button(btns, text="打开浏览器", command=self.open_browser, state="disabled")
        self.open_btn.pack(side="left")
        self.check_btn = ttk.Button(btns, text="我已完成授权", command=self.check_done, state="disabled")
        self.check_btn.pack(side="left", padx=8)
        ttk.Button(btns, text="关闭", command=self.win.destroy).pack(side="right")

        self.status = ttk.Label(pad, text="", foreground="#555")
        self.status.pack(anchor="w", pady=6)

        self._qr_image = None
        threading.Thread(target=self._start, daemon=True).start()

    def _start(self) -> None:
        try:
            log("开始飞书授权流程（设备码）")
            lark = LarkCli(self.cp)
            if not lark.ensure_app_configured():
                self._set_status("飞书应用未配置：请先在「设置」中填写 App ID / App Secret")
                log("飞书应用未配置，无法发起授权", "WARN")
                return
            data = lark.start_device_login()
            self.device_code = data.get("device_code")
            url = data.get("verification_url", "")
            log(f"已获取飞书授权链接：{url}")
            self.win.after(0, lambda: self.url_var.set(url))
            self.win.after(0, lambda: self.open_btn.configure(state="normal"))
            self.win.after(0, lambda: self.check_btn.configure(state="normal"))
            png = os.path.join(app_dir(), "qr_login.png")
            if lark.make_qrcode(url, png):
                self.win.after(0, lambda: self._show_qr(png))
                log("已生成授权二维码")
            self._set_status("等待授权…（10 分钟内有效）")
        except Exception as e:  # noqa: BLE001
            log(f"获取飞书授权链接失败：{e}", "ERROR")
            self._set_status(f"获取授权链接失败：{e}")
            if "未找到 lark-cli" in str(e):
                self.win.after(0, self._locate_cli)

    def _locate_cli(self) -> None:
        from tkinter import filedialog

        path = filedialog.askopenfilename(
            parent=self.win,
            title="请选择 lark-cli.exe",
            filetypes=[("lark-cli", "lark-cli.exe"), ("可执行文件", "*.exe"), ("所有文件", "*.*")],
        )
        if not path:
            return
        path = prefer_exe_path(path)
        self.cp.set("feishu", "lark_cli", path)
        save_config(self.cp)
        log(f"已指定 lark-cli 路径：{path}")
        threading.Thread(target=self._start, daemon=True).start()

    def _show_qr(self, png: str) -> None:
        try:
            img = tk.PhotoImage(file=png)
            self._qr_image = img
            self.qr_label.configure(image=img, text="")
        except Exception:  # noqa: BLE001
            self.qr_label.configure(text="二维码加载失败，请使用浏览器打开链接")

    def _set_status(self, text: str) -> None:
        self.win.after(0, lambda: self.status.configure(text=text))

    def open_browser(self) -> None:
        url = self.url_var.get()
        if url.startswith("http"):
            webbrowser.open(url)

    def check_done(self) -> None:
        if not self.device_code:
            return
        self.check_btn.configure(state="disabled")
        self._set_status("正在确认授权结果…")

        def work() -> None:
            try:
                LarkCli(self.cp).complete_device_login(self.device_code or "")
                log("飞书授权成功")
                self.win.after(0, lambda: messagebox.showinfo("授权成功", "飞书授权已完成"))
                self.win.after(0, self.win.destroy)
                if self.on_done:
                    self.on_done()
            except Exception as e:  # noqa: BLE001
                log(f"飞书授权未完成：{e}", "ERROR")
                self._set_status(f"授权未完成：{str(e)[:200]}")
                self.win.after(0, lambda: self.check_btn.configure(state="normal"))

        threading.Thread(target=work, daemon=True).start()


class LwLoginDialog:
    """光轮账号登录：可直接验证账号密码，也可打开官网登录页。"""

    SITE = "https://cloud.lightwheel.net/web/human/project/perf-manage"

    def __init__(self, parent: tk.Misc, cp: configparser.ConfigParser, on_done: Callable[[], None] | None = None):
        self.cp = cp
        self.on_done = on_done
        self._ssl_retried = False
        self.win = tk.Toplevel(parent)
        self.win.title("光轮账号登录")
        self.win.geometry("420x300")
        self.win.resizable(False, False)
        self.win.transient(parent)
        self.win.grab_set()
        self.win.attributes("-topmost", True)
        self.win.after(1200, lambda: self.win.attributes("-topmost", False))
        self.win.lift()

        pad = ttk.Frame(self.win, padding=14)
        pad.pack(fill="both", expand=True)

        ttk.Label(pad, text="光轮（Lightwheel）账号登录", font=("Microsoft YaHei UI", 11, "bold")).pack(anchor="w")
        ttk.Label(pad, text="如果忘记密码或账号异常，可先点「打开网站登录页」在浏览器里确认。", wraplength=380, foreground="#666").pack(anchor="w", pady=(2, 10))

        form = ttk.Frame(pad)
        form.pack(fill="x")
        ttk.Label(form, text="用户名").grid(row=0, column=0, sticky="w", pady=4)
        self.user_var = tk.StringVar(value=cp.get("lightwheel", "username", fallback=""))
        ttk.Entry(form, textvariable=self.user_var, width=32).grid(row=0, column=1, sticky="we", pady=4)
        ttk.Label(form, text="密码").grid(row=1, column=0, sticky="w", pady=4)
        self.pwd_var = tk.StringVar(value=cp.get("lightwheel", "password", fallback=""))
        ttk.Entry(form, textvariable=self.pwd_var, width=32, show="*").grid(row=1, column=1, sticky="we", pady=4)
        form.columnconfigure(1, weight=1)

        btns = ttk.Frame(pad)
        btns.pack(fill="x", pady=10)
        ttk.Button(btns, text="打开网站登录页", command=self.open_site).pack(side="left")
        self.login_btn = ttk.Button(btns, text="登录", command=self.do_login)
        self.login_btn.pack(side="left", padx=8)
        ttk.Button(btns, text="取消", command=self.win.destroy).pack(side="right")

        self.status = ttk.Label(pad, text="", foreground="#666", wraplength=380)
        self.status.pack(anchor="w")
        log("打开光轮登录窗口")

    def open_site(self) -> None:
        log(f"打开光轮网站登录页：{self.SITE}")
        webbrowser.open(self.SITE)

    def do_login(self) -> None:
        user = self.user_var.get().strip()
        pwd = self.pwd_var.get()
        if not user or not pwd:
            self.status.configure(text="请填写用户名和密码", foreground="#c62828")
            return
        self.login_btn.configure(state="disabled")
        self.status.configure(text="正在登录…", foreground="#666")
        log(f"验证光轮账号：{user}")

        def work() -> None:
            base = self.cp.get("lightwheel", "base_url").rstrip("/")
            status, data = http_json(
                f"{base}/api/authenticate/v2/user/login",
                {"username": user, "password": pwd},
            )
            ok = status == 200 and isinstance(data, dict) and data.get("token")
            if ok:
                self.cp.set("lightwheel", "username", user)
                self.cp.set("lightwheel", "password", pwd)
                save_config(self.cp)
                log(f"光轮账号登录成功并已保存：{user}")
                try:
                    os.remove(os.path.join(app_dir(), "token_cache.json"))
                except OSError:
                    pass
                self.win.after(0, lambda: messagebox.showinfo("登录成功", f"光轮账号 {user} 登录成功"))
                self.win.after(0, self.win.destroy)
                if self.on_done:
                    self.on_done()
            else:
                msg = data.get("message") if isinstance(data, dict) else str(data)
                text = str(msg)
                if ("CERTIFICATE_VERIFY_FAILED" in text or "certificate verify" in text.lower()) and not self._ssl_retried:
                    log("HTTPS 证书校验失败，询问是否跳过校验", "WARN")
                    self.win.after(0, lambda: self._offer_insecure(text))
                    return
                log(f"光轮账号登录失败：{text[:150]}", "ERROR")
                self.win.after(0, lambda: self.status.configure(text=f"登录失败：{text[:120]}", foreground="#c62828"))
                self.win.after(0, lambda: self.login_btn.configure(state="normal"))

        threading.Thread(target=work, daemon=True).start()

    def _offer_insecure(self, text: str) -> None:
        self.login_btn.configure(state="normal")
        self.status.configure(text=f"登录失败：{text[:100]}", foreground="#c62828")
        if messagebox.askyesno(
            "HTTPS 证书校验失败",
            "检测到证书校验失败，常见于公司代理 / 杀毒软件 / 未安装根证书。\n\n"
            "是否跳过 HTTPS 证书校验后重试？（只影响本工具的请求）",
        ):
            self.cp.set("options", "insecure_ssl", "true")
            save_config(self.cp)
            configure_ssl(self.cp)
            log("已启用跳过 HTTPS 证书校验，重新尝试登录", "WARN")
            self._ssl_retried = True
            self.do_login()


class SettingsDialog:
    def __init__(self, parent: tk.Misc, cp: configparser.ConfigParser):
        self.cp = cp
        self.win = tk.Toplevel(parent)
        self.win.title("设置")
        self.win.geometry("520x520")
        self.win.transient(parent)
        self.win.grab_set()

        pad = ttk.Frame(self.win, padding=14)
        pad.pack(fill="both", expand=True)

        self.vars: dict[tuple[str, str], tk.StringVar] = {}
        rows = [
            ("lightwheel", "username", "光轮用户名"),
            ("lightwheel", "password", "光轮密码"),
            ("feishu", "app_id", "飞书 App ID"),
            ("feishu", "app_secret", "飞书 App Secret"),
            ("feishu", "lark_cli", "lark-cli 路径（可留空）"),
            ("feishu", "app_token", "飞书 Base Token"),
            ("feishu", "table_id", "飞书 Table ID"),
            ("feishu", "view_id", "飞书 View ID"),
        ]
        for i, (section, key, label) in enumerate(rows):
            ttk.Label(pad, text=label).grid(row=i, column=0, sticky="w", pady=4)
            var = tk.StringVar(value=cp.get(section, key, fallback=""))
            self.vars[(section, key)] = var
            show = "*" if key in ("password", "app_secret") else ""
            ttk.Entry(pad, textvariable=var, width=42, show=show).grid(row=i, column=1, sticky="we", pady=4)
        pad.columnconfigure(1, weight=1)

        self.insecure_var = tk.BooleanVar(value=cp.getboolean("options", "insecure_ssl", fallback=False))
        ttk.Checkbutton(pad, text="跳过 HTTPS 证书校验（公司代理/杀毒软件导致登录失败时勾选）", variable=self.insecure_var).grid(
            row=len(rows), column=0, columnspan=2, sticky="w", pady=(8, 0)
        )

        ttk.Label(pad, text="提示：换电脑使用时，需要填写飞书 App ID / App Secret 并重新授权一次。", wraplength=460, foreground="#666").grid(row=len(rows) + 1, column=0, columnspan=2, sticky="w", pady=10)

        btns = ttk.Frame(pad)
        btns.grid(row=len(rows) + 2, column=0, columnspan=2, sticky="e", pady=8)
        ttk.Button(btns, text="保存", command=self.save).pack(side="left", padx=4)
        ttk.Button(btns, text="取消", command=self.win.destroy).pack(side="left")

    def save(self) -> None:
        for (section, key), var in self.vars.items():
            self.cp.set(section, key, var.get().strip())
        self.cp.set("options", "insecure_ssl", "true" if self.insecure_var.get() else "false")
        save_config(self.cp)
        configure_ssl(self.cp)
        log("设置已保存")
        messagebox.showinfo("已保存", "配置已保存，建议点击「重新授权飞书」验证。")
        self.win.destroy()
