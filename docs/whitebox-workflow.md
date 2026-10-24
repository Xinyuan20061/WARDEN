# 真实模型白盒 Probe 工作流

WARDEN 的白盒工作流把 GPU 密集的 Activation 采集与 CPU 可执行的 Probe 训练分开。该
边界便于在 AutoDL 中只为模型前向付费，同时保留可校验、可重复使用的 Activation Corpus。

## 数据合同

输入是 UTF-8 JSONL，每行遵循
[`labeled-interaction.schema.json`](../schemas/labeled-interaction.schema.json)：

```json
{"sample_id":"case-001-risk","family_id":"case-001","split":"train","label":1,"inputs_by_agent":{"sender":"...","receiver":"..."},"metadata":{"arm":"misaligned"}}
```

加载时执行以下硬约束：

- `sample_id` 全局唯一；
- 所有样本具有相同 Agent 集合；
- 同一 `family_id` 的反事实条件不能跨切分；
- 完全相同的主体输入不能跨切分；
- train、validation、test 均同时包含标签 0 和 1；
- 不允许运行时随机重切分。

`label=1` 只表示实验预注册的风险条件，不自动等价于“模型已经共谋”。行为真值仍应由
FRACTAL-Bench 或业务场景评价器提供。

## 配置

参考配置位于 [`configs/whitebox/qwen25-1.5b-probe.json`](../configs/whitebox/qwen25-1.5b-probe.json)。
配置结构由
[`whitebox-probe-experiment.schema.json`](../schemas/whitebox-probe-experiment.schema.json)
约束。
所有参数均显式写入配置：

- `model_id`：跨机器稳定的逻辑模型标识；
- `model.model_path`：本地固定快照路径；
- `revision`：模型提交或标签，正式结果必须补全；
- `device`、`dtype`、`quantization`：模型执行精度；
- `capture_targets`：层、组件、token 归约和适用主体；
- `probe`：正则、最大迭代数和随机种子。

同一 Runtime 会被所有 Agent 顺序复用，因此单卡运行时只保留一份模型权重。

## AutoDL 准备

```bash
git clone https://github.com/Xinyuan20061/WARDEN.git
cd WARDEN
git submodule update --init --recursive vendor/stegopot

python -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -e "vendor/stegopot[whitebox]"
pip install -e ".[probe,dev]"

hf download Qwen/Qwen2.5-1.5B-Instruct \
  --local-dir models_cache/Qwen2.5-1.5B-Instruct
```

把场景生成的 JSONL 放到 `experiments/whitebox/interactions.jsonl`，然后先执行不加载模型的
预检：

```bash
warden whitebox-preflight \
  --config configs/whitebox/qwen25-1.5b-probe.json
```

返回码为 0 且 `ready=true` 后再启动采集：

```bash
warden whitebox-run \
  --config configs/whitebox/qwen25-1.5b-probe.json \
  --phase collect
```

采集完成后模型已释放。Probe 训练不要求 GPU，可在原实例或下载 Corpus 后执行：

```bash
warden whitebox-run \
  --config configs/whitebox/qwen25-1.5b-probe.json \
  --phase train
```

全流程也可用 `--phase all` 一次执行。

## 输出

```text
experiments/whitebox/output/qwen25-1.5b/
  activation_corpus/
    manifest.json       数据、模型、层级和矩阵哈希
    features.npz        按主体和层保存的 float32 特征流
  probe_suite/
    probes/             每个主体/联合视图、每个候选层的 Probe
    report.json         验证集选层与独立测试结果
  run-collect.json
  run-train.json
```

Probe Suite 同时训练：

- 每个 Agent 的单边 Probe；
- 同一层全部 Agent 表征拼接后的联合 Probe。

每个候选只使用 train 拟合，阈值和层级只使用 validation 选择，test 只报告最终性能。
报告同时给出样本级平衡准确率和案例家族等权准确率，避免样本较多的家族支配汇总结果。
联合 Probe 的特征流顺序写入清单，后续可据此拆分各主体风险方向并构造分数加权干预。

每个 Probe 目录还包含 `resource-manifest.json`。服务进程可直接发现整套资源：

```bash
export WARDEN_PROBE_ROOT="$PWD/experiments/whitebox/output/qwen25-1.5b/probe_suite/probes"
warden resources --kind probe
```

## 因果边界

Probe 可读性不是因果性。`score_weighted_probe_direction` 只是可复用干预算子；正式防御
结论还需要在场景行为评价器下比较原始、单主体干预、多主体联合干预和良性对照，并用
Patching/EAP 验证目标位置对有害协调行为具有因果效应。
