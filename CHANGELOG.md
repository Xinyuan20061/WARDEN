# Changelog

## 0.4.0rc1 - 2026-10-28

- 保留历史场景 Adapter，升级已回归验证的 FRACTAL 固定引用，新增独立 MechanismDataset Adapter。
- M 数据从官方验证与 split 合同导入，标签语义和数据指纹贯穿 Corpus 与 Probe。
- 使用固定 concept-erasure 0.2.4 实现 train-only LEACE 及安全工件保存加载。
- 通过 StegoPot 公共 Intervention 绑定 LEACE 与单位置 residual patch，校验模型、token 与张量对齐。
- 新增 SQLite 持久单 worker 队列，支持请求幂等、跨进程恢复、正文冲突与中断对账。
- 原审计请求增加可选研究引用；研究阶段复用既有 PipelineAuditExecutor 与白盒函数。
- 研究写接口增加令牌验证，公开响应采用受限投影，工件下载使用审批白名单与 SHA 校验。
- 增加显式未执行状态、ITT/执行后 SRR 分母与逐 Gate 验收文档。
- 此候选版交付已验证的工程适配；真实模型基线和行为干预实验状态见 Gate 报告。

## 0.3.0 - 2026-10-24

- 新增家族隔离的三分交互数据合同，阻止反事实样本和完全相同输入跨切分泄漏。
- 新增 StegoPot 真实模型 Activation 特征提取器和带 SHA-256 校验的 Activation Corpus。
- 新增逐层单主体/联合主体 Probe Suite，使用训练集拟合、验证集选层、测试集最终评价。
- 新增 Probe 风险方向拆分与分数加权 Activation 干预算子。
- 新增 AutoDL 白盒实验预检、分阶段 CLI、Qwen2.5-1.5B 参考配置和完整运行文档。

## 0.2.0 - 2026-10-23

- 新增可注册分阶段 `PipelineAuditExecutor`、执行上下文与失败证据保留。
- 新增本地微型双智能体模型与真实线性 Probe 的端到端示例。

## 0.1.0 - 2026-10-23

- 建立 WARDEN 分层内核、公开契约和运行预检。
- 加入 StegoPot 与 FRACTAL-Bench submodule。
- 提供 Probe/SAE 工件规范、参考实现入口和空资源目录。
- 提供版本化 REST API、CLI、文件工件存储和平台协作契约。
- 提供可替换 `RunDispatcher`、本地参考调度器和任务状态 API。
- 通过薄 Adapter 复用 StegoPot 的 Activation、SAE 和 EAP 能力。
