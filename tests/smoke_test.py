"""冒烟测试：拆分后的 lw_sync 包可导入、关键符号齐全、CLI 解析正常。"""
from __future__ import annotations

import importlib
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

MODULES = [
    "lw_sync.paths",
    "lw_sync.logging_util",
    "lw_sync.config",
    "lw_sync.http",
    "lw_sync.lightwheel",
    "lw_sync.lark",
    "lw_sync.rows",
    "lw_sync.pipeline",
    "lw_sync.ui_app",
    "lw_sync.ui_datepicker",
    "lw_sync.ui_dialogs",
    "lw_sync.gui",
    "lw_sync.tasks",
    "lw_sync.cli",
]

REQUIRED = {
    "lw_sync.paths": ["APP_NAME", "DEFAULT_CONFIG", "app_dir", "config_path", "log_dir"],
    "lw_sync.config": ["load_config", "save_config"],
    "lw_sync.http": ["http_json", "make_ssl_context"],
    "lw_sync.lightwheel": ["LightwheelClient", "jwt_exp"],
    "lw_sync.lark": ["LarkCli"],
    "lw_sync.rows": ["Row", "aggregate_rows", "build_fields"],
    "lw_sync.pipeline": ["collect", "write_csv", "sync"],
    "lw_sync.cli": ["build_parser", "main"],
}


def main() -> int:
    for name in MODULES:
        importlib.import_module(name)
    for name, syms in REQUIRED.items():
        mod = importlib.import_module(name)
        for sym in syms:
            assert hasattr(mod, sym), f"{name} 缺少 {sym}"
    pkg = importlib.import_module("lw_sync")
    public = [n for n in dir(pkg) if not n.startswith("_")]
    assert len(public) >= 50, f"re-export 符号过少：{len(public)}"
    # 解析器自检（不执行网络/写表）
    parser = importlib.import_module("lw_sync.cli").build_parser()
    opts = parser.parse_args(["sync", "--days", "3", "--dry-run"])
    assert opts.days == 3 and opts.dry_run is True
    print(f"OK modules={len(MODULES)} reexport={len(public)} argv-parse-ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
