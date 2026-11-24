# 拆分映射表（lw_sync）

源文件：`C:\Users\Administrator\Desktop\软件\lw-sync\sync_app.py`（共 1649 行，公共 import 区 35 行）

| 原文件 | 行段 | 新模块 | 行数 | 依赖的包内模块 |
| --- | --- | --- | --- | --- |
| sync_app.py | 37-97 | lw_sync/paths.py | 61 | - |
| sync_app.py | 98-142 | lw_sync/logging_util.py | 45 | paths |
| sync_app.py | 143-177 | lw_sync/config.py | 35 | http, logging_util, paths |
| sync_app.py | 178-226 | lw_sync/http.py | 49 | - |
| sync_app.py | 227-321 | lw_sync/lightwheel.py | 95 | http, logging_util, paths |
| sync_app.py | 322-576 | lw_sync/lark.py | 255 | logging_util, paths |
| sync_app.py | 577-655 | lw_sync/rows.py | 79 | logging_util |
| sync_app.py | 656-757 | lw_sync/pipeline.py | 102 | lark, lightwheel, logging_util, rows |
| sync_app.py | 758-1077 | lw_sync/ui_app.py | 320 | config, lark, lightwheel, logging_util, paths, pipeline, tasks, ui_datepicker, ui_dialogs |
| sync_app.py | 1078-1153 | lw_sync/ui_datepicker.py | 76 | - |
| sync_app.py | 1154-1435 | lw_sync/ui_dialogs.py | 282 | config, http, lark, logging_util, paths |
| sync_app.py | 1436-1441 | lw_sync/gui.py | 6 | ui_app |
| sync_app.py | 1442-1564 | lw_sync/tasks.py | 123 | config, lark, lightwheel, logging_util, paths, pipeline |
| sync_app.py | 1565-1649 | lw_sync/cli.py | 85 | config, gui, lark, lightwheel, logging_util, paths, pipeline, tasks |

## 校验

- 每个模块 `py_compile` 通过
- 包 `__init__.py` 全量 re-export 原符号
- 循环依赖：无

## 未在包内解析的名字（需人工确认来源）

```json
{
 "paths": [
  "__file__",
  "os",
  "sys"
 ],
 "logging_util": [
  "Callable",
  "dt",
  "os",
  "sys"
 ],
 "config": [
  "configparser",
  "os"
 ],
 "http": [
  "Any",
  "configparser",
  "json",
  "os",
  "ssl",
  "urllib"
 ],
 "lightwheel": [
  "Any",
  "base64",
  "configparser",
  "json",
  "os",
  "time"
 ],
 "lark": [
  "Any",
  "configparser",
  "dt",
  "json",
  "os",
  "shutil",
  "subprocess",
  "sys",
  "time"
 ],
 "rows": [
  "Any",
  "dataclass",
  "dt"
 ],
 "pipeline": [
  "configparser",
  "csv",
  "dt"
 ],
 "ui_app": [
  "Callable",
  "configparser",
  "dt",
  "messagebox",
  "os",
  "queue",
  "threading",
  "tk",
  "ttk",
  "webbrowser"
 ],
 "ui_datepicker": [
  "Callable",
  "dt",
  "tk",
  "ttk"
 ],
 "ui_dialogs": [
  "Callable",
  "configparser",
  "messagebox",
  "os",
  "threading",
  "tk",
  "ttk",
  "webbrowser"
 ],
 "gui": [
  "configparser",
  "tk"
 ],
 "tasks": [
  "configparser",
  "dt",
  "os",
  "subprocess",
  "sys",
  "time"
 ],
 "cli": [
  "argparse",
  "sys"
 ]
}
```
