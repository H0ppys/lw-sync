"""TLS 上下文与 JSON HTTP 客户端（拆分自 sync_app.py 第 178-226 行）"""
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




_SSL = {"insecure": False, "ca_bundle": ""}


def configure_ssl(cp: configparser.ConfigParser) -> None:
    try:
        _SSL["insecure"] = cp.getboolean("options", "insecure_ssl", fallback=False)
    except ValueError:
        _SSL["insecure"] = False
    _SSL["ca_bundle"] = cp.get("options", "ca_bundle", fallback="").strip()


def make_ssl_context() -> ssl.SSLContext:
    if _SSL["insecure"]:
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        return ctx
    ca = _SSL["ca_bundle"]
    if ca and os.path.exists(ca):
        return ssl.create_default_context(cafile=ca)
    return ssl.create_default_context()


def http_json(url: str, payload: Any = None, headers: dict[str, str] | None = None, method: str | None = None, timeout: int = 30) -> tuple[int, Any]:
    data = None
    hdrs = {"Accept": "application/json"}
    if payload is not None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        hdrs["Content-Type"] = "application/json"
    if headers:
        hdrs.update(headers)
    req = urllib.request.Request(url, data=data, headers=hdrs, method=method or ("POST" if data else "GET"))
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=make_ssl_context()) as resp:
            body = resp.read().decode("utf-8", "replace")
            try:
                return resp.status, json.loads(body) if body else None
            except json.JSONDecodeError:
                return resp.status, body
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")
        try:
            return e.code, json.loads(body)
        except json.JSONDecodeError:
            return e.code, body
    except urllib.error.URLError as e:
        return 0, f"网络错误：{e.reason}"
