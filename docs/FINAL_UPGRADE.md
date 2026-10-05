# Atlas 决赛升级（2026-10-05）

## 本次行为

- 报告新增 `performance_score` / `performance_score_version=performance_v1`；旧 `score` 为旧版综合分。表现分只由 Sharpe、年化收益、回撤换算，缺指标或完整性失败为null；排名缺分末尾且无名次。证据状态独立，六项指标画像沿用旧公式，不代表已完成完整六维评价。
- 运行 `valuation_at` 取最后已记录K线快照，无快照为null。缺数、失败、未折算费用单独提示，初始分配不等于估值净值。
- 创建平台模拟/K线运行可选 `behavior_position_limit_bps`（100–10000，创建后固定）。Decimal严格超限才偏离，缺数不可评估，仅覆盖已记录快照；不改变风控、下单或暂停行为。旧运行默认不启用。
- 报告和运行详情提供A4打印摘要及公开/本人有权查看字段的JSON下载。Proof页面补齐失败重试与绑定提示，不将普通监测称为ZKP。

## 本地验证

后端565项、前端148项Vitest+63项Node测试通过；lint/build/diff check通过。提交前另从Git索引导出源码快照，用锁定的合约npm依赖验证后端，并用现有前端依赖验证全部测试、lint和build；隔离Supervisor命令从该快照构建通过。390/768/1440界面检查、登录/查看/核验/浏览器下载/离线核验及隔离篡改拒绝通过。测试全部使用隔离或专用测试身份。

```sh
cd backend && .venv/bin/pytest
cd ../frontend && npm test && npm run lint && npm run build
```

Supervisor源码保持MIT许可证。提交前删除历史配置凭据注释，并关闭隔离开发链中的上游SMTP辅助功能；无云端凭据提交。`go test -vet=off ./supervisor ./cmd/atlas-isolated-supervisor` 和隔离命令build通过；标准go test会被上游两个现有格式化vet问题阻断，未宣称上游全库验证通过。正式Supervisor服务没有替换。

## 云端部署

当前HTTPS入口为 https://124.221.183.247:9443/ 。发布目录 `/opt/atlas-quant/releases/20261005-final-upgrade`，候选Compose项目 `atlas-quant-final-candidate`，入口18083，新数据卷 `atlas-quant-final-candidate_atlas-data`。

先停止旧API、完整备份并复制正式卷，再执行增量迁移及认证/运行/Proof回归后切换Nginx。既有订单/Proof和旧运行记录保留；旧监测阈值NULL。API/Web healthy，Nginx配置与TLS公网健康检查通过。67个API源文件哈希对比仅 `app/data/providers.py` 有差异，它是保留的服务器行情代理定制。

API镜像 `sha256:9db529b2b7d0116f3a043536374f3971088c4d29e3a32bc99b0ad218bc2e4347`；Web镜像 `sha256:6b7d5c1e9673786583507fec3424f297c73d2179aa94bea75946f2119f420c38`。镜像沿用已核对的旧平台依赖层；这不是本提交干净检出镜像构建验收。

完整备份位于服务器 `/opt/atlas-quant/backups/atlas-data-before-final-upgrade-20261005T075454Z.tgz`。发布目录内 `rollback.override.yaml` / `rollback-current-volume.sh` 已检查但未执行：只切换应用镜像，保留当前卷，禁止用旧数据库覆盖发布后的新写入。

## 边界与剩余

真实receipt证明固定guest在承诺输入上的计算，不证明行情来源、实盘收益、正式链付款或TEE。生产Supervisor链不更换。Linux zkVM验证器仍需独立准备固定架构/hash/image ID的制品，不能把本机macOS二进制打进Linux镜像；CI不声明容器构建验收。

三轮核心交互已复跑；连续实时录屏和三次完整口述两分钟排练未完成。已生成的截图视频和本地验收证据保留在用户工作区，不提交私有截图或本机交接记忆。本轮不新增实盘交易、付费云证明、TEE或全券商聚合。
