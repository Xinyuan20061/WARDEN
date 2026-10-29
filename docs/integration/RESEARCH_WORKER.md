# 持久研究 Worker

默认未配置执行器时仍只提供诊断。配置 `WARDEN_RUN_DB`、`WARDEN_EXECUTION_CONFIG`、
`WARDEN_ARTIFACT_ROOT` 与 `WARDEN_RESEARCH_TOKEN` 后，分别运行：

```powershell
python -m warden.interface.cli serve --host 127.0.0.1 --port 18765
python -m warden.interface.cli worker
# 单次消费，失败退出码为 1
python -m warden.interface.cli worker --once
```

API 与 Worker 必须使用同一 Python 依赖和环境变量。HTTP 提交不执行模型。
注册表格式：

```json
{"schema_version":1,"protocols":[{"protocol_ref":"mechanism-qwen05-v1","arm_ref":"baseline","config":"whitebox.json","phase":"collect"}]}
```

`whitebox.json` 复用 `warden.whitebox-probe-experiment/1`，当前注册执行器只接受
`fractal_mechanism`，必须固定 revision、官方家族切分、离线本地权重并关闭 remote code。
每个数据文件获得独立的 `mechanism-<sha256>` 契约；历史契约来源仍保留。
Worker 核对计划的协议、实验臂、契约、模型、模式及采集坐标；配置、数据、切分和执行器代码
进入阶段标识，变化后旧任务不会由新实现静默执行。
`collect` 只采集真实模型激活；`all` 额外运行原 Probe 工作流。均不代表实时通信或防御效果。

每次运行独占输出目录。原始激活保存在 `restricted/<run_id>`；只将公共摘要通过已有
FileArtifactRepository 与 ArtifactGateway 发布，下载要求 Bearer Token，读取时重新校验哈希。
摘要记录输入工件哈希、模型文件哈希、实际依赖版本、UTC、种子和缺失指标原因。

队列只支持显式单 Worker。中断任务保留 running，不自动重放。操作者必须先确认旧进程已退出，
再调用 SQLiteRunDispatcher.reconcile_interrupted(run_id) 对账为 ambiguous；副作用不明时不得重试。
需要重新实验时使用新的注册/请求标识，不修改已有数据或工件。blocked 记录也持久化且幂等。

本次机器上的准确配置、命令、Run ID 和测试结果见 App 仓库的
`docs/integration/THREE_REPO_E2E_ACCEPTANCE.md`。四类干预尚未注册为可执行研究臂。

本次真实浏览器 Run：run-48fec68756304a73a8025388e5d35975；24 条 M 条件；SHA-256 c54c53ff4db8aeca41e4048521a937d18da8b715906eefabe7a4193102c9040b。配对分析 incomplete，四类干预效果 NOT_RUN。
