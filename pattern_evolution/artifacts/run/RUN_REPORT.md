# CCEM v0.2 端到端运行报告

运行日期：2026-08-22
运行状态：**PASSED**

## 1. 本轮实际完成的闭环

```text
proxy CandidateSubgraphPackage
        + upstream ValidationReport (accepted=true)
        -> ValidatedSubgraphPackage
        -> API Hypothesis Generation Agent
        -> role induction + ID anonymization + WL fingerprint
        -> executable CCEM detector
        -> positive / augmented / counterfactual replay
        -> DetectorLibrary ADD, v0 -> v1
        -> next-round detection
        -> Multi-GNN tensor contract
```

使用的生成模型：`deepseek/deepseek-v4-flash`。API 配置从
`/home/bingqinshao/MOOSE-Chem/main.sh` 运行时读取，密钥没有复制到代码或产物。

## 2. 运行指标

| 指标 | 结果 |
|---|---:|
| 自进化前 proxy recall | 0 |
| 自进化后 proxy recall | 1 |
| 反事实误报数（4 个） | 0 |
| 旧 gather-scatter 回归 | 0 |
| 正例 replay | 通过 |
| 轻微增强正例 replay | 通过 |
| 经验库操作 | ADD |
| 经验库版本 | v1 |
| Hypothesis Agent | success |

新经验 ID：

```text
ccem_relay_bridge_gather_scatter_4ac4df971c
```

## 3. 编译出的可执行经验

模式结构：

```text
sources(>=3) -> collector(1) -> relay(1) -> sinks(>=3)
```

执行约束：

- 总时间跨度不超过 72 小时。
- `gather < bridge < scatter` 的时间偏序成立。
- bridge/input 与 output/bridge 金额比均在 `[0.6, 1.4]`。
- 上下文干扰边比例不超过 0.25。
- 允许干扰边，但不能替代 collector-to-relay 核心桥。

四个被拒绝的反事实：

1. 删除 collector-to-relay 桥。
2. 把桥重连到正常账户。
3. 将 scatter 时间移动到 bridge 之前。
4. 置换金额并破坏桥接资金连续性。

## 4. Agent 假设与可执行经验的隔离

API 生成的解释名为 `Concentrated Relay Scatter`。它被保存为
`agent_hypothesis_view.non_executable=true`，不能修改：

- 因果验证的 `accepted` 决策；
- 编译器的结构和金额阈值；
- replay 是否通过；
- 经验库的 ADD/MERGE/SPECIALIZE/PRUNE 决策。

这次输出恰好说明隔离的必要性：Agent 提议“context edge ratio < 0.3”，
但编译器依据冻结配置执行的是 `<= 0.25`。系统保留 Agent 的解释能力，同时不让
自然语言建议绕过可重放的验收门。

## 5. 独特设计点

1. **因果证书是写权限，不是特征。** 它决定某个模式能否进入经验编译器，
   但不被编码进待检测图，避免验证标签泄漏。
2. **事实图与经验图分离。** 交易事实保存在 `G_t`；新经验、角色和证书关系保存
   在 `K_t`。经验不会作为伪交易边写回原图。
3. **经验是可执行程序，而非总结文本。** 经验主体由角色、结构约束、时间偏序、
   金额连续性、反事实不变量和谱系组成；LLM 文本仅是视图。
4. **自进化必须证明能力增量。** 本轮用 `recall 0 -> 1`、反事实误报 0 和旧规则
   回归 0 共同决定是否提交库版本，而不是简单地向规则库追加一段描述。

## 6. Multi-GNN 对接结果

本轮 Validated 包包含 9 个节点和 9 条边，Adapter 已实际生成 PyTorch 张量：

```text
x           [9, 1]
edge_index  [2, 9]
edge_attr   [9, 4]
timestamps  [9]
```

`edge_attr` 顺序为：

```text
timestamp, base_amount, base_currency_code, transaction_type_code
```

本机没有安装 `torch_geometric`，因此未实例化 Multi-GNN 的 PyG `GraphData`；
张量契约已经跑通，安装 PyG 后可直接调用 `to_pyg()`。

## 7. 结论边界

本轮使用的是符合 v0.2 的确定性 proxy 与 `model_behavior` ValidationReport，证明的是：

> 一个已通过上游验证的新型子图，能够被自动编译为 ID 无关的可执行经验，并在
> 下一轮增加相应模式的检测能力，同时拒绝关键反事实且不破坏旧模式。

它不是 IBM 全量数据上的真实业务因果结论，也不能声称该结构导致真实洗钱结果上升。
要升级为 `aml_outcome` 结论，需要接入 IBM 总体交易 artifact、受控 outcome、处理组/
对照组和正式 CausalValidator。
