#!/usr/bin/env python3
"""Create a small IBM-schema synthetic fixture for an end-to-end smoke test."""

from __future__ import annotations

import argparse
import csv
import math
import random
from datetime import datetime, timedelta
from pathlib import Path


HEADER = [
    "Timestamp", "From Bank", "Account", "To Bank", "Account.1",
    "Amount Received", "Receiving Currency", "Amount Paid",
    "Payment Currency", "Payment Format", "Is Laundering",
]


def make_data(output: Path, accounts: int, days: int, seed: int) -> None:
    rng = random.Random(seed)
    start = datetime(2026, 1, 1)
    rows = []
    previous_treatment = [0] * accounts
    for day in range(days):
        next_treatment = [0] * accounts
        for acct in range(accounts):
            risk = (acct % 10) / 10
            n_normal = 1 + int(rng.random() < 0.35 + 0.25 * risk)
            for j in range(n_normal):
                other = (acct + 1 + rng.randrange(accounts - 1)) % accounts
                ts = start + timedelta(days=day, hours=8 + rng.randrange(10), minutes=rng.randrange(60))
                amount = round(math.exp(rng.normalvariate(5.5 + risk, 0.7)), 2)
                laundering = int(rng.random() < 0.01 + 0.22 * previous_treatment[acct])
                rows.append([ts, acct % 5, f"A{acct}", other % 5, f"A{other}", amount, "USD", amount, "USD", "ACH", laundering])
            treat = int(rng.random() < 0.05 + 0.18 * risk)
            next_treatment[acct] = treat
            if treat:
                source, dest = (acct + 7) % accounts, (acct + 13) % accounts
                ts = start + timedelta(days=day, hours=12, minutes=rng.randrange(20))
                amount = round(1000 + 2000 * risk + rng.random() * 500, 2)
                rows.append([ts, source % 5, f"A{source}", acct % 5, f"A{acct}", amount, "USD", amount, "USD", "Wire", 0])
                paid = round(amount * rng.uniform(0.9, 0.99), 2)
                rows.append([ts + timedelta(minutes=20), acct % 5, f"A{acct}", dest % 5, f"A{dest}", paid, "USD", paid, "USD", "Wire", 0])
        previous_treatment = next_treatment
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(HEADER)
        writer.writerows(sorted(rows, key=lambda r: r[0]))


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--accounts", type=int, default=300)
    p.add_argument("--days", type=int, default=18)
    p.add_argument("--seed", type=int, default=42)
    a = p.parse_args()
    make_data(a.output, a.accounts, a.days, a.seed)
    print(a.output)

