# Audit Executor

`PipelineAuditExecutor` 是 WARDEN 将稳定审计合同与具体实验方法分开的用例内核。
它只负责顺序、状态和证据完整性，不猜测模型层、Probe 输入或干预语义。

## Execution Contract

```text
AuditPlan.stages
  -> preflight all registered stages
  -> execute stage in declared order
  -> merge StageResult
  -> publish tensor-free status event
  -> EvidenceBundle(completed | failed)
```

每个 `AuditStage` 只有两个稳定接口：

```python
class AuditStage(Protocol):
    @property
    def stage_id(self) -> str: ...

    def execute(self, context: AuditExecutionContext) -> StageResult: ...
```

`StageResult` 分为两类数据：

- 对外证据：`artifacts`、`risk_scores`、`findings`、`metrics`、`limitations`。
- 任务内状态：`state_updates`，可携带张量或模型输出，但不进入 REST JSON。

## Integrity Rules

- 执行前一次检查计划中的全部阶段，缺失任一阶段时不产生副作用。
- 阶段不能覆盖已有中间状态，避免实验插件暗中改变上游结果。
- 指标按 `<stage_id>.<metric>` 命名空间聚合，并拒绝 NaN 和无穷值。
- 某阶段失败时返回 `failed` 证据包，保留之前已完成的工件和结果。
- 事件发布故障会被记入 `limitations`，不会被静默丢弃。
- 原始 Activation 只能通过 `ArtifactRef` 对外引用。

## Stage Registration

简单实验可以用 `CallableAuditStage` 减少样板代码：

```python
from warden.application import CallableAuditStage, PipelineAuditExecutor, StageResult


def detect(context):
    features = context.require("probe_features")
    scores = trained_probe.score(features, sample_ids=("sender", "receiver"))
    return StageResult(risk_scores=scores)


executor = PipelineAuditExecutor(
    [CallableAuditStage("probe_detection", detect)]
)
```

本地 API 组合根将执行器注入应用服务：

```python
from warden.application import WardenService
from warden.infrastructure.execution import InProcessRunDispatcher
from warden.interface.api import create_app

dispatcher = InProcessRunDispatcher(executor)
service = WardenService(
    resources=resource_catalog,
    threat_source=threat_source,
    components=capability_reports,
    dispatcher=dispatcher,
)
app = create_app(service)
```

生产环境将执行器交给持久化 `RunDispatcher`。`InProcessRunDispatcher` 会同步执行，
仅适用于本地调试、小模型验证和实验脚本。

## Local Smoke Test

[`examples/local_tiny_audit.py`](../examples/local_tiny_audit.py) 使用无需下载的微型双智能体
神经模型，实际训练线性 Probe，并运行 Activation 工件化、Probe 读出、联合
patch、按风险加权干预和良性效用测量。它是软件链路测试，不是科研结论。

```bash
pip install -e ".[probe]"
python examples/local_tiny_audit.py
```
