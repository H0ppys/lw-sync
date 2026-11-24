# 架构说明（lw-sync）

## 数据流

```
config.ini ──► config.load_config ──► ConfigParser
                                        │
        lightwheel.LightwheelClient ◄────┤（base_url / username / password）
     POST /api/humancase/v1/continuous-collect-dashboard/list-collectors
                                        │  raw records
                                        ▼
                    rows.aggregate_rows ──► [Row]（按 producerName 聚合，单位小时）
                                        │
                    rows.build_fields ──► [飞书字段 dict]
                                        ▼
      lark.LarkCli.write / batch-create ──► 飞书「作业记录」多维表格
```

`pipeline.sync()` 是编排入口：解析日期（`resolve_date`，含 `date_offset`）→ `collect()` → 聚合 → 写表或落 CSV → 记录日志与上次同步结果。`watch` 只是按 `interval_seconds` 循环调用 `sync()`。

## 分层

| 层 | 模块 | 约束 |
| --- | --- | --- |
| 常量 | `paths` | import 时只计算路径与默认配置 |
| 基础设施 | `logging_util`、`http` | 日志与 HTTP，不认识业务字段 |
| 配置 | `config` | 依赖 `paths`/`logging_util`；`configure_ssl` 会读 `[options] insecure_ssl/ca_bundle` |
| 外部系统 | `lightwheel`、`lark` | 各自封装一种外部依赖，互不调用 |
| 领域 | `rows` | 纯函数式聚合，无 IO |
| 编排 | `pipeline` | 唯一同时使用 `lightwheel` 与 `lark` 的模块 |
| 界面 | `ui_app`、`ui_datepicker`、`ui_dialogs`、`gui` | 只通过 `pipeline`/`tasks` 触发动作；所有 IO 在后台线程，结果经 `queue` 回主线程 |
| 命令 | `tasks`、`cli` | `cli` 捕获 `AuthRequired`（退出码 2）、其余异常（退出码 1）、`KeyboardInterrupt`（130） |

## 关键设计点

1. **授权是显式的**：`lark` 只负责调用 `lark-cli`；授权过期时抛 `AuthRequired`，UI 弹 `ReauthDialog`（授权链接 + 二维码），CLI 直接以退出码 2 结束，方便计划任务区分。
2. **写表幂等**：按「采集完成日期 + 采集员」先查后写，重复运行只更新不新增（`lark.LarkCli` 内 record-id 缓存）。
3. **凭证不进仓库**：`DEFAULT_CONFIG` 里的 `app_token/table_id/view_id` 已替换为 `<FILL_*>`；真实值只在用户机器的 `config.ini`。
4. **打包兼容**：`lark.prefer_exe_path` 处理 onefile 解包后的临时目录问题（优先取 exe 旁或 `%LOCALAPPDATA%` 已释放的 `lark-cli.exe`）。

## 拆分边界

- `App`（320 行）保留为单类、独立 `ui_app.py`：窗口构建顺序与 `self.*` 状态耦合，拆 mixin 会大面积改 `self` 引用，收益低于风险；需要复用单个面板时从 `ui_app` import `App` 再组合。
- `DatePicker`、三个对话框独立成模块，因为它们各自 `Toplevel`，与主窗口只有回调关系。
