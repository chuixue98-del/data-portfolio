# Data quality automation

Three small workflows that find data errors before people do. Each one gives the
data owners a simple list of what to fix.

The data is made up. The workflows copy ones I run at work.

| Folder | When | What it does |
|---|---|---|
| `snapshot_check` | after each export | Compares the new factory list with the last one: new factories, removed factories, changed supplier IDs |
| `ops_cleaning` | monthly | Cleans the operations data for Power BI, and lists missing months, unknown names and totals that do not add up |
| `weekly_dq` | every Monday | Power Automate runs a query on the dashboard data and writes the errors to an Excel file in SharePoint |

## How the weekly check works

1. Power Automate starts every Monday at 11:00.
2. It runs a DAX query (`nc_quantity_check.dax`) on the published dashboard.
3. An Office Script (`generate_dq_output.ts`) writes two lists to Excel:
   recalls with no quantity, and recalls with the wrong unit.

`generate_dq_output.py` does the same in Python, as a backup.

## Run it

Each folder has a Python script and a test file. For example:

```
cd ops_cleaning
python clean_ops_export.py
python -m unittest
```
