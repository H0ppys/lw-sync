#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
作业记录同步工具 (LWSync)

数据源：光轮人类数据平台 → 绩效管理 → 被动采集看板 → 采集员维度汇总
目标：飞书多维表格「作业记录」（通过已授权的 lark-cli 写入）

界面版：双击 LWSync.exe，可一键同步、预览、重新授权飞书。
命令行：LWSync-cli.exe sync|watch|test|config|install-task|uninstall-task
"""

from __future__ import annotations

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


_LOG_SINKS: list[Callable[[str], None]] = []


def add_log_sink(fn: Callable[[str], None]) -> None:
    """注册日志接收器（界面用它把每条日志同步显示到日志栏）。"""
    _LOG_SINKS.append(fn)


def log(msg: str, level: str = "INFO") -> None:
    ts = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] [{level}] {msg}"
    try:
        if sys.stdout is not None:
            print(line, flush=True)
    except Exception:
        pass
    try:
        with open(os.path.join(log_dir(), f"sync-{dt.date.today():%Y%m%d}.log"), "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        pass
    for sink in list(_LOG_SINKS):
        try:
            sink(line)
        except Exception:
            pass


def setup_console() -> None:
    try:
        if os.name == "nt":
            import ctypes

            ctypes.windll.kernel32.SetConsoleOutputCP(65001)
            ctypes.windll.kernel32.SetConsoleCP(65001)
    except Exception:
        pass
    for stream in (sys.stdout, sys.stderr):
        try:
            if stream is not None:
                stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


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


# --------------------------------------------------------------------------
# 飞书（lark-cli）
# --------------------------------------------------------------------------
class AuthRequired(RuntimeError):
    """飞书授权缺失或过期，需要用户重新登录。"""


def prefer_exe_path(path: str) -> str:
    """用户选了 lark-cli.cmd 时，尽量换成同目录下的 lark-cli.exe（避免 cmd 破坏 JSON 参数）。"""
    if not path or not path.lower().endswith((".cmd", ".bat")):
        return path
    base = os.path.dirname(path)
    for cand in (
        os.path.join(base, "node_modules", "@larksuite", "cli", "bin", "lark-cli.exe"),
        os.path.join(os.path.dirname(base), "node_modules", "@larksuite", "cli", "bin", "lark-cli.exe"),
        os.path.join(base, "lark-cli.exe"),
    ):
        if os.path.exists(cand):
            return cand
    return path


class LarkCli:
    def __init__(self, cp: configparser.ConfigParser):
        self.cp = cp
        self.identity = cp.get("feishu", "identity", fallback="user") or "user"
        self.base_token = cp.get("feishu", "app_token").strip()
        self.table_id = cp.get("feishu", "table_id").strip()
        self.view_id = cp.get("feishu", "view_id").strip()
        self.exe = self._resolve_cli(cp.get("feishu", "lark_cli").strip())

    @staticmethod
    def _resolve_cli(configured: str) -> str:
        # 优先使用 .exe：.cmd 经 cmd.exe 解析时，JSON 参数里的引号会被破坏
        candidates: list[str] = []
        if configured:
            candidates.append(prefer_exe_path(configured))
        env_path = os.environ.get("LARK_CLI_PATH")
        if env_path:
            candidates.append(env_path)
        candidates += [
            os.path.join(app_dir(), "lark-cli.exe"),
            os.path.join(app_dir(), "lark-cli.cmd"),
            os.path.join(app_dir(), "runtime", "lark-cli.exe"),
            os.path.join(app_dir(), "lark-cli", "lark-cli.exe"),
        ]
        for base in (os.environ.get("APPDATA"), os.environ.get("LOCALAPPDATA")):
            if base:
                candidates.append(os.path.join(base, "npm", "node_modules", "@larksuite", "cli", "bin", "lark-cli.exe"))
        for path in candidates:
            if path.lower().endswith(".exe") and os.path.exists(path):
                return path

        bundled = LarkCli._release_bundled_cli()
        if bundled:
            return bundled

        # 兜底：没有 .exe 时才用 .cmd（可能影响带 JSON 参数的命令）
        for base in (os.environ.get("APPDATA"), os.environ.get("LOCALAPPDATA")):
            if base:
                for name in ("lark-cli.cmd", "lark-cli.bat"):
                    p = os.path.join(base, "npm", name)
                    if os.path.exists(p):
                        log(f"仅找到 {p}，建议改用 lark-cli.exe", "WARN")
                        return p
        found = shutil.which("lark-cli.exe") or shutil.which("lark-cli") or shutil.which("lark-cli.cmd")
        if found:
            return found
        raise RuntimeError(
            "未找到 lark-cli.exe：请确认它与 LWSync.exe 在同一目录（压缩包里的 lark-cli.exe 可能被杀毒软件删掉了），"
            "或在「设置 → lark-cli 路径」中手动指定。"
        )

    @staticmethod
    def _release_bundled_cli() -> str | None:
        """单文件 exe 内置的 lark-cli：首次使用时释放到本地目录，避免每次启动都解压。"""
        base = getattr(sys, "_MEIPASS", None)
        if not base:
            return None
        src = os.path.join(base, "lark-cli.exe")
        if not os.path.exists(src):
            return None
        dest_dir = os.path.join(os.environ.get("LOCALAPPDATA") or app_dir(), "LWSync")
        dest = os.path.join(dest_dir, "lark-cli.exe")
        try:
            os.makedirs(dest_dir, exist_ok=True)
            if not os.path.exists(dest) or os.path.getsize(dest) != os.path.getsize(src):
                shutil.copy2(src, dest)
                log(f"已释放内置 lark-cli：{dest}")
            return dest
        except OSError:
            return src

    def _run(self, args: list[str], stdin_text: str | None = None, timeout: int = 180, retries: int = 3) -> Any:
        if self.exe.lower().endswith((".cmd", ".bat")):
            # cmd 元字符（如 URL 里的 &）需要在参数层面加引号，否则会被 cmd 拆开
            safe_args = [f'"{a}"' if any(c in a for c in "&|<>^()%!") else a for a in args]
            cmd: list[str] = ["cmd", "/c", self.exe, *safe_args]
        else:
            cmd = [self.exe, *args]
        last_err = ""
        label = " ".join(a for a in args[:2] if not a.startswith("-"))
        log(f"调用 lark-cli：{label}")
        for attempt in range(retries):
            proc = subprocess.run(
                cmd,
                capture_output=True,
                timeout=timeout,
                cwd=app_dir(),
                input=(stdin_text.encode("utf-8") if stdin_text is not None else None),
                creationflags=CREATE_NO_WINDOW,
            )
            out = proc.stdout.decode("utf-8", "replace").strip()
            err = proc.stderr.decode("utf-8", "replace").strip()
            if out:
                try:
                    data = json.loads(out)
                except json.JSONDecodeError:
                    data = None
                    last_err = f"返回非 JSON：{out[:300]}"
                if isinstance(data, dict):
                    if data.get("ok") is False:
                        last_err = json.dumps(data.get("error", data), ensure_ascii=False)[:400]
                    else:
                        return data
            else:
                last_err = f"无输出（exit={proc.returncode}）：{err[:300]}"
            if attempt < retries - 1:
                log(f"lark-cli 调用失败，准备重试：{last_err[:100]}", "WARN")
                time.sleep(1.5 * (attempt + 1))
        raise RuntimeError(f"lark-cli 调用失败：{last_err}")

    # ---- 授权 ----
    def auth_status(self) -> dict:
        try:
            return self._run(["auth", "status"], retries=1)
        except Exception as e:  # noqa: BLE001
            return {"error": str(e)}

    def is_authorized(self) -> bool:
        status = self.auth_status()
        user = (status.get("identities") or {}).get("user") or {}
        st = user.get("status")
        log(f"飞书授权状态：{st or 'unknown'}")
        if st == "ready":
            return True
        if st == "needs_refresh":
            # access token 过期但 refresh token 还有效，lark-cli 会在下次调用时自动刷新
            exp = user.get("refreshExpiresAt") or ""
            try:
                return dt.datetime.fromisoformat(exp) > dt.datetime.now(dt.timezone.utc).astimezone()
            except ValueError:
                return True
        return False

    def app_configured(self) -> bool:
        try:
            self._run(["config", "show"], retries=1)
            return True
        except Exception:  # noqa: BLE001
            return False

    def ensure_app_configured(self) -> bool:
        """新电脑上 lark-cli 还没有应用配置时，用 config.ini 里的 app_id/app_secret 初始化。"""
        if self.app_configured():
            return True
        app_id = self.cp.get("feishu", "app_id", fallback="").strip()
        app_secret = self.cp.get("feishu", "app_secret", fallback="").strip()
        if not app_id or not app_secret:
            return False
        self._run(["config", "init", "--app-id", app_id, "--app-secret-stdin", "--brand", "feishu"], stdin_text=app_secret + "\n")
        log("已完成飞书应用配置初始化")
        return True

    def start_device_login(self) -> dict:
        data = self._run(["auth", "login", "--no-wait", "--json", "--domain", "base"], retries=1)
        return data

    def complete_device_login(self, device_code: str) -> None:
        self._run(["auth", "login", "--device-code", device_code, "--json"], timeout=660, retries=1)

    def make_qrcode(self, url: str, png_path: str) -> bool:
        try:
            self._run(["auth", "qrcode", url, "-o", png_path, "--size", "280"], retries=1)
            return os.path.exists(png_path)
        except Exception:  # noqa: BLE001
            return False

    # ---- 数据读写 ----
    def _common(self) -> list[str]:
        return ["--base-token", self.base_token, "--table-id", self.table_id, "--as", self.identity]

    def export_records(self) -> tuple[list[dict], dict[str, dict]]:
        if not self.is_authorized():
            raise AuthRequired("飞书授权已过期或未登录")
        out_name = f"records_{os.getpid()}.ndjson"
        out_file = os.path.join(app_dir(), out_name)
        args = ["base", "+record-list", *self._common(), "--format", "ndjson", "--output", out_name, "--overwrite", "--limit", "2000"]
        meta = self._run(args)
        records: list[dict] = []
        columns: dict[str, dict] = {}
        if isinstance(meta, dict) and isinstance(meta.get("columns"), dict):
            columns = meta["columns"]
        try:
            with open(out_file, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    item = json.loads(line)
                    if isinstance(item, dict) and isinstance(item.get("columns"), dict) and "record_id" not in item:
                        columns = item["columns"]
                        continue
                    if isinstance(item, dict) and item.get("record_id"):
                        records.append(item)
        finally:
            try:
                os.remove(out_file)
            except OSError:
                pass
        log(f"读取飞书记录：{len(records)} 条")
        return records, columns

    def create_records(self, records: list[dict]) -> int:
        created = 0
        for i in range(0, len(records), 200):
            chunk = records[i : i + 200]
            self._run_with_json(["base", "+record-batch-create", *self._common()], {"create_records": chunk})
            created += len(chunk)
        return created

    def update_records(self, updates: dict[str, dict]) -> int:
        updated = 0
        items = list(updates.items())
        for i in range(0, len(items), 200):
            chunk = dict(items[i : i + 200])
            self._run_with_json(["base", "+record-batch-update", *self._common()], {"update_records": chunk})
            updated += len(chunk)
        return updated

    def _run_with_json(self, base_args: list[str], payload: dict) -> Any:
        """把 JSON 写进临时文件再以 @文件 传入，避免命令行转义把 JSON 弄坏。"""
        name = f"payload_{os.getpid()}.json"
        path = os.path.join(app_dir(), name)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False)
        try:
            return self._run([*base_args, "--json", "@" + name])
        finally:
            try:
                os.remove(path)
            except OSError:
                pass


# --------------------------------------------------------------------------
# 数据整理
# --------------------------------------------------------------------------
@dataclass
class Row:
    date: str
    user: str
    parent: float
    sub: float
    inspected: float
    passed: float
    pass_rate: str


def aggregate_rows(raw: list[dict], date: str, aggregate: str = "user", unit: str = "hours", decimals: int = 2) -> list[Row]:
    def conv(seconds: float) -> float:
        return round(seconds / 3600.0 if unit == "hours" else seconds, decimals)

    buckets: dict[tuple[str, str], dict[str, float]] = {}
    for r in raw:
        user = (r.get("producerName") or "").strip()
        if not user:
            continue
        key = (user, r.get("projectName") or "") if aggregate == "user_project" else (user, "")
        b = buckets.setdefault(key, {"parent": 0.0, "sub": 0.0, "inspected": 0.0, "passed": 0.0, "rejected": 0.0})
        b["parent"] += float(r.get("parentCollectDurationSeconds") or 0)
        b["sub"] += float(r.get("subCollectDurationSeconds") or 0)
        b["inspected"] += float(r.get("subInspectInspectedDurationSeconds") or 0)
        b["passed"] += float(r.get("subInspectPassedDurationSeconds") or 0)
        b["rejected"] += float(r.get("subInspectRejectedDurationSeconds") or 0)

    rows: list[Row] = []
    for key, v in sorted(buckets.items()):
        user = key[0]
        denom = v["passed"] + v["rejected"]
        rate = f"{v['passed'] / denom * 100:.1f}%" if denom > 0 else ""
        rows.append(
            Row(
                date=date,
                user=user,
                parent=conv(v["parent"]),
                sub=conv(v["sub"]),
                inspected=conv(v["inspected"]),
                passed=conv(v["passed"]),
                pass_rate=rate,
            )
        )
    log(f"按{'用户' if aggregate == 'user' else '用户+项目'}汇总：{len(rows)} 行")
    return rows


def normalize_date(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (int, float)):
        return dt.datetime.fromtimestamp(value / 1000).strftime("%Y-%m-%d")
    return str(value).strip().replace("/", "-")[:10]


def text_value(v: float, unit: str) -> str:
    return f"{v:.2f}" if unit == "hours" else f"{v:.0f}"


def build_fields(row: Row, names: dict[str, str], columns: dict[str, dict], unit: str) -> dict:
    date_type = columns.get(names["date"], {}).get("field_type")
    date_val: Any = row.date
    if date_type == "datetime":
        date_val = f"{row.date} 00:00"
    return {
        names["date"]: date_val,
        names["user"]: row.user,
        names["parent_duration"]: text_value(row.parent, unit),
        names["sub_duration"]: text_value(row.sub, unit),
        names["inspected_duration"]: text_value(row.inspected, unit),
        names["passed_duration"]: text_value(row.passed, unit),
        names["pass_rate"]: row.pass_rate,
    }


# --------------------------------------------------------------------------
# 同步流程
# --------------------------------------------------------------------------
def resolve_date(cp: configparser.ConfigParser, arg_date: str | None) -> str:
    if arg_date:
        dt.datetime.strptime(arg_date, "%Y-%m-%d")
        return arg_date
    offset = int(cp.get("options", "date_offset", fallback="0") or 0)
    return (dt.date.today() + dt.timedelta(days=offset)).strftime("%Y-%m-%d")


def collect(cp: configparser.ConfigParser, date: str) -> list[Row]:
    lw = LightwheelClient(cp)
    lw.login()
    raw = lw.fetch_collectors(date)
    unit = cp.get("options", "unit", fallback="hours")
    decimals = int(cp.get("options", "decimals", fallback="2"))
    aggregate = cp.get("options", "aggregate", fallback="user")
    return aggregate_rows(raw, date, aggregate=aggregate, unit=unit, decimals=decimals)


def write_csv(cp: configparser.ConfigParser, rows: list[Row], path: str) -> None:
    names = {k: cp.get("fields", k) for k in ("date", "user", "parent_duration", "sub_duration", "inspected_duration", "passed_duration", "pass_rate")}
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow([names[k] for k in ("date", "user", "parent_duration", "sub_duration", "inspected_duration", "passed_duration", "pass_rate")])
        for r in rows:
            w.writerow([r.date, r.user, r.parent, r.sub, r.inspected, r.passed, r.pass_rate])
    log(f"已导出 CSV：{path}")


def sync(cp: configparser.ConfigParser, date: str | None = None, dry_run: bool = False, csv_path: str | None = None, days: int | None = None) -> int:
    end = resolve_date(cp, date)
    if days is None:
        try:
            days = int(cp.get("options", "sync_days", fallback="7"))
        except ValueError:
            days = 7
    days = max(1, min(days, 90))
    start = dt.date.fromisoformat(end) - dt.timedelta(days=days - 1)
    dates = [(start + dt.timedelta(days=i)).isoformat() for i in range(days)]
    log(f"===== 开始同步 {dates[0]} ~ {dates[-1]}（共 {days} 天）=====")

    rows_all: list[Row] = []
    for d in dates:
        rows = collect(cp, d)
        if not rows:
            log(f"{d} 没有采集数据，跳过", "WARN")
            continue
        for r in rows:
            log(f"  {r.date} {r.user:<18} 父={r.parent:>8}  子={r.sub:>8}  质检={r.inspected:>8}  通过={r.passed:>8}  通过率={r.pass_rate or '-'}")
        rows_all.extend(rows)

    if not rows_all:
        log("该时间范围内没有采集数据，跳过写入", "WARN")
        if csv_path:
            write_csv(cp, rows_all, csv_path)
        return 0

    if csv_path:
        write_csv(cp, rows_all, csv_path)
    if dry_run:
        log("dry-run：不写入飞书")
        return 0

    lark = LarkCli(cp)
    if not lark.ensure_app_configured():
        raise AuthRequired("飞书未配置应用凭证，请在「设置」中填写 App ID / App Secret 后重新授权")
    if not lark.is_authorized():
        raise AuthRequired("飞书授权已过期，请点击「重新授权飞书」")

    records, columns = lark.export_records()
    names = {k: cp.get("fields", k) for k in ("date", "user", "parent_duration", "sub_duration", "inspected_duration", "passed_duration", "pass_rate")}
    missing = [n for n in names.values() if n not in columns]
    if missing:
        raise RuntimeError(f"飞书表格中找不到字段：{missing}")

    user_field = names["user"]
    date_field = names["date"]
    index: dict[tuple[str, str], str] = {}
    for rec in records:
        key = (normalize_date(rec.get(date_field)), str(rec.get(user_field) or "").strip())
        if key[1]:
            index[key] = rec.get("record_id", "")

    unit = cp.get("options", "unit", fallback="hours")
    to_create: list[dict] = []
    to_update: dict[str, dict] = {}
    for r in rows_all:
        fields = build_fields(r, names, columns, unit)
        rid = index.get((r.date, r.user))
        if rid:
            to_update[rid] = fields
        else:
            to_create.append(fields)

    updated = lark.update_records(to_update) if to_update else 0
    created = lark.create_records(to_create) if to_create else 0
    log(f"同步完成：{dates[0]} ~ {dates[-1]} 新增 {created} 条，更新 {updated} 条")
    return created + updated


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


def run_gui(cp: configparser.ConfigParser) -> None:
    root = tk.Tk()
    App(root, cp)
    root.mainloop()


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
