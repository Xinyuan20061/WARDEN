# WARDEN Architecture

## Scope

WARDEN 的最小职责是把多智能体协调事件转换为可追踪的内部表征坐标，并完成以下闭环：

```text
Threat Contract
  -> Audit Plan
  -> Coordination Trace
  -> Activation Evidence
  -> Probe / SAE Candidates
  -> Causal Verification
  -> Controlled Intervention
  -> Utility-aware Evaluation
```

WARDEN 不负责通用 Agent 编排、基础模型托管、可视化或 FRACTAL-Bench 场景生成。

## Dependency Rule

```text
interface -> application -> core
infrastructure -----------> core
```

`core` 不导入 FastAPI、NumPy、PyTorch、StegoPot 或 FRACTAL-Bench。`application` 不实例化
具体 Adapter。组合只发生在 CLI/API factory 或调用方代码中。

## Responsibility

### Core

- `ActivationCoordinate`：Agent、消息、模型调用和张量位置的统一坐标。
- `ThreatContract`：与具体基准解耦的有害交互定义。
- `AuditRequest` / `AuditPlan`：测试平台请求和预检后的执行计划。
- `ResourceManifest`：Probe/SAE 的版本、状态、数据指纹和工件引用。
- Ports：Activation、Runtime、Threat、Probe、SAE、Artifact 和 Event 协议。
- `RunDispatcher`：隔离内核与本地线程、队列或分布式执行方案。

### Application

- 资源目录只登记经过清单验证的资源。
- 计划编译器检查能力、训练资源和模型位置，不猜测层号或 Hook。
- 应用服务为 REST、SDK 和研究脚本提供同一入口。

### Infrastructure

- Probe 参考实现负责训练与推理，不承担标签定义。
- SAE Analyzer 负责分解与重构审计，不自动解释 Feature 语义。
- StegoPot Adapter 把 CaptureTarget 转换为 TensorRef/TracePolicy。
- StegoPot EAP Adapter 复用上游评分器，不在 WARDEN 重新实现归因公式。
- FRACTAL Adapter 把 BenchmarkInstance 转换为 ThreatContract。
- Artifact Store 只在事件和报告中暴露内容寻址引用。
- `InProcessRunDispatcher` 仅作为本地参考实现；长任务由部署层注入队列。

### Interface

- `/v1` API 是测试平台的稳定边界。
- Python SDK 不暴露内部类路径。
- CLI 提供依赖诊断、资源发现和本地服务启动。

## Offline and Online Boundary

完整 EAP、跨层 Patching、SAE Feature 搜索和阈值选择属于离线审计。在线防御只加载已经
在独立数据上验证的 Probe 与干预计划。当前版本首先固定这套边界，不宣称未训练资源可用。

## Fail-closed Rules

- API 模型不能声明 Activation 能力。
- 未指定模型相关 CaptureTarget 时阻塞计划。
- 未训练、哈希错误或不兼容的 Probe/SAE 不进入 ready 状态。
- Probe 可读性不自动转化为因果结论。
- 干预结果必须同时报告有害行为和正常任务效用。
