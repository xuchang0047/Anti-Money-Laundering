# Attack × Shared Subgraph Package v0.2 接口确认单

状态：等待团队确认  
参考文档：`validated_subgraph_interface_v0.2_draft.md`  
涉及模块：Attack / Mutation、Matcher / Extractor、CausalValidator、Pattern Evolution

## 1. 当前 Attack 模块状态

Attack prototype 当前输出：

```text
outputs/attacks/<attack_id>/
├── base_transactions.csv
├── mutated_transactions.csv
└── attack_summary.json
```

当前已经实现：

```text
baseline CSV
→ 构图
→ 2-hop scatter-gather candidate retrieval
→ 特征提取
→ prototype detector
→ controlled mutation
→ 重新构图、重新检索、重新检测
→ attack summary
```

第一版 attack 类型：

```text
temporal_stretch
path_extension
amount_perturbation
```

Attack 不生成或猜测因果验证结果，也不应读取 Oracle/Outcome。

以下问题会直接影响 `CandidateSubgraphPackage` 的生成方式，需要在继续修改 Attack 输出前确认。

---

## 2. Retrieval 失败时是否仍生成 CandidateSubgraphPackage？

### 背景

`path_extension` 会把：

```text
source → intermediate → destination
```

变为：

```text
source → intermediate → relay → destination
```

当前 2-hop retriever 无法重新找到该模式，因此：

```json
{
  "mutated_retrieved": false,
  "failure_stage": "retrieval",
  "attack_success": true
}
```

但 Attack 知道本次 mutation 修改了哪些原始边、增加了哪些 relay 节点和新边，因此仍可以确定性导出完整变异子图。

### 选项

**A. 只有重新检索成功时才生成 CandidateSubgraphPackage**

- retrieval failure 只保留 CSV 和 attack summary；
- CausalValidator / Pattern Evolution 收不到对应变异子图。

**B. retrieval failure 时仍生成 CandidateSubgraphPackage**

- 图来自已知 mutation scope，不伪造 retriever 结果；
- package 中保留：

```json
{
  "mutation": {
    "base_retrieved": true,
    "mutated_retrieved": false,
    "failure_stage": "retrieval"
  }
}
```

### Attack 模块建议

建议选择 **B**。Retrieval evasion 正是需要交给模式发现/更新模块分析的案例；如果不导出变异子图，下游只能知道失败，无法观察失败结构。

### 团队确认

```text
[ ] 选择 A
[ ] 选择 B
[ ] 需要其他方案：
```

---

## 3. `model_behavior` 如何表示布尔规则结果？

### 背景

当前 Attack 验证的是旧 prototype detector 是否仍触发：

```json
{
  "old_rule_result": {
    "before_attack": true,
    "after_attack": false
  }
}
```

因此对应的 validation target 应是：

```json
{
  "requested_validation_target": "model_behavior"
}
```

而不是 `aml_outcome`。当前 detector 输出是布尔值 `suspicious_candidate`，没有连续模型分数。v0.2 草案要求 `model_behavior` 提供 model artifact、outcome metric 和评分方向，但尚未冻结布尔规则的字段形式。

### 建议结构

```json
{
  "analysis_context": {
    "requested_validation_target": "model_behavior",
    "model_artifact": {
      "artifact_id": "prototype-scatter-gather-detector-v0.1",
      "format": "json",
      "uri": "artifact://prototype-scatter-gather-detector-v0.1",
      "sha256": "<attack_config.json sha256>"
    },
    "outcome_metric": "suspicious_candidate",
    "outcome_metric_type": "boolean",
    "positive_value": true
  }
}
```

对于布尔 outcome，建议不强制填写连续分数的 `score_direction`；或者明确增加：

```json
{
  "score_direction": "true_is_more_suspicious"
}
```

### 团队确认

```text
[ ] 接受 outcome_metric_type=boolean + positive_value
[ ] 布尔结果仍要求 score_direction，字段值为：
[ ] 旧规则必须改为输出连续 score
[ ] 需要其他结构：
```

---

## 4. 谁负责生成 CandidateSubgraphPackage？

### 背景

v0.2 职责矩阵规定：

```text
Attack / Mutation   写 mutation、边级谱系和攻击产物
Matcher / Extractor 写 Candidate 图、scope 和选中边
```

但当前 prototype 的 candidate retriever 和 feature extractor 与 Attack 位于同一代码模块和同一运行流程中。

### 选项

**A. Attack 只输出 CSV、summary 和 edge lineage**

由独立 Matcher / Extractor 读取这些产物并生成 `candidate_subgraph.json`。

**B. 当前 prototype 由 Attack 流程直接输出 `candidate_subgraph.json`**

代码可以放在 Attack 仓库，但逻辑上由 `CandidatePackageBuilder/Extractor` 负责组装 graph 和 scope；Attack mutation 本身仍只负责 mutation 和 lineage。

### Attack 模块建议

时间紧，建议选择 **B**。保持一个可运行进程，但在代码职责上单独创建 package builder，避免把 Candidate JSON 拼装逻辑塞进 mutation 函数。

### 团队确认

```text
[ ] 选择 A
[ ] 选择 B
[ ] Candidate package 由以下队友/模块负责：
```

---

## 5. `attack_summary.json` 是保留还是被 Candidate 包替代？

### 背景

`attack_summary.json` 已作为 Attack 与 pattern evolution 队友之间的稳定轻量输出，包含：

```text
attack_id
source_pattern
attack_type
base_retrieved
mutated_retrieved
base_case_features
mutated_case_features
stable_features
changed_features
old_rule_result
failed_rule_conditions
failure_stage
attack_success
```

v0.2 Candidate 包又包含顶层 `mutation`。

### 选项

**A. 保留 attack_summary.json，同时把其规范字段嵌入 Candidate.mutation**

- summary 继续方便调试和独立使用；
- Candidate 是共享接口；
- 两者必须由同一内存对象写出，防止字段漂移。

**B. 删除独立 attack_summary.json，只保留 candidate_subgraph.json**

### Attack 模块建议

建议选择 **A**。CSV → summary 的轻量接口仍可独立使用；Candidate 包供需要图结构和验证上下文的模块消费。

### 团队确认

```text
[ ] 选择 A
[ ] 选择 B
[ ] 需要其他兼容策略：
```

---

## 6. 边级谱系保存在哪里？

### 背景

v0.2 要求每条 Candidate 边包含：

```text
parent_edge_ids
mutation_role
```

CSV 中直接保存 JSON 数组不够简洁；但只在 Candidate JSON 中保存谱系，会使独立 CSV 缺少变异来源。

### 建议方案

1. mutation 函数内部返回：

```text
mutated DataFrame + edge_lineage mapping
```

2. `attack_summary.json` 保存：

```json
{
  "edge_lineage": {
    "tx_004_path_1": {
      "parent_edge_ids": ["tx_004"],
      "mutation_role": "added"
    }
  }
}
```

3. Candidate builder 将同一 mapping 写入 `graph.edges[*]`。

4. `mutated_transactions.csv` 不增加数组型谱系列，继续保持通用交易表格式。

### 团队确认

```text
[ ] 接受“summary + Candidate JSON 保存谱系，CSV 不保存”
[ ] CSV 也必须保存谱系，序列化格式为：
[ ] 需要其他方案：
```

---

## 7. 修改边是否必须生成新的 edge_id？

### 背景

`temporal_stretch` 和 `amount_perturbation` 当前保留原 `transaction_id`，只修改 timestamp 或 amount。

如果 Candidate 中写成：

```json
{
  "edge_id": "tx_004",
  "parent_edge_ids": ["tx_004"],
  "mutation_role": "modified"
}
```

会形成看似自引用的谱系，难以区分 baseline edge 与 mutated edge。

### 建议方案

修改边生成新的 edge ID：

```text
tx_004
→ tx_004_temporal_stretch

tx_004
→ tx_004_amount_perturbation
```

并保存：

```json
{
  "parent_edge_ids": ["tx_004"],
  "mutation_role": "modified"
}
```

未修改边继续保留原 ID，`parent_edge_ids=[]`、`mutation_role=preserved`。

### 团队确认

```text
[ ] 修改边必须生成新 edge_id（建议）
[ ] 修改边沿用原 edge_id，基线版本通过其他字段区分：
```

---

## 8. Synthetic / AMLSim 节点 ID 的命名规则

### 背景

v0.2 推荐：

```text
dataset_id::bank_id::account_id
```

当前 synthetic mock 只有账户 `A/B/C/D/X`，没有 bank ID。部分 AMLSim 导出也可能只提供 account ID。

### 建议规则

```text
有 bank_id：dataset_id::bank_id::account_id
无 bank_id：dataset_id::account_id
```

例如：

```text
synthetic-scatter-gather::A
AMLSim-1K::1001
```

禁止为了满足三段格式伪造 bank ID。

### 团队确认

```text
[ ] 接受 bank_id 可选的两段/三段格式
[ ] 必须固定三段，缺失 bank_id 使用保留值：
[ ] 使用其他 node_id 规则：
```

---

## 9. Prototype 阶段如何处理 artifact URI？

### 背景

v0.2 要求 artifact 使用：

```text
artifact_id
format
uri
sha256
```

但 Artifact Registry 的解析方式仍在冻结前清单中，当前 prototype 只有本地 CSV 和 JSON 文件。

### 建议方案

Prototype 先写稳定逻辑引用和真实 SHA-256：

```json
{
  "artifact_id": "synthetic-sg-001-base-transactions",
  "format": "csv",
  "uri": "artifact://synthetic-sg-001-base-transactions",
  "sha256": "<真实文件哈希>"
}
```

运行时同时通过本地 manifest 将 `artifact_id` 映射到相对路径；共享 Candidate 包不写某台机器的绝对路径。

### 团队确认

```text
[ ] Prototype 接受 logical artifact URI + sha256 + 本地 manifest
[ ] 必须等待正式 Artifact Registry
[ ] 当前阶段允许其他 URI 形式：
```

---

## 10. 时间量化规则

### 背景

当前 synthetic CSV 使用 ISO 时间；Candidate 包要求相对时间、`time_unit`、`time_precision` 和 `time_origin`。

### 建议规则

第一版统一：

```text
time_unit      = second
time_precision = 1.0
time_origin    = baseline artifact 中的最早 timestamp
quantization   = round_half_up_to_nearest_second
```

Candidate 边的 `timestamp` 保存相对 `time_origin` 的非负秒数。CSV 继续保留 ISO timestamp，便于人工检查。

### 团队确认

```text
[ ] 接受上述规则
[ ] 使用其他 precision：
[ ] 使用其他量化方式：
```

---

## 11. 建议的最小确认结果

为避免阻塞 Attack 调整，至少需要团队确认以下六项：

```text
1. Retrieval failure 是否导出 Candidate：A / B
2. model_behavior 布尔 outcome 的字段结构
3. Candidate package 的实际生产模块：A / B
4. 是否继续保留 attack_summary.json：A / B
5. 边谱系是否只写 summary + Candidate JSON
6. 修改边是否生成新 edge_id
```

Node ID、artifact URI 和时间量化可以随后冻结，但必须在 Candidate JSON 进入团队共享前确定。

## 12. 团队回复模板

```text
Q2 Retrieval failure Candidate：
Q3 model_behavior boolean schema：
Q4 Candidate producer：
Q5 保留 attack_summary：
Q6 lineage 存储位置：
Q7 modified edge ID：
Q8 node_id 规则：
Q9 artifact URI：
Q10 时间量化：

其他意见：
```

---

## 13. Pattern Evolution / CCEM 模块确认回复（2026-08-22）

### 13.1 确认结果总表

```text
Q2 Retrieval failure Candidate：选择 B，仍然导出 Candidate
Q3 model_behavior boolean schema：接受 boolean + positive_value；统一使用 scoring_direction
Q4 Candidate producer：选择 B，由 Attack 进程内独立 CandidatePackageBuilder 生产
Q5 保留 attack_summary：选择 A
Q6 lineage 存储位置：summary + Candidate JSON，CSV 不保存数组型谱系
Q7 modified edge ID：修改边必须生成新的、带 attack_id 的 edge_id
Q8 node_id 规则：固定三段；无 bank_id 时使用显式保留值 __NO_BANK__
Q9 artifact URI：logical artifact URI + 真实 sha256 + 本地相对路径 manifest
Q10 时间量化：second / 1.0 / baseline 最早时间 / ROUND_HALF_UP
```

以上决定可以直接作为 Attack v0.2 prototype 的实现基线。

### 13.2 Q2：Retrieval 失败时仍导出 Candidate

确认选择 **B**。Retrieval failure 本身就是有价值的 evasion evidence。如果 Attack 已经
通过 mutation 谱系确定了变异作用域，下游应当能够观察该结构。

必须区分三个互不等价的状态：

```text
mutated_retrieved    Matcher 是否重新找到变异模式
attack_success       旧 detector 是否由命中变为未命中
validation.accepted  变异结构是否通过因果/反事实验证
```

Candidate 建议保存：

```json
{
  "mutation": {
    "base_retrieved": true,
    "mutated_retrieved": false,
    "failure_stage": "retrieval",
    "candidate_source": "mutation_scope",
    "attack_success": true
  }
}
```

Mutation 修改、新增及构成变异路径闭包的边写为 `scope=candidate`；额外邻域边写为
`scope=context`。不得把 `candidate_source=mutation_scope` 描述成 retriever 成功。
Candidate 仍不得携带 `validation` 或边级 `causal_role`。若 mutation scope 不足以完成
验证，下游应输出 `ValidationReport(accepted=false)`，而不是阻止 Candidate 导出。

### 13.3 Q3：布尔 model behavior 的冻结结构

接受 `outcome_metric_type=boolean + positive_value`，旧规则不需要伪造连续 score。
为了统一方向语义，仍要求方向字段；字段名冻结为 `scoring_direction`，不同时支持
`score_direction` 别名。

```json
{
  "analysis_context": {
    "requested_validation_target": "model_behavior",
    "model_artifact": {
      "artifact_id": "prototype-scatter-gather-detector-v0.1",
      "format": "json",
      "uri": "artifact://prototype-scatter-gather-detector-v0.1",
      "sha256": "<attack_config.json 的真实 SHA-256>"
    },
    "outcome_metric": "suspicious_candidate",
    "outcome_metric_type": "boolean",
    "positive_value": true,
    "scoring_direction": "true_is_more_suspicious"
  }
}
```

Attack success 判定冻结为：

```text
before_attack == positive_value and after_attack != positive_value
```

连续模型以后使用 `outcome_metric_type=continuous`，方向取
`higher_is_more_suspicious | lower_is_more_suspicious`。布尔命中变化只证明
`model_behavior` 改变，不能解释为真实洗钱风险变化。

### 13.4 Q4：Candidate 生产者

确认选择 **B**。当前允许 Attack 进程直接输出 `candidate_subgraph.json`，但代码职责拆为：

```text
MutationEngine
    -> mutated DataFrame + edge_lineage + mutation metadata
Retriever / Extractor
    -> selected edge IDs + scope + retrieval metadata
CandidatePackageBuilder
    -> CandidateSubgraphPackage v0.2
```

`CandidatePackageBuilder` 可暂时位于 Attack 仓库，但 JSON 组装逻辑不能散落在三个
mutation 函数中。建议 provenance 记录：

```json
{"generator": "attack.CandidatePackageBuilder", "generator_version": "0.2.0"}
```

### 13.5 Q5：保留 attack_summary.json

确认选择 **A**。

- summary 是 Attack 内部调试、审计和轻量交接产物；
- Candidate 是跨模块规范接口；
- 两者公共字段必须由同一内存对象序列化；
- 公共字段不一致时构建任务硬失败；
- 下游以 Candidate 为准，不通过 summary 补齐 Candidate 缺失字段。

至少检查：`attack_id`、`attack_type`、`attack_success`、`old_rule_result`、
`failed_rule_conditions` 和 `edge_lineage` 在两份输出中一致。

### 13.6 Q6：边级谱系存储位置

接受“summary + Candidate JSON 保存谱系，CSV 不保存”。Mutation 函数返回：

```text
mutated DataFrame + edge_lineage: dict[edge_id, Lineage]
```

同一个 `edge_lineage` 同时写入 `attack_summary.edge_lineage` 和
`candidate.graph.edges[*].parent_edge_ids/mutation_role`。CSV 保持通用交易表，只保存事实
边的稳定 transaction ID。未来若需仅凭 CSV 重建谱系，应增加独立
`edge_lineage.jsonl` sidecar，不在 CSV 单元格内嵌 JSON 数组。

### 13.7 Q7：修改边必须生成新 edge_id

确认修改边必须生成新 ID，禁止 `edge_id=tx_004` 同时
`parent_edge_ids=[tx_004]` 的自引用。为防止跨攻击碰撞，格式冻结为：

```text
修改边：<parent_edge_id>__mut__<attack_id>__<op_index>
新增边：<attack_id>__add__<op_index>
```

| 边类型 | edge_id | parent_edge_ids | mutation_role |
|---|---|---|---|
| 未修改边 | 保留原 ID | `[]` | `preserved` |
| 修改边 | 新 ID | 至少一个父 ID | `modified` |
| 新增边 | 新 ID | 有结构来源则写父 ID，否则 `[]` | `added` |

ID 必须确定性且 package 内唯一；同参数、同 seed、同 attack_id 重跑得到相同 ID。

### 13.8 Q8：Synthetic / AMLSim node_id

选择固定三段格式，缺失 bank ID 使用显式保留值：

```text
dataset_id::bank_id::account_id
dataset_id::__NO_BANK__::account_id
```

`__NO_BANK__` 表示数据源未提供 bank 维度，不代表真实银行，因此不是伪造 bank ID。
固定三段避免消费者根据段数猜测语义。原字段包含 `::` 时必须可逆转义；不得把标签、
case 局部序号或 mutation round 编入 node ID。

### 13.9 Q9：Prototype artifact URI

接受 logical URI + 真实 SHA-256 + 本地 manifest，无需等待正式 Registry。

```json
{
  "schema_version": "ccem.artifact_manifest/v0.1",
  "artifacts": {
    "synthetic-sg-001-base-transactions": {
      "path": "outputs/attacks/attack_017/base_transactions.csv",
      "format": "csv",
      "sha256": "<真实文件 SHA-256>"
    }
  }
}
```

Manifest path 相对 manifest 文件解析，不使用机器绝对路径。读取时重新计算 SHA-256，
不匹配则硬失败。Candidate 与 manifest 的 `artifact_id/format/sha256` 必须一致；manifest
不嵌入 Candidate，也不进入经验规则。

### 13.10 Q10：时间量化

接受并冻结：

```text
time_unit      = second
time_precision = 1.0
time_origin    = baseline artifact 中最早的 UTC timestamp
quantization   = ROUND_HALF_UP
```

补充约束：

1. CSV ISO timestamp 必须带时区；无时区输入按数据集配置解释后转 UTC。
2. Candidate timestamp 是相对 origin 的有限非负秒数。
3. Python `round()` 是 ties-to-even，不能直接使用；采用
   `Decimal.quantize(..., rounding=ROUND_HALF_UP)` 或等价整数算法。
4. 同秒多边合法，由 multigraph 和唯一 edge ID 区分。
5. 当前 mutation 不得产生早于 baseline origin 的边；未来若支持时间前移，需另行冻结
   origin 重定位规则，不能输出负 timestamp。
6. 量化规则写入 provenance 或 attack config，并计入配置哈希。

### 13.11 额外接口不变量

1. `case_id` 跨同一原始案例的多个 attack 保持稳定；`attack_id` 标识一次具体 mutation。
2. retrieval、attack success、causal acceptance 三类状态不得互相推导或复用。
3. Attack、Builder、Pattern Evolution 均不得读取 Oracle/Outcome。
4. Attack 只能生成 Candidate；仅 CausalValidator 能生成 Validated 和 `causal_role`。
5. `compile_experience()` 只接受 `ccem.validated_subgraph/v0.2` 且 accepted=true 的包。
6. `model_behavior` 证书不能冒充 `aml_outcome` 因果结论。
7. 正式发布需包含 JSON Schema、合法/非法 fixture、summary/Candidate 一致性测试和确定性
   重跑结果。

### 13.12 Attack 队友可直接执行的顺序

```text
1. 抽出 CandidatePackageBuilder
2. 让 mutation 返回 DataFrame + edge_lineage
3. 按新 ID 规则修改三种 mutation
4. retrieval failure 时从 mutation scope 构造 Candidate
5. 同源生成 summary 与 Candidate.mutation
6. 添加 artifact manifest 和 SHA-256 校验
7. 添加 ROUND_HALF_UP 时间量化
8. 增加契约测试并输出 retrieval-failure 合法 fixture
```
