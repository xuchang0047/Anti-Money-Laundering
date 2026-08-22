import unittest

import pandas as pd

from subgraph_patterns import identify_temporal_subgraphs


class TemporalSubgraphTest(unittest.TestCase):
    def test_chain_cycle_and_fans(self):
        day = pd.Timestamp("2026-01-01")
        raw = [
            ("A", "B", "10:00", 100, 100),
            ("B", "C", "10:10", 95, 95),
            ("C", "A", "10:20", 90, 90),
            ("E", "D", "11:00", 10, 10),
            ("F", "D", "11:05", 11, 11),
            ("G", "D", "11:10", 12, 12),
            ("H", "I", "12:00", 20, 20),
            ("H", "J", "12:05", 21, 21),
            ("H", "K", "12:10", 22, 22),
        ]
        edges = pd.DataFrame([
            {
                "source": source,
                "target": target,
                "timestamp": pd.Timestamp(f"2026-01-01 {hhmm}"),
                "date": day,
                "amount_paid": paid,
                "payment_currency": "USD",
                "amount_received": received,
                "receiving_currency": "USD",
            }
            for source, target, hhmm, paid, received in raw
        ])
        rapid = pd.DataFrame([
            {"account_key": "B", "date": day, "rapid_transfer": 1}
        ])
        members, instances = identify_temporal_subgraphs(edges, rapid)
        indexed = members.set_index("account_key")

        self.assertTrue({"A", "B", "C"}.issubset(set(indexed.index[indexed.cycle_member == 1])))
        self.assertEqual(indexed.loc["D", "fan_in_member"], 1)
        self.assertEqual(indexed.loc["H", "fan_out_member"], 1)
        self.assertEqual(indexed.loc["B", "rapid_transfer"], 1)
        self.assertTrue({"chain", "cycle", "fan_in", "fan_out"}.issubset(set(instances["type"])))


if __name__ == "__main__":
    unittest.main()
