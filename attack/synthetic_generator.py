"""Generate a tiny synthetic scatter-gather transaction case."""

from pathlib import Path

import pandas as pd


def generate_base_scatter_gather(output_path: Path) -> pd.DataFrame:
    """Create A → {B,C,D} → X as synthetic suspicious-pattern test data."""
    rows = [
        ("tx_001", "2022-09-01T00:00:00Z", "A", "B", 100.0),
        ("tx_002", "2022-09-01T00:10:00Z", "A", "C", 110.0),
        ("tx_003", "2022-09-01T00:20:00Z", "A", "D", 90.0),
        ("tx_004", "2022-09-01T02:00:00Z", "B", "X", 95.0),
        ("tx_005", "2022-09-01T02:10:00Z", "C", "X", 104.5),
        ("tx_006", "2022-09-01T02:20:00Z", "D", "X", 85.5),
    ]
    frame = pd.DataFrame(
        rows,
        columns=["transaction_id", "timestamp", "source", "target", "amount"],
    )
    frame["pattern_id"] = "synthetic_sg_001"
    frame["pattern_type"] = "scatter_gather"
    frame["synthetic_label"] = "synthetic suspicious pattern"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(output_path, index=False)
    return frame
