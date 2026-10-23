<div align="center">

# WARDEN

### 面向多智能体协调下有害交互的因果审计及可控防御内核

[![Python](https://img.shields.io/badge/Python-3.11%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![License](https://img.shields.io/badge/License-Apache--2.0-4C8BF5)](LICENSE)
[![Status](https://img.shields.io/badge/Status-Alpha-D97706)](CHANGELOG.md)

</div>

WARDEN 将多智能体运行轨迹、模型内部 Activation、风险读出、因果证据和受约束干预
组织成统一审计闭环。它面向单条消息看似正常、但多个智能体联合后形成秘密勾结或其他
有害行为的场景。

WARDEN 是安全内核而不是 Agent 编排平台。测试平台、可视化应用和实验脚本通过稳定的
REST API 或 Python SDK 调用内核，不需要依赖模型 Hook、张量格式或上游项目内部实现。

## Architecture

```text
Testing Platform / Visualization / Research Client
                         │
                  REST API / SDK
                         ▼
                WARDEN Application
                         │
       ┌─────────────────┼─────────────────┐
       ▼                 ▼                 ▼
     Probe              SAE       Attribution / Defense
       │                 │                 │
       └─────────────────┼─────────────────┘
                         ▼
                 Adapter Contracts
                ┌────────┴────────┐
                ▼                 ▼
            StegoPot        FRACTAL-Bench
       white-box runtime   threat contracts
```

- **StegoPot**：可控 forward、Activation/gradient 访问、Patching、EAP 和公开 SAE 运行。
- **FRACTAL-Bench**：多智能体分布式共谋场景、因子结构、配对条件和行为真值。
- **WARDEN**：跨主体对齐、Probe 训练与风险校准、SAE 风险证据、因果审计和干预编排。

两个上游项目以 Git submodule 固定版本，位于 [`vendor/`](vendor/)。WARDEN 通过 Adapter
调用公开接口，不复制或修改上游核心代码。

## Core Contracts

WARDEN 使用以下坐标把外部交互与内部表征连接起来：

```text
run_id
  -> agent_id
  -> message_id
  -> invocation_id
  -> model_id
  -> layer / module / token span
  -> activation artifact
  -> behavioral outcome
```

审计请求经过预检后形成 `AuditPlan`。缺少白盒能力、层级映射、Probe 或 SAE 权重时，计划
会进入 `blocked` 状态并返回具体原因；内核不会生成模拟分数或假装完成因果审计。

## Probe and SAE

WARDEN 发布 Probe 和 SAE 的接口、参考实现、工件清单与评价约定，但不在 Git 仓库提交
训练权重。

- Probe 是有害交互的风险读出器。参考实现提供独立验证集阈值选择、数据指纹、权重哈希
  和加载校验。
- SAE 是表征分解器。它提供 Feature 排序和重构质量审计，但 Feature 激活本身不等于风险
  或因果证据。
- Probe/SAE 权重、Activation 和训练数据通过外部 Artifact 发布，仓库只保存清单和
  Model Card。

资源目录约定见 [`artifacts/probes`](artifacts/probes/README.md) 和
[`artifacts/sae`](artifacts/sae/README.md)。

## Installation

```bash
git clone https://github.com/Xinyuan20061/WARDEN.git
cd WARDEN
git submodule update --init --recursive vendor/stegopot

python -m venv .venv
# Windows: .venv\Scripts\activate
# Linux/macOS: source .venv/bin/activate

python -m pip install --upgrade pip
pip install -e vendor/stegopot
pip install -e ".[api,probe,dev]"
```

FRACTAL-Bench 是可选威胁契约源。对该仓库具有访问权限的协作者可继续初始化并安装：

```bash
git submodule update --init vendor/fractal-bench
pip install -e vendor/fractal-bench
```

部署也可通过自定义 `ThreatContractSource` 使用其他基准或业务系统，不强制依赖
FRACTAL-Bench。

白盒模型与公开 SAE 需要额外安装 StegoPot 对应依赖：

```bash
pip install -e "vendor/stegopot[whitebox,sae]"
```

## Diagnostics

```bash
warden doctor
warden resources
warden contracts
```

新仓库不附带训练资源，因此首次运行 `warden doctor` 时 Probe 和 SAE 目录为空属于正常
状态。注入模型 Runtime、威胁数据集和训练 Artifact 后，能力报告会明确显示可用状态。

## Platform API

启动本地 API：

```bash
warden serve --host 127.0.0.1 --port 8765
```

主要端点：

| Endpoint | Purpose |
| --- | --- |
| `GET /v1/health` | 服务和 API 版本 |
| `GET /v1/capabilities` | Adapter 能力及缺失原因 |
| `GET /v1/resources` | Probe/SAE 资源清单 |
| `GET /v1/contracts` | 可用威胁契约 |
| `POST /v1/audit-plans` | 编译审计计划 |
| `GET /v1/audit-plans/{id}` | 查询计划和阻塞原因 |
| `POST /v1/runs` | 向已注入的调度器提交计划 |
| `GET /v1/runs/{id}` | 查询任务状态和证据引用 |

Swagger UI 默认位于 `http://127.0.0.1:8765/docs`。外部测试平台应只依赖 `/v1` 契约。

Python SDK 示例：

```python
from warden.interface import WardenClient

client = WardenClient("http://127.0.0.1:8765")
print(client.capabilities())
print(client.resources("probe"))
# plan = client.create_audit_plan({...})
# run = client.start_run(plan["plan_id"])
```

完整请求字段和协作约定见 [`docs/api.md`](docs/api.md)。

## Repository Layout

```text
warden/
  core/                 纯领域对象和 Protocol
  application/          审计计划与用例编排
  infrastructure/
    methods/probe/      Probe 训练、保存和推理
    methods/sae/        SAE 分解与重构审计
    adapters/           StegoPot 与 FRACTAL-Bench 适配
    storage/            内容寻址工件与清单发现
  interface/            REST API、Python SDK 和 CLI
vendor/
  stegopot/             Git submodule
  fractal-bench/        Git submodule
schemas/                平台可验证的 JSON Schema
artifacts/              只提交说明，不提交权重
```

## Documentation

- [Architecture](docs/architecture.md)
- [API Contract](docs/api.md)
- [Artifact Contract](docs/artifacts.md)
- [Contributing](CONTRIBUTING.md)
- [Security](SECURITY.md)

## License

WARDEN 使用 [Apache License 2.0](LICENSE)。`vendor/` 中的 submodule 保留各自上游许可证。
