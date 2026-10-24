# Probe and SAE Artifact Contract

## Source Repository

源码仓库只保存清单规范、加载代码和 Model Card 模板。下列内容被 `.gitignore` 排除：

- Probe 权重；
- SAE 权重；
- 原始 Activation；
- 训练、验证和测试数据；
- 实验运行目录。

## Required Provenance

Probe 清单至少记录：

- Probe ID 和版本；
- 基础模型 ID；
- TensorRef 与 pooling；
- 标签定义；
- 家族级数据切分与数据指纹；
- 随机种子、训练器版本和超参数；
- 验证集阈值；
- 独立测试集指标；
- 权重 SHA-256。

参考线性 Probe 使用两层清单：

- `manifest.json` 保存算法输入合同、阈值和权重哈希；
- `resource-manifest.json` 把该 Probe 暴露给 WARDEN `ResourceCatalog`。

`WARDEN_PROBE_ROOT` 可以指向单个 Probe 目录或包含多个 Probe 的父目录。

SAE 清单至少记录：

- SAE ID、来源和许可证；
- 基础模型 ID；
- 原始 Hook 名和 WARDEN TensorRef 映射；
- 输入宽度和 Feature 宽度；
- 重构误差、余弦相似度和稀疏度；
- 权重哈希与依赖版本。

## State

- `declared`：存在清单，但资源尚未下载或训练。
- `ready`：工件存在、哈希正确、兼容性检查通过。
- `unavailable`：来源不存在、依赖缺失或尚未训练。
- `invalid`：清单、哈希或模型映射不一致。

只有 `ready` 资源可以进入正式审计计划。
