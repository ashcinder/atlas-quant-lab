# 项目目录说明

Atlas Quant Lab 采用一个仓库管理前端、后端和策略开发工具链。根目录只保留能够独立说明职责的一级模块。

## 根目录

| 目录 | 职责 | 是否运行时必需 | 维护边界 |
| --- | --- | --- | --- |
| `backend/` | FastAPI 服务、行情适配器、指标与回测引擎、研究任务、QuantJudge、ZKP receipt 验证及 SQLite 本地数据 | 是 | Atlas 后端源码 |
| `frontend/` | React + TypeScript 界面、K 线与指标图表、单标的/多资产回测、策略实验室和 QuantJudge 市场 | 是 | Atlas 前端源码 |
| `strategy/` | 策略作者侧的 SDK、示例、打包命令以及本地 ZKP 证明工程 | 开发策略或生成证明时需要 | Atlas 开发工具链 |
| `docs/` | 产品规格、系统架构、策略开发契约、ZKP 与 Supervisor 接入说明及文档图片 | 否 | 项目文档 |
| `Supervisor/` | 用户已经配置的外部区块链 Supervisor 节点 | 链上锚定时需要 | 外部只读工程；Atlas 不修改、不提交 |
| `.artifacts/` | Playwright 截图、策略包和视觉验收结果等可重新生成的本地产物 | 否 | 不提交 Git，可安全清理 |

根目录中的 `README.md` 是统一入口，`.gitignore` 定义依赖、缓存、密钥和生成产物的排除规则。

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
└── pyproject.toml
```

`.venv/`、`.data/`、测试缓存均是本地生成目录，不进入 Git。

## `frontend/`

```text
frontend/
├── src/
│   ├── components/  工作台、图表、策略实验室与 QuantJudge 组件
│   ├── api.ts        后端 API 客户端与数据类型
│   └── styles.css    全局设计系统和页面布局
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
- `assets/`：README 与文档引用的图片。

## 生成目录处理原则

依赖、缓存、数据库、证明产物和截图均保留在各自模块的隐藏目录或构建目录中，并由 `.gitignore` 排除。它们可以重新生成，不应与源码一起评审或发布。
