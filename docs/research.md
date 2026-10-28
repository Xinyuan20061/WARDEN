# 跨层干预研究接口

WARDEN 通过原有审计阶段、Probe 训练器与 StegoPot Runtime 组织跨层干预。
FRACTAL 历史场景由 `FractalDatasetThreatSource` 读取，MechanismDataset 由
`FractalMechanismDatasetAdapter` 读取；两种数据格式有独立入口。

## 实验轨道与标签

M 使用 codebook_binding 的冻结消息重放，预测 `decoded_directive`，行为读出为
`semantic_decode`、`conditioned_decision` 和 `public_control`。S 使用真实发送端、
信道投递与接收端解码，秘密恢复标签为 `secret_bit` 或 `secret_payload`。
风险意图 `misaligned` 是另一个测量目标。全部切分以 case_family 为单位。

从官方机制数据导入：

```python
from pathlib import Path
from warden.infrastructure.adapters.fractal_mechanism import FractalMechanismDatasetAdapter

dataset = FractalMechanismDatasetAdapter(
    Path("experiments/codebook/testbed.json"),
    Path("experiments/codebook/split_manifest.json"),
).load()
```

使用原 CLI 时，在白盒配置中设置
`dataset_format: "fractal_mechanism"`、`dataset_path` 与 `split_path`；
其余字段沿用白盒工作流。`agent_ids` 为 `["receiver"]`。官方验证器先检查
配对关系和 split SHA，再转换授权上下文。derived_labels 不参与 prompt 构造。
Corpus 和 Probe 清单记录标签语义、来源、数据与切分哈希。

## 方法组合

| 层级 | 组合入口 | 执行边界 |
|---|---|---|
| Agent Ban | StegoPot 原有拓扑条件 | oracle_ban 与 detector_ban 分别配置 |
| Message | `adapters.stegopot_channels.channel_transform` | 原 BlockChannel/ReplaceChannel，边选择由原实验配置确定 |
| LEACE | `methods.intervention.leace.LeaceTransform` | train-only 拟合，官方 0.2.4 实现，保存 npz 和哈希清单 |
| Activation Patch | `adapters.stegopot_interventions.build_paired_patch` | 固定模型与 tokenizer revision、相同长度与目标 token，对齐后执行原 ReplaceOperator |

LEACE 通过 `build_leace_intervention` 转换成 StegoPot Intervention。首轮作用于
单层 residual 的末 token，拟合元数据中的 tensor_ref 必须与目标完全一致。
目标擦除、表面擦除与 Probe 方向平移是不同方法，分别命名并留工件。

LEACE 依赖安装：

```bash
pip install -e '.[research,probe]'
```

可用 `requirements/research-lock.txt` 对算法 wheel 强制校验哈希。
官方实现采用 MIT 许可证，来源：
[EleutherAI/concept-erasure](https://github.com/EleutherAI/concept-erasure)，
[PyPI 0.2.4](https://pypi.org/project/concept-erasure/0.2.4/)。
没有复制第三方算法源码。拟合时在 CPU float64 计算，应用结果恢复输入 dtype/device。

## 审计任务组合

`whitebox_stage(config, phase="collect"|"train", artifacts=store)` 返回既有
`CallableAuditStage`，仍由 `PipelineAuditExecutor` 执行。
组合根把可信的 `(research_protocol_ref, study_arm_ref)` 映射到这些阶段；
未注册引用返回 blocked。不要把请求正文、用户文件路径直接交给执行器。

`SQLiteRunDispatcher(database, executor)` 实现原 submit/get/list，提交只落盘。
由独立 worker 进程显式调用 `run_next()` 执行，HTTP 不承担模型计算。
相同 request_id 与规范正文返回原 run；异正文抛出冲突，REST 映射到 409。
同一个数据库存在 running 时不再领取其他任务。重启可以查询计划与证据；
中断任务须确认 worker 停止后调用 `reconcile_interrupted`，不自动执行第二次。

应用仍需在部署层配置进程隔离、GPU/磁盘配额和超时。SQLite 适配器没有承诺
多副本 exactly-once、硬件配额或自动杀进程。正式 worker 的资源验收见 Gate 2。

研究写请求使用 `Authorization: Bearer ...`。服务端通过
`create_app(..., research_token=...)` 注入；CLI 可使用 `WARDEN_RESEARCH_TOKEN`。
默认未配置令牌时拒绝研究写操作。`WardenClient(token=...)` 支持相同令牌。
公开计划与运行响应隐藏 truth、任意 metadata、原始错误、findings 和本地 URI。
详细诊断保留于可信 Python/worker 域。

工件下载使用 `/v1/artifacts/{artifact_id}/content`，必须授权并注入
`ArtifactGateway.read`。网关只接收显式白名单中的 public-summary，不支持任意 URL、
绝对路径、原始 activation 或秘密训练数据。返回前核对大小和内容 SHA。

## 统计与验收

StudyObservation 区分 receiver 未执行、未完整解码和错误恢复。BER 来自原
StegoEvaluator；未执行时保持 null 并给原因。ITT SRR 以所有计划条件为分母，
receiver-executed SRR 使用实际执行条件分母，二者同时保存。
`summarize_observations` 只聚合同轨道同实验臂，不把四条件当独立案例。

真实实验沿用 FRACTAL `AMNESIC_FEASIBILITY_PROTOCOL.md`：train-only 拟合，
validation 选层和阈值，确认集新 seed；至少 20 次匹配秩与位移的随机对照，
冻结与重训 Probe，并保留三个行为读出。工程测试不替代这些实验验收。

阶段验证与未解决条件见 [开发验收索引](development/RESEARCH_GATES.md)。
