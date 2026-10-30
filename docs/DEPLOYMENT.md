# 私有部署与运维

更新：2026-10-30，实现基线 `4be31bf`。当前能力见[版本说明](CURRENT_STATUS.md)；源码分享见[DEPLOY](../DEPLOY.md)。

## 运行路线

- `compose.yaml`：源码构建的Web/API基础栈，默认只映射 `127.0.0.1:8080`；不自行启动Supervisor。
- `compose.release.yaml`：固定镜像Web/API，目标机禁止现场build/pull，具体变量和账户管理见[基础离线部署](LAB_OFFLINE_DEPLOYMENT.md)。
- `compose.release.yaml` 加 `compose.chain.yaml`：Supervisor/MySQL完整四镜像实验室测试链，见[完整链部署](LAB_CHAIN_DEPLOYMENT.md)。不要将只含两镜像的包当作完整包。
- 三种路线均单API worker。共享任务预算每账号1项、全局2项；真实TEE、一般Python Runner和交易所接入另有前提。当前不承诺公网多租户生产就绪。

## 构建前置条件

需要Docker Engine与支持 `--wait` 的Compose v2。干净克隆不含 `strategy/zkvm/release/linux-amd64/atlas-zkvm`；从源码构建API前须提供经审核的Linux x86-64 ELF：

- SHA-256：`b62a2d6ed3dd49e0f02762f8291aab2f075c4f0686290844113779d797d582b3`。
- v2 image ID：`02b08452a95d405b82b52dd475fc448639da4465123324711b369d7e18c27cd4`。

用已有工具检查并安装制品：

```bash
python3 scripts/prepare-linux-verifier.py /reviewed/linux/atlas-zkvm
```

Dockerfile还会检查架构、哈希与profile。重新源码编译不保证相同文件哈希，不能改登记值绕过；本地工具构建见[代码到Proof](CODE_TO_PROOF_WALKTHROUGH.md#0-准备本地证明工具)。macOS文件不能装进Linux镜像；`compose.zkvm.yaml`的运行时挂载也不能跳过基础镜像构建要求。无制品时可做README双终端开发，但Proof依然需要可用验证器。

已交付镜像内含固定Linux验证器；接收方按包清单校验并加载，不需上述源码构建步骤。构建和接收镜像的资源要求不同，完整Proof模式API限额6GiB、主机至少8GiB可用，建议12GiB以上；更大输入性能待验。

## 运行

基础源码容器从仓库根目录执行，先审查 `.env`、项目名和数据卷：

```bash
cp .env.example .env
# 编辑实际来源/端口；公网TLS代理需配置Secure Cookie和明确可信代理地址。
docker compose config --quiet
docker compose up --build --detach --wait --wait-timeout 180
docker compose ps
```

`.env.example`当前demo=false、测试私钥空。前端Dockerfile拒绝开启demo或携带测试私钥。默认本机HTTP Cookie不设Secure；HTTPS发布必须设 `ATLAS_COOKIE_SECURE=true`，Origin含实际非默认端口。Web仅信任配置的宿主代理，API仅信任Web，禁止用星号扩大代理信任。

访问 `http://127.0.0.1:8080`；源码本地可注册，固定镜像发布模板默认关注册，管理员使用隐藏密码输入建号。新账号空库，不包含历史策略/Proof。健康接口：

```bash
curl --fail http://127.0.0.1:8080/healthz
curl --fail http://127.0.0.1:8080/api/v1/health
```

健康成功只说明进程可用。固定镜像部署、TLS渲染与建号请直接按[离线指南](LAB_OFFLINE_DEPLOYMENT.md)，不混用构建方式和ENV。

## Supervisor与付款恢复

源码默认RPC `127.0.0.1:42515`在API容器内指向自身，基础栈需另外提供持久RPC。完整栈API使用内部 `http://supervisor:42515`，Web不访问RPC，MySQL在独立internal网，二者均不发布宿主端口。浏览器keystore离线签名，API只转发已签名原交易，不保管钱包私钥。

付款绑定chain ID1051和创世哈希，还核对成功回执及规范区块。重播使用同一原交易；换链不能恢复订单，不得再付一次来掩盖原任务失败。完整链初始化、测试币分发及同订单Proof恢复见[完整链指南](LAB_CHAIN_DEPLOYMENT.md)。

根 `start.sh` 需Go、Node、前后端依赖及本机MySQL，创建RPC42519的临时新链；它不能恢复持久完整栈或旧订单，不要替换其数据目录。

## 持久化、升级与停止

源码默认项目 `atlas-quant`、业务卷 `atlas-quant_atlas-data`；固定镜像默认项目 `atlas-quant-lab`，用户配置可更名。升级必须保留实际项目与卷，不能用默认值推测旧数据归属。业务目录 `/app/backend/.data` 包含SQLite、行情缓存、包密文、签名及加密密钥，缺密钥不能恢复私密包。

固定镜像基础模式使用受控ENV：

```bash
bash deploy/release/backup-data.sh /etc/atlas/lab.env /secure/atlas-data.private.tar.gz
bash deploy/release/restore-data.sh /etc/atlas/lab.env /secure/atlas-data.private.tar.gz atlas-restore-check
```

完整链模式用合并后的 `/etc/atlas/full.env` 调用同样工具；它按API→Supervisor→MySQL停写，备份业务、链state、MySQL和秘密，再恢复服务。恢复创建独立三卷与受限秘密目录，拒绝覆盖既有卷；启动独立恢复栈前更换端口/网段/代理地址，核对创世身份、余额/nonce、订单、Proof与密钥后才切换。

基础源码栈可在确认原项目后 `docker compose stop api`，复制完整目录再恢复；此单业务卷步骤不能代替完整链冷备。旧单容器若数据仍在可写层，必须先保护目录，不先删除容器。私有备份需加密保存，不能上传源码仓库。

回退只切换兼容镜像、保留当前卷，不用旧快照覆盖发布后的写入。本地已完成受控冷备与两代恢复；不代表任意崩溃时跨SQLite/MySQL/trie原子性已经证明，也不替代目标机验收。

## 依赖与CI范围

npm锁文件、Python精确版本锁文件和单worker配置以源码为准；依赖锁未附完整哈希，基础镜像构建标签不等于digest锁。当前CI为前端lint/test/build及Python3.12/3.14 pytest和依赖检查，不包含镜像/链/真实模型/TEE部署。当前版本已有本地镜像和真实业务验收，见[统一验收边界](CURRENT_STATUS.md#已有验收与待验证)。

`python3 deploy/smoke.py`需要Docker及制品，使用临时项目与测试卷，不能拿生产项目代替。文档修订不要求重新收费或改当前观察服务。

## OCR、HTTPS与可选执行

OCR worker与WASM由本站提供，语言模型首次加载可能需网络；离线要预缓存。图片在浏览器识别。云DeepSeek已有真实联调，但Key需每会话配置；Ollama/gVisor和Nitro硬件仍有独立部署前提，见[执行边界](EXECUTION_TRUST.md)。

对公网开放仍需目标机原生、HTTPS、成员、网络资源、审计及恢复验收；现有代理限流和计算预算不能替代完整多租户安全审计。

## 历史部署检查点（2026-09-07）

以下保留原验收及失败记录，不作为当前镜像、Docker运行状态或外部服务可用性的保证：

本次本地 `docker compose config --quiet` 通过。本机 Docker 守护进程未运行，且镜像仓库连接超时，因此没有在本机启动容器。

随后 GitHub Linux 环境已完成真实验证：提交 `1907430` 的 [Actions #34077168667](https://github.com/ashcinder/atlas-quant-lab/actions/runs/34077168667) 中，前端、后端、容器三个 job 全部通过。`deploy/smoke.py` 实际构建并启动了镜像，验证同源路由、非 root / 只读后端、离线回测，以及重建后数据库记录、签名身份和包加密密钥的一致性。测试只使用独立临时项目与数据卷，没有部署公开服务。

这项验证不覆盖本机 Docker 环境、生产数据备份恢复演练、容器 ZKP 验证器或真实 AI / TEE。不能用容器健康接口在线代替这些检查。

对公网开放之前，还需要独立审查身份鉴别与租户权限，并完成 TLS、速率和资源限制、外置任务队列、可观测性、备份恢复演练、依赖安全审查，以及 AI / 通用策略 Runner / TEE 的隔离与可信执行实现。

## 历史CI说明更正（原检查点2026-09-30）

当时记录“尚未提交触发远端Actions”仅是当时检查点；后续已经发布源码提交。当前CI范围以仓库工作流和对应提交结果为准。决赛部署记录见 [历史决赛升级](FINAL_UPGRADE.md)，不等于本轮部署或容器重验。
