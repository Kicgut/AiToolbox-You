# 仓库更新

本项目以 Git 仓库形式发布。克隆后无需下载或生成协议 schema；完整 schema、数据库、日志和本机更新设置都留在被忽略的本地目录中。

## 日常使用

1. 通过 `run.bat` 启动应用，打开“设置 → 仓库更新”。
2. 点击“检查更新”。页面只检查固定的官方 `origin/main`，不会接受或执行外部 URL。
3. 有更新时点击“下载并应用”，成功后重启应用。更新不会重装或升级 Codex、Claude、CC Switch 等外部软件。

若存在未提交改动、当前不在 `main`、本地领先远端，或有 Workbench Run 正在执行，按钮会被禁用或请求会被拒绝。请先自行提交、暂存或处理这些改动；应用不会自动 stash、reset、merge 或覆盖文件。

## 自动更新

在“设置”开启“下次启动前自动安全更新”后，本机设置会保存到 `data/ai_workbench/repository_update.json`（不进入 Git）。下一次由 `run.bat` 启动时，启动器会先执行一次只允许快进的检查：仅在官方远端、`main` 分支和干净工作树同时满足时拉取更新；否则静默跳过并保持现状。

自动更新不在服务运行期间改写仓库，也不要求生产用户安装 Node.js。前端静态产物随仓库提交；`run.bat` 会在启动时按 `requirements.txt` 对齐本项目的 Python 依赖（不升级外部软件）。

## 维护者更新协议契约

`app/ai_workbench/execution/codex_app_server_manifest.json` 是受版本控制的最小协议契约；`.artifacts/tmp/` 中的完整 schema 是可再生成的本地校验证据，不进入 Git。升级运行时兼容层时，应更新 manifest、代码和测试并一同提交。
