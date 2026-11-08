# 浏览器计算与轻量部署

普通单次回测、组合、研究和指标在浏览器 Web Worker 执行；浏览器上传结果始终标记用户侧计算、未验证。平台保存结果不会为其生成 ZKP 或真实成交记录。保密订阅版本仅由 Linux 受限子进程执行，不交付源码、指令或秘密参数；macOS 原生服务明确不提供此执行能力。

## 独立行情发布

先准备 Python 依赖并使用独立配置，以下命令从项目根执行。示例仅含 BTC、ETH，不在安装或 HTTP 请求中自动联网采集。

```sh
PYTHONPATH=backend python -m app.data.publish_market --config config/market-publication.example.json --once
PYTHONPATH=backend python -m app.data.publish_market --config config/market-publication.example.json --interval 300
PYTHONPATH=backend python -m app.data.publish_market --config config/market-publication.example.json --cached-only --once
```

生产环境用独立进程、计划任务或容器运行发布器，与 API 生命周期分开。配置为查询数组，指定标的、资产类别、周期、复权、来源、日期和所需 `base_currencies`。发布器先创建币种换算版本，再发布引用这些不可变数据集的原币种清单；历史版本及历史 Proof 原始数据不改写。跨币种换算遵循现有历史汇率规则，USD/USDT 沿用等价约定。

`--cached-only` 只读取精确 SQLite 缓存键，不合并来源、复权或不同日期查询；`auto` 对应多个缓存时要求配置明确来源。该模式拒绝需要抓取历史汇率的转换；缓存缺失或发布失败时退出非零，保留旧版本，不用演示数据补齐。正常采集可能使用明确标记的旧缓存，清单保留来源与过期状态。配置日期限定了发布覆盖范围，不能把较短快照当作整个历史范围。

## 对象存储与 CDN

`ATLAS_OBJECT_ROOT` 指向本机持久目录或对象存储挂载。`public/` 仅保存可公开行情块；`private/` 保存账户结果，禁止向 CDN 或公共 bucket 同步整个根目录。`ATLAS_PUBLIC_DATA_URL` 设置为公共块 URL 前缀，例如 `https://data.example.com/market`，块文件名固定为 `<sha256>.json`。配置 CORS 允许前端 GET，并保留不可变长期缓存头；清单仍从应用取得。平台逐块核对 SHA-256，错误不能静默跳过或替换数据。

若启用 `ATLAS_PUBLIC_S3_URI`，仅由支持此选项的对象发布实现上传 `public/`；此变量不创建 bucket、CDN、账户或访问策略。部署者预先配置对象服务、最小权限和公共只读分发。私有结果下载始终经过账户授权，并使用 `no-store`。CDN 存储、传输、回源和发布器采集成本仍需独立计量。

SQLite 使用持久卷。每账户最多一项保密任务，全局串行、最多四项等待。每项子进程 CPU 30 秒、墙钟 60 秒、地址空间 1280 MiB、输入输出各 16 MiB；排队最多 60 秒。资源不足或执行失败明确报错，不把普通浏览器任务转交服务器。本机资源和压力实测见[r23 验收报告](testing/comprehensive-20261108/FOLLOWUP.md)。

## 作者本机生成 Proof

```sh
python scripts/author-proof.py check-install
python scripts/author-proof.py prepare --dataset /path/market.json --python-source /path/strategy.py --output /path/private-witness.json
python scripts/author-proof.py prove --witness /path/private-witness.json --output /path/new-proof-directory
```

包装入口只调用既有 `prepare-zk-witness.py` 和 `prove-private-program.py`，不修改密码学实现、guest、profile 或 Image ID，也不会自动构建二进制。证明器固定位置为 `strategy/zkvm/target/release/atlas-zkvm`；该原生产物不随 Git 提供，作者需自行安装匹配平台且经过审查的版本。`check-install` 只检查文件及执行权限，不证明二进制来源或密码学结果。

下载并保留原始证明数据集。源码与私有 witness 留在作者设备；仅将生成的 receipt 按现有网站 Proof 上传流程提交，平台执行真实验真，离线包仍可独立验证。不要上传 `author.private.json`、witness 或整个输出目录。预检不是 Proof；只有真实 receipt 及报告绑定通过后才显示验证状态。

新流程关闭服务器证明建单和自动生成。历史订单、profile、证明和验真能力保留；存在已付款或已提交交易但未完成的任务时，先通过既有恢复路径处理，迁移检查必须阻止直接停用旧执行器。升级前检查历史付费任务并保存可验证的备份。


## 模式、接口与兼容

默认 `ATLAS_COMPUTE_MODE=browser`；非法值拒绝运行。仅显式 `legacy` 保留旧计算接口，旧云Proof恢复还需 `ATLAS_CLOUD_PROOF_GENERATION=true`，不能用 legacy 作为浏览器失败后的自动回退。新前端始终使用浏览器流程；回退旧版本需要成套回退前后端并保护迁移后数据。

- `GET /api/v1/compute/capabilities?release_id=...`：服务器核对归属和活动订阅。作者拿到自己的规则；订阅者仅拿到执行能力。`purpose=runtime` 用于实时报价联调和作者签名运行。旧版本默认保密；`published` 只代表市场上架，`source_visibility=public` 是明确公开逻辑的不可变选项。
- `GET /api/v1/market/manifest`、`/market/datasets/{id}`：查询已发布快照，未就绪返回202。`chunks` 的实际首尾和 `coverage` 的发布查询边界分别保存，休市日不制造K线；coverage也不是数据源完整性认证。固定来源请求不会替换成其他来源。只有组合使用预发布的历史汇率转换版本，单次回测继续用原报价币种。
- `POST /api/v1/compute/runs`：保存用户侧计算结果，服务器赋予ID、入库时间和未验证来源。SQLite只保存索引与私有对象引用，行情以数据集引用保存。研究结果另有服务器研究ID，供原项目关联流程使用。
- `POST /api/v1/compute/private-backtests`：活动订阅者的单次回测；拒绝作者/公开策略通过此入口回退计算，拒绝策略覆盖及批量研究。服务器不向订阅者返回秘密参数、指令或调试原因。平台运营方仍可读取托管策略，不构成TEE保密。
- `POST /api/v1/compute/runtime/{id}/heartbeat`：15秒续期、45秒在线租约，与135秒计算互斥锁独立。浏览器自己生成自有/公开策略信号，服务器校验当前数据版本和账本规则；订阅策略由受限子进程生成信号。租约到期不推进、重新打开后重新锚定，不补造历史成交。账户同步、交易确认与既有订单对账仍属服务器职责。

Worker支持进度、取消、AI轻量代理回调；缺少Worker、IndexedDB或安全摘要能力时明确报错。IndexedDB按登录用户隔离，切换账号终止工作；完成研究保留，刷新后未完成研究标记中断，不假装继续后台计算。用户的AI配置仍只在服务器登录会话内存中，不写Worker、IndexedDB、镜像或导出。提醒条件在浏览器计算，冷却与记录归属由服务器检查。

## 发布公开报告和证明文件

报告成功发布后导出白名单字段的公共JSON；绑定的真实Proof通过既有验真后，才导出原始receipt。使用独立 `artifacts-public/` 目录与登记白名单，绝不导出witness、源码、开发者令牌、私有快照或整个离线包。

- `ATLAS_PUBLIC_ARTIFACT_URL` 是公共报告/receipt的CDN URL前缀；缺省经 `/api/v1/public-artifacts/{sha256}.json` 或 `.r0` 提供不可变缓存与CORS。
- `ATLAS_PUBLIC_ARTIFACT_S3_URI=s3://bucket/prefix` 显式启用公开制品上传；行情块独立使用 `ATLAS_PUBLIC_S3_URI`。配置上传的运行环境必须预先安装AWS CLI并配置自己的最小权限身份；默认发布镜像未包含AWS CLI。本轮未读取个人凭据、开通bucket或真实上传。
- 跨域CDN还需配置 `ATLAS_PUBLIC_CDN_ORIGINS`（空格分隔的HTTPS origin，不带路径），使Nginx CSP允许下载数据。对象存储端点覆盖仅接受HTTPS。
- 导出失败不会撤销已发布报告，也不重复创建报告；作者可用原开发者凭证单独 `POST /api/v1/quantjudge/reports/{id}/distribution` 重试。只有已明确发布的receipt下载才会转向CDN，其他仍保留原鉴权路径。

## 本机 Docker 和测试

先准备[固定 Linux 验证器](DEPLOYMENT.md#构建前置条件)。独立项目的启动步骤见[README](../README.md#docker)，浏览器与负载复验入口见[隔离验收指南](../tools/e2e/README.md)。算法对照使用固定合成数据。生成工具位于 `tools/browser_compute/`，更新期望结果前须核对独立数值依据。

`compose.yaml` 固定使用 linux/amd64，与内置验真器一致。叠加 `compose.browser.yaml` 后会启动共享同一持久卷的独立 `market-publisher`，每轮结束后等待300秒再采集；API请求不触发上游采集。发布器只读挂载 `ATLAS_MARKET_CONFIG` 指定的JSON，缺省为BTC/ETH日线示例。容器健康检查核实配置中的清单已经发布；已有清单不会因上游失败而删除，过期来源仍如实标记。发布器单独最多0.5CPU/512MiB，不包含在原API+Web的2CPU/1920MiB配额内。

本机部署配置 `config/market-publication.docker.json` 覆盖BTC/ETH/SOL的五种周期及常用股票/ETF日线，真实源 `auto` 与明确标记的 `demo` 分别发布。该配置不是任意标的、周期、复权和固定来源的全覆盖；增加市场时需显式扩展配置并等待独立发布。不要把demo发布到auto查询键。

使用 `ATLAS_MARKET_CONFIG=./config/market-publication.docker.json` 选择扩展示例。Compose 的 API 与 Web 默认配额合计 2 CPU / 1920 MiB。本机正式 50 人复验使用 4 CPU / 4 GiB 配额，行情发布器和测试链服务分别计量。
宿主机执行 `PYTHONPATH=backend ... publish_market` 默认写宿主数据目录，不会自动写Docker卷。Docker部署应使用上述共享卷发布器。旧离线交付包脚本仍针对历史release/chain配置，本次本机部署没有重新生成离线交付包；不能把旧包作为新版browser部署包。
