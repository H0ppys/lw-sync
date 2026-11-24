"""光轮人类数据平台客户端（登录态、看板接口、JWT 过期）（拆分自 sync_app.py 第 227-321 行）"""
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
from .http import http_json  # noqa: F401
from .logging_util import log  # noqa: F401
from .paths import app_dir  # noqa: F401




# --------------------------------------------------------------------------
# 光轮平台
# --------------------------------------------------------------------------
class LoginRequired(RuntimeError):
    """光轮账号未登录或登录失败，需要用户重新登录。"""


class LightwheelClient:
    def __init__(self, cp: configparser.ConfigParser):
        self.base = cp.get("lightwheel", "base_url").rstrip("/")
        self.username = cp.get("lightwheel", "username").strip()
        self.password = cp.get("lightwheel", "password")
        self.token: str | None = None
        self._token_file = os.path.join(app_dir(), "token_cache.json")

    def login(self, force: bool = False) -> None:
        if not self.username or not self.password:
            raise LoginRequired("光轮账号未配置，请先登录")
        if not force and self._load_cached_token():
            return
        status, data = http_json(
            f"{self.base}/api/authenticate/v2/user/login",
            {"username": self.username, "password": self.password},
        )
        if status != 200 or not isinstance(data, dict) or not data.get("token"):
            msg = data.get("message") if isinstance(data, dict) else str(data)
            raise LoginRequired(f"光轮账号登录失败：{str(msg)[:120]}")
        self.token = data["token"]
        try:
            with open(self._token_file, "w", encoding="utf-8") as f:
                json.dump({"username": self.username, "token": self.token}, f)
        except OSError:
            pass
        log(f"光轮平台登录成功：{self.username}")

    def _load_cached_token(self) -> bool:
        try:
            with open(self._token_file, encoding="utf-8") as f:
                cache = json.load(f)
            if cache.get("username") != self.username:
                return False
            token = cache.get("token") or ""
            if jwt_exp(token) - 300 > time.time():
                self.token = token
                return True
        except (OSError, ValueError):
            pass
        return False

    def _headers(self) -> dict[str, str]:
        return {"Authorization": self.token or "", "UserName": self.username}

    def _post(self, path: str, payload: dict, retry: bool = True) -> Any:
        if not self.token:
            self.login()
        status, data = http_json(f"{self.base}{path}", payload, headers=self._headers())
        if status == 401 and retry:
            self.login(force=True)
            return self._post(path, payload, retry=False)
        if status != 200:
            raise RuntimeError(f"接口调用失败 {path}（HTTP {status}）：{str(data)[:200]}")
        return data

    def fetch_collectors(self, date: str, page_size: int = 200) -> list[dict]:
        rows: list[dict] = []
        page = 1
        while True:
            payload = {
                "filter": {
                    "collectCompletedStartDate": f"{date} 00:00:00",
                    "collectCompletedEndDate": f"{date} 23:59:59",
                },
                "page": page,
                "pageSize": page_size,
            }
            data = self._post("/api/humancase/v1/continuous-collect-dashboard/list-collectors", payload)
            batch = data.get("data", []) if isinstance(data, dict) else []
            rows.extend(batch)
            total = int(data.get("total", 0) or 0) if isinstance(data, dict) else 0
            if not batch or len(rows) >= total or page >= 100:
                break
            page += 1
        log(f"{date} 采集员维度汇总：{len(rows)} 条记录")
        return rows


def jwt_exp(token: str) -> int:
    try:
        payload = token.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        return int(json.loads(base64.urlsafe_b64decode(payload)).get("exp", 0))
    except Exception:
        return 0
