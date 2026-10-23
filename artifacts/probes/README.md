# Probe Artifacts

此目录保留 Probe 资源约定、版本化清单和 Model Card。训练权重、数据和
运行输出不提交 Git。

每个 Probe 使用独立子目录，至少包含 `manifest.json`、`MODEL_CARD.md` 和权重文件。将资源
状态设置为 `ready` 前，必须完成哈希、输入位置、数据指纹和独立测试指标校验。
