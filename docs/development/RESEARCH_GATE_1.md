# Gate 1：真实 Sender–Receiver 基线

状态：BLOCKED_LOCAL_MODEL_AND_FROZEN_STUDY_DATA。

授权模型缓存 `models_cache/` 仅有说明文件，本次没有可用于真实推理的模型快照，
也没有本研究冻结的 S 轨道数据。未下载模型、未启动 AutoDL、无 GPU 费用。
因此真实模型 baseline、SRR/BER/U、消息 arm 效果、模型 revision 证据均为 NOT_RUN。

工程侧保留 StegoPot 的 CodecPolicy、TrialRunner、StegoEvaluator 与节点拓扑入口；
新增信道工厂仅构造官方 BlockChannel/ReplaceChannel，不另写 runtime 或 BER。
历史 tiny 和 fake extractor 仅作为回归，不纳入本研究效果证据。

真实开跑须冻结：模型/Tokenizer revision、精度、采样参数、family split SHA、
协议 SHA、种子、全部计划条件与日志目录。先 2–8 开发家族验证基线，保留失败。
M 使用 Bench 协议的 0.80 语义/决策与 0.90 public_control 验证门；
S 的恢复动态范围与正常任务门槛须在真实研究协议中预注册后才能运行。
