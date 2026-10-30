# 实验室完整链依赖交付

本模式在Web/API之外增加Supervisor和MySQL两套固定Linux amd64镜像。它创建独立实验室单节点测试链，BKC余额为初始化测试额度；不能接入真实资金或称为正式共识网络。已有服务器的正式Supervisor网络及旧订单不自动迁移。空卷会产生新的创世块，不能核验绑定另一创世块的旧订单。

## TEE暂缺的影响

行情、回测、云DeepSeek、策略订阅、Supervisor签名交易、链上摘要存证，以及受限Python程序的RISC Zero证明生成/验真，不以TEE为前提。没有TEE时普通服务器可以读取用于执行和证明的策略及witness，不能向作者承诺管理员不可读。界面中的TEE保持未接入，不能把Docker、签名、链上存证或ZKP混称TEE。任意Python隔离执行和真实交易仍需要它们各自的配置，未因本模式自动开放。

证明流程明确要求作者同意服务器读取程序；仅固定受限Python程序支持Proof，不代表任意AI/Python或真实收益来源已验证。链上保存声明和哈希，不是在Supervisor合约中重新验证RISC Zero。

## 服务器准备及初始化

1. 先按基础部署说明准备Linux amd64、Docker/Compose、系统Python3.9+、Bash/openssl/curl和HTTPS代理。完整模式预检要求至少8GiB可用内存，建议12GiB以上；新证明内存显著高于验真。不得根据仅验真用量配置主机。
2. 校验并加载含API/Web/Supervisor/MySQL的完整包，禁止只加载旧v2双镜像包。镜像ID必须匹配发布清单。
3. 填写基础受控配置 `/etc/atlas/lab.env`。执行 `bash deploy/chain/init-secrets.sh /etc/atlas/chain` 生成独立链随机数据库密码和随机测试付款钱包。目录700，文件600；初始化拒绝覆盖已有文件。钱包私钥不嵌入镜像、不传给API服务，仅在账户所有者本地签名。
4. 合并公共链配置而不执行shell：`python3 deploy/chain/merge-env.py /etc/atlas/lab.env /etc/atlas/chain/chain.env /etc/atlas/full.env`。按实际项目审查端口和独立网段，TLS代理gateway及API信任地址必须一致。密钥路径只在私有配置中，镜像无密钥。
5. 生成并安装HTTPS代理，再执行 `bash deploy/release/start-release.sh /etc/atlas/full.env`。`ATLAS_CHAIN_MODE=isolated_lab` 会自动加载 `compose.chain.yaml`；启动仅用 `--no-build --pull never`，无现场源码编译或拉取。
6. 创建成员后核验：Supervisor连接、chain ID1051、创世块身份；作者设置版本价格，订阅者本地签名→API广播→确认→授权；版本/报告存证；Proof报价→本地签名付款→确认→排队生成→真实验真→下载→断网独立复核→Proof摘要存证。测试资产必须标清为实验室额度。只有完成这些检查后才能称该目标机完整流程可用。

默认完整网段172.30.123.0/29：gateway .1、API .2、Web .3、Supervisor .5；MySQL位于另一个仅Supervisor可访问的internal网络。RPC与数据库均不发布宿主端口；Supervisor的Go进程仍仅绑定容器loopback，通过只允许API地址的内部代理访问。不要将RPC作为公网钱包端点开放。浏览器钱包本地签名，API只接收签名后的原始交易。

`init-secrets.sh`中的随机付款钱包用于本次独立链验收；其他成员的测试额度转账由该测试钱包持有人逐笔签名完成，不把私钥分发为公共演示密钥。支付价格和收款地址是部署合同配置，示例1 BKC属于实验室默认测试价格，可在使用前审查。版本订阅价格一经发布不可覆盖，需另发版本。

管理员从已登录页面的网络状态取得并独立核对创世hash后，可使用 `python3 deploy/chain/fund-test-account.py /etc/atlas/full.env EXPECTED_GENESIS MEMBER_PUBLIC_ADDRESS 10` 分发10个测试BKC。工具检查链1051和指定创世hash，在一次性容器中读取本地测试钱包签名；不把钱包挂入API、不开放RPC端口，输出只有公开交易身份。网络身份不匹配时拒绝签名。成员只提供自己的公开地址，不能共享初始付款私钥。

## 持久化与故障恢复

业务SQLite及文件、Supervisor状态trie、MySQL必须整体持久。只替换镜像不会重置余额/nonce/创世块；禁止只删除其中一个卷继续使用另一个卷。基础版仅备份业务目录；完整模式的同名备份命令会按API→Supervisor→MySQL顺序停止写入，再一起打包三个卷及私有链配置，最后依次恢复服务。

```sh
bash deploy/release/backup-data.sh /etc/atlas/full.env /secure/atlas-full.private.tar.gz
bash deploy/release/restore-data.sh /etc/atlas/full.env /secure/atlas-full.private.tar.gz atlas-restore-check
```

完整备份包含数据库密码和测试付款钱包，属于敏感材料，必须受控加密保存。恢复拒绝覆盖既有卷，创建新项目的业务/链/数据库卷，以及备份所在目录下 `<新项目>.secrets` 私有目录和 `restored.env`。秘密恢复工具保留同一钱包/数据库密码，修正宿主目录与Supervisor UID101读取权限，失败时清理本次创建的卷。审查生成配置，换新端口和全部网段/代理地址后再启动独立恢复栈；不能用重新初始化的钱包或密码替代恢复秘密。

重启恢复后核对创世hash、最新块、付款交易/余额/nonce、授权记录、Proof receipt哈希和登录身份，恢复实例确认后才能切换。当前测试只建立正常受控停止/重启与冷备份恢复证据，不声明任意时刻崩溃写入的跨存储原子性已验证。

镜像回退工具只切换API/Web，保持链/DB镜像及卷不变；链数据版本升级/回退需单独审查兼容性，不能盲目将旧链文件覆盖新写入。收费证明失败时保留原订单与交易哈希，不能为同一任务再次付款。

TEE真实硬件验收、正式多节点网络、真实交易、行情来源认证和完整可信扩展继续单列，不用本实验室测试替代。
