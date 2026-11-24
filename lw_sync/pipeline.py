"""采集 → 聚合 → 写表主流程（拆分自 sync_app.py 第 656-757 行）"""
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
from .lark import AuthRequired, LarkCli  # noqa: F401
from .lightwheel import LightwheelClient  # noqa: F401
from .logging_util import log  # noqa: F401
from .rows import Row, aggregate_rows, build_fields, normalize_date  # noqa: F401




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
