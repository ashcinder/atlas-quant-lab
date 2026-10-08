# 可恢复的本机测试链演示

使用独立 Supervisor 测试链、测试钱包与隔离数据库，展示既有真实 receipt 的核验及报告摘要存证。receipt 验证固定程序对承诺输入的计算；摘要存证确认精确摘要位于绑定网络的当前规范块，不宣称最终不可逆、实盘收益或链上执行 ZKP。

## 环境与启动

当前控制器面向 macOS，本机 MySQL 位于 `/usr/local/mysql/bin`；需要 Go、Node 和项目后端 `.venv`。按根 README 安装依赖，在 frontend 执行 `npm run build`。初始化依赖见[隔离链说明](../../contracts/isolated-supervisor/README.md)。

默认演示目录是仓库外 `~/.local/share/atlas-competition-20261008`，端口为 RPC42529、专用MySQL19326、API8018。目录只允许专用 `atlas-competition-*` 名称，私密文件不放入Git。

首次创建新案例，确保目录不存在且专用端口空闲：

```sh
python3 docs/competition/demo.py init
python3 docs/competition/demo.py recover
python3 docs/competition/demo.py api
python3 docs/competition/demo.py status
```

打开 `http://127.0.0.1:8018`，自行创建专用测试账号。停止后恢复原案例：

```sh
python3 docs/competition/demo.py stop
python3 docs/competition/demo.py recover
python3 docs/competition/demo.py api
```

`init`拒绝覆盖已有目录；`start/recover`复用数据与状态，核对原创世块。不要删除目录重建后仍沿用旧交易结论。根目录 `start.sh`创建新链，不是此案例的恢复入口。停止操作核对PID命令与演示根目录，保留链数据。

## 导入与锚定

真实 receipt、固定 Image ID 和相应架构验证器需独立准备。本仓库不附比赛数据库、测试身份、私有输入、Proof包、制品二进制或录屏。以下脚本的 `--help` 提供参数说明：

```sh
python3 scripts/import-verified-proof.py --help
python3 scripts/anchor-zk-report.py --help
python3 scripts/verify-proof-bundle.py --help
```

导入时固定预期receipt SHA-256，明确 `--data-dir` 指向专用root下的隔离库。若需保留作者身份，新建 `--author-file` 必须位于仓库外带 `demo.json.test_only=true` 标识的演示root/secrets目录。凭证独占创建、权限0600，在创建Agent前落盘；不要输出或公开该文件。

若凭证已落盘但后续导入失败，应先核对隔离库完成状态、备份诊断资料，仅对确认孤立的测试凭证做清理后重跑。已完成案例的凭证不能删除或重建。

使用测试钱包和测试币为报告摘要签名；`contracts/isolated-supervisor/scripts/sign-demo-anchor.mjs`只生成本机私密签名文件，广播由锚定脚本执行。锚定保存chain ID与genesis，核验交易hash、回执对应关系、双方区块hash/高度、精确input与当前规范块，并在确认前重读网络身份。缺网络身份的旧记录保持待确认；RPC不可用或响应不一致撤销本次确认，缓存不替代当前核验。

## 验收边界

分别检查正常存证、网络身份变化、错误交易/回执、非规范块、payload篡改、RPC不可用、receipt及报告篡改拒绝。停止恢复后应独立查询原交易。仓位检查仅针对已记录快照，与这份Proof独立。

比赛PPT/PDF、易拉宝、真实案例记录、离线包及个人团队资料保留在本机，未随源码发布。源码测试和本机验收不等同另一台电脑核验、真人计时、现场播放或生产部署验收。
