import unittest

import pandas as pd

from generate_dq_output import check


class CheckTest(unittest.TestCase):
    def rows(self, data):
        # Same header shape as the Power BI query result.
        return pd.DataFrame(data, columns=["[Record ID]", "[Quantity Impacted]", "[UoM]"])

    def test_missing_quantity(self):
        r = check(self.rows([("NC-1", None, None), ("NC-2", 100, "CU")]))
        self.assertEqual(r["Missing quantity"]["Record ID"].tolist(), ["NC-1"])
        self.assertTrue(r["Wrong unit"].empty)

    def test_wrong_or_blank_unit(self):
        r = check(self.rows([("NC-1", 100, "KG"), ("NC-2", 100, None), ("NC-3", 100, " CU ")]))
        self.assertEqual(r["Wrong unit"]["Record ID"].tolist(), ["NC-1", "NC-2"])

    def test_blank_quantity_not_counted_as_wrong_unit(self):
        r = check(self.rows([("NC-1", None, "KG")]))
        self.assertTrue(r["Wrong unit"].empty)


if __name__ == "__main__":
    unittest.main()
