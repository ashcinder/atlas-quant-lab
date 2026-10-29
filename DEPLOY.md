# Atlas Quant Lab 部署与源码分享

更新：2026-10-29；按 QuantJudge `672e8b8` 的实现核对。当前维护入口为 API/Web 双服务 Compose，完整前提、备份与恢复见 [部署指南](docs/DEPLOYMENT.md)。

## 先确认运行方式

- 本机开发优先按 [README](README.md) 用两个终端运行前后端，不需要启动链。
- `./start.sh` 另需 Go、本机 MySQL 和已安装的前后端依赖；它创建全新的临时隔离链，不能恢复已有付款订单。
- Compose 不启动 Supervisor、模型或真实 TEE。构建还需要经校验的 Linux zkVM 制品，干净克隆不能直接跳过该条件。
- 根 `Dockerfile`、`deploy/build.sh` 和 `package.sh` 的旧单镜像路线未维护，不再作为可用部署入口。`deploy/run.sh` 已停用并非零退出；它不调用 Docker，也不删除旧容器。

## 首次使用 Compose

先按 [构建前置条件](docs/DEPLOYMENT.md#构建前置条件) 准备验证器；确认数据卷、服务来源与可选链配置后，将示例里的 `VITE_TRINE_DEMO_MODE=false`、`VITE_TRINE_TEST_PRIVATE_KEY=`（空值）落实到实际构建环境，避免把公开演示密钥编入前端，再在仓库根目录执行：

```bash
docker compose config --quiet
docker compose up --build --detach --wait --wait-timeout 180
docker compose ps
```

访问 `http://127.0.0.1:8080`，API 文档为 `http://127.0.0.1:8080/api/docs`。前端同源代理 API，默认只监听宿主回环地址。会话密钥默认在数据目录生成；若显式设置 `ATLAS_SESSION_SECRET`，至少32字符，不使用示例短字符串。

## 已有安装的升级

先确认旧容器的数据实际位于容器可写层、绑定目录还是命名卷。停止写入并备份数据库、隐藏密钥及策略资料，验证恢复后才切换。旧单容器不能仅靠沿用 Compose 项目名就自动迁入；本指南不执行自动迁移。

双服务部署必须保留原 Compose 项目名和实际卷映射；默认卷为 `atlas-quant_atlas-data`，挂载 `/app/backend/.data`。不要在运行中覆盖数据库，不执行删除卷或自动清理旧容器的命令。具体操作见 [数据保存与备份](docs/DEPLOYMENT.md#持久化升级与停止)。

## 分享源码

只分享已审查、已提交的源码。以下命令在仓库根目录运行；输出文件必须尚不存在：

```bash
archive_path="../atlas-quant-source-$(git rev-parse --short HEAD).tar.gz"
if test -e "$archive_path"; then
  printf '%s\n' '输出文件已存在，请另选路径。' >&2
else
  git archive --format=tar.gz --output="$archive_path" HEAD
fi
```

`git archive HEAD` 只包含当前提交的文件，不包含未提交修改、未跟踪的 `.env`、数据库或私有密钥。Git 中已提交的内容仍需先审查，忽略规则不会抹除已提交的敏感文件。归档仍包含已跟踪的 `.env.example` 等公开示例（其中有公开测试密钥，不能充值或用于真实资金），不包含你未提交的个人配置、依赖或Linux发布制品。接收者必须先关闭demo模式、清空测试密钥，再完成安装与构建前置条件。

源码分享不是数据备份。完整私有备份含密钥、数据库和策略输入，应单独保存在受控的加密存储中，不能随源码分发。
