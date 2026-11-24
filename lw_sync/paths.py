"""应用常量、默认配置、运行目录解析（拆分自 sync_app.py 第 37-97 行）"""
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


APP_NAME = "LWSync"
VERSION = "2.7.0"
CREATE_NO_WINDOW = 0x08000000 if os.name == "nt" else 0

DEFAULT_CONFIG = {
    "lightwheel": {
        "base_url": "https://data.lightwheel.net",
        "username": "",
        "password": "",
    },
    "feishu": {
        "lark_cli": "",
        "app_id": "",
        "app_secret": "",
        "identity": "user",
        "app_token": "<FILL_APP_TOKEN>",
        "table_id": "<FILL_TABLE_ID>",
        "view_id": "<FILL_VIEW_ID>",
    },
    "fields": {
        "date": "采集完成日期",
        "user": "采集员",
        "parent_duration": "父采集时长",
        "sub_duration": "子采集时长",
        "inspected_duration": "质检完成时长（子）",
        "passed_duration": "通过时长（子）",
        "pass_rate": "通过率",
    },
    "options": {
        "unit": "hours",
        "decimals": "2",
        "aggregate": "user",
        "date_offset": "0",
        "interval_seconds": "3600",
        "task_name": "LWSync_Hourly",
        "sync_days": "7",
        "insecure_ssl": "false",
        "ca_bundle": "",
    },
}

TASK_NAME_DEFAULT = "LWSync_Hourly"


# --------------------------------------------------------------------------
# 基础工具
# --------------------------------------------------------------------------
def app_dir() -> str:
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


def config_path() -> str:
    return os.path.join(app_dir(), "config.ini")


def log_dir() -> str:
    d = os.path.join(app_dir(), "logs")
    os.makedirs(d, exist_ok=True)
    return d
