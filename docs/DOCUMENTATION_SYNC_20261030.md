# QuantJudge Markdown统一核对清单

日期：2026-10-30。实现基线：[4be31bf](https://github.com/ashcinder/atlas-quant-lab/commit/4be31bf4a4457829cd5581c0463d198948f09aa9)。覆盖该提交全部 **54份** Git跟踪Markdown；本次另增[当前状态](CURRENT_STATUS.md)及本清单。后续本科选题基于这一统一实现。

## 本轮处理

- 当前指南统一到基础Web/API与完整Supervisor/MySQL范围，校正模板无真实凭据、代理信任、单worker及每账号1项/全局2项预算。
- 统一六维evaluation_v1和缺数处理，保留业绩排名/证据区别；补上DeepSeek已验收代码链路、服务器Proof读取授权与原付款恢复。
- 历史记录保留日期、失败和旧链地址，不机械改成当前“已完成”；设计、硬件准备、上游手册和资源来源明确适用范围。
- 业务实现保持4be31bf；本次不部署、不重启服务、不重新执行付费/模型实验，也不取消24小时/目标机等待验要求。

## 原54份逐篇清单

| 文件 | 用途 | 核对与修订 |
| --- | --- | --- |
| [DEPLOY.md](../DEPLOY.md) | 当前 | 源码/离线/完整链入口，项目与卷归属，安全源码导出 |
| [DESIGN.md](../DESIGN.md) | 设计/准备 | 仅定义工作流界面的设计沿革，不升级为全产品功能验收 |
| [PRODUCT.md](../PRODUCT.md) | 当前 | DeepSeek已验收代码链路、六维部分可评和未实现诊断Agent |
| [README.md](../README.md) | 当前 | 统一入口、当前能力、三种运行路线、评分/AI/Proof、模板与待验边界 |
| [contracts/README.md](../contracts/README.md) | 历史 | 历史42516合约/地址保留，不指代当前完整测试链已部署合约 |
| [contracts/isolated-supervisor/README.md](../contracts/isolated-supervisor/README.md) | 当前 | 一次性新链runner、已脱敏入库源码与原上游分开 |
| [contracts/supervisor-src/README.ATLAS.md](../contracts/supervisor-src/README.ATLAS.md) | 当前 | 临时与持久测试链入口、创世锁和原数据不可混用 |
| [contracts/supervisor-src/README.md](../contracts/supervisor-src/README.md) | 参考 | 保留上游手册/换行，只补Atlas适用入口 |
| [deploy/chain/README.md](../deploy/chain/README.md) | 当前 | 四镜像一致源码、ENV按数据读取、三卷及秘密备份，移除仅备两卷描述 |
| [deploy/nitro/README.md](../deploy/nitro/README.md) | 设计/准备 | 真实硬件与独立KMS授权待验，安装准备不是保密服务验收 |
| [docs/ARCHITECTURE.md](ARCHITECTURE.md) | 当前 | evaluation/work_limits、SQLite行情缓存、服务器Proof输入、完整链及API路径 |
| [docs/BACKTEST_CONTROLS_BKC.md](BACKTEST_CONTROLS_BKC.md) | 当前 | 当前keystore离线签名替代旧MetaMask主流程，创世身份及恢复 |
| [docs/CODE_TO_PROOF_WALKTHROUGH.md](CODE_TO_PROOF_WALKTHROUGH.md) | 当前 | 本地工具与profile核验，另述服务器读取输入需要授权 |
| [docs/CONFIDENTIAL_SUBSCRIPTION_REQUIREMENTS_20260915.md](CONFIDENTIAL_SUBSCRIPTION_REQUIREMENTS_20260915.md) | 历史 | 保留原日期、旧链/ID/测试及失败证据；顶部指向当前状态，不作为本轮验收或安装步骤 |
| [docs/CURRENT_WORKSPACE_WALKTHROUGH.md](CURRENT_WORKSPACE_WALKTHROUGH.md) | 当前 | 发布默认成员建号、AI已验收范围、本地和服务器Proof及链身份 |
| [docs/DEPLOYMENT.md](DEPLOYMENT.md) | 当前 | 固定Linux制品、模板/代理、计算预算、完整冷备及历史检查点 |
| [docs/DOCUMENTATION_UPDATE_20261029.md](DOCUMENTATION_UPDATE_20261029.md) | 历史 | 保留原日期、旧链/ID/测试及失败证据；顶部指向当前状态，不作为本轮验收或安装步骤 |
| [docs/EXECUTION_TRUST.md](EXECUTION_TRUST.md) | 当前 | DeepSeek与Ollama验收分开，服务器witness边界，历史gVisor不当本次启用 |
| [docs/FINAL_UPGRADE.md](FINAL_UPGRADE.md) | 历史 | 保留原日期、旧链/ID/测试及失败证据；顶部指向当前状态，不作为本轮验收或安装步骤 |
| [docs/INTEGRATION.md](INTEGRATION.md) | 历史 | 原账本整合结果保留，当前导航扩充到完整四镜像 |
| [docs/LAB_CHAIN_DEPLOYMENT.md](LAB_CHAIN_DEPLOYMENT.md) | 当前 | 四镜像标签和身份、完整构建与交付、资源、内部RPC及三卷冷备 |
| [docs/LAB_OFFLINE_DEPLOYMENT.md](LAB_OFFLINE_DEPLOYMENT.md) | 当前 | 基础两镜像范围，指纹变化与重打包条件，私有验收目录不分享 |
| [docs/LAB_QUICKSTART.md](LAB_QUICKSTART.md) | 当前 | 云模型当前设置、真实代码辅助范围、Ollama另配及批量审核限制 |
| [docs/LIVE_PROFIT_PROOF_DESIGN.md](LIVE_PROFIT_PROOF_DESIGN.md) | 设计/准备 | 保留原日期、旧链/ID/测试及失败证据；顶部指向当前状态，不作为本轮验收或安装步骤 |
| [docs/MAIN_MERGE.md](MAIN_MERGE.md) | 当前＋历史 | 当前运行入口同步完整栈，原合并成绩保留历史日期 |
| [docs/MERGE_VERIFICATION.md](MERGE_VERIFICATION.md) | 历史 | 保留原日期、旧链/ID/测试及失败证据；顶部指向当前状态，不作为本轮验收或安装步骤 |
| [docs/PARAMETER_SWEEP.md](PARAMETER_SWEEP.md) | 当前 | 浏览器串行100组和后端500/2500研究上限不是同一入口 |
| [docs/PDF_ACCEPTANCE_20260914.md](PDF_ACCEPTANCE_20260914.md) | 历史 | 保留原日期、旧链/ID/测试及失败证据；顶部指向当前状态，不作为本轮验收或安装步骤 |
| [docs/PRD.md](PRD.md) | 当前 | 现有六维缺数口径和可复现实验导出扩展候选，不夸大完整六维 |
| [docs/PRIVATE_STRATEGY_EXECUTION.md](PRIVATE_STRATEGY_EXECUTION.md) | 历史 | 保留原日期、旧链/ID/测试及失败证据；顶部指向当前状态，不作为本轮验收或安装步骤 |
| [docs/PROJECT_PROGRESS_20260913.md](PROJECT_PROGRESS_20260913.md) | 历史 | 原进度表保留，不把通用Python待办混同已验收严格子集 |
| [docs/PROJECT_STRUCTURE.md](PROJECT_STRUCTURE.md) | 当前 | release/chain/evaluation职责，区分可再生缓存和私有artifacts |
| [docs/PYTHON_AI_PROOF_FEASIBILITY.md](PYTHON_AI_PROOF_FEASIBILITY.md) | 设计/准备 | 通用Python/AI仍为研究，历史合约验收与当前摘要存证区分 |
| [docs/QUANTJUDGE.md](QUANTJUDGE.md) | 当前 | 六维/业绩排名/证据分开，作者侧与服务器Proof隐私区别及内部RPC |
| [docs/QUANTJUDGE_DEMO_ACCEPTANCE.md](QUANTJUDGE_DEMO_ACCEPTANCE.md) | 历史 | 保留原日期、旧链/ID/测试及失败证据；顶部指向当前状态，不作为本轮验收或安装步骤 |
| [docs/QUANTJUDGE_UI_PROBE_ACCEPTANCE.md](QUANTJUDGE_UI_PROBE_ACCEPTANCE.md) | 历史 | 保留原日期、旧链/ID/测试及失败证据；顶部指向当前状态，不作为本轮验收或安装步骤 |
| [docs/REFACTOR_PROGRESS.md](REFACTOR_PROGRESS.md) | 历史 | 保留原日期、旧链/ID/测试及失败证据；顶部指向当前状态，不作为本轮验收或安装步骤 |
| [docs/STRATEGY_DEVELOPMENT.md](STRATEGY_DEVELOPMENT.md) | 当前 | 格式契约与真正启用运行时区分，严格子集/SDK/AI及版本授权 |
| [docs/SUPERVISOR_ZKP_RESULT.md](SUPERVISOR_ZKP_RESULT.md) | 历史 | 保留原日期、旧链/ID/测试及失败证据；顶部指向当前状态，不作为本轮验收或安装步骤 |
| [docs/TEE_DEPLOYMENT.md](TEE_DEPLOYMENT.md) | 设计/准备 | 真实硬件/KMS/工作器待验，不混入普通Docker镜像验收 |
| [docs/TERMINAL_AND_AI_UPDATE.md](TERMINAL_AND_AI_UPDATE.md) | 历史 | 保留原日期、旧链/ID/测试及失败证据；顶部指向当前状态，不作为本轮验收或安装步骤 |
| [docs/THEMES_DATA_DCA_ACCOUNTS.md](THEMES_DATA_DCA_ACCOUNTS.md) | 历史 | 保留原日期、旧链/ID/测试及失败证据；顶部指向当前状态，不作为本轮验收或安装步骤 |
| [docs/TRADING.md](TRADING.md) | 当前 | 更新实现基线；平台模拟、测试网显式自动与实盘逐笔确认边界保持 |
| [docs/TRINE_SERVICE_WORKFLOW.md](TRINE_SERVICE_WORKFLOW.md) | 当前＋历史 | 当前付款及原订单恢复、原子结果/超时清理，基础与完整容器区分 |
| [docs/TRINE_TEST_ACCOUNTS.md](TRINE_TEST_ACCOUNTS.md) | 当前 | 无私钥模板、发布成员账号、测试币分发、原付款查询与动态报价 |
| [docs/UI_REDESIGN.md](UI_REDESIGN.md) | 历史 | 保留原日期、旧链/ID/测试及失败证据；顶部指向当前状态，不作为本轮验收或安装步骤 |
| [docs/ZKP.md](ZKP.md) | 当前 | Supervisor源码维护、签名广播、服务器受控witness，禁止静默替换登记ID |
| [docs/ZKP_ACCEPTANCE_20260913.md](ZKP_ACCEPTANCE_20260913.md) | 历史 | 保留原日期、旧链/ID/测试及失败证据；顶部指向当前状态，不作为本轮验收或安装步骤 |
| [docs/ZKP_E2E_20260916.md](ZKP_E2E_20260916.md) | 历史 | 保留原日期、旧链/ID/测试及失败证据；顶部指向当前状态，不作为本轮验收或安装步骤 |
| [docs/ZKP_EXTENSION_ASSESSMENT.md](ZKP_EXTENSION_ASSESSMENT.md) | 历史 | 保留原日期、旧链/ID/测试及失败证据；顶部指向当前状态，不作为本轮验收或安装步骤 |
| [frontend/public/asset-icons/README.md](../frontend/public/asset-icons/README.md) | 参考 | 本地资源与商标来源不变，不将上游素材当平台背书 |
| [strategy/README.md](../strategy/README.md) | 当前 | 作者侧SDK/示例/zkVM工具与平台运行边界 |
| [strategy/examples/pdf-acceptance/README.md](../strategy/examples/pdf-acceptance/README.md) | 历史 | 定义可参考，旧测试网实例/余额不随新安装生成 |
| [strategy/examples/strategies/risk_aware_momentum/README.md](../strategy/examples/strategies/risk_aware_momentum/README.md) | 当前 | 因果行情与确定性风控，示例运行仍需独立Runner配置 |

## 验证及证据边界

原54份与清单逐项对应；最终文档集合检查仓库相对链接/标题锚点、shell代码块语法、文件引用、修改范围及敏感模式。各命令按真实执行目录核对；历史退役命令保留明确提示，不作为当前步骤。相关API路径与运行中OpenAPI只读交叉核对。

4be31bf源码CI [41053163337](https://github.com/ashcinder/atlas-quant-lab/actions/runs/41053163337)确认成功；后端609、前端149+账本63及Docker/DeepSeek/链/Proof成绩为该实现已有验收，本轮不声称重新执行全部业务。后续文档提交CI以相应GitHub Actions为准。

本清单为项目文档核对，不作为独立安全审计或全部功能无缺陷证明。

文档一致不等于全部功能无缺陷。真实TEE、通用Python/AI证明、数据来源/完整实盘收益证明及目标机持续运行仍有边界。source-manifest包含文档，新文档会改变构建指纹，原镜像/交付包保留原清单身份；不能把旧镜像冒充本次重新构建。

## 统一后的本科选题

[本科毕设选题](UNDERGRADUATE_THESIS.md)基于统一文档版本5c04f4b及实现4be31bf，按已有功能、学生任务、完成标准和参考材料四部分组织；另附[计算贯通案例](examples/backtest-prerequisite/README.md)。这些是后续新增材料，未混入主工作区的旧选题提交或A股草稿。

新增材料纳入后，最终共59份Markdown；本地链接/锚点252处、shell代码块47段检查通过。计算贯通案例在禁网只读容器中复跑通过，未触碰正在运行服务的数据卷。
