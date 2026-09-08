# 项目目录说明

Atlas Quant Lab 采用一个仓库管理前端、后端和策略开发工具链。根目录只保留能够独立说明职责的一级模块。

## 根目录

| 目录 | 职责 | 是否运行时必需 | 维护边界 |
| --- | --- | --- | --- |
| `backend/` | FastAPI 服务、行情适配器、指标与回测引擎、研究任务、QuantJudge、ZKP receipt 验证及 SQLite 本地数据 | 是 | Atlas 后端源码 |
| `frontend/` | React + TypeScript 界面、K 线与指标图表、单标的/多资产回测、策略实验室和 QuantJudge 市场 | 是 | Atlas 前端源码 |
| `strategy/` | 策略作者侧的 SDK、示例、打包命令以及本地 ZKP 证明工程 | 开发策略或生成证明时需要 | Atlas 开发工具链 |
| `deploy/` | 前后端容器镜像、同源代理与隔离容器冒烟测试 | 容器部署时需要 | 仅 Atlas 私有部署，不包含 Supervisor |
| `docs/` | 产品规格、系统架构、策略开发契约、ZKP 与 Supervisor 接入说明及文档图片 | 否 | 项目文档 |
| `.github/workflows/` | 构建、测试和容器验收的 GitHub Actions 配置 | 否 | 自动验证，不自动部署 |
| `Supervisor/` | 用户已经配置的外部区块链 Supervisor 节点 | 链上锚定时需要 | 外部只读工程；Atlas 不修改、不提交 |
| `.artifacts/` | Playwright 截图、策略包和视觉验收结果等可重新生成的本地产物 | 否 | 不提交 Git，可安全清理 |
| `output/playwright/` | 工作空间重构的浏览器视觉验收截图 | 否 | 本地生成，不提交 Git |

根目录中的 `README.md` 是统一入口，`compose.yaml` 编排私有部署，`.env.example` 说明可选设置。`.gitignore` 排除私密数据和生成产物；`.dockerignore` 限制镜像构建上下文，避免将数据库、密钥与 Supervisor 发送给构建器。

## `backend/`

```text
backend/
├── app/             API 和领域实现
│   ├── backtest/    回测执行与组合计算
│   ├── data/        行情源、缓存与数据清洗
│   └── strategies/  平台内置策略实现
├── tests/           后端自动化测试
├── .data/           SQLite、行情缓存、策略包与证明回执（本地生成）
├── requirements*.txt
├── requirements*.lock  生产 / 测试依赖的精确版本清单
└── pyproject.toml
```

`.venv/`、`.data/`、测试缓存均是本地生成目录，不进入 Git。

## `frontend/`

```text
frontend/
├── src/
│   ├── components/  工作台、图表、策略实验室与 QuantJudge 组件
│   ├── api.ts        按领域组织的后端 API 客户端
│   ├── request.ts    超时、取消与可读错误处理
│   ├── types.ts      前后端数据契约
│   ├── styles.css    图表、控件与原有页面基础样式
│   ├── workspace.css 统一工作空间视觉与响应式布局
│   └── operations.css 系统状态、异常恢复与工作区保持
├── dist/             生产构建产物（本地生成）
├── package.json
└── vite.config.ts
```

`node_modules/` 与 `dist/` 不进入 Git。

## `strategy/`

```text
strategy/
├── examples/strategies/  JSON DSL、Python Runner 与远程 Runner 示例
├── sdk/python/           Python 策略 SDK、风险限制模型和测试
├── tools/                策略包构建工具
└── zkvm/                 RISC Zero guest、host、profiles 与构建脚本
```

把作者侧工具集中在这里，可以明确区分“平台应用代码”和“第三方策略开发套件”。`strategy/zkvm/target/` 是体积较大的 Rust 构建缓存，不进入 Git。

## `docs/`

- `PRD.md`：产品范围和需求。
- `ARCHITECTURE.md`：前后端、数据、回测和安全架构。
- `STRATEGY_DEVELOPMENT.md`：策略格式、SDK、Runner 和 AI 工作流开发流程。
- `QUANTJUDGE.md`：策略市场、证据链和 Supervisor 对接。
- `ZKP.md`：零知识证明协议、公开输入和威胁模型。
- `UI_REDESIGN.md`：工作空间重构、交互修复、验收与能力边界。
- `REFACTOR_PROGRESS.md`：本轮交付、实际验证结果与未完成事项。
- `DEPLOYMENT.md`：本机容器运行、数据持久化、备份及部署边界。
- `assets/`：README 与文档引用的图片。

## 生成目录处理原则

依赖、缓存和截图可以重新生成，不应与源码一起发布。数据库、策略包、签名 / 加密密钥和证明资料同样不进入 Git，但它们包含不可随意丢弃的用户数据；不能当作缓存清理，必须按部署指南成套备份。
# 新增执行与证明目录

- `strategy/runner/`：只在 gVisor 镜像内执行的 Python SDK 工作进程，不能直接在 API 宿主运行用户代码。
- `strategy/zkvm/program-core/`：独立版本的私密整数程序解释器和确定性回测语义；不修改历史 SMA core。
- `strategy/zkvm/program-methods/`：v2 RISC Zero guest 与构建锁文件。
- `backend/app/execution*.py`、`sandbox.py`、`ai_runtime.py`、`tee.py`：请求模型、受控执行、隔离适配、本地 AI 与 Nitro 验证；不等于已部署真实 TEE。
- `deploy/runner.Dockerfile`、`runner_smoke.py`、`zk_program_smoke.py`：运行镜像和使用临时数据的真实隔离 / 证明集成验收。
- `docs/EXECUTION_TRUST.md`：各路径能力、数据保管、部署要求与尚未完成的边界。
