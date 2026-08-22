#!/usr/bin/env python3
"""Build an account-day IBM AML panel and estimate a DoWhy causal effect."""

from __future__ import annotations

import argparse
import json
from collections import defaultdict, deque
from pathlib import Path

import numpy as np
import pandas as pd

from subgraph_patterns import MEMBER_COLUMNS, identify_temporal_subgraphs


RAW_COLUMNS = [
    "Timestamp", "From Bank", "Account", "To Bank", "Account.1",
    "Amount Received", "Receiving Currency", "Amount Paid",
    "Payment Currency", "Is Laundering",
]

CONFOUNDERS = [
    "hist_event_count", "hist_in_amount", "hist_out_amount",
    "hist_in_count", "hist_out_count", "hist_cross_bank_count",
    "hist_laundering_count", "hist_counterparty_days",
    "hist_currency_days", "day_of_week", "day_index",
]

HYPOTHESIS = (
    "在可观测历史行为相近的账户中，当日发生快速资金中转（收款后1小时内以"
    "近似金额、同币种转出）会提高该账户次日涉及洗钱标记交易的概率。"
)

TREATMENT_HYPOTHESES = {
    "rapid_transfer": HYPOTHESIS,
    "cycle_member": "参与时间有序循环资金子图会提高账户次日涉及洗钱标记交易的概率。",
    "fan_out_member": "参与扇出资金分散子图会提高账户次日涉及洗钱标记交易的概率。",
    "fan_in_member": "参与扇入资金归集子图会提高账户次日涉及洗钱标记交易的概率。",
    "chain_member": "参与多级时间有序资金链条会提高账户次日涉及洗钱标记交易的概率。",
}


def _account_key(bank: pd.Series, account: pd.Series) -> pd.Series:
    return bank.astype("string") + "::" + account.astype("string")


def load_transactions(path: Path, max_rows: int | None = None) -> pd.DataFrame:
    available = set(pd.read_csv(path, nrows=0).columns)
    missing = sorted(set(RAW_COLUMNS) - available)
    if missing:
        raise ValueError(f"上游交易文件缺少必填字段: {missing}")
    df = pd.read_csv(path, usecols=RAW_COLUMNS, nrows=max_rows, low_memory=False)
    df["Timestamp"] = pd.to_datetime(df["Timestamp"], errors="coerce")
    for col in ["Amount Received", "Amount Paid"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    label = pd.to_numeric(df["Is Laundering"], errors="coerce")
    invalid_label = label.isna() | ~label.isin([0, 1])
    if invalid_label.any():
        raise ValueError(f"Is Laundering 包含 {int(invalid_label.sum())} 个非 0/1 值")
    df["Is Laundering"] = label.astype("int8")
    if (df[["Amount Received", "Amount Paid"]] < 0).any().any():
        raise ValueError("Amount Received/Amount Paid 不允许负数")
    df = df.dropna(subset=[
        "Timestamp", "From Bank", "Account", "To Bank", "Account.1",
        "Amount Received", "Amount Paid", "Receiving Currency", "Payment Currency",
    ]).copy()
    empty_currency = (
        df["Receiving Currency"].astype("string").str.strip().eq("")
        | df["Payment Currency"].astype("string").str.strip().eq("")
    )
    if empty_currency.any():
        raise ValueError(f"币种字段包含 {int(empty_currency.sum())} 个空字符串")
    return df


def transaction_events(tx: pd.DataFrame) -> pd.DataFrame:
    cross = (tx["From Bank"].astype("string") != tx["To Bank"].astype("string")).astype("int8")
    out = pd.DataFrame({
        "account_key": _account_key(tx["From Bank"], tx["Account"]),
        "timestamp": tx["Timestamp"],
        "role": "out",
        "amount": tx["Amount Paid"].astype(float),
        "currency": tx["Payment Currency"].astype("string"),
        "counterparty": _account_key(tx["To Bank"], tx["Account.1"]),
        "cross_bank": cross,
        "is_laundering": tx["Is Laundering"].to_numpy(),
    })
    inc = pd.DataFrame({
        "account_key": _account_key(tx["To Bank"], tx["Account.1"]),
        "timestamp": tx["Timestamp"],
        "role": "in",
        "amount": tx["Amount Received"].astype(float),
        "currency": tx["Receiving Currency"].astype("string"),
        "counterparty": _account_key(tx["From Bank"], tx["Account"]),
        "cross_bank": cross,
        "is_laundering": tx["Is Laundering"].to_numpy(),
    })
    events = pd.concat([out, inc], ignore_index=True)
    events["date"] = events["timestamp"].dt.floor("D")
    return events


def transaction_edges(tx: pd.DataFrame) -> pd.DataFrame:
    edges = pd.DataFrame({
        "source": _account_key(tx["From Bank"], tx["Account"]),
        "target": _account_key(tx["To Bank"], tx["Account.1"]),
        "timestamp": tx["Timestamp"],
        "amount_paid": tx["Amount Paid"].astype(float),
        "payment_currency": tx["Payment Currency"].astype("string"),
        "amount_received": tx["Amount Received"].astype(float),
        "receiving_currency": tx["Receiving Currency"].astype("string"),
    })
    edges["date"] = edges["timestamp"].dt.floor("D")
    return edges


def daily_features(events: pd.DataFrame) -> pd.DataFrame:
    e = events.assign(
        in_count=(events["role"] == "in").astype("int8"),
        out_count=(events["role"] == "out").astype("int8"),
        in_amount=events["amount"].where(events["role"] == "in", 0.0),
        out_amount=events["amount"].where(events["role"] == "out", 0.0),
    )
    return (
        e.groupby(["account_key", "date"], observed=True, sort=False)
        .agg(
            event_count=("role", "size"),
            in_amount=("in_amount", "sum"),
            out_amount=("out_amount", "sum"),
            in_count=("in_count", "sum"),
            out_count=("out_count", "sum"),
            cross_bank_count=("cross_bank", "sum"),
            laundering_count=("is_laundering", "sum"),
            counterparty_days=("counterparty", "nunique"),
            currency_days=("currency", "nunique"),
            laundering=("is_laundering", "max"),
        )
        .reset_index()
    )


def rapid_transfer_by_day(
    events: pd.DataFrame, rapid_hours: float, min_ratio: float, max_ratio: float
) -> pd.DataFrame:
    """Exact one-pass existence test; the same incoming event is not summed/reused."""
    order = events["role"].map({"out": 0, "in": 1}).astype("int8")
    work = events.assign(_role_order=order).sort_values(
        ["account_key", "date", "timestamp", "_role_order"], kind="mergesort"
    )
    horizon_ns = int(rapid_hours * 3600 * 1_000_000_000)
    result: list[tuple[str, pd.Timestamp, int]] = []
    current = None
    queues: dict[str, deque[tuple[int, float]]] = defaultdict(deque)
    rapid = 0

    for row in work[["account_key", "date", "timestamp", "role", "currency", "amount"]].itertuples(index=False):
        key = (row.account_key, row.date)
        if key != current:
            if current is not None:
                result.append((current[0], current[1], rapid))
            current, queues, rapid = key, defaultdict(deque), 0
        currency = str(row.currency)
        t_ns = int(row.timestamp.value)
        amount = float(row.amount)
        q = queues[currency]
        if row.role == "out":
            while q and t_ns - q[0][0] > horizon_ns:
                q.popleft()
            if amount > 0 and any(
                0 < t_ns - incoming_t <= horizon_ns
                and min_ratio <= amount / incoming_amount <= max_ratio
                for incoming_t, incoming_amount in q
                if incoming_amount > 0
            ):
                rapid = 1
        else:
            q.append((t_ns, amount))
    if current is not None:
        result.append((current[0], current[1], rapid))
    return pd.DataFrame(result, columns=["account_key", "date", "rapid_transfer"])


def build_panel(
    input_path: Path,
    panel_path: Path,
    subgraph_path: Path | None = None,
    lookback_days: int = 7,
    rapid_hours: float = 1.0,
    min_ratio: float = 0.8,
    max_ratio: float = 1.2,
    motif_hours: float = 1.0,
    fan_threshold: int = 3,
    motif_min_ratio: float = 0.5,
    motif_max_ratio: float = 1.2,
    max_rows: int | None = None,
) -> pd.DataFrame:
    if lookback_days < 1 or rapid_hours <= 0 or motif_hours <= 0:
        raise ValueError("lookback_days 必须 >=1，rapid_hours/motif_hours 必须 >0")
    if fan_threshold < 2:
        raise ValueError("fan_threshold 必须 >=2")
    if not (0 < min_ratio <= max_ratio) or not (0 < motif_min_ratio <= motif_max_ratio):
        raise ValueError("金额比必须满足 0 < min_ratio <= max_ratio")
    tx = load_transactions(input_path, max_rows=max_rows)
    events = transaction_events(tx)
    daily = daily_features(events).sort_values(["account_key", "date"])
    rapid = rapid_transfer_by_day(events, rapid_hours, min_ratio, max_ratio)
    membership, subgraphs = identify_temporal_subgraphs(
        transaction_edges(tx), rapid, motif_hours=motif_hours, fan_threshold=fan_threshold,
        min_ratio=motif_min_ratio, max_ratio=motif_max_ratio,
    )

    base_cols = [
        "event_count", "in_amount", "out_amount", "in_count", "out_count",
        "cross_bank_count", "laundering_count", "counterparty_days", "currency_days",
    ]
    rolled = (
        daily.set_index("date").groupby("account_key")[base_cols]
        .rolling(f"{lookback_days}D", closed="left").sum()
        .reset_index()
        .rename(columns={c: f"hist_{c}" for c in base_cols})
    )
    panel = daily[["account_key", "date"]].merge(rolled, on=["account_key", "date"], how="left")
    panel = panel.merge(membership, on=["account_key", "date"], how="left")

    outcome = daily[["account_key", "date", "laundering"]].copy()
    outcome["date"] = outcome["date"] - pd.Timedelta(days=1)
    panel = panel.merge(outcome, on=["account_key", "date"], how="left")
    panel = panel[panel["date"] < daily["date"].max()].copy()
    panel["laundering"] = panel["laundering"].fillna(0).astype("int8")
    motif_cols = ["rapid_transfer", *MEMBER_COLUMNS]
    panel[motif_cols] = panel[motif_cols].fillna(0).astype("int8")
    panel["subgraph_risk_score"] = panel["subgraph_risk_score"].fillna(0.0)
    hist_cols = [c for c in panel if c.startswith("hist_")]
    panel[hist_cols] = panel[hist_cols].fillna(0.0)
    panel["day_of_week"] = panel["date"].dt.dayofweek.astype("int8")
    panel["day_index"] = (panel["date"] - panel["date"].min()).dt.days.astype("int32")

    panel_path.parent.mkdir(parents=True, exist_ok=True)
    if panel_path.suffix.lower() == ".parquet":
        panel.to_parquet(panel_path, index=False)
    else:
        panel.to_csv(panel_path, index=False)
    if subgraph_path is not None:
        subgraph_path.parent.mkdir(parents=True, exist_ok=True)
        if subgraph_path.suffix.lower() == ".parquet":
            subgraphs.to_parquet(subgraph_path, index=False)
        else:
            subgraphs.to_csv(subgraph_path, index=False)
    return panel


def _read_panel(path: Path) -> pd.DataFrame:
    return pd.read_parquet(path) if path.suffix.lower() == ".parquet" else pd.read_csv(path)


def _refuter_payload(refuter) -> dict:
    payload = {"summary": str(refuter)}
    value = getattr(refuter, "new_effect", None)
    if value is not None:
        try:
            payload["new_effect"] = float(np.asarray(value).mean())
        except (TypeError, ValueError):
            pass
    result = getattr(refuter, "refutation_result", None)
    if result is not None and hasattr(result, "get"):
        p_value = result.get("p_value")
        if p_value is not None:
            payload["p_value"] = float(p_value)
    return payload


def _ipw_effect(x: np.ndarray, treatment: np.ndarray, outcome: np.ndarray, seed: int) -> float:
    from sklearn.linear_model import LogisticRegression

    model = LogisticRegression(solver="liblinear", max_iter=2000, random_state=seed)
    model.fit(x, treatment)
    ps = np.clip(model.predict_proba(x)[:, 1], 0.01, 0.99)
    wt = treatment / ps
    wc = (1 - treatment) / (1 - ps)
    return float(np.sum(wt * outcome) / np.sum(wt) - np.sum(wc * outcome) / np.sum(wc))


def run_refuters(df: pd.DataFrame, treatment: str, simulations: int, seed: int) -> dict:
    """Freshly refit propensity models after every perturbation."""
    rng = np.random.default_rng(seed)
    x = df[CONFOUNDERS].to_numpy(dtype=float)
    t = df[treatment].to_numpy(dtype=int)
    y = df["laundering"].to_numpy(dtype=float)
    placebo, random_cause, subset = [], [], []
    subset_n = max(2, int(len(df) * 0.8))
    for i in range(simulations):
        placebo.append(_ipw_effect(x, rng.permutation(t), y, seed + i))
        augmented = np.column_stack([x, rng.normal(size=len(df))])
        random_cause.append(_ipw_effect(augmented, t, y, seed + i))
        idx = rng.choice(len(df), size=subset_n, replace=False)
        subset.append(_ipw_effect(x[idx], t[idx], y[idx], seed + i))

    def payload(name: str, values: list[float]) -> dict:
        return {
            "summary": f"{name}; {simulations} fresh propensity-model refits",
            "new_effect": float(np.mean(values)),
            "simulation_std": float(np.std(values)),
        }

    return {
        "placebo_treatment_refuter": payload("Permuted treatment", placebo),
        "random_common_cause": payload("Added random common cause", random_cause),
        "data_subset_refuter": payload("80% row subset", subset),
    }


def cluster_bootstrap_ci(
    df: pd.DataFrame, treatment: str, simulations: int, seed: int
) -> dict:
    """Account-cluster bootstrap interval for the IPW risk difference."""
    if simulations < 1:
        return {"ci95": None, "standard_error": None, "successful_simulations": 0}
    rng = np.random.default_rng(seed)
    x = df[CONFOUNDERS].to_numpy(dtype=float)
    t = df[treatment].to_numpy(dtype=int)
    y = df["laundering"].to_numpy(dtype=float)
    groups = df["account_key"].astype(str).to_numpy()
    unique_groups = np.unique(groups)
    group_indices = {g: np.flatnonzero(groups == g) for g in unique_groups}
    values = []
    for i in range(simulations):
        sampled = rng.choice(unique_groups, size=len(unique_groups), replace=True)
        idx = np.concatenate([group_indices[g] for g in sampled])
        if np.unique(t[idx]).size < 2:
            continue
        values.append(_ipw_effect(x[idx], t[idx], y[idx], seed + 10_000 + i))
    if not values:
        return {"ci95": None, "standard_error": None, "successful_simulations": 0}
    return {
        "ci95": [float(np.percentile(values, 2.5)), float(np.percentile(values, 97.5))],
        "standard_error": float(np.std(values, ddof=1)) if len(values) > 1 else None,
        "successful_simulations": len(values),
    }


def _confidence(
    n: int, treated_n: int, control_n: int, overlap: float, max_weight: float,
    estimate: float, refuters: dict, refute_simulations: int,
) -> dict:
    checks = {
        "adequate_sample": n >= 1000 and min(treated_n, control_n) >= 100,
        "good_overlap": overlap >= 0.80 and max_weight <= 20,
        "adequate_refuter_simulations": refute_simulations >= 20,
    }
    tolerance = max(abs(estimate) * 0.25, 0.001)
    for name, item in refuters.items():
        new_effect = item.get("new_effect")
        if new_effect is None:
            checks[f"{name}_stable"] = False
        elif name == "placebo_treatment_refuter":
            checks[f"{name}_stable"] = abs(new_effect) <= tolerance
        else:
            checks[f"{name}_stable"] = abs(new_effect - estimate) <= tolerance
    passed = sum(checks.values())
    level = "HIGH" if passed == len(checks) else "MEDIUM" if passed >= 3 else "LOW"
    return {"level": level, "checks": checks, "note": "评级不是后验概率，且不能排除未观测混杂。"}


def run_dowhy(
    panel_path: Path, output_path: Path, treatment: str = "rapid_transfer",
    refute_simulations: int = 20, seed: int = 42, bootstrap_simulations: int = 50,
) -> dict:
    from dowhy import CausalModel
    from sklearn.linear_model import LogisticRegression
    from sklearn.preprocessing import StandardScaler

    if treatment not in TREATMENT_HYPOTHESES:
        raise ValueError(f"不支持的 treatment: {treatment}")
    if refute_simulations < 1:
        raise ValueError("refute_simulations 必须 >=1")
    if bootstrap_simulations < 0:
        raise ValueError("bootstrap_simulations 必须 >=0")
    df = _read_panel(panel_path).dropna(subset=CONFOUNDERS + [treatment, "laundering"]).copy()
    if df[treatment].nunique() < 2 or df["laundering"].nunique() < 2:
        raise ValueError("Treatment 和 outcome 都必须同时包含 0 与 1；请扩大数据或检查阈值。")
    for col in [c for c in CONFOUNDERS if c.startswith("hist_")]:
        df[col] = np.log1p(df[col].clip(lower=0))
    # Standardize inside the analysis table so DoWhy refuters inherit the same
    # numerically stable design matrix when they clone/refit the estimator.
    df[CONFOUNDERS] = StandardScaler().fit_transform(df[CONFOUNDERS].astype(float))

    x = df[CONFOUNDERS].astype(float)
    t = df[treatment].astype(int)
    propensity_model = LogisticRegression(
        solver="liblinear", max_iter=2000, random_state=seed
    ).fit(x, t)
    propensity = np.clip(propensity_model.predict_proba(x)[:, 1], 1e-3, 1 - 1e-3)
    weights = np.where(t.to_numpy() == 1, 1 / propensity, 1 / (1 - propensity))
    overlap = float(((propensity >= 0.05) & (propensity <= 0.95)).mean())

    dag_path = Path(__file__).parent / "config" / "dag.dot"
    dag = dag_path.read_text(encoding="utf-8").replace("rapid_transfer", treatment)
    model = CausalModel(
        data=df, treatment=treatment, outcome="laundering", graph=dag,
    )
    estimand = model.identify_effect(proceed_when_unidentifiable=False)
    estimate_obj = model.estimate_effect(
        estimand,
        method_name="backdoor.propensity_score_weighting",
        target_units="ate",
        method_params={
            "weighting_scheme": "ips_weight",
            "min_ps_score": 0.01,
            "max_ps_score": 0.99,
            "propensity_score_model": LogisticRegression(
                solver="liblinear", max_iter=2000, random_state=seed
            ),
        },
    )
    effect = float(estimate_obj.value)

    # PropensityScoreWeightingEstimator writes scores and weights into the
    # supplied frame. Remove them before refutation; otherwise a cloned
    # estimator can silently reuse the old score after treatment/confounders
    # have been perturbed, invalidating the refuter.
    generated = [
        c for c in model._data.columns
        if c == "propensity_score" or c.endswith("_weight")
    ]
    if generated:
        model._data.drop(columns=generated, inplace=True)

    refuters = run_refuters(model._data, treatment, refute_simulations, seed)
    bootstrap = cluster_bootstrap_ci(model._data, treatment, bootstrap_simulations, seed)

    treated_n, control_n = int(t.sum()), int((1 - t).sum())
    result = {
        "Hypothesis": TREATMENT_HYPOTHESES[treatment],
        "Causal Effect": {
            "treatment": treatment,
            "estimand": "ATE risk difference",
            "estimate": effect,
            "ci95_cluster_bootstrap": bootstrap["ci95"],
            "bootstrap_standard_error": bootstrap["standard_error"],
            "bootstrap_simulations": bootstrap["successful_simulations"],
            "treated_rate_unadjusted": float(df.loc[t == 1, "laundering"].mean()),
            "control_rate_unadjusted": float(df.loc[t == 0, "laundering"].mean()),
            "n": int(len(df)), "treated_n": treated_n, "control_n": control_n,
        },
        "Validation": {
            "propensity_overlap_0.05_0.95": overlap,
            "max_unstabilized_ipw": float(weights.max()),
            "refuters": refuters,
        },
        "Confidence": _confidence(
            len(df), treated_n, control_n, overlap, float(weights.max()), effect,
            refuters, refute_simulations,
        ),
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest="command", required=True)
    for command in ["build", "all"]:
        s = sub.add_parser(command)
        s.add_argument("--input", type=Path, required=True)
        s.add_argument("--panel", type=Path, required=True)
        s.add_argument("--subgraphs", type=Path)
        s.add_argument("--lookback-days", type=int, default=7)
        s.add_argument("--rapid-hours", type=float, default=1.0)
        s.add_argument("--min-ratio", type=float, default=0.8)
        s.add_argument("--max-ratio", type=float, default=1.2)
        s.add_argument("--motif-hours", type=float, default=1.0)
        s.add_argument("--fan-threshold", type=int, default=3)
        s.add_argument("--motif-min-ratio", type=float, default=0.5)
        s.add_argument("--motif-max-ratio", type=float, default=1.2)
        s.add_argument("--max-rows", type=int)
    run = sub.add_parser("run")
    run.add_argument("--panel", type=Path, required=True)
    for command in [run, sub.choices["all"]]:
        command.add_argument("--output", type=Path, required=True)
        command.add_argument(
            "--treatment", choices=sorted(TREATMENT_HYPOTHESES), default="rapid_transfer"
        )
        command.add_argument("--refute-simulations", type=int, default=20)
        command.add_argument("--bootstrap-simulations", type=int, default=50)
        command.add_argument("--seed", type=int, default=42)
    return p


def main() -> None:
    args = parser().parse_args()
    if args.command in {"build", "all"}:
        panel = build_panel(
            args.input, args.panel, args.subgraphs, args.lookback_days, args.rapid_hours,
            args.min_ratio, args.max_ratio, args.motif_hours, args.fan_threshold,
            args.motif_min_ratio, args.motif_max_ratio, args.max_rows,
        )
        print(f"Panel: {args.panel} ({len(panel):,} rows)")
    if args.command in {"run", "all"}:
        result = run_dowhy(
            args.panel, args.output, args.treatment, args.refute_simulations, args.seed,
            args.bootstrap_simulations,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
