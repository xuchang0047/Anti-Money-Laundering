"""Temporal AML motif identification on directed transaction edges."""

from __future__ import annotations

import json
from bisect import bisect_right
from collections import defaultdict

import pandas as pd


MEMBER_COLUMNS = [
    "fan_in_member", "fan_out_member", "chain_member", "cycle_member"
]


def identify_temporal_subgraphs(
    edges: pd.DataFrame,
    rapid: pd.DataFrame,
    motif_hours: float = 1.0,
    fan_threshold: int = 3,
    min_ratio: float = 0.5,
    max_ratio: float = 1.2,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Identify directed, time-respecting motifs within each calendar day.

    Chain: A->B followed by B->C, A!=C, within motif_hours.
    Cycle: time-respecting 2-cycle or 3-cycle within motif_hours.
    Fan-in/out: at least fan_threshold distinct counterparties in one day.
    """
    horizon_ns = int(motif_hours * 3600 * 1_000_000_000)
    memberships: dict[tuple[str, pd.Timestamp], set[str]] = defaultdict(set)
    instances: list[dict] = []

    def add_instance(
        day, motif_type: str, nodes: set[str], center: str | None,
        path_count: int, start, end,
    ) -> None:
        nodes = {str(n) for n in nodes}
        instances.append({
            "date": day,
            "type": motif_type,
            "center": center or "",
            "nodes": json.dumps(sorted(nodes), ensure_ascii=False),
            "node_count": len(nodes),
            "path_count": int(path_count),
            "start_timestamp": start,
            "end_timestamp": end,
        })
        member_col = f"{motif_type}_member"
        for node in nodes:
            memberships[(node, day)].add(member_col)

    work = edges.sort_values(["date", "timestamp"], kind="mergesort")
    for day, group in work.groupby("date", sort=False, observed=True):
        records = list(group[[
            "source", "target", "timestamp", "amount_paid", "payment_currency",
            "amount_received", "receiving_currency",
        ]].itertuples(index=False))
        incoming: dict[str, list] = defaultdict(list)
        outgoing: dict[str, list] = defaultdict(list)
        edge_records: dict[tuple[str, str], list[tuple]] = defaultdict(list)
        for row in records:
            t_ns = int(row.timestamp.value)
            incoming[str(row.target)].append(
                (t_ns, str(row.source), float(row.amount_received), str(row.receiving_currency))
            )
            outgoing[str(row.source)].append(
                (t_ns, str(row.target), float(row.amount_paid), str(row.payment_currency))
            )
            edge_records[(str(row.source), str(row.target))].append((
                t_ns, float(row.amount_paid), str(row.payment_currency),
                float(row.amount_received), str(row.receiving_currency),
            ))

        # Fan motifs are aggregated around a daily center account.
        for center, rows in incoming.items():
            sources = {source for _, source, _, _ in rows if source != center}
            if len(sources) >= fan_threshold:
                add_instance(
                    day, "fan_in", sources | {center}, center, len(rows),
                    pd.Timestamp(min(r[0] for r in rows)), pd.Timestamp(max(r[0] for r in rows)),
                )
        for center, rows in outgoing.items():
            targets = {target for _, target, _, _ in rows if target != center}
            if len(targets) >= fan_threshold:
                add_instance(
                    day, "fan_out", targets | {center}, center, len(rows),
                    pd.Timestamp(min(r[0] for r in rows)), pd.Timestamp(max(r[0] for r in rows)),
                )

        # Two-edge temporal chains, aggregated by middle account.
        for middle in set(incoming) & set(outgoing):
            outs = sorted(outgoing[middle])
            out_times = [x[0] for x in outs]
            chain_nodes, path_count, starts, ends = {middle}, 0, [], []
            for t1, source, incoming_amount, incoming_currency in incoming[middle]:
                lo = bisect_right(out_times, t1)
                hi = bisect_right(out_times, t1 + horizon_ns)
                for t2, target, outgoing_amount, outgoing_currency in outs[lo:hi]:
                    if source == target or source == middle or target == middle:
                        continue
                    if (
                        incoming_amount <= 0
                        or incoming_currency != outgoing_currency
                        or not min_ratio <= outgoing_amount / incoming_amount <= max_ratio
                    ):
                        continue
                    chain_nodes.update([source, target])
                    path_count += 1
                    starts.append(t1)
                    ends.append(t2)
            if path_count:
                add_instance(
                    day, "chain", chain_nodes, middle, path_count,
                    pd.Timestamp(min(starts)), pd.Timestamp(max(ends)),
                )

        # Time-respecting cycles of length two and three.
        cycle_seen: set[tuple] = set()
        for (source, target), first_edges in edge_records.items():
            reverse = edge_records.get((target, source), [])
            reverse_times = [r[0] for r in reverse]
            for t1, paid1, paycur1, received1, reccur1 in first_edges:
                j = bisect_right(reverse_times, t1)
                if j < len(reverse) and reverse[j][0] <= t1 + horizon_ns:
                    t2, paid2, paycur2, received2, reccur2 = reverse[j]
                    continuous = (
                        received1 > 0 and paid1 > 0
                        and reccur1 == paycur2 and min_ratio <= paid2 / received1 <= max_ratio
                        and reccur2 == paycur1 and min_ratio <= received2 / paid1 <= max_ratio
                    )
                    if not continuous:
                        continue
                    key = ("2", tuple(sorted([source, target])))
                    if key not in cycle_seen:
                        cycle_seen.add(key)
                        add_instance(
                            day, "cycle", {source, target}, "", 1,
                            pd.Timestamp(t1), pd.Timestamp(t2),
                        )
                    break

        for middle in set(incoming) & set(outgoing):
            outs = sorted(outgoing[middle])
            out_times = [x[0] for x in outs]
            for t1, source, incoming_amount, incoming_currency in incoming[middle]:
                lo = bisect_right(out_times, t1)
                hi = bisect_right(out_times, t1 + horizon_ns)
                for t2, target, outgoing_amount, outgoing_currency in outs[lo:hi]:
                    if len({source, middle, target}) < 3:
                        continue
                    if (
                        incoming_amount <= 0 or incoming_currency != outgoing_currency
                        or not min_ratio <= outgoing_amount / incoming_amount <= max_ratio
                    ):
                        continue
                    closing = edge_records.get((target, source), [])
                    closing_times = [r[0] for r in closing]
                    k = bisect_right(closing_times, t2)
                    if k < len(closing) and closing[k][0] <= t1 + horizon_ns:
                        t3, paid3, paycur3, received3, reccur3 = closing[k]
                        if (
                            paid3 <= 0 or outgoing_amount <= 0
                            or paycur3 != outgoing_currency
                            or not min_ratio <= paid3 / outgoing_amount <= max_ratio
                        ):
                            continue
                        key = ("3", tuple(sorted([source, middle, target])))
                        if key not in cycle_seen:
                            cycle_seen.add(key)
                            add_instance(
                                day, "cycle", {source, middle, target}, "", 1,
                                pd.Timestamp(t1), pd.Timestamp(t3),
                            )

    # rapid_transfer is a center-account behavior rather than a whole-motif
    # membership flag, but it participates in the composite risk score.
    for row in rapid.loc[rapid["rapid_transfer"] == 1, ["account_key", "date"]].itertuples(index=False):
        memberships[(str(row.account_key), row.date)].add("rapid_transfer")

    member_rows = []
    for (account, day), flags in memberships.items():
        row = {"account_key": account, "date": day, "rapid_transfer": int("rapid_transfer" in flags)}
        row.update({col: int(col in flags) for col in MEMBER_COLUMNS})
        row["subgraph_risk_score"] = (
            row["rapid_transfer"] * 1.0
            + row["fan_in_member"] * 1.5
            + row["fan_out_member"] * 1.5
            + row["chain_member"] * 2.0
            + row["cycle_member"] * 3.0
        ) / 9.0
        member_rows.append(row)

    membership = pd.DataFrame(member_rows)
    if membership.empty:
        membership = pd.DataFrame(columns=[
            "account_key", "date", "rapid_transfer", *MEMBER_COLUMNS, "subgraph_risk_score"
        ])
    instance_df = pd.DataFrame(instances)
    if not instance_df.empty:
        instance_df.insert(0, "subgraph_id", [f"SG{i:09d}" for i in range(1, len(instance_df) + 1)])
    else:
        instance_df = pd.DataFrame(columns=[
            "subgraph_id", "date", "type", "center", "nodes", "node_count",
            "path_count", "start_timestamp", "end_timestamp",
        ])
    return membership, instance_df
