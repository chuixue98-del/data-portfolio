import unittest
from pathlib import Path
import tempfile

import pandas as pd

from snapshot_check import compare, find_snapshots


def snap(rows):
    return pd.DataFrame(rows, columns=["FACTORY_ID", "FACTORY_NAME", "VENDOR_ID_ERP"])


class CompareTest(unittest.TestCase):
    def test_identical(self):
        s = snap([("F-1", "A", "100"), ("F-2", "B", "200")])
        self.assertTrue(compare(s, s.copy()).identical)

    def test_new_and_removed_factory(self):
        old = snap([("F-1", "A", "100"), ("F-2", "B", "200")])
        new = snap([("F-1", "A", "100"), ("F-3", "C", "300")])
        d = compare(old, new)
        self.assertEqual(list(d.new.FACTORY_ID), ["F-3"])
        self.assertEqual(list(d.removed.FACTORY_ID), ["F-2"])

    def test_vendor_moved_between_factories(self):
        old = snap([("F-1", "A", "100"), ("F-1", "A", "101"), ("F-2", "B", "200")])
        new = snap([("F-1", "A", "100"), ("F-2", "B", "200"), ("F-2", "B", "101")])
        d = compare(old, new)
        self.assertEqual(d.moved, [("101", "F-1", "F-2")])
        self.assertEqual(d.vendor_removed, {"F-1": ["101"]})
        self.assertEqual(d.vendor_added, {"F-2": ["101"]})
        self.assertIn("moved", d.summary())

    def test_snapshots_sorted_by_name_date(self):
        with tempfile.TemporaryDirectory() as t:
            for n in ["master_list_2026-11-04-1741.csv", "master_list_2026-10-09-1015.csv", "other.csv"]:
                (Path(t) / n).write_text("FACTORY_ID\n")
            labels = [l for l, _ in find_snapshots(Path(t))]
            self.assertEqual(labels, ["2026-10-09-1015", "2026-11-04-1741"])


if __name__ == "__main__":
    unittest.main()
