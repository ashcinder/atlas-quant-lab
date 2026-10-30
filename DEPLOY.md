# Atlas Quant Lab 部署与源码分享

更新：2026-10-30；按实现版本 `4be31bf` 核对。功能与验收边界见[当前版本](docs/CURRENT_STATUS.md)。

## 选择运行方式

| 需求 | 入口 |
| --- | --- |
| 本机修改源码 | [README 本地启动](README.md#本地启动)，前后端双终端；不需要链 |
| 从源码构建Web/API容器 | [构建前置条件](docs/DEPLOYMENT.md#构建前置条件)，准备固定Linux验证器，再使用 `compose.yaml` |
| 固定镜像离线安装 | [基础离线部署](docs/LAB_OFFLINE_DEPLOYMENT.md)，Web/API两镜像、默认关闭新付款 |
| 完整实验室测试链 | [完整链部署](docs/LAB_CHAIN_DEPLOYMENT.md)，四镜像及三卷持久化，支持测试BKC流程 |

源码构建需要应用工具链及审核制品；镜像接收方只需Docker/Compose及运维依赖，不在目标机编译。根 `Dockerfile`、`deploy/build.sh` 和 `package.sh` 的旧单镜像路线未维护；`deploy/run.sh` 已停用。`start.sh` 是Go/MySQL一次性新链开发入口，不用于恢复既有订单。

## 已有安装升级

先核对原Compose项目、镜像、实际卷及网络身份。停止写入，备份完整业务数据与密钥；完整链模式还须同批备份链state、MySQL和私有配置。恢复到独立项目核对后再切换，不能仅沿用chain ID或新建空卷期待旧订单恢复。

基础源码Compose默认项目 `atlas-quant`；固定镜像配置默认 `atlas-quant-lab`，实际以审核ENV为准。项目名变化可能连接空卷。备份及回退见[部署指南](docs/DEPLOYMENT.md#持久化升级与停止)。

## 分享源码

只导出已审查、已提交文件。仓库根目录执行，输出必须尚不存在：

```bash
archive_path="../atlas-quant-source-$(git rev-parse --short HEAD).tar.gz"
if test -e "$archive_path"; then
  printf '%s\n' '输出文件已存在，请另选路径。' >&2
else
  git archive --format=tar.gz --output="$archive_path" HEAD
fi
```

归档不包含未提交修改、未跟踪个人配置、数据库或Linux发布制品；已跟踪文件仍需审查。当前 `.env.example`、`.env.lab.example`、`.env.chain.lab.example` 为无真实凭据模板，demo默认关闭，测试私钥为空或由初始化工具在仓库外生成。接收者需准备自己的域名、凭据及制品，不能把源码包当作可恢复的业务备份。

完整私有备份含数据库、策略输入及密钥，应加密并单独受控保存，不随源码分发。
