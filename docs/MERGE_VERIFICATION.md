# QuantJudge 与投资日志 main 的合并

日期：2026-09-08。基线：main `b7e06dc`、QuantJudge `cc1a434`。

## 整合内容

- 保留注册登录、个人账本、OCR、回测与研究的账户隔离，加入策略市场、策略实验室、金融指标和私密执行/证明模块。
- 登录中间件支持有界 multipart 包/证明上传；浏览器传递会话 Cookie，分别处理会话过期和开发者凭证错误。
- 策略项目和订阅增加 owner_id；私有策略/研究只能关联本账号制品，包/工作流关联需要对应开发者凭证。旧无归属记录保持 local，不自动归给新注册用户。
- 前端统一 npm；新版样式限定于策略工作区；容器保留 PostCSS/OCR、同源认证和持久化密钥。旧单镜像 Dockerfile 保留。

## 本地验证

- 后端 Python 3.12：256 项测试通过。命令：`PATH=/opt/homebrew/opt/openssl@3/bin:$PATH .venv/bin/python -m pytest -q`。
- 前端：42 项 Vitest 与 61 项账本测试通过；`npm run build` 通过；`npm run lint` 无错误，保留 chart.tsx 两项既有 Fast Refresh 警告。
- 新集成测试覆盖 >4 MB 的合法策略包上传/下载、登录/来源/开发者凭证边界、证明上传传输、账号间项目/同名策略隔离、私密包关联授权、订阅隔离以及旧项目 owner 列迁移。
- `git diff --check` 和 `docker compose config --quiet` 通过。
- 初次后端失败为新测试缺失 client fixture 以及 macOS 系统 LibreSSL 不支持严格证书验证参数；已补 fixture，并使用 OpenSSL 3 完成 TEE 测试，没有放宽证书验证。

## 部署边界

本地 Docker 守护进程不可用，Linux 镜像/容器检查由 GitHub Actions 执行。以上单元/传输测试不宣称真实 TEE 硬件、AI 推理或 ZKP 证明生成完成。既有真实证明能力边界仍见 EXECUTION_TRUST.md 与 ZKP.md。

未操作真实账本、迁移生产数据或部署服务器。已有单容器安装升级到双容器前需按 DEPLOYMENT.md 保留原 Compose 项目名/完整数据卷；不要因项目名变化连接到新空卷。
