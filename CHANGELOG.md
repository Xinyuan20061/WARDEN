# Changelog

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
