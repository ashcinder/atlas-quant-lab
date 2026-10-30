# 实验室离线镜像部署

> 当前指南：按QuantJudge实现4be31bf核对（2026-10-30）；环境验收与限制见[统一状态](https://github.com/ashcinder/atlas-quant-lab/blob/QuantJudge/docs/CURRENT_STATUS.md)。

本文为基础Web/API两镜像路线。需要测试链付款、新Proof和存证时使用[完整四镜像路线](https://github.com/ashcinder/atlas-quant-lab/blob/QuantJudge/docs/LAB_CHAIN_DEPLOYMENT.md)，不要将基础模板原样当作完整服务配置。

本交付面向 Linux amd64、Docker Engine 和 Compose v2。服务器不需要安装应用的 Python/Node/Rust 工具链或编译依赖；运维工具使用系统 Python 3.9+、Bash、curl 和宿主 Nginx。镜像内已包含应用与固定 Linux Proof 验证器。Apple Silicon 上的本地测试使用 amd64 仿真，不能代替目标机原生检查。

## 构建与交付

在可信构建机准备固定验证器，执行：

```sh
python3 scripts/prepare-linux-verifier.py /reviewed/linux/atlas-zkvm
bash deploy/release/build-images.sh
ATLAS_SMOKE_NO_BUILD=1 ATLAS_API_IMAGE=atlas-quant-api:20261030-lab-v1-amd64 ATLAS_WEB_IMAGE=atlas-quant-web:20261030-lab-v1-amd64 python3 deploy/smoke.py
bash deploy/release/package-release.sh --proof-bundle /public/verified-proof.zip /output/atlas-quant-lab.tar.gz
```

示例镜像名必须对应此次源码构建。文档/源码变化也会改变source-manifest指纹；旧镜像不能直接重新打成新版本包，需以新指纹重新构建并验收或保留原包。

输出包及同名 `.sha256`。打包工具只接受与当前源码指纹一致的镜像；`source_commit` 是基线提交，`source_snapshot.snapshot_sha256` 和镜像标签标识实际修改后的源码。不会把未提交的修改描述为基线提交原内容。文件清单、两镜像ID、架构、固定验证器哈希和可选公开样本哈希保存在发布清单内。包中没有用户数据库、私有配置、云模型Key、证书私钥或旧用户数据。

## 目标服务器启动

1. 核对实际目标机身份、Linux amd64、可用内存和磁盘。运行后至少保留2GiB磁盘；API内存上限2GiB，建议主机至少4GiB可用内存。先确认宿主Docker/Nginx环境和安全组。
2. 从可信渠道核对压缩包SHA256，解压，执行 `bash deploy/release/load-images.sh`。它先校验全部文件，再加载镜像并核对镜像ID与平台。
3. 将 `.env.lab.example` 复制到受控目录如 `/etc/atlas/lab.env`，权限600。填写真实域名、HTTPS端口、证书和Key路径。非443端口必须同时写入Origin，例如 `https://atlas.lab.edu:9443`。配置不作为shell代码执行。
4. 生成TLS代理配置：`python3 deploy/release/render-tls-proxy.py --env-file /etc/atlas/lab.env --output /tmp/atlas-nginx.conf`。管理员确认它与既有站点没有端口/zone冲突，安装到宿主Nginx的http上下文，执行 `nginx -t` 成功后重载。
5. 执行 `bash deploy/release/start-release.sh /etc/atlas/lab.env`。预检通过后仅用 `--no-build --pull never` 启动，不会从仓库下载或现场编译镜像。
6. 本机和另一台实验室电脑分别访问HTTPS，验证成员登录、行情、回测和Proof；通过后开放成员使用。

宿主Nginx只向回环Web端口转发；API不发布宿主端口。默认独立网段172.30.120.0/29：gateway .1、API .2、Web .3。Web只信任宿主gateway的客户端地址和HTTPS协议，API只信任Web。部署预检检查网段冲突；如需更改，必须一起修改配置中的全部网络地址。禁止把可信代理设为星号或任意网段。发布的只读配置以明确ENV文件为准，防止shell环境覆盖审核值。

## 成员与空库

公开注册默认关闭，管理员创建成员：

```sh
python3 deploy/release/compose.py /etc/atlas/lab.env exec api python /app/scripts/admin-user.py member@lab.edu
```

密码通过隐藏提示输入并二次确认，不放命令参数、配置或日志。新成员从空账本开始。不会自动生成旧账号、策略、历史资金或Proof。

## 六维评价

后端统一输出 `evaluation_v1`：收益、Sharpe、回撤、市场适应性、回测实盘一致性、策略纯度。收益/Sharpe/回撤沿用既有刻度。市场适应性沿用牛熊震荡规则，排除前200根预热；三阶段各至少30个配对收益观测，以同标的买入持有为基准，阶段复合收益按该市场周期因子年化，三阶段年化超额等权平均，[-20%,20%]映射[0,100]。

这些刻度属于平台规则，不代表经实证校准。无配对实盘数据、风格基线或原始市场数据的维度明确不可评估，不补零、不生成不完整六维总分。已有排名公式及签名/Proof声明不改。

## 云模型

成员登录后在设置中选择DeepSeek，输入自己的Key，明确同意向供应商发送请求和源码，再执行连接测试。Key只在当前登录会话内存保存8小时，服务重启后需重新配置，不写进镜像或导出包。完成生成/修改、预览、人工应用、受限Python校验和手动回测才算真实联调通过。模型连接测试通过不等于完整流程通过。

超时、额度不足、格式错误给出失败提示，不自动应用。云AI、回测、研究与Proof验证共用每账号1项/全局2项计算预算，超额429，无无限等待队列。AI不改确定性评分，不自动下单。

## 可选公开Proof验收样本

公开样本单独保存在 `proof/public-proof.zip`；不会随镜像自动导入。管理员可显式将其导入空库：

```sh
python3 deploy/release/import-proof.py /etc/atlas/lab.env
```

先从可信发布清单核对receipt哈希。导入会使用真实验证器，拒绝不匹配profile/行情/receipt以及冲突身份；重复导入幂等。该记录标为历史隔离测试输入，不属于新用户实盘或本次云付款。在线验证后可下载离线包。在禁网只读容器中使用同一固定验证器独立复核，篡改receipt或image ID应失败。

基础双镜像模式不启用新付费Proof、BKC支付或Supervisor锚定。用户后续扩展的完整实验室模式需使用含Supervisor/MySQL的四镜像包和 `ATLAS_CHAIN_MODE=isolated_lab`，具体初始化、测试资产、资源、网络与一致恢复要求见 [完整链部署说明](https://github.com/ashcinder/atlas-quant-lab/blob/QuantJudge/docs/LAB_CHAIN_DEPLOYMENT.md)。TEE缺失不阻断这些主流程，但不能提供对平台管理员的硬件保密保证。真实交易、zkTLS、DID、真实TEE、监管工作台、券商以及完整A股引擎仍不作为本次交付能力。

## 备份、恢复与回退

```sh
bash deploy/release/backup-data.sh /etc/atlas/lab.env /secure/atlas-data.tar.gz
bash deploy/release/restore-data.sh /etc/atlas/lab.env /secure/atlas-data.tar.gz atlas-restore-test
bash deploy/release/rollback-images.sh /etc/atlas/lab.env PREVIOUS_API_IMAGE PREVIOUS_WEB_IMAGE
```

备份短暂停API写入后复制完整数据目录，包含SQLite、签名身份和加密Key；备份属敏感材料，权限600，需加密离线保存。恢复只创建新的独立卷，拒绝覆盖已有卷。恢复后启动独立项目验收时，必须同时换独立网段、端口和所有代理地址，避免与正式项目冲突；核对数据库完整性、业务记录、Proof及密钥一致再决定切换。

镜像回退保留当前数据卷，不用旧数据库覆盖发布后的新写入。旧镜像必须与当前数据库兼容；回退命令不代替兼容性验收。之后同步更新私有env文件的镜像名，避免下次启动切回。

## 验收记录

每个发布包附本轮结果和未完成项；公开摘要与清单只包含脱敏信息；本地 `.artifacts/` 可能同时包含私有账号/秘密和完整备份，不能整目录分享。已验收完整栈范围见仓库[当前状态](https://github.com/ashcinder/atlas-quant-lab/blob/QuantJudge/docs/CURRENT_STATUS.md)，本机详细记录不随源码发布。容器冒烟、真实Proof、页面和备份恢复必须针对最终镜像ID执行。24小时观察从最终镜像连续启动后计时；休眠、Docker停止和中断必须记录，不提前宣称通过。目标机架构、域名/证书及有效AI配置未具备时，相应验收保持待完成。
