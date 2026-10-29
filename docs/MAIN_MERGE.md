# main → QuantJudge 合并说明与当前入口

更新：2026-10-29。当前操作按QuantJudge `672e8b8` 核对。原合并来源为main `b7e06dc` 与QuantJudge `cc1a434`，合并验收记录保留在下方，不能当作当前运行状态。

## 当前使用方式

- 安装与两个终端开发：遵循 [README](../README.md#本地启动)，使用npm及已提交的 `package-lock.json`，无需全局安装pnpm。
- 本机带链开发：依赖预装后使用根 `./start.sh`，另需Go和本机MySQL，每次生成新链，不能恢复旧付款订单。
- API/Web容器：先完成 [部署构建前提](DEPLOYMENT.md#构建前置条件)，核对原项目和数据卷，再运行Compose。根Dockerfile仍在但未维护；旧单镜像启动器已停用。
- 策略使用、发布、订阅及运行：见 [当前工作流](CURRENT_WORKSPACE_WALKTHROUGH.md)。默认空库，不自带历史验收账号、策略或Proof。

## 合入与后续能力

账号注册登录、按用户隔离的账本、OCR、定投、回测、研究、模板和提醒共用FastAPI/SQLite后端。定投只记账，不产生券商成交。旧无账号数据保留local归属，不自动迁给新用户。

策略实验室保留规则、工作流、研究、版本与SDK；受限Python可手动回测并发布确定性运行版本，不能执行任意Python依赖。AI审核依赖提供方配置，持续运行不自动执行AI节点。普通策略包静态加密不代表服务器管理员不可读。

QuantJudge保留市场与有限ZKP能力；可运行版本的BKC授权区别于旧Agent沙盒记录。Supervisor摘要存证、隔离链合约验收与来源/实盘收益证明分别说明，见 [证据边界](QUANTJUDGE.md)。

React/TypeScript通过Vite同源代理访问FastAPI；OCR执行代码构建为本站资源，语言模型首次加载可能需要网络。当前CI只覆盖源码测试与构建，不替代镜像、链、真实模型或Nitro硬件验收。

## 本地源码检查

以下连续命令从仓库根目录开始，依赖已安装，测试数据必须隔离：

```bash
cd backend
.venv/bin/pytest
.venv/bin/pip check
cd ../frontend
npm test
npm run lint
npm run build
```

容器smoke另需Docker及发布制品，不属于上述源码检查。完整备份/恢复与HTTPS设置见 [部署指南](DEPLOYMENT.md)。

## 历史合并验收

### 本轮验收结果（2026-09-08）

- 合并提交 `d44a211`，双亲为原 QuantJudge `cc1a434` 与 main `b7e06dc`，已推送至 `origin/QuantJudge`。
- [GitHub Actions 完整验收](https://github.com/ashcinder/atlas-quant-lab/actions/runs/34153344830)：frontend、backend、containers、isolated-runner 四项全部通过。容器测试实际构建镜像、注册登录、执行离线回测并重建容器验证持久数据/密钥；隔离测试实际使用 Linux gVisor。
- 本地后端 253 项通过；前端 Vitest 43 项、账本 Node 测试 61 项通过；生产构建、依赖一致性检查通过。ESLint 无错误，保留账本图表组件的 2 条 Fast Refresh 导出警告；后端测试有上游 Starlette/httpx 弃用提示。
- 真实浏览器完成注册、量化行情显示、切换账本、创建账户、刷新后持久化、OCR 加载到人工核对、退出登录。截图识别使用合成测试账户，未将 OCR 结果写入账本；不据此承诺任意截图的识别准确率。
- 已目视检查 1440px 桌面与 390px 手机布局，手机页面实际 `scrollWidth === innerWidth`。截图保存在本地 `output/playwright/merge-*.png`，不提交私人浏览器状态。

以上是本次合并的回归验收，不代表真实 AI/TEE 或任意 Python ZKP 已完成，也不替代公网部署前的安全审计。
