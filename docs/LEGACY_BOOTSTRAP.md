> Archived setup notes. Counts and milestones below describe earlier work. For the current ABC pilot, open the [project README](../README.md). Run commands from the project root.

# Nepal Trail RAG

For the ABC six-day pilot on this Mac, open [run-abc-live.command](../run-abc-live.command). Its English web app includes reviewed route questions, on-demand point forecasts and official bulletin lookup. The [deployment guide](../docs/DEPLOYMENT.md#abc-weather-and-trail-updates) covers the 85-record package, data freshness and the limits of trail-status checks.

本轮已在 Mac 跑通真实模型、1024维语义检索与页面：28项自动检查通过，8题配对采集完成，人工评分待填写。具体失败样例、配置与下一轮验收安排见 [本轮原型验收材料](../docs/PROTOTYPE_REVIEW_20261118.md)。

一个在 Mac 本机运行的英文尼泊尔徒步资料问答原型。页面把回答、检索证据、原文定位与许可信息放在一起，方便核对“答案依据什么”。研究目标是比较同一个 Qwen3.5-4B 在有检索和无检索时的回答表现。

**目前只接入六条已经接受的非距离事实：`K07`、`K08`、`W01`–`W04`。** 它们支持特定 ABC 参考行程的天数标签、日段端点及社区资料描述的走廊顺序。它们不能回答完整路线距离、海拔、爬升、耗时、许可费用、实时天气、当前开放状态或个人安全判断。ABC、EBC、ACT 和 EBC–Gokyo 是后续方向，尚未成为当前资料覆盖。

原 R03 冻结审核版保持不变。K09 已排除，K01–K06 的距离资料继续暂停；W05–W06、P01–P02 等待人工验收，开发原型不会自动批准它们。现阶段不宣称 RAG 已比基线更准确，也不宣称系统能够减少事故。

## 两种运行方式

| 方式 | 检索与生成 | 用途 |
| --- | --- | --- |
| 轻量证据预览 | 词汇特征哈希 + Qdrant Local；生成模型未配置 | 检查页面、数据边界、来源展示和检索链；不是模型评估 |
| 真实本地模型 | Qwen3-Embedding-0.6B / sentence-transformers + Qdrant Local；MLX-LM 运行 Qwen3.5-4B 4-bit | 真正的 RAG / 无 RAG 配对运行；实际结果需另行记录、评分 |

两种方式使用同一份受控 release。默认预览不会下载模型；未连接生成器时，无 RAG 基线显示不可用，不伪造答案。LM Studio 也可作为兼容本地 API 的运行器，但同一次比较应固定 runner、模型、量化版本及生成参数。

## 项目目录

```text
nepal-trail-rag/
├── app/
│   ├── config.py                 # 本地配置与端点限制
│   ├── release.py                # manifest、许可、哈希与依赖校验
│   ├── retrieval.py              # embedding 与 Qdrant Local
│   ├── llm.py                    # 本地兼容生成接口
│   ├── service.py                # 问答、共同范围与证据处理
│   ├── main.py                   # FastAPI 与同源页面
│   └── static/                   # 英文界面 HTML / CSS / JS
├── data/
│   ├── release/                  # 六条事实、来源、scope、署名和 manifest
│   ├── data_contract.json        # 数据合同
│   ├── bootstrap_validation.audit.json
│   └── export_verified_subset.py # 受控子集导出记录
├── evaluation/
│   ├── development.json          # 八道开发题与评分依据，禁止进入知识库
│   ├── build_development_subset.py
│   └── README.md
├── scripts/
│   ├── setup_mac.py              # 在本地 Caches 创建环境并安装约束依赖
│   ├── download_models.py        # 下载公开模型并记录固定 revision
│   ├── launch_local.py           # 启动固定模型与语义 RAG 应用
│   ├── validate_release.py       # 无需模型的数据校验
│   ├── stage_update.py           # 产生待审候选与清洗日志
│   ├── promote_release.py        # 经明确人审后产生新发布目录
│   └── run_development.py        # 真实模型配对运行与待评分表
├── docs/
│   ├── CLEANING_AND_INGESTION.md
│   ├── ARCHITECTURE.md
│   ├── DEPLOYMENT.md
│   └── EXPERIMENTS_AND_REVIEW.md
├── tests/                        # 数据、人审边界和应用检查
├── .github/workflows/ci.yml      # 离线质量检查；不运行模型或部署
├── .env.example
├── config/model_pins.json        # 生成与 embedding 模型的固定 revision
├── requirements/                # 直接依赖约束与本机完整环境观察快照
├── pyproject.toml
└── run-local.command             # Mac 双击启动真实本地模型服务
```

实际环境和模型缓存位于项目目录外：

```text
~/Library/Caches/Trailwise/nepal-trail-rag/
├── fresh-venv/                   # Python 3.12 与项目依赖
└── model-runtime/
    ├── hf/                      # 固定模型 snapshots / 权重
    ├── model_snapshots.json      # 实际 revision 与本地路径
    └── qdrant/                  # 按 release / embedding 隔离的派生索引
```

本机 `Documents` 由 iCloud 管理，曾出现依赖与权重变为按需下载文件、导入长时间等待的情况。因此环境、模型及运行索引改放本地 `Library/Caches`。项目内原有 `.venv/` 与 `runtime/` 保留为已忽略的旧生成目录，不是当前启动器使用的环境或模型依据；不通过符号链接或搬移项目环境来配置新安装。

## Mac 设置与真实模型启动

这台Mac已完成初始化，日常启动可双击项目中的 `run-local.command`。以下设置步骤用于新机器或重建环境，需要先有可用的Python 3.12；本机虚拟环境不随仓库分发。

需要 Python 3.12。以下命令在项目目录运行：

```sh
python3.12 scripts/setup_mac.py --install
source ~/Library/Caches/Trailwise/nepal-trail-rag/fresh-venv/bin/activate
python scripts/download_models.py
python scripts/validate_release.py
python scripts/launch_local.py
```

初始化完成后，也可在 Finder 双击 `run-local.command`，它会使用 Caches 中的 `fresh-venv` 启动真实模型服务与应用。浏览器打开 [本地页面](http://127.0.0.1:8765)，在启动终端按 Ctrl+C 停止两项服务。端口已被占用时先停止已有服务，避免同时启动两套。

设置脚本按 `requirements/constraints-mac.txt` 安装 `dev,embeddings,mlx,download` 依赖。首次安装与模型下载需要联网；缺少 `python3.12` 时先准备 Python 3.12。项目代码与审核资料留在原位置，设置脚本不迁移旧环境或建立目录链接。

下载脚本默认把两个固定 revision 保存到上述 Caches 的 `model-runtime`，并记录 `model_snapshots.json`。启动脚本核对 `config/model_pins.json`，使用 CPU embedding、单进程应用和 MLX 生成服务。`requirements/constraints-*.txt` 固定直接依赖版本；`requirements/macos-py312.freeze.txt` 另记录本机完整安装环境，它是观察快照，不能视为跨平台或带制品哈希的锁文件。运行比较时不得悄悄换成更新的模型。

模型兼容接口为 `http://127.0.0.1:8081/v1`，应用为 `http://127.0.0.1:8765`。启动脚本设置模型 snapshot、语义 embedding 和本地缓存配置；直接使用 LM Studio 时再按 `.env.example` 配置其端口与实际模型 ID。同一次比较应固定运行器。

16 GB 统一内存下先采用低并发、短输出和 CPU embedding；实际峰值内存与耗时由运行记录提供。分别确认：模型接口可连接、指定生成模型已加载、embedding 为语义模式、release 与索引匹配。仅有服务端口或页面可打开，不能证明完整模型链已运行成功。此处不代表八题共十六次回答已完成或已评分；实际验证另行记录。

## 仅启动证据预览

完成上述环境设置后，可在不启动生成服务、不下载模型的情况下预览页面：

```sh
source ~/Library/Caches/Trailwise/nepal-trail-rag/fresh-venv/bin/activate
EMBEDDING_MODE=hash MODEL_ID='' RUNTIME_DIR="$HOME/Library/Caches/Trailwise/nepal-trail-rag/model-runtime/preview" python -m uvicorn app.main:app --host 127.0.0.1 --port 8765
```

页面应明确显示证据预览和生成模型的真实状态。`.env.example` 提供可选配置参考，已有 `.env` 时先查看内容，避免覆盖自己的配置。

## 新资料如何接入

新来源可以继续使用相同字段与 JSONL 格式；条目数没有固定为六条。每一批依次进行：原文与许可登记 → 候选提取 → 清洗与版本核对 → 冲突检查 → 人工接受精确哈希 → 新发布版 → 新索引与回归检查。

先产生待审候选：

```sh
python scripts/stage_update.py --facts incoming.jsonl --output "$HOME/Library/Caches/Trailwise/nepal-trail-rag/model-runtime/staging/review-02"
```

这一步只规范叙述字段的 Unicode 与空白，保留数值、单位、实体和来源字段。与基线不同的既有事实增加 revision，所有候选重置为 `PENDING`。候选及审核日志不能直接加入检索。

逐条人工审核后，才可以使用实际审核文件创建一个新目录：

```sh
python scripts/promote_release.py --facts reviewed.jsonl --sources reviewed_sources.jsonl --scope scope.json --review-event review_event.json --output data/releases/review-02 --release-id NEPAL-LOCAL-REVIEW-02
```

文件名是操作示例。命令要求事实与来源的接受记录匹配当前内容哈希，并要求明确的人工确认事件；先校验完整临时发布版，再建立新目录。**已有目录不覆盖，也不自动切换应用或恢复停用事实。** 新 release 确认后可通过 `DATA_RELEASE_DIR` 选择，并重启单个应用进程。细则与审核事件要求见 [清洗与接入规则](../docs/CLEANING_AND_INGESTION.md)。

新发布版与人工事件应纳入可靠的版本管理/备份；Caches 只保存可重建运行物和待审临时内容，不能成为审核历史的唯一保存位置。

## 检查与开发题

```sh
python scripts/validate_release.py
ruff check app scripts tests
pytest -q
```

GitHub Actions 在 PR、推送 `main` 和手动触发时执行这些离线检查。它不下载模型、不调用本机模型服务、不使用模型 token，也不部署应用。

真实模型和语义 embedding 就绪后，可以运行八题配对开发实验：

```sh
python scripts/run_development.py --base-url http://127.0.0.1:8765
```

程序保存实际回答、检索与运行配置及待填写的人工评分表；没有合格模型配置时拒绝把预览算成实验。六道正答题与两道边界题分开报告；共同范围规则直接返回的边界响应属于流程行为，单独记录，不当作检索或生成模型收益。**人工评分、引用是否支持断言，以及 RAG 是否改善的结论仍待实际检查。** 后续还需要未参与调试的保留题，不能把开发题成绩当作整体泛化效果。

## 每轮验收与部署

每轮按“一个改进假设 → 一项有界变化 → 检查结果和错误 → 人工验收 → 冻结新版本”推进。代码检查通过不等于新事实被接受，模型链运行成功也不等于 RAG 更好。保留失败案例、缺失资料和实测成本，为 report 与 oral presentation 的 limitations 提供证据。

当前部署目标是 Mac 本机，应用、模型 API 与数据库保持本地访问。没有配置公共发布流程。公网服务所需的访问控制、HTTPS、并发与成本限制、许可展示、日志及回滚，须按照 [部署规则](../docs/DEPLOYMENT.md) 另行实现和验收；不要直接把本地模型端口暴露到公网。

更多说明：[项目架构](../docs/ARCHITECTURE.md) · [清洗与增量接入](../docs/CLEANING_AND_INGESTION.md) · [实验、人工验收与六项作业证据](../docs/EXPERIMENTS_AND_REVIEW.md) · [开发题说明](../evaluation/README.md)。资料署名见 [ATTRIBUTION](../data/release/ATTRIBUTION.txt)，其许可范围独立于项目代码和模型权重。
