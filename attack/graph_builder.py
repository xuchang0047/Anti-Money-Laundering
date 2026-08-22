"""Build a lightweight directed transaction multigraph."""

import networkx as nx
import pandas as pd


REQUIRED_COLUMNS = {
    "transaction_id",
    "timestamp",
    "source",
    "target",
    "amount",
    "pattern_id",
    "pattern_type",
}


def build_transaction_graph(df: pd.DataFrame) -> nx.MultiDiGraph:
    """Return a MultiDiGraph with accounts as nodes and transactions as edges."""
    missing = sorted(REQUIRED_COLUMNS - set(df.columns))
    if missing:
        raise ValueError(f"Missing transaction columns: {', '.join(missing)}")
    if df.empty:
        raise ValueError("Transaction data must not be empty")
    if df["transaction_id"].astype(str).duplicated().any():
        raise ValueError("transaction_id values must be unique")

    graph = nx.MultiDiGraph()
    for record in df.to_dict(orient="records"):
        timestamp = pd.to_datetime(record["timestamp"], utc=True, errors="raise")
        amount = float(record["amount"])
        if amount <= 0:
            raise ValueError("All transaction amounts must be positive")

        source = str(record["source"])
        target = str(record["target"])
        transaction_id = str(record["transaction_id"])
        graph.add_edge(
            source,
            target,
            key=transaction_id,
            transaction_id=transaction_id,
            amount=amount,
            timestamp=timestamp,
            pattern_id=str(record["pattern_id"]),
            pattern_type=str(record["pattern_type"]),
        )
    return graph
