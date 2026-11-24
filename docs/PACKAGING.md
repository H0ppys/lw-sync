# 打包说明（lw-sync）

## 原有产物

| 文件 | 大小 | 类型 | 说明 |
| --- | --- | --- | --- |
| `LWSync.exe` | 24.99 MB | PyInstaller onefile，`console=False` | 图形界面版 |
| `LWSync-cli.exe` | 24.99 MB | PyInstaller onefile，`console=True` | 命令行版（计划任务用） |
| `config.ini` | — | 运行期配置 | 与 exe 同目录 |
| `logs\` | — | 运行期日志 | 自动创建 |

打包 Python 为 **3.12**（内嵌 `python312.dll`），两个 exe 的 CArchive 都有 952 个条目、PYZ 有 133 个模块（详见 [UNPACK.md](UNPACK.md)）。

## 拆分后打包

```bash
# 先准备 lark-cli.exe（49 MB，从 Lark 官方 CLI 发行包或原便携目录取）
python -m PyInstaller --onefile --windowed --add-binary "lark-cli.exe;." --name LWSync main.py
python -m PyInstaller --onefile --console  --add-binary "lark-cli.exe;." --name LWSync-cli main.py
```

要点：
- `--add-binary` 把 `lark-cli.exe` 打进 onefile；`lark.prefer_exe_path()` 会优先用 `%LOCALAPPDATA%\LWSync\lark-cli.exe`（首次运行释放），其次取 exe 同目录，避免每次启动解压 49 MB；
- `paths.app_dir()` 用 `sys.frozen` 判分支，`config.ini`/`logs` 落在 exe 旁；
- tkinter 由 PyInstaller hook 自动收集；无第三方 Python 依赖，无需 `hiddenimports`；
- 若要减体积，可对 lark-cli 改用 onedir 模式（`--onedir`），代价是分发变成目录。

## 体积构成（原产物实测）

| 部分 | 约 |
| --- | --- |
| `python312.dll` | 6–7 MB |
| `lark-cli.exe`（内嵌） | 49 MB 压缩后 ~20 MB |
| tcl/tk 运行时 | 2–3 MB |
| 应用代码（`sync_app` pyc） | 0.12 MB |

> 内置 `lark-cli` 占了大头，因此 CLI 版与 GUI 版体积相同。
