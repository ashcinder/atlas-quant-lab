# 隔离完整执行 Proof 测试

这些工具只处理新建合成输入，不能挂载手测应用卷或恢复已付压测栈。运行前阅读项目 AGENTS/HANDOFF；不创建收费订单、不使用开发模式，不访问云证明服务。

## 制品与配置

- SDK固定3.0.6，guest、v1/v2 profile及Image ID不变。`extract_guests.py`可从固定发布二进制恢复ELF供host单独构建，**必须先运行Rust固定Image ID测试**；提取manifest本身不是验收。
- `prove`默认分段20；显式`--segment-limit-po2 16..20`启用实验；`--segment-path`仅接受已有目录，调用者负责生命周期。
- `analyze`执行完整guest，输出`execution_only=true`、完整journal、cycles及分段，不生成receipt或`valid=true`。
- 作者脚本支持`ATLAS_PROOF_THREADS=1..3`（默认1）、`ATLAS_PROOF_SEGMENT_PO2=16..20`（默认不传）、`ATLAS_PROOF_DISK_SEGMENTS=0|1`（默认0）。启用磁盘分段时只创建/清理该任务的0700临时目录。参数不改变策略、输入、费用或profile。
- host证明强制走SDK本地实现，保持项目脚本原有local行为；不接受远端prover选择。公开`prover_performance`只含性能白名单字段。

## 单档与递增实验

从项目根执行，使用项目已有Python3.12环境：

```bash
./.artifacts/remediation-20261031/venv/bin/python tools/proofbench/run.py \
  --binary /absolute/path/to/atlas-zkvm \
  --image atlas-proofbench-api:20261104-arm64 --platform linux/arm64 \
  --output /absolute/path/to/new-evidence-directory \
  --program sma --bars 16 32 100 500 1000 \
  --mode prove --po2 18 --threads 2 --cpus 3 --memory 5g --timeout 1800
```

`zero/sma/state`三种输入均固定、可重算；均线程序预热20根，有状态程序用寄存器跨根更新。先`analyze`再证明。证明容器无网络、无swap、上限3CPU/5GiB；API集成须显式`--integrated --memory 6g`，API和证明共用cgroup，单worker。镜像需有Python、项目依赖及C++运行库，二进制架构须匹配。

每档记录精确binary SHA、镜像ID、参数、kernel `memory.peak`、CPU累计、临时文件和宿主内存采样。容器95%或宿主85%持续10秒、OOM或手测health连续3次失败即终止系列；500根超时30分钟，1000根单独设置60分钟。不要将较大Docker宿主的受限容器结果称为4核8GiB整机验收。

`--disk-segments`只用于比较磁盘与默认tmpfs；不预设临时文件是内存故障原因。样本输出目录只创建一次，失败保留原始结果；不得复用覆盖失败证据。

独立模式和集成模式均有容器内部的证明进程超时，外部监测失联也不能无限证明。外部每约2秒检查资源/手测健康；保护测试可运行`pytest -q tools/proofbench/test_runner.py`，不启动Docker或真实Proof。

## 验真与功能

`sweep.py --resume`只复用已成功的真实Proof并重新验真，失败样本拒绝自动重试。旧验证目录重命名保留。若监测被中断但Proof已完成，单独记录`measurement_complete=false`及观测峰值下界，不能把它当作完整资源验收，也不参与候选参数选择。

- `validate.py`在独立运行容器内使用`/source`只读程序、`/candidate/atlas-zkvm`及`/sample`新测试目录，登记真实receipt、调用现有API验真/下载、执行现有离线脚本，并测试receipt/Image ID/行情/公开结果篡改。
- Rust测试`development_receipt_is_rejected`检查假receipt拒绝；`rejects_missing_reordered_and_replaced_segments`必须设置`ATLAS_REAL_RECEIPT_TEST_PATH`为真实多段证明并显式运行`--ignored`，否则不算该项通过。
- `integrated.py`仅由`run.py --integrated`调用。新建五个账号并通过真实HTTP登录，先测60秒基线，再在Proof运行时按每人每2秒一次请求读查询/账本和保存项目，检查状态、响应及P95。它直接调用local host，不创建或仿造已付任务；付费任务/共享计算槽恢复由后端回归覆盖，不能将此测试写成真实支付链验收。
- 16MiB回执、在线45秒、离线60秒限制不放宽。真实receipt必须完整journal等于原输入inspect，decision_count与观测数、全部K线根数相等。保持旧Proof可验。

## 回退与运行边界

实验参数全部移除即可恢复默认线程1/分段20/SDK默认临时文件，数据库不迁移。当前手测四服务、Supervisor/MySQL和卷不自动更新；这些实验工具不执行提交、推送、资源购买、支付或运行服务更新；发布须另有明确授权。测试制品仅候选，不能直接覆盖运行中的验证器。

`.artifacts`中的隔离应用含新生成的会话/签名材料；只分享脱敏报告、性能统计与明确可公开的合成Proof包，不整体打包测试应用目录。

## 隔离新guest实验（用户追加授权）

`prepare_guest_experiments.py DEST`只创建新目录，拒绝覆盖。生成baseline（仅实验标签）、sha（SDK RustCrypto SHA wrapper）与optimized（再加精确i128均线前缀和、逐根清空的复用栈）。不修改正式guest、Image ID、profiles、付费任务或运行服务。

`build_guest_experiments.py DEST`使用已验证官方SHA的Rust1.97.0-dev工具链、SDK3.0.6 user guest flags、原Cargo.lock，在无网络amd64独立容器离线编译；此编译架构不代表Proof架构。guest本身不把回测拆块。先运行各实验core的`cargo test --offline --release`，再通过完整500/1000根执行对比全部journal（仅归一实验profile标签）。

`experimental-driver`是单独crate，编译时复制项目原Cargo.lock，保留SDK3.0.6与disable-dev-mode。`pack USER_ELF OLD_R0BF NEW_R0BF`校验旧R0BF固定Image ID后，仅复用其SDK内核；`analyze|prove GUEST_R0BF EXPECTED_IMAGE_ID WITNESS PO2 SEGMENT_DIR [RECEIPT]`核对实际guest ID、完整执行并与原算法逐字段对比，真实Proof仍为SDK完整Session/Composite。`tampercheck RECEIPT ID`要求真多段Proof，检查删除、乱序、替换及假receipt拒绝。

实验driver通过`run.py --experimental-guest ... --experimental-image-id ... --disk-segments`运行，原资源/健康/内外超时保护均保留。实验普通API竞争必须另传`--integrated --memory 6g --verifier-binary STANDARD_HOST`；API保留原profiles/模型与标准验证器，独立实验driver只生成Proof，不把实验CLI接到普通API上。该模式测试资源争用，完成后的新receipt仍需隔离迁移模型验真；不代表正式API支持新profile。变体暂共用实验标签，**身份必须使用标签+各自固定Image ID二元组**，不得合并样本注册表或把标签当正式唯一guest版本。

验真阶段`validate.py`挂载的是**标准candidate-arm64/atlas-zkvm验证器**，不是实验driver。标准验证器已支持显式expected Image ID。实验分支只在新验证目录创建额外profile注册项，保留正式v2旧ID；API/store/离线原路径均使用这个私有注册表，正式v2必须拒绝新receipt。inspect使用原v2算法计算全部字段，再仅归一实验标签。16MiB、在线45秒和离线60秒限制不变。此隔离验证不代表正式服务已支持新profile；上线迁移仍需独立审查与授权。

当前正式`ZkPublicStatement.proof_profile`是v1/v2 Literal，已实测拒绝新实验profile。`prepare_guest_validation.py DEST/backend`仅在新代码副本添加实验Literal，保留旧值及所有字段约束；`sweep.validate(..., backend_source=DEST/backend)`才使用这份隔离迁移副本。正式应用模型/注册表不变，不能把隔离API成功写成当前服务已支持新guest。

追加授权的整数除法实验由`prepare_narrow_guest.py SOURCE_OPTIMIZED DEST_NARROW`生成。工具固定核对canonical reference与实测optimized源SHA，只有15处原i128除法换成同位置的`div_exact`；乘法、括号、截断位置及f64不变。两操作数可精确转换u32/u64才窄除法，负数/超界回退原i128，零除和MIN/-1仍拒绝。`build_guest_experiments.py --variants narrow`与`compare_guest_experiments.py --variants narrow`可单独追加新变体，不覆盖旧全量分析。`verify_division_paths.py`另做3个合法完整guest输入，明确命中u32、u64、i128 SMA路径并比较完整journal，均不是Proof。

`--mode trace`仅允许隔离driver，聚合PC命中和SDK累计user cycle delta，不驻留完整事件流；末指令flush后必须精确等于session.user_cycles。分页事件只单列全局统计，不能归属某PC。`pc_trace_lines.go USER_ELF PC_TRACE_JSON`根据实际ELF的DWARF映射源码。追踪和带debug信息guest用于诊断，不纳入Proof计时或冒充真Proof。新增测试代码可能改变ELF的非加载符号表；通过SDK计算相同Image ID才能确认加载程序完全相同，不能只比较ELF文件大小。

隔离目录复用同一容器路径与Cargo target时，复制源文件应采用新mtime，避免Cargo重用其他根包的旧测试可执行文件；生成器使用`copyfile`，保留失败日志。依赖步骤使用`set -e`或`subprocess.run(check=True)`，生成失败后不得继续测试或证明。

`prepare_buffered_guest.py SOURCE_NARROW DEST_BUFFERED`固定核对core/reference/旧入口SHA，只把guest一次性witness读取改为SDK3.0.6支持的8KiB `BufReader`；序列化协议与core完全不变，添加直接serde依赖但不升级版本。该实验是隔离入口实现选择，不能当作已获正式profile迁移授权。`build_guest_experiments.py`、`compare_guest_experiments.py`支持单独`--variants buffered`，仍先做全量journal对比。

`verify_buffered_input.py EXPERIMENT --driver INPUT_DRIVER --output NEW_DIR`使用实际SDK `to_vec`序列化3/16/32/100/500/1000根，分析原/缓冲guest的完整输入、1..4字节末尾截断、8/16KiB边界截断与追加4字节；拒绝必须是`DeserializeUnexpectedEnd`且无成功输出，OOM不算拒绝。旧入口和缓冲入口均忽略尾随字节，测试保持这一行为，未增加EOF规则。实验driver的`encode`只序列化，`analyze-raw`只执行分析，不能进入prove；正常prove始终使用原`builder.write(&witness)`路径。输入诊断driver单独冻结，不能覆盖已计时的Proof driver。

`test_runner.py`当前17项覆盖保护条件、内外超时、API隔离/SLO与最终cgroup峰值/尾部OOM；结束前最后读取kernel `memory.peak`，防止采样遗漏末尾内存尖峰。若最后读取不可用，标记监测不完整。

`prepare_signed_guest.py SOURCE_BUFFERED DEST_SIGNED`继续精确32/64位除法实验：先保留u32/u64，再对双方精确容纳的i32/i64使用`checked_div`；窄`MIN / -1`升级或回原i128，宽值及最终溢出/零除仍走原表达式。15个原公式调用点不再改动。host测试新增signed边界及各1万随机i32/i64差分；`verify_division_paths.py --signed`再明确执行负i32、负i64与i32 MIN/-1完整guest输入。`--variants signed`先比较全量journal与周期，有收益才考虑新真实Proof，不能把分析当Proof。

最新runner共17项测试。集成API启动前实际运行标准host的v2 profile并核对原注册ID，实验driver的相同SHA副本也拒绝作为API验证器；API SLO失败独立记录`ordinary_api_slo`。内部Proof严格按指定秒数结束；外部最多15秒只用于收集完成/竞争记录，缺结束marker标测量不完整。process marker临时文件原子重命名，防止读到半份JSON。

`accept_experimental.py EXPERIMENT --variant signed --initial-sma COMPLETED_SMA_ROOT --verifier STANDARD_HOST --output NEW_DIR [--explore-1000]`只复用同一guest/driver、固定完整输入、原生3CPU/3线程/5GiB且已成功的16/32/100/500均线样本，重新真实验真后才开始状态递增与500重复。500统一po19，第三次均线重复为API/Proof共同6GiB的真实竞争，SLO必须显式通过。两种策略各三次500≤1800秒通过后，显式`--explore-1000`才允许各3600秒探测；失败/保护立即停止，不重跑失败目录。`acceptance.json`始终保留4CPU8GiB整机待验收标记。控制流单元测试使用mock，不作为真实Proof证据。

## 2026-11-05 第二轮隔离热点实验

`prepare_hash_guest.py SOURCE_SIGNED DEST [--full-market]`固定输入源、Cargo与锁SHA，批量编码完全相同的哈希预映像，SDK标准`Impl::hash_bytes`保留SHA padding，Merkle仅在原leaf Vec内逐层压缩（奇数末叶复制保持）。`hashbatch`逐bar48B更新，`hashfull`完整market预映像一次hash，额外内存约48×bars字节，必须在证明内存测量中计入。host额外覆盖SHA边界/不对齐、1..129及500/1000/20000叶奇数树、字符串长度前缀。

`prepare_word_guest.py SOURCE_HASHFULL DEST`保持原SDK Serde协议，仅以`WordReader`从BufReader缓冲区直接读LE u32，跨短读回退read_exact，padding仍必须存在但不解释。`verify_buffered_input.py ... --variants signed hashwords`真实SDK编码检查完整输入、截断及尾随1/3/4字节兼容；分析结果不是Proof。

`prepare_lto_guest.py SOURCE_HASHWORDS DEST`仅比较guest release fatLTO/codegen1；`prepare_inline_guest.py SOURCE_HASHWORDS DEST [--lto]`替换原div_exact #[inline]为#[inline(always)]，公式和宽整数回退不变，无fast-math。所有新候选使用同SDK3.0.6/工具链/锁，并在新的名字/文件夹中构建、打包和比较，不覆盖冻结产物。历史hashinline/hashinlinelto最初重复属性实验无效（后者主动中止构建），保留为失败证据；修复后的候选名hashforceinline/hashforcelto。

先运行host差分和完整500/1000×3程序journal/cycles比较，再选出已测候选，不宣称全局最优。新真Proof仍按16/32/100/500串行、3CPU5GiB、500≤1800秒和原健康/资源保护；失败不重试、不扩大。accept_experimental支持新variant，旧整机/重复/SLO门控不放宽；1000必须六次500及共享6GiB API竞争均通过后才允许。当前服务、正式profile和旧付费任务保持原路径。

## 用户主动暂停后的显式恢复

只有用户明确要求恢复后，使用原`accept_experimental.py`参数并额外提供`--resume-user-pause PRIOR_ACCEPTANCE_DIR --pause-record USER_PAUSE_JSON`，`--output`必须指向全新目录。该入口只承认先前验收为KeyboardInterrupt、独立审计标明用户暂停、实际样本为observer_interrupted/未完成且没有receipt，并核对原guest/driver/runtime/宿主配置、输入、未触发OOM/持续资源或健康保护的原始观测。超时或其他失败不能借此重试。

原样本必须是固定计划的完整有序前缀（包括初始SMA四档），且全部在新output/reverified副本上重新完整验真后才运行缺失项；原receipt/witness/parameters/result保持只读，并记录其SHA。输出不能位于旧验收或初始样本树内。已有process.json、退出码或容器已停止均拒绝当作暂停，避免中断与进程退出竞态。旧partial与验收JSON保留，恢复样本写入新目录。各三次500+共享6GiB五用户SLO门控不变，1000仍显式条件探测。此恢复入口是本地隔离实验工具，不涉及付费任务恢复、订单或正式API。

## 2026-11-05 安全修复边界

新增生成入口共用配置校验；元数据四字段最多4096 UTF-8字节、witness最多16MiB（有界读取），新付费任务在建单前预算完整私有witness。冻结guest未修改，内部没有新增长度约束。磁盘段仅回收0700任务目录内带归属marker且无活动锁的本任务目录，旧无marker残留不自动删除；底层host继承task/global worker锁。

标准host仅为固定v3实验标签增加只读inspect，不允许其prove/analyze/profile，不改变正式registry/models。实验源码快照在strategy/zkvm/source-snapshots，下载包含固定清单，离线只信任checkout固定映射；guest_source_verified不代表本轮重编guest。公开性能不再含timings/input_bytes/cycles，完整诊断留0600私有文件。详见docs/testing/proof-safety-fix-20261105/REPORT.md；本轮没有切换手测版本或生成新Proof。
