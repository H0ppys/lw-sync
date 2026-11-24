# 脱敏说明（lw-sync）

| 位置 | 字段 | 处理 |
| --- | --- | --- |
| `lw_sync/paths.py` | `DEFAULT_CONFIG["feishu"]["app_token"]` | → `<FILL_APP_TOKEN>` |
| `lw_sync/paths.py` | `DEFAULT_CONFIG["feishu"]["table_id"]` | → `<FILL_TABLE_ID>` |
| `lw_sync/paths.py` | `DEFAULT_CONFIG["feishu"]["view_id"]` | → `<FILL_VIEW_ID>` |
| `legacy/sync_app.py` | 同上三处 | 同步替换（故 legacy 非 100% 逐字节） |
| `config.example.ini` | `[lightwheel] username/password`、`[feishu] app_token/table_id/view_id` | → `<FILL_*>` |

## 未纳入仓库

- `config.ini`（含光轮账号密码、飞书 app_token）、
- `lark-cli.exe`（49 MB 官方二进制）、
- `token_cache.json`（飞书 user access token）、
- `records_*.manifest.json` ×30、`*.ndjson`（业务数据，含采集员工号与时长）、
- `logs/`。

## 使用提醒

光轮账号密码以明文写在 `config.ini`（原设计如此）。放到多人可读的机器上时，建议改用系统凭据管理器或至少 `icacls` 限制 ACL——本仓库不提供凭据存储实现，只保留配置读取路径。
