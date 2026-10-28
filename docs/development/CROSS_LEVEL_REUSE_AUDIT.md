# 跨层研究复用审计

审计日期：2026-10-28。WARDEN 基线 `381fc08`，StegoPot 固定
`f374a39b306c589ec7bf9eeff9d1c2dc1e942fb5`；FRACTAL 原固定
`8081bc61f98cca243034c20951f64522b84ab5fa`，兼容候选
`a0584cbc982b7b4260a1ebf1ccd51b64ede72eab`。基础库源码只读。

## 实现与复用边界

| 能力 | 最近实现与事实 | 扩展理由与兼容成本 |
|---|---|---|
| 历史场景合同 | `adapters/fractal_bench.py`，已有集成测试 | 保留原类和旧 BenchmarkInstance 含义 |
| M 数据 | FRACTAL `JsonMechanismDatasetStore`、Validator、split | 新薄 Adapter 只做授权视图与训练标签分离，不复刻生成器 |
| Probe | `data/corpus.py`、`methods/probe/linear.py` 与 `suite.py` | 复用训练器，补充 label_semantics/source/readout 来源 |
| LEACE | 现有方向平移不能表达协方差擦除 | 新方法 Adapter 调用固定第三方库；不复制数学内核 |
| Patching | StegoPot `Intervention`、`ReplaceOperator`、`TensorRef` | 薄适配器校验 donor/recipient，禁止新建 Hook |
| 研究阶段 | `CallableAuditStage`、`PipelineAuditExecutor` | 复用阶段包装器接入既有 whitebox 函数 |
| 持久任务 | `InProcessRunDispatcher` 仅内存且同步 | 新 SQLite 适配器实现原端口，额外提供幂等提交和显式单 worker 消费 |
| 工件下载 | `FileArtifactRepository` 有内容寻址，open 缺严格 ID 校验 | 扩展既有存储校验和授权网关，不接收任意 URI |
| S 通信 | StegoPot topology、CodecPolicy、ChannelTransform、TrialRunner | 原实现可复用；真实基线需本地模型和冻结数据，不以模拟结果代替 |
| 指标 | StegoPot StegoEvaluator 已有 BER | WARDEN 仅聚合执行状态、ITT 分母，BER 由上游传入 |

## FRACTAL API 差异

候选版本由 0.4.0 到 0.5.1，Python 要求仍为 >=3.11，运行依赖无新增。
历史 `JsonDatasetStore` 与 Scenario 入口保留；新增独立
`JsonMechanismDatasetStore`、`schema/mechanism.py`、mechanism validator 与
codebook_binding。两种 schema 必须按明确 API 分别读取。

## 验证分类

已有 Probe 与 tiny audit 属于本地实现验证。真实 Qwen baseline、通信干预效果、
LEACE 行为选择性、Patching 真实生成效果均需独立运行证据；源码存在不等于通过。
每阶段的实际结果见 `RESEARCH_GATE_*.md`。不推送远程、不启动计费 GPU。
