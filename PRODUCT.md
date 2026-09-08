# Product
<!-- impeccable:product-schema 1 -->

## Platform
web

## Users
希望制定和验证量化策略的用户：既包括不熟悉代码的用户，也包括希望直接编写代码策略的用户。

## Product Purpose
DeAI Quant Hub 提供可信投资策略验证。策略实验室让用户用图形化规则和 AI 积木表达交易全流程。

## Product Principles
- 引导式策略画布，默认简单，按需展开高级配置（2026-09-08 用户确认）。
- 两种开发方式并列：引导式图形化策略、多语言代码策略（2026-09-08 用户新指令）。
- 代码模块支持本地导入、编辑、下载与侧边 AI 建议；应用 AI 修改前可预览。
- 保留深入定制能力，用交易语言解释配置。

## Capabilities and Constraints
现有 React/TypeScript + FastAPI 应用支持规则回测、工作流结构校验和私密版本保存。AI 工作流执行尚未接入；不能将配置或结构有效称为 AI 已执行或策略已验证。平台不执行实盘交易。

## Evidence on Hand
现有应用及用户提供的旧界面截图；HANDOFF 和 docs/memory/GOALS 记录事实边界。
