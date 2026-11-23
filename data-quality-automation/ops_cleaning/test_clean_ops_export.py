import unittest

import pandas as pd

from clean_ops_export import clean, HEADER_MAP


def ops(rows):
    return pd.DataFrame(rows, columns=["Location", "Location Type", "YearMonth", "Question", "Value"])


MAPPING = pd.DataFrame({"Source Name": ["Alpha - Line 1", "Alpha - Line 2", "Beta - Line 1"],
                        "Factory ID": ["F-1", "F-1", "F-2"]})


class CleanTest(unittest.TestCase):
    def test_owned_plants_dropped_and_lines_summed(self):
        df = ops([
            ("Alpha - Line 1", "Co-manufacturer", 202401, "Volume (units)", 100),
            ("Alpha - Line 2", "Co-manufacturer", 202401, "Volume (units)", 50),
            ("Owned Plant - Line 1", "Owned", 202401, "Volume (units)", 999),
        ])
        vol, _, issues = clean(df, MAPPING, {"F-1"}, set())
        self.assertEqual(vol.units.tolist(), [150])
        self.assertTrue(issues["Unmapped names"].empty)  # owned plant is filtered before mapping

    def test_missing_month_is_padded(self):
        df = ops([
            ("Alpha - Line 1", "Co-manufacturer", 202401, "Volume (units)", 100),
            ("Alpha - Line 1", "Co-manufacturer", 202403, "Volume (units)", 100),
        ])
        vol, _, issues = clean(df, MAPPING, {"F-1"}, set())
        self.assertEqual(len(vol), 3)
        self.assertEqual(issues["Missing reports"].month.astype(str).tolist(), ["2024-02"])

    def test_unmapped_name_reported(self):
        df = ops([("Gamma - Line 1", "Joint venture", 202401, "Volume (units)", 10)])
        _, _, issues = clean(df, MAPPING, set(), set())
        self.assertEqual(issues["Unmapped names"].Location.tolist(), ["Gamma - Line 1"])

    def test_subtotal_above_total_flagged(self):
        df = ops([
            ("Beta - Line 1", "Joint venture", 202401, "Complaints - total", 3),
            ("Beta - Line 1", "Joint venture", 202401, "Complaints - manufacturing", 5),
            ("Beta - Line 1", "Joint venture", 202401, "Complaints - packaging", 0),
        ])
        _, cc, issues = clean(df, MAPPING, set(), {"F-2"})
        self.assertEqual(len(issues["Consistency"]), 1)

    def test_header_variants_map_to_same_name(self):
        self.assertEqual(HEADER_MAP["type"], HEADER_MAP["partner type"])
        self.assertEqual(HEADER_MAP["cert. expiry"], HEADER_MAP["certificate expiry"])


if __name__ == "__main__":
    unittest.main()
