# DeAI Quant Hub 隔离验收

在仓库根目录运行。测试使用合成账号和独立 Docker 卷。运行清单、三引擎结果、性能采样和失败记录写入 `.artifacts/`。同一 Docker 主机已有五服务站点时，设置 `ATLAS_E2E_PROTECTED_PROJECT` 为该 Compose 项目名，并在本轮所有命令中保持一致。独立测试主机可以使用空保护基线。

准备[固定 Linux 验证器](../../docs/DEPLOYMENT.md#构建前置条件)，再构建测试所需的镜像。测试 Web 镜像使用本次构建的前端文件，`freeze.py` 核对容器中实际提供的字节。

```sh
npm --prefix frontend ci
npm --prefix frontend exec -- playwright install chromium firefox webkit
npm --prefix frontend test
npm --prefix frontend run lint
npm --prefix frontend run build
ATLAS_API_IMAGE=atlas-quant-api:r23-local ATLAS_WEB_IMAGE=atlas-quant-web:r23-local \
  bash deploy/release/build-images.sh
docker build --platform linux/amd64 -f tools/e2e/web.Dockerfile -t atlas-e2e-web:local frontend/dist
python3 tools/e2e/control.py start --run-id e2e-functional-local --port 18221 --web-image atlas-e2e-web:local
python3 tools/e2e/freeze.py .artifacts/e2e-functional-local
ATLAS_E2E_FIXTURE="$PWD/.artifacts/e2e-functional-local/fixture.json" \
ATLAS_E2E_EVIDENCE="$PWD/.artifacts/e2e-functional-local/playwright" \
npm --prefix frontend run test:e2e
```

首次准备固定 OCR 模型。

```sh
mkdir -p .artifacts/comprehensive-20261108/samples
curl -fL 'https://cdn.jsdelivr.net/npm/@tesseract.js-data/eng/4.0.0_best_int/eng.traineddata.gz' \
  -o .artifacts/comprehensive-20261108/samples/eng.traineddata.gz
shasum -a 256 .artifacts/comprehensive-20261108/samples/eng.traineddata.gz
```

期望摘要为 `45b4cb346724ac1774f1c36f42f182b887bcdb28ebe63e6fff90ac41f3fcff91`。也可用 `ATLAS_E2E_OCR_MODEL` 指定同一份文件。

后端使用现有 Python 虚拟环境运行 `python -m pytest backend/tests -o addopts= -q`。真实 Proof 场景需在启动时传入 `--receipt-bundle /path/to/compat-bundle.zip`，样本固定 SHA-256 见 `bootstrap.py`。取得固定 OCR 模型与既有 receipt 后再执行完整矩阵。AI、支付和交易所由 `bootstrap.py` 在外部服务边界模拟，Nginx、鉴权、SQLite、账本及计算入口使用实际应用。真实公共行情通过 `online-market.json` 交给独立卷上的行情发布器，之后用 `online.mjs` 检查来源、覆盖数量及真实计算。

容量脚本的宿主采样当前使用 macOS 的 `caffeinate` 与 `vm_stat`。短档诊断和正式对账需要独立卷。正式长测使用已验证的既有 Proof 样本。

```sh
python3 tools/e2e/control.py start --run-id e2e-performance-local --port 18222 \
  --web-image atlas-e2e-web:local --cpus 4 --memory 4096 \
  --receipt-bundle /path/to/compat-bundle.zip
python3 tools/e2e/freeze.py .artifacts/e2e-performance-local
# 3600 秒负载和 600 秒恢复
bash tools/e2e/run-capacity.sh .artifacts/e2e-performance-local
```

每个并发档位在上一档结束后执行。负载脚本建立独立 Chromium 会话并通过 UI 登录。长测期间不要同时运行其他浏览器、构建或测试。脚本将短测状态写为 `diagnostic_pass`，一小时主体状态写为 `success`。恢复脚本独立记录各模拟运行的成交、租约和五个受保护服务。只有专属环境中可尝试资源扩容，使用 `control.py start --cpus 4 --memory 4096` 建立新卷和项目。

用 `gate.py` 评估证据目录。三个浏览器的 Playwright JSON 分别为 `chromium.json`、`firefox.json` 和 `webkit.json`。补充证据的状态和路径填入 `supplements.json`，原一小时测量结果为 `performance.json`。缺失检查使工具返回 2。发布仍需审核具体矩阵、备份和回退材料。

```sh
python3 tools/e2e/control.py stop --run-id e2e-functional-local
python3 tools/e2e/control.py stop --run-id e2e-performance-local
```

剩余计划补验位于 `frontend/e2e/gap-*.spec.ts`：慢网和真实客户端超时保留草稿、Proof 验证服务故障恢复、跨市场组合、自动定投、各可达弹窗及隐藏工作区的键盘操作。付款与本地设置是 modeless；只对 modal 要求 Tab 留在弹窗内。定时器前进仅作用于独立浏览器页面，不修改服务器时间。

原生 200% 缩放脚本使用一次性浏览器资料目录，禁止替换为 CSS zoom 或 deviceScaleFactor。Chromium 使用 tabs zoom API，Firefox 使用内置 Marionette 的 FullZoom，WebKit 使用本机非持久 WKWebView 的 pageZoom（不代表 Safari 或真实手机）。

```sh
node tools/e2e/chromium-native-zoom.mjs .artifacts/e2e-functional-local .artifacts/zoom-chromium
python3 tools/e2e/native-zoom/firefox.py --help
swiftc tools/e2e/native-zoom/webkit.swift -o /tmp/atlas-wkzoom
/tmp/atlas-wkzoom .artifacts/e2e-functional-local/run.json .artifacts/zoom-webkit user97
python3 tools/e2e/verify-public-receipts.py --help
```

组合联合边界独立核算在 `frontend/src/compute/portfolio-boundaries.test.ts`。恶意归档及静态软链接边界在后端测试；软链接检查不承诺防御已取得应用同 UID 目录写权限的并发替换。真实 Proof 只验证可取得的既有 receipt；无样本 profile 单列阻塞，不生成收费 Proof 补数。
