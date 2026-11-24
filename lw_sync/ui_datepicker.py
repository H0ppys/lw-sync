"""日期选择弹窗（拆分自 sync_app.py 第 1078-1153 行）"""
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




class DatePicker(tk.Toplevel):
    """轻量日历，点选日期，不需要手输。"""

    WEEK = ["一", "二", "三", "四", "五", "六", "日"]

    def __init__(self, parent: tk.Misc, initial: str, on_pick: Callable[[str], None]):
        super().__init__(parent)
        self.on_pick = on_pick
        try:
            base = dt.datetime.strptime(initial, "%Y-%m-%d").date()
        except ValueError:
            base = dt.date.today()
        self.year, self.month = base.year, base.month

        self.title("选择日期")
        self.resizable(False, False)
        self.transient(parent)
        self.grab_set()
        self.attributes("-topmost", True)
        self.after(800, lambda: self.attributes("-topmost", False))
        try:
            parent.update_idletasks()
            x = parent.winfo_rootx() + max(0, (parent.winfo_width() - 300) // 2)
            y = parent.winfo_rooty() + 110
            self.geometry(f"+{max(0, x)}+{max(0, y)}")
        except Exception:  # noqa: BLE001
            pass

        self.head = ttk.Frame(self, padding=(8, 8, 8, 0))
        self.head.pack(fill="x")
        ttk.Button(self.head, text="◀", width=3, command=lambda: self.shift(-1)).pack(side="left")
        self.title_var = tk.StringVar()
        ttk.Label(self.head, textvariable=self.title_var, anchor="center", font=("Microsoft YaHei UI", 11, "bold")).pack(side="left", fill="x", expand=True)
        ttk.Button(self.head, text="▶", width=3, command=lambda: self.shift(1)).pack(side="right")

        self.grid_frame = ttk.Frame(self, padding=8)
        self.grid_frame.pack()
        self.render()

    def shift(self, delta: int) -> None:
        m = self.month + delta
        y = self.year + (m - 1) // 12
        m = (m - 1) % 12 + 1
        self.year, self.month = y, m
        self.render()

    def render(self) -> None:
        for w in self.grid_frame.winfo_children():
            w.destroy()
        self.title_var.set(f"{self.year} 年 {self.month} 月")
        for i, wd in enumerate(self.WEEK):
            ttk.Label(self.grid_frame, text=wd, width=4, anchor="center").grid(row=0, column=i, padx=1, pady=2)
        import calendar as _cal

        today = dt.date.today()
        for r, week in enumerate(_cal.Calendar(firstweekday=0).monthdayscalendar(self.year, self.month), start=1):
            for c, day in enumerate(week):
                if day == 0:
                    continue
                d = dt.date(self.year, self.month, day)
                label = f"{day}"
                btn = tk.Button(
                    self.grid_frame,
                    text=label,
                    width=3,
                    relief="flat",
                    bg="#d6e9ff" if d == today else "#ffffff",
                    command=lambda d=d: self.pick(d),
                )
                btn.grid(row=r, column=c, padx=1, pady=1)

    def pick(self, d: dt.date) -> None:
        self.on_pick(d.strftime("%Y-%m-%d"))
        self.destroy()
