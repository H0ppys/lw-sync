# 打包产物解包报告（LWSync）

## 对象

| 项 | 值 |
| --- | --- |
| 文件 | `作业记录同步-便携版\LWSync.exe`、`LWSync-cli.exe` |
| 大小 | 26,205,447 字节（各 24.99 MB） |
| 打包器 | PyInstaller 6.x（onefile） |
| Python | 3.12（PYZ magic `cb0d0d0a`，内嵌 `python312.dll`） |
| 同目录 | `config.ini`、`README.md`、30 个 `records_*.manifest.json`、`token_cache.json` |

## 解包结果

| 项 | 值 |
| --- | --- |
| CArchive 条目 | 952（含 tcl/tk 数据文件、`.pyd` 扩展模块、`lark-cli.exe` 等二进制） |
| PYZ 模块 | 133 |
| 入口脚本 | `sync_app`（pyc，116,788 字节）= 本仓库 `legacy/sync_app.py` |
| 引导模块 | `pyimod01_archive`、`pyimod02_importers`、`pyimod03_ctypes`、`pyimod04_pywin32`、`pyi_rth_inspect`、`pyi_rth__tkinter` |

## 方法与限制

1. 从 exe 尾部定位 cookie `MEI\014\013\012\013\016`（偏移 26,205,359），读出 `archive_length/toc_offset/toc_length/pyver/python_libname`；
2. 按 CArchive TOC（`!IIIIIB` + 变长 name）遍历，只提取 `.pyz` 与入口 pyc，其余条目仅记录元数据（952 条清单见解包工作目录 `REPORT.json`）；
3. PYZ 头部布局：`b'PYZ\0'` + 4B pyc magic（`cb0d0d0a`=3.12）+ 4B TOC 偏移（BE）；TOC 为 `marshal` 序列化的 `[(name,(pos,len,ulen)),…]`，成功读出 **133 个模块名**；
4. **未做字节码反汇编**：本机解释器为 3.15.2（magic `520e0d0a`），`marshal` 无法安全加载 3.12 的 code object（跨版本会直接崩溃），因此只导出 `modules.list.txt` 与 pyc 原始 bytes。需要反汇编时用 Python 3.12 + `decompyle3/uncompyle6` 或 `xdis` 处理提取出的 `sync_app` pyc。

## 核对结论

- 入口 pyc `sync_app` 与 `legacy/sync_app.py`（1649 行）同源：模块级符号数量、`App` / `DatePicker` / `ReauthDialog` / `LwLoginDialog` / `SettingsDialog` / `LarkCli` / `LightwheelClient` / `Row` 等类均存在；
- `LWSync.exe` 与 `LWSync-cli.exe` 的 CArchive TOC 完全一致（同一份源码，只差 bootloader 的 console 标志）；
- 未发现额外的反调试、联网上报或混淆逻辑（除 PyInstaller 自带引导模块外，PYZ 内只有 133 个标准库/入口模块，无第三方包）。

## 未纳入仓库

解包目录（`PYZ.pyz`、`sync_app` pyc、952 条 `REPORT.json`）保留在分析工作区，不入库。
