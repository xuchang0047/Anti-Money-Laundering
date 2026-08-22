# Agentic AML Evolution：CCEM 最小闭环

该原型按照 `Shared Subgraph Package v0.2-draft` 实现一次完整的自进化检测回合：

```text
Candidate + ValidationReport
        -> accepted Validated
        -> Hypothesis Agent（仅解释视图）
        -> 角色归纳 / WL 指纹 / CCEM 编译
        -> 正例与反事实 replay
        -> DetectorLibrary ADD/MERGE/SPECIALIZE/PRUNE
        -> 下一轮重新检测
        -> Multi-GNN 张量契约
```

核心约束：

- 经验编译器只接受 `validation.accepted=true` 的 Validated 包。
- LLM 不能决定因果验收，也不能修改可执行规则；其输出只作为非执行解释视图。
- 编译经验不保存账户 ID、Oracle 或 outcome 标签。
- 交易图 `G_t` 与经验知识图 `K_t` 分开保存。
- 经验入库前必须命中原正例和轻微增强正例，并拒绝四个关键反事实。

## 与 Attack 的边界

```text
attack/                         pattern_evolution/
Mutation + Candidate Builder   Validated -> executable experience
             │                              ▲
             └── Candidate v0.2 -> CausalValidator（团队上游）
```

- Attack 只生成 Candidate，不生成或猜测 `validation.accepted`。
- Pattern Evolution 只编译 Validated，Candidate 不能进入编译入口。
- 两个模块只共享 v0.2 JSON 和 artifact manifest，不 import 对方内部代码。

运行 Attack 并验证三个 Candidate 的接口：

```bash
cd /home/bingqinshao/Multi-GNN
python3 attack/main.py
python3 -m pattern_evolution.validate_attack_contract
```

## 一键运行

使用 `/home/bingqinshao/MOOSE-Chem/main.sh` 前几行的 OpenAI-compatible 配置：

```bash
cd /home/bingqinshao/Multi-GNN
python3 -m pattern_evolution.run_demo --require-api
```

只验证确定性主链路：

```bash
python3 -m pattern_evolution.run_demo --no-api
```

运行 Pattern Evolution 与 Attack 接口测试：

```bash
python3 -m unittest discover -s pattern_evolution/tests -t . -v
```

## 预期验收指标

```text
before proxy recall              = 0
after proxy recall               = 1
counterfactual false positives   = 0
old-pattern regression           = 0
library version                  = 1
evolution operation              = ADD
```

结果在 `artifacts/` 下：

- `proxies/`：Candidate、ValidationReport、Validated 和四个反事实。
- `library/`：原始规则库 v0 和自进化规则库 v1。
- `run/hypothesis_agent_result.json`：API 假设视图，不含密钥。
- `run/multignn_adapter_contract.json`：Multi-GNN 输入张量形状。
- `run/latest_summary.json`：端到端指标。

当前机器已有 PyTorch，但缺少 `torch_geometric`。因此 demo 已实际生成并验证 PyTorch 张量；安装 PyG 后可直接调用 `pattern_evolution.src.multignn_adapter.to_pyg()` 构造 PyG `Data`，不会影响当前闭环。
