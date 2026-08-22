# Shared Subgraph Package v0.3

状态：本子项目实现基线。确认依据见 `attack_v0.3_interface_confirmation_questions.md`
第 13 节。

## 1. 包与职责

| 对象 | 版本 | 生产者 | 作用 |
|---|---|---|---|
| Candidate | `ccem.candidate_subgraph/v0.3` | CandidatePackageBuilder | 待验证事实图，不含因果结论 |
| ValidationReport | `ccem.validation_report/v0.3` | CausalValidator | 无论通过或失败都输出 |
| Validated | `ccem.validated_subgraph/v0.3` | CausalValidator | 仅在 `accepted=true` 时输出 |
| Artifact manifest | `ccem.artifact_manifest/v0.1` | 数据提供方 | 将 logical artifact ID 映射到相对路径与 SHA-256 |

`attack_success`、`mutated_retrieved`、`validation.accepted` 是三个独立状态，禁止互相
推导。检索失败时，只要 mutation scope 可确定，Candidate 仍可导出，并明确记录
`candidate_source=mutation_scope`。

## 2. Candidate 图不变量

- 图必须 `directed=true`、`multigraph=true`。
- `node_id` 固定为 `dataset_id::bank_id::account_id`；缺少银行维度时使用
  `dataset_id::__NO_BANK__::account_id`。
- 时间固定为相对秒：`time_unit=second`、`time_precision=1.0`、
  `time_quantization=ROUND_HALF_UP`，origin 为基线数据最早 UTC 时间。
- 边时间必须有限、非负并量化到整秒；金额必须有限、非负。
- `scope=candidate` 表示变异路径闭包，`scope=context` 表示额外邻域。
- Candidate 禁止包含 `validation` 和 `graph.edges[*].causal_role`。

## 3. Edge lineage

| 类型 | `edge_id` | `parent_edge_ids` | `mutation_role` |
|---|---|---|---|
| preserved | 原 ID | `[]` | `preserved` |
| modified | `<parent>__mut__<attack_id>__<op_index>` | 至少一个父 ID | `modified` |
| added | `<attack_id>__add__<op_index>` | 可为空或写结构来源 | `added` |

lineage 同时写入 attack summary 与 Candidate；CSV 不写数组型 lineage。两份对象的
`attack_id`、`attack_type`、`attack_success`、retrieval 状态、`old_rule_result`、
`failed_rule_conditions` 和 `edge_lineage` 不一致时硬失败。

## 4. Validation target

`aml_outcome` 必须提供 `population_artifact` 与 `outcome_ref`，并授权
`CausalValidator` 读取标签。

`model_behavior` 必须提供 `model_artifact`、`outcome_metric`、
`outcome_metric_type`、`positive_value` 与冻结字段 `scoring_direction`。布尔值使用
`true_is_more_suspicious`；连续值使用 `higher_is_more_suspicious` 或
`lower_is_more_suspicious`。模型行为变化不能解释为真实 AML outcome 变化。

## 5. Artifact manifest

Candidate 保存 logical URI、format 与真实 SHA-256。manifest 只保存项目内相对路径、
format 与 SHA-256；消费者按 manifest 所在目录解析路径并重新计算摘要。Candidate 和
manifest 的 `artifact_id`、`format`、`sha256` 必须一致。

可执行示例分别位于 `fixtures/` 与 `schemas/`，语义校验由 `interface_v03.py` 完成。
