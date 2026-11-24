# lw-sync

光轮人类数据平台（Lightwheel）「采集员维度汇总」→ 飞书多维表格「作业记录」的同步工具（LWSync v2.7.0）。图形界面一键同步 / 预览 / 重新授权，命令行版供计划任务调用。

## 1. 原始来源

| 项 | 值 |
| --- | --- |
| 来源路径 | `C:\Users\Administrator\Desktop\软件\lw-sync\`（源码）与 `作业记录同步-便携版\`（打包产物） |
| 原始单文件 | `sync_app.py`（1649 行） |
| 打包配置 | `LWSync.exe`（GUI，onefile，24.99 MB）、`LWSync-cli.exe`（CLI，onefile） |
| 便携包版本 | `作业记录同步-便携版-v2.7.zip`（49.24 MB） |
| 版本 | `VERSION = "2.7.0"` |

## 2. 目录结构

```
lw-sync/
  main.py                     # 入口（GUI / CLI 同一可执行文件）
  lw_sync/                    # 拆分后的包（14 个模块）
    paths.py                  # 常量、DEFAULT_CONFIG、目录解析
    logging_util.py           # 日志汇聚（文件 + 界面回调）
    config.py                 # config.ini 读写
    http.py                   # TLS 上下文 + JSON HTTP
    lightwheel.py             # 光轮平台客户端（登录态、看板接口）
    lark.py                   # lark-cli 封装（授权、读写表格、内嵌 exe 释放）
    rows.py                   # 行模型、聚合、字段映射
    pipeline.py               # 采集 → 聚合 → 写表
    ui_app.py                 # 主窗口
    ui_datepicker.py          # 日期选择弹窗
    ui_dialogs.py             # 重新授权 / 光轮登录 / 设置
    gui.py                    # GUI 启动入口
    tasks.py                  # 自检子命令 + 计划任务
    cli.py                    # argparse 入口
  legacy/sync_app.py          # 原单文件（已脱敏）
  docs/                       # 架构 / 拆分映射 / 打包 / 解包报告 / 脱敏
  tests/smoke_test.py
  config.example.ini
```

## 3. 安装与运行

```bash
# 纯标准库（tkinter + urllib + ssl），外部依赖只有 lark-cli
python main.py                                  # 图形界面
python main.py sync --days 7                    # 最近 7 天
python main.py sync --date 2026-11-24 --dry-run # 只看结果
python main.py sync --csv out.csv               # 同时落 CSV
python main.py watch --interval 7200            # 常驻每小时同步
python main.py test                             # 账号/授权自检
python main.py config                           # 打开配置文件
python main.py install-task --hours 2
python main.py uninstall-task
```

`lark-cli.exe` 定位顺序：`config.ini [feishu] lark_cli` → 同目录 → `PATH`。打包版内置 `lark-cli`，首次运行释放到 `%LOCALAPPDATA%\LWSync\lark-cli.exe`。

## 4. 模块说明

| 模块 | 职责 | 关键符号 |
| --- | --- | --- |
| `paths` | `APP_NAME/VERSION/DEFAULT_CONFIG/TASK_NAME_DEFAULT`、`app_dir`、`config_path`、`log_dir` | — |
| `logging_util` | 多路日志（文件 + UI 队列）、控制台编码设置 | `log`、`add_log_sink`、`setup_console` |
| `config` | `config.ini` 读取（含默认值合并）与保存 | `load_config`、`save_config` |
| `http` | 自定义 CA / 关闭校验、`http_json` 统一请求与错误包装 | `make_ssl_context`、`http_json` |
| `lightwheel` | 登录（账号密码 → JWT）、`list-collectors` 看板接口、`jwt_exp` | `LightwheelClient`、`LoginRequired` |
| `lark` | 授权流程（扫码/授权链接）、写入多维表格、内嵌 exe 释放 | `LarkCli`、`AuthRequired` |
| `rows` | `Row` 数据类、按采集员/日期聚合、字段映射与数值格式 | `aggregate_rows`、`build_fields` |
| `pipeline` | 日期解析 → 采集 → 聚合 → 写表 / 落 CSV | `sync`、`collect` |
| `ui_app` | 状态区、日期与范围选择、按钮、日志窗、自动刷新 | `App` |
| `ui_datepicker` | 日历弹窗 | `DatePicker` |
| `ui_dialogs` | 重新授权飞书、光轮登录、设置三个对话框 | `ReauthDialog`、`LwLoginDialog`、`SettingsDialog` |
| `gui` | 建窗并进入 mainloop | `run_gui` |
| `tasks` | `config/test/watch` 与 Windows 计划任务 | `install_task`、`remove_task`、`task_query` |
| `cli` | argparse 与异常兜底（`AuthRequired` → 退出码 2） | `build_parser`、`main` |

## 5. 配置（`config.example.ini`）

```ini
[lightwheel]
base_url = https://data.lightwheel.net
username = <FILL_USERNAME>
password = <FILL_PASSWORD>

[feishu]
lark_cli =                  ; 留空自动寻找
identity = user
app_token = <FILL_APP_TOKEN>
table_id = <FILL_TABLE_ID>
view_id = <FILL_VIEW_ID>
app_id =
app_secret =

[fields]                    ; 飞书列名映射
date = 采集完成日期
user = 采集员
parent_duration = 父采集时长
sub_duration = 子采集时长
inspected_duration = 质检完成时长（子）
passed_duration = 通过时长（子）
pass_rate = 通过率

[options]
unit = hours
decimals = 2
aggregate = user
date_offset = 0
interval_seconds = 7200
task_name = LWSync_Hourly
insecure_ssl = false
ca_bundle =
sync_days = 7
```

## 6. 打包

原产物是 PyInstaller onefile（`LWSync.exe` / `LWSync-cli.exe`，内嵌 `lark-cli.exe` 与 `python312.dll`）。拆分后：

```bash
python -m PyInstaller --onefile --windowed --add-binary "lark-cli.exe;." --name LWSync main.py
python -m PyInstaller --onefile --console  --add-binary "lark-cli.exe;." --name LWSync-cli main.py
```

详见 [docs/PACKAGING.md](docs/PACKAGING.md)、[docs/UNPACK.md](docs/UNPACK.md)。

## 7. 拆分说明

- 纯搬运拆分，函数体逐字保留；`__init__.py` 全量 re-export（61 个公共符号）。
- 依赖方向 `cli → gui → ui_app → {ui_dialogs, ui_datepicker, pipeline, tasks} → {lark, lightwheel, rows, http, config} → {paths, logging_util}`，拆分器 AST 检查 `cycles = []`。
- `App`（320 行）保持单类：控件布局与 `self.*` 状态强耦合，按 mixin 拆分会改动 200+ 处 `self` 引用；改为独立模块后仍可单独 import 做界面测试。
- 细节见 [docs/SPLIT.md](docs/SPLIT.md)。

## 8. 校验

```bash
python -c "import compileall,sys; sys.exit(0 if compileall.compile_dir('.',quiet=1) else 1)"
python tests/smoke_test.py      # OK modules=14 reexport=61 argv-parse-ok
```
