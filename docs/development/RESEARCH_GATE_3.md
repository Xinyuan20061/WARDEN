# Gate 3–5：方法适配与工程回归

LEACE 使用 concept-erasure 0.2.4（MIT）；官方 wheel SHA-256：
`a7665b49d97c6aa3bfd504ca724ef460bb61237aa510ae31e9550de8619806af`。
训练限定 train；工件绑定模型、revision、tensor_ref、标签语义与 split SHA；
npz 加载禁用 pickle 并校验哈希。末 token residual 干预拒绝 mean_tokens 来源。

Patching 复用 StegoPot Intervention 与 ReplaceOperator。检查模型/Tokenizer revision、
序列长度、目标 token、完整 TensorRef（含 call_index）、shape/dtype/device；
冻结 donor 副本。head patch 返回 UNSUPPORTED_HEAD_PATCH。

已通过的算法测试是 CPU 随机矩阵上的官方数值一致性、保存加载往返、
非训练集拟合拒绝、位置与 revision 不匹配拒绝、donor 替换及形状拒绝。
这些属于 method unit-tested，不是 real model validated。

真实 no-op/block/replace/ban、LEACE 的至少 20 次随机对照、surface 对照、
冻结与重训 Probe、三个行为读出、真实模型续算与 path patch 均为 NOT_RUN。
W1 前置条件未通过，不对选择性、防御有效或路径因果作结论。

本地完整测试：`python -m pytest -o addopts='' -q --basetemp .pytest-tmp-cross-level-final`，
退出 0，38 passed、2 skipped；无 PyTorch 的基础环境跳过可选方法测试模块。
已有 CPU PyTorch 环境运行 `test_leace_and_patching.py`，退出 0，2 passed。
Ruff 与 compileall 退出 0；原 `examples/local_tiny_audit.py` 退出 0。
构建和 CI 结果在发行说明中记录。上游源码只读；
所有失败与缺失前置条件保留，不用有利样本替代验收。
