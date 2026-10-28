# WARDEN 开发约束

## 项目定位

WARDEN 是面向多智能体协调下有害交互的因果审计及可控防御内核。它负责把多智能体
运行轨迹、模型内部表征、风险读出、因果证据和干预结果组织成可复现的安全审计闭环。

WARDEN 不是通用 Agent 编排平台、模型托管平台、前端应用或单篇论文的实验脚本。

## 依赖方向

```text
interface -> application -> core
infrastructure -----------> core
interface composition ----> infrastructure
```

- `core/domain` 只包含标准库领域对象。
- `core/ports` 只声明 Protocol，不依赖实现。
- `application` 编排用例，只依赖 `core`。
- `infrastructure` 实现 Probe、SAE 分析、存储和外部项目适配。
- `interface` 暴露 REST、事件和 CLI，并作为组合入口。
- StegoPot 与 FRACTAL-Bench 只能由 `infrastructure/adapters` 导入。

## StegoPot 与 FRACTAL-Bench 边界

- StegoPot 负责可控 forward、activation/gradient 访问、Patching、EAP 和公开 SAE 运行。
- FRACTAL-Bench 负责威胁场景、因子结构、配对条件、结构真值和行为评价。
- WARDEN 负责跨主体对齐、Probe 训练与校准、SAE 风险证据、审计计划、因果验证和干预编排。
- 不复制上游源码；两个项目通过 `vendor/` 下的 Git submodule 固定版本。

## Probe 与 SAE

- Probe 是风险读出器，必须记录数据指纹、切分、TensorRef、指标和校准信息。
- SAE 是表征分解器。SAE feature 激活不能直接表述为风险或因果证据。
- Probe/SAE 代码和清单规范进入主仓库；权重、activation 和训练数据不得提交。
- 未加载权重时显式返回 `unavailable`，不得生成模拟分数或占位检测结果。
- Probe 候选必须经过独立测试集评价；因果主张必须由 Patching 或干预实验支持。
- Probe 数据必须按案例家族固定为 train/validation/test，反事实条件不得跨切分。
- GPU Activation 采集与 CPU Probe 训练分阶段执行；重复实验应复用带哈希的 Corpus。
- 单主体和联合主体 Probe 必须共享样本行顺序，并在清单中记录联合拼接顺序。
- M 机制重放与 S 实际通信分别记录；decoded_directive、secret_bit 和 misaligned 不得混用。
- LEACE 复用固定的 concept-erasure，不以 Probe 方向平移替代；只在 train 拟合。
- 精确 token 干预不能使用 mean_tokens 拟合坐标；head patch 无后端支持时明确拒绝。
- 基础库源码默认只读；gitlink 升级必须先完成历史与新版数据回归。
- 研究阶段复用 PipelineAuditExecutor；SQLite 队列只作显式单 worker 消费。
- 中断后副作用未知的任务保留 ambiguous 信息，禁止自动重试。

## 外部接口

- 测试平台只能依赖 `/v1` API、事件契约和 Python SDK，不得导入内部实现类。
- 原始 activation 不进入普通 JSON；API 只返回 `ArtifactRef` 和统计摘要。
- 所有公开 Schema 必须版本化，新增字段默认保持向后兼容。
- 长任务通过 run ID 和状态查询表达，不在 HTTP 请求中阻塞执行完整实验。
- 研究协议与实验臂使用服务端引用白名单；禁止透传任意客户端 JSON 为执行参数。
- 研究写入要求操作者令牌。公共投影不含真值、本地 URI 或未审批工件。

## 代码规范

- 标识符使用英文；注释、docstring、参数说明和用户错误信息使用中文。
- 公开构造器和方法必须说明参数、返回值、异常和资源所有权。
- 值对象优先使用不可变 dataclass，并拒绝未知或非法状态。
- 重型依赖必须惰性导入；基础安装不强制 PyTorch、FastAPI 或 scikit-learn。
- 资源必须支持显式 `close`，异常路径也必须清理 Hook、模型和文件句柄。
- 不吞异常，不把失败样本当作阴性，不伪造训练完成、因果成立或防御有效。

## 验证

```bash
python -m compileall -q warden tests
python -m pytest
python -m build
warden doctor
warden whitebox-preflight --config configs/whitebox/qwen25-1.5b-probe.json
```

接口修改必须增加 contract test。适配器修改必须覆盖缺失依赖、能力不足和资源关闭。
