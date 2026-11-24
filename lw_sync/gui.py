"""图形界面启动入口（拆分自 sync_app.py 第 1436-1441 行）"""
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
from .ui_app import App  # noqa: F401




def run_gui(cp: configparser.ConfigParser) -> None:
    root = tk.Tk()
    App(root, cp)
    root.mainloop()
