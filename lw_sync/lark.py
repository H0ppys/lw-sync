"""lark-cli 封装（授权、读写多维表格、内嵌 exe 释放）（拆分自 sync_app.py 第 322-576 行）"""
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
from .logging_util import log  # noqa: F401
from .paths import CREATE_NO_WINDOW, app_dir  # noqa: F401




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
