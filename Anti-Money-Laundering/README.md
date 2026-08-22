# AML 子图识别与 DoWhy 因果实验（v0.3）

本目录是一套可独立运行的命令行工作流：读取共享
`CandidateSubgraphPackage v0.3` 和 artifact manifest，验证候选图中的子图模式，基于 IBM
AML 格式交易构造账户日面板，并运行 DoWhy/IPW 因果估计与验证。

## 快速运行

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python run_pipeline.py \
  --candidate fixtures/candidate_rapid_transfer_v03.json \
  --manifest fixtures/artifact_manifest_v01.json \
  --attack-summary fixtures/attack_summary_v03.json \
  --output-dir outputs/demo
python -m unittest discover -s tests -v
```

输出包括账户日面板、识别出的子图、DoWhy 结果、`ValidationReport v0.3`、运行清单；
只有验证通过时才生成 `ValidatedSubgraphPackage v0.3`。

完整变量、DAG 和执行步骤见 [WORKFLOW.md](WORKFLOW.md)，共享契约见
[shared_subgraph_interface_v0.3.md](docs/shared_subgraph_interface_v0.3.md)。

## 目录

```text
interface_v03.py       v0.3 契约与 artifact/摘要一致性校验
subgraph_patterns.py   rapid/chain/cycle/fan-in/fan-out 子图识别
aml_dowhy.py           IBM AML 面板构造、DoWhy/IPW、refuter 与 bootstrap
pipeline.py            端到端编排及 ValidationReport/Validated 输出
run_pipeline.py        命令行入口
fixtures/              可运行的 Candidate、manifest、attack summary
schemas/               共享 JSON Schema
tests/                 单元测试与端到端测试
```
