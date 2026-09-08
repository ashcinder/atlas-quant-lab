# Strategy Platform

`strategy/` 集中保存面向策略开发者的工具链，不承载 Web 服务或页面代码。

```text
strategy/
├── examples/    可直接参考和打包的策略示例
├── sdk/         策略作者使用的语言 SDK；当前提供 Python SDK
├── tools/       `.qstrategy` 等开发与打包命令
└── zkvm/        RISC Zero guest、host、证明配置与构建脚本
```

应用运行时的确定性风控、策略包校验和证明验证仍由 `backend/` 负责；这里提供的是作者侧开发与本地证明工具。

入门流程见 [`../docs/STRATEGY_DEVELOPMENT.md`](../docs/STRATEGY_DEVELOPMENT.md)，证明协议见 [`../docs/ZKP.md`](../docs/ZKP.md)。
