"""数据行模型、聚合、字段映射（拆分自 sync_app.py 第 577-655 行）"""
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
