# 私有部署与运维

本指南对应 2026-09-07 的工作空间重构。部署目标是**单用户本机或受控私网研究环境**，不是可直接向公众开放的 SaaS。

## 当前边界

- 没有平台级用户认证、租户隔离和完整配额控制。不可直接绑定公网地址。
- 不连接真实交易账户；支付仍为沙盒。
- 研究任务与提醒在进程内运行，后端必须只有一个 worker，不能直接水平扩容。
- 容器提供行情、规则与组合回测、策略归档和平台签名服务。基础镜像不包含 zkVM 验证器：`verifier_ready` 会为 false，不能声称容器已完成 ZKP 验收。
- 本机 macOS 验证器不能复制到 Linux 容器使用；需要单独构建和审计对应平台的 RISC Zero 验证器镜像，核对 profile/image ID，并跑有效与篡改 receipt 测试。
- Supervisor 不挂载、不启动、不修改。默认 RPC 指向容器自己的回环地址，明确不可用。即使接入节点，链连接成功也不表示报告已上链。

## 运行

需要已经运行的 Docker Engine / Docker Desktop 和支持 `--wait` 的 Docker Compose v2。在仓库根目录执行：

```bash
docker compose config --quiet
docker compose up --build --detach --wait --wait-timeout 180
docker compose ps
```

浏览器访问 `http://127.0.0.1:8080`。可选配置见根目录 `.env.example`；默认无需创建 `.env`。只有前端映射到 `127.0.0.1`，后端不发布端口，浏览器通过同源 `/api` 访问 API。不要把绑定地址改成 `0.0.0.0` 来绕过认证边界。

```bash
curl --fail http://127.0.0.1:8080/healthz
curl --fail http://127.0.0.1:8080/api/v1/health
docker compose logs --tail 100 api web
```

也可点击应用顶部“系统状态”查看后端、证明配置及链连接；这个检查不提交交易、报告或证明。

## 持久化、升级与停止

`atlas-quant_atlas-data` 命名卷映射到 `/app/backend/.data`，同时保存数据库、行情缓存、策略包密文、加密密钥和签名密钥。**数据库与密钥必须一起保留**。仅备份 SQLite 文件不能恢复私密策略包。

```bash
# 停止但保留数据
docker compose down
# 更新代码后重建，仍使用原数据卷
docker compose up --build --detach --wait
```

不要对正式项目执行 `docker compose down --volumes`。不要把 `.data`、备份、开发者凭证、私密策略或证明 witness 上传 GitHub。

### 一致性备份

先停止后端，防止 SQLite 和文件状态在备份过程中变化。以下命令示范导出整个数据目录；指定一个新的、明确的备份目录，不覆盖旧备份：

```bash
mkdir -m 700 atlas-backup-2026-09-07
docker compose stop api
docker compose cp api:/app/backend/.data/. ./atlas-backup-2026-09-07/
docker compose start api
```

该目录含密钥与私密资料，需使用受控、加密的离线存储，不要放进仓库。以上只是操作说明，本次没有执行实际用户数据备份。

恢复前，先备份当前卷并停止后端；将完整快照恢复到一个独立的新卷，在隔离的 Compose 项目中确认文件所有者为 `10001:10001`，验证历史记录、签名公钥身份与策略包可读取后再切换。不要在运行中的服务上覆盖数据库，也不要让空数据目录生成的新密钥替代备份密钥。

## 可复现依赖与 CI

- 前端直接依赖及 pnpm 版本固定，容器与 CI 使用 `pnpm install --frozen-lockfile`。
- `backend/requirements.lock` 是测试环境的精确版本清单；`requirements-dev.lock` 补充测试工具。它们不是带哈希的供应链完整性锁。
- 镜像使用精确版本标签，但尚未锁定 digest。镜像下载仍依赖上游仓库可用性。
- `.github/workflows/ci.yml` 包含前端构建 / lint / 测试、隔离后端测试和容器冒烟测试。它不向服务器部署，也不推送镜像。
- `python deploy/smoke.py` 会创建随机命名的独立测试项目，验证同源路由、非 root、离线回测及容器重建后数据库 / 密钥持久化；最后仅移除这个随机测试项目及其测试卷，不触碰正式数据卷。

## 验证记录与尚未通过的检查

本次本地 `docker compose config --quiet` 通过。本机 Docker 守护进程未运行，且镜像仓库连接超时，因此没有在本机启动容器。

随后 GitHub Linux 环境已完成真实验证：提交 `1907430` 的 [Actions #34077168667](https://github.com/ashcinder/atlas-quant-lab/actions/runs/34077168667) 中，前端、后端、容器三个 job 全部通过。`deploy/smoke.py` 实际构建并启动了镜像，验证同源路由、非 root / 只读后端、离线回测，以及重建后数据库记录、签名身份和包加密密钥的一致性。测试只使用独立临时项目与数据卷，没有部署公开服务。

这项验证不覆盖本机 Docker 环境、生产数据备份恢复演练、容器 ZKP 验证器或真实 AI / TEE。不能用容器健康接口在线代替这些检查。

对公网开放之前，还需要独立完成身份鉴别与租户权限、TLS、速率和资源限制、外置任务队列、可观测性、备份恢复演练、依赖安全审查，以及 AI / 通用策略 Runner / TEE 的隔离与可信执行实现。
