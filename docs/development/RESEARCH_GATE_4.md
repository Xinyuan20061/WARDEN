# 规范响应坐标与前向证据修正验收

日期：2026-10-28。基础：v0.4.0-rc.1；修正：v0.4.0-rc.2。

## 复用边界

扩展原 FractalMechanismDatasetAdapter、StegoPotActivationFeatureExtractor、
ActivationCorpusBuilder 和 whitebox collect，不更改底层库、模型 Hook 或原 Probe Trainer。
新增 CanonicalInput 只描述经渲染的输入和坐标，无法由原字符串字段单独表达其分词来源。
新增 forward_evidence 函数使用原 ArtifactRepository，不新建工件仓库。
CanonicalInputValidator 是旧提取端口的可选增强，避免给原 extract 签名增加必需参数，
由基础层声明、模型适配器实现，数据层只依赖该端口。

## 修正

- user 上下文与 assistant 固定响应分开，响应后不追加结束标记或换行。
- 模板缺失、空响应、特殊token、末尾空白、坐标/hash/分词版本不符时显式失败。
- 历史 load() 结构预检兼容，未经渲染的 M 数据不能进入实际 Corpus 构建。
- 正式 collect 固定 tokenizer revision，并使用精确 token_ids，避免二次隐式添加EOS。
- 规范 LEACE 需要 prepared_input 和匹配的分词器版本；普通旧变换入口保留。
- 原始/各干预/撤销 logits 保存为 npz，工件SHA与指标可独立复算。

## 真实模型复测

模型：Qwen3-0.6B，本地 revision `c1899de289a04d12100db370d81485cdf75e47ca`。
8家族、32条件，train/validation/test=4/2/2家族；float16，RTX4060，既有本地快照。
正式 whitebox all 阶段完成32条采集、Corpus保存/加载及ProbeSuite训练。
末token ID=9207，坐标与Corpus完全一致，LEACE和Patch实际写入符合预期。
加载保存的完整151936维logits复算：LEACE变化L2=2.4185847444，Patch=14.2376573591，
撤销后原始logits逐位一致。工件 SHA：
`494d29e37ef7adf3303f3a25f6ce26d48e6aa8dd8b0b4f2c607ecd8ecfd821cc`。

原始输入、activation、logits与官方私有数据仅保存在忽略的 experiments 目录。
没有下载模型、没有云费用，没有编辑上游源码。

## 验证边界

这轮是规范输入及真实模型执行的工程验收。先前能力门失败、缺少完整行为续算及随机对照
的结论保持有效；上述数值不证明秘密信息被稳定擦除或有害交互被选择性抑制。
真实模型性能效果的Gate仍未通过。

本地基础回归：45 passed、2 skipped；可选CPU PyTorch方法测试3 passed。
Ruff、编译及发行包由CI再次验证。
