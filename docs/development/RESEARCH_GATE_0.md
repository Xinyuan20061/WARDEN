# Gate 0：依赖兼容

2026-10-28，本地功能分支 `feature/cross-level-research`。

- 原 pin 历史 Adapter 回归：`python -m pytest -q tests/integration/test_fractal_adapter.py --basetemp .pytest-tmp-old-bench`，退出 0，1 passed。
- 新 pin 兼容测试：同一历史测试加 FRACTAL 的 `test_codebook_binding.py`、`test_mechanism_cli.py`、`test_mechanism_schema.py`，退出 0，12 passed。
- 本地有私有仓库访问权限，候选提交已获取；不是 BLOCKED_PRIVATE_DEPENDENCY。
- 新 pin 保留旧 Scenario 与 Store 入口；新增独立 MechanismDataset，不重解释旧实例。
- StegoPot pin 未变，上游源码均未编辑。
- 回滚：将 FRACTAL gitlink 恢复到 `8081bc61f98cca243034c20951f64522b84ab5fa`。
- 成本：本地 CPU 回归，无模型推理、无云 GPU。
- 候选 FRACTAL 全量回归：`python -m pytest -q vendor/fractal-bench/tests --basetemp .pytest-tmp-bench-full`，退出 0，95 项通过。
