# 项目流程与框架

## 首轮范围与目标

首轮构建一个可展示证据的英文问答原型，使用已接受的六条非距离事实。普通提问者可以询问指定参考版本的端点、行程标签及途经顺序；页面须同时显示引用与证据边界。原型先验证资料如何进入回答，不把少量基础资料描述成完整的徒步风险规划服务。

总体目标仍是逐步支持不同经验水平的尼泊尔徒步者做行前信息核对。ABC、EBC、ACT 和 EBC–Gokyo 是原项目方向，未收集、未接受或未测试的路线不算当前覆盖。

## 组件与运行路径

```text
已接受事实 + 来源清单 + release 哈希
                ↓ 校验、字段白名单
              派生 chunks
                ↓ embedding
            Qdrant Local
                ↑ 检索与参考版本过滤
浏览器页面 → FastAPI → 问题/范围检查 → 同一生成模型 → 回答 + 引用
                         └ 无RAG基线：不加入检索证据
```

| 组件 | 首轮选择与职责 |
| --- | --- |
| 生成模型 | 已选 Qwen3.5-4B；量化版本、实际模型 ID、runner 与参数须记录在真实运行配置中 |
| Mac运行器 | 本轮启动器使用 MLX-LM；LM Studio 可作为另一兼容运行器，不改变比较中所用的生成模型 |
| Embedding | Qwen3-Embedding-0.6B；语义模式与离线词汇模式明确区分 |
| 向量库 | Qdrant Local；派生索引与原始审核资料分开，可重建 |
| 应用服务 | FastAPI 提供状态、检索及问答接口，并同源提供页面 |
| 页面 | 原生 HTML/CSS/JS；英文问答、模式切换、示例问题、来源卡片、状态和范围提示 |
| 评估 | 独立开发题与人工评分；事实得分与检索/引用指标分别计算 |

目录职责：`app/` 放应用与静态界面，`scripts/` 放校验和可重复运行工具，`data/release/` 放首批受控事实与来源，`evaluation/` 放开发题和实验产物，`docs/` 放规范，`tests/` 放可验证的业务边界，`.github/workflows/` 放离线CI。运行时索引、缓存、模型权重、私有配置和临时日志不提交到Git。

`config/model_pins.json` 固定生成与 embedding 的 revision；`requirements/` 约束直接依赖版本。Mac 通过 `python3.12 scripts/setup_mac.py --install` 建立本地 `~/Library/Caches/Trailwise/nepal-trail-rag/fresh-venv` 和 `model-runtime`。下载脚本默认写入该缓存，启动器从其 `model_snapshots.json` 核对模型，并将生成服务设为 `127.0.0.1:8081`、应用设为 `127.0.0.1:8765`。`run-local.command` 使用该环境启动两项真实服务；预览方式须明确选择词汇模式。

## 问答契约

1. 先检查问题是否涉及当前覆盖、是否需要明确参考版本；不补造缺失的距离、天气或个人安全结论。
2. RAG 模式检索当前 release 的事实，按 reference 过滤，再把有限证据和来源 ID 传入 prompt。检索文档是数据，不能覆盖系统规则；文档中出现的指令不执行。
3. 生成器用与基线相同的模型与采样配置，输出英文回答。RAG 引用必须指向实际提供的证据，不伪造 URL 或将无关命中当作支持。
4. 响应保留问题、模式、模型标识、release、检索路径、证据 ID 与耗时，供后续检查；不默认保存用户完整会话。

模型服务未连接时，页面可以显示 **Evidence preview**，但这是检索证据预览，不能称为LLM回答或记入模型比较。无RAG模式在生成器不可用时应显示不可用；不能用模板答案补成一个虚假的基线。

## 16 GB Mac 的资源策略

生成与embedding模型都按需加载，控制并发为小规模交互；小语料的向量可预计算后复用。使用量化生成模型、有限上下文和输出上限；首次下载和加载耗时不混入稳定运行的回答时延。实际峰值内存、首轮延迟和稳定延迟由真实运行记录提供，不能只由参数规模推算。

不要求同时运行两个生成模型，也不依赖Windows显卡。MLX-LM与LM Studio只选一个作为同次比较的生成服务，不能在RAG与基线之间换runner或量化版本。

运行存储也是资源设计的一部分。本机 `Documents` 的 iCloud FileProvider 曾将旧环境/权重置为按需下载状态，造成导入与加载等待，因此依赖、模型与派生索引放在非项目目录的本机 Caches。原项目 `.venv/`、`runtime/` 仅保留为被忽略的历史生成目录，不建立符号链接、不作为启动器依据。权威事实、来源审核与实验证据继续独立保存；缓存可重建，不能承担唯一备份职责。环境检查、真实问答运行与十六次开发题回答的完成状态分别记录。

## 迭代与扩展

每轮采用“一个假设 → 一项有界变化 → 检查与错误分析 → 人工验收 → 保存新版本”。资料扩展沿清洗规范进行；服务接口与展示层使用稳定 fact / source / reference ID，不依赖Excel行号。

优先实验为：无RAG对比、检索失败与生成失败分离、不同chunk或top-k的有界消融。reranker、混合检索、实时天气工具或更多路线只有在已有错误分析表明需要时才加入，避免用组件数量替代效果证据。

官方技术参考：[LM Studio兼容端点](https://lmstudio.ai/docs/developer/openai-compat)、[MLX-LM](https://github.com/ml-explore/mlx-lm)、[Qwen3-Embedding-0.6B模型卡](https://huggingface.co/Qwen/Qwen3-Embedding-0.6B)、[Qdrant文档](https://qdrant.tech/documentation/)。运行实测状态以本轮实际记录为准。
