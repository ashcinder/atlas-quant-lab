# 私有部署与运维

更新：2026-10-29；当前操作说明按 QuantJudge `672e8b8` 核对。目标为本机或受控私网研究环境，虽然已有账号隔离，也不能直接视为公网多租户生产就绪。源码分享见 [DEPLOY](../DEPLOY.md)，本地开发见 [README](../README.md)。

## 当前边界

- API/Web 双服务共用来源，后端使用一个 worker；研究、提醒和定投调度在进程内，不能直接水平扩容。
- 已有账号、个人账本和策略资源隔离。交易所测试网可按实例显式开启自动执行，实盘接口默认关闭且要求所有者逐笔确认，见 [交易指南](TRADING.md)。BKC依赖真实链回执，不是通用沙盒支付；人民币支付未实现。
- Compose不启动Supervisor、模型、gVisor或真实Nitro环境；链连接、平台签名、receipt验证与链上锚定分别判断。
- 根 `Dockerfile`、`deploy/build.sh`、`package.sh` 的旧单镜像路线未维护。`deploy/run.sh` 已停用，执行只报错退出，不删除、启动或停止容器。

## 构建前置条件

需要Docker Engine及支持 `--wait` 的Compose v2。干净Git克隆还缺少 `strategy/zkvm/release/linux-amd64/atlas-zkvm`，不能直接构建当前API镜像。

`deploy/backend.Dockerfile`要求Linux x86-64 ELF、固定SHA-256和固定v2 image ID：

- 二进制SHA-256：`b62a2d6ed3dd49e0f02762f8291aab2f075c4f0686290844113779d797d582b3`。
- v2 image ID：`02b08452a95d405b82b52dd475fc448639da4465123324711b369d7e18c27cd4`。

制品必须来自可追溯、已审核的Linux构建，不能使用macOS二进制。在Linux构建主机安装工程要求的Rust/RISC Zero工具链后，可按 [本地Proof工具构建与profile核对](CODE_TO_PROOF_WALKTHROUGH.md#0-准备本地证明工具) 构建。**从源码构建成功不保证得到上述固定文件哈希**；若架构、哈希或profile不匹配，应停止容器发布并另行审核制品来源，不改登记值或Dockerfile来绕过。

已取得并核对候选制品后，从仓库根目录依次执行，任一步失败即停止：

```bash
# 此处假定经审核的Linux候选制品位于本地target/release；先完成上述profile核对。
printf '%s  %s\n' \
  b62a2d6ed3dd49e0f02762f8291aab2f075c4f0686290844113779d797d582b3 \
  strategy/zkvm/target/release/atlas-zkvm | sha256sum --check --status
mkdir -p strategy/zkvm/release/linux-amd64
install -m 755 strategy/zkvm/target/release/atlas-zkvm strategy/zkvm/release/linux-amd64/atlas-zkvm
```

镜像构建还会验证ELF架构和image ID。`compose.zkvm.yaml`的 `TRINE_LINUX_ZKVM_BINARY` 只控制运行时只读挂载，不能替代基础镜像所需的构建制品。没有该制品时，可使用README的双终端开发路径；不要宣称已完成容器验收。

## 运行

首次部署先阅读下文的数据归属和恢复要求。需要可选配置时复制 `.env.example` 到本机 `.env` 并编辑，不能提交凭据。该示例含公开演示测试密钥和demo=true：部署前必须同时设置 `VITE_TRINE_DEMO_MODE=false`、清空 `VITE_TRINE_TEST_PRIVATE_KEY`，重建前端并检查最终配置；不能原样复制上线，也不要向公开测试账户充值。从仓库根目录执行：

```bash
docker compose config --quiet
docker compose up --build --detach --wait --wait-timeout 180
docker compose ps
```

访问 `http://127.0.0.1:8080`。只有Web映射宿主回环端口，API不发布端口，浏览器通过同源 `/api` 访问。首次注册从空账本开始，历史本机测试账号、策略、交易或Proof不会随源码生成。数据卷包含数据库和隐藏密钥；开发数据目录与Compose卷彼此独立。

```bash
curl --fail http://127.0.0.1:8080/healthz
curl --fail http://127.0.0.1:8080/api/v1/health
docker compose logs --tail 100 api web
```

健康检查只说明服务状态，不证明ZKP、交易所或TEE已验收。不得把绑定地址改为公网来跳过认证与部署审查。

## Supervisor与付款恢复

API默认RPC为 `http://127.0.0.1:42515`，在容器中指向容器自身；Compose没有Supervisor服务。付款部署必须设置容器实际可达的 `QUANTJUDGE_SUPERVISOR_RPC_URL`，当前浏览器keystore在本地离线签名，再由后端广播，浏览器不需要直连RPC；返回的订单与网络信息来自后端。不要把宿主机的回环地址原样当作容器地址。

订单绑定chain ID1051和创世哈希；仅chain ID相同不能换链恢复。持续服务需固定且可恢复的链状态，RPC重启必须保持网络身份。具体金额、收款、规范区块与回执检查见 [BKC工作流](TRINE_SERVICE_WORKFLOW.md)。

`./start.sh` 使用入库的 `contracts/supervisor-src` 与隔离runner，需要Go、Node、本机 `/usr/local/mysql/bin/mysqld`、后端虚拟环境和前端依赖。默认RPC42519，每次新建临时目录与创世块，退出停止本轮进程；8000端口占用时拒绝启动。这是一次性开发链，不能恢复另一创世哈希的旧付款订单。它也不代表分布式共识或跨存储崩溃原子性已验收。

## 持久化、升级与停止

默认Compose项目为 `atlas-quant`，卷为 `atlas-quant_atlas-data`，挂载 `/app/backend/.data`。实际旧部署可能采用其他项目名、绑定目录或容器可写层，必须先核对。新默认项目名可能创建空卷，不能自动继承原数据。

旧单容器升级前停止写入并备份完整实际数据目录，包括数据库、缓存、策略密文和隐藏密钥。只保留SQLite不能恢复加密策略。若旧数据尚在容器可写层，切勿先删容器；本项目不提供自动迁移或清理步骤。

对已核对原项目及卷映射的双服务部署，可停止后重建，并保持同一配置：

```bash
docker compose stop
# 确认仍使用原项目名、原卷和已核验制品后：
docker compose up --build --detach --wait
```

不要删除正式卷，不要在运行中覆盖数据库。旧无归属记录保留 `local`，不会自动归给新注册者；迁移归属需单独确认。

### 一致性备份与恢复

在仓库外创建新的受控备份目录；下例假定已处于正确的Compose项目，备份目录通过 `mktemp` 创建，不能覆盖旧备份：

```bash
backup_dir="$(mktemp -d "$HOME/atlas-backup-XXXXXXXX")"
chmod 700 "$backup_dir"
docker compose stop api
docker compose cp api:/app/backend/.data/. "$backup_dir/"
# 确认复制成功后再恢复写入；失败时先处理备份错误。
docker compose start api
```

完整私有备份包含密钥，应加密离线保存，不随源码分享。恢复前先备份现状并停止写入，将完整快照恢复到独立新卷，在隔离项目核对 `10001:10001` 所有者、历史记录、签名身份和策略包可读后再切换。不能用新数据目录自动生成的密钥替换原密钥。本轮未执行生产备份或迁移。

## 依赖与CI范围

前端使用npm与 `package-lock.json`；后端使用精确版本锁文件，未提供依赖哈希完整性锁。基础镜像标签尚未锁定digest。当前CI执行前端lint/测试/build和Python3.12/3.14后端pytest、依赖检查，不自动部署，不包含镜像或链验收。

`python3 deploy/smoke.py` 是需要Docker和已核验制品的独立容器检查，使用随机临时项目与测试卷；源码CI通过不能代替它，也不能代替生产恢复演练。历史Actions数字仅对应当时提交。

## OCR、HTTPS与可选执行

OCR的worker和WASM执行代码由本站构建资源提供；语言模型首次加载仍可能需要网络，离线须预缓存。图片在浏览器内识别，不上传第三方OCR服务。

HTTPS代理部署应设置 `ATLAS_COOKIE_SECURE=true`；回环HTTP开发默认false。核对实际来源和Cookie属性，不无条件信任转发头。显式会话密钥至少32字符，否则保留自动生成配置。真实Nitro、AI提供方和gVisor仍需分别配置、验收，见 [执行与信任边界](EXECUTION_TRUST.md)。

公开部署前仍需账号与资源限额、审计、外置任务与备份恢复等独立验收；本指南不构成公网生产就绪承诺。

## 历史部署检查点（2026-09-07）

以下保留原验收及失败记录，不作为当前镜像、Docker运行状态或外部服务可用性的保证：

本次本地 `docker compose config --quiet` 通过。本机 Docker 守护进程未运行，且镜像仓库连接超时，因此没有在本机启动容器。

随后 GitHub Linux 环境已完成真实验证：提交 `1907430` 的 [Actions #34077168667](https://github.com/ashcinder/atlas-quant-lab/actions/runs/34077168667) 中，前端、后端、容器三个 job 全部通过。`deploy/smoke.py` 实际构建并启动了镜像，验证同源路由、非 root / 只读后端、离线回测，以及重建后数据库记录、签名身份和包加密密钥的一致性。测试只使用独立临时项目与数据卷，没有部署公开服务。

这项验证不覆盖本机 Docker 环境、生产数据备份恢复演练、容器 ZKP 验证器或真实 AI / TEE。不能用容器健康接口在线代替这些检查。

对公网开放之前，还需要独立审查身份鉴别与租户权限，并完成 TLS、速率和资源限制、外置任务队列、可观测性、备份恢复演练、依赖安全审查，以及 AI / 通用策略 Runner / TEE 的隔离与可信执行实现。

## 历史CI说明更正（原检查点2026-09-30）

当时记录“尚未提交触发远端Actions”仅是当时检查点；后续已经发布源码提交。当前CI范围以仓库工作流和对应提交结果为准。决赛部署记录见 [历史决赛升级](FINAL_UPGRADE.md)，不等于本轮部署或容器重验。
