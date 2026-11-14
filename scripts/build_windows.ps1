param([string]$Version = "0.4.0-beta.1")
$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot -Parent)
python -m pip install -r requirements.txt "pyinstaller>=6.16,<7"
if ($LASTEXITCODE -ne 0) { throw "Dependencies failed" }
python -m PyInstaller --noconfirm --clean --windowed --name NovelVisualizer --add-data "novelviz/web;novelviz/web" --add-data "novelviz/demo;novelviz/demo" --add-data "LICENSE;." --add-data "THIRD_PARTY_NOTICES.md;." --add-data "licenses;licenses" main.py
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed" }
@"
墨境 v$Version 测试版（非稳定正式版）

完整解压本目录后，双击 NovelVisualizer.exe。
不需要安装 Node.js、Docker 或 Python。不要单独移动 exe，保留 _internal 目录。
启动先进入访客工作区，实际操作时选择或创建本地账户。
已有资料：在账户窗口选择原数据根目录；升级前建议备份用户目录。
默认数据保存在系统文档目录下“墨境用户资料”，不写入安装目录。

源代码与完整许可：https://github.com/yourwjd123/novel-visualizer
本包未经代码签名，Windows 可能显示未知发布者。
模型需自行配置；不会自动调用付费服务或重试失败请求。
"@ | Set-Content -Path "dist/NovelVisualizer/测试版本说明.txt" -Encoding UTF8
Copy-Item README.md, CHANGELOG.md, TEST_REPORT.md -Destination dist/NovelVisualizer
Compress-Archive -Path dist/NovelVisualizer -DestinationPath "dist/NovelVisualizer-v$Version-windows-x64-test.zip" -Force
