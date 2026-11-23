/**
 * Office Script: build the weekly NC data quality workbook.
 *
 * Called by Power Automate (Excel Online > Run script) right after the DAX query.
 * Inputs come from the flow:
 *   rowsJson  JSON array of the query rows (keys look like "[Record ID]")
 *   runTime   local run time, written to the "Update Info" sheet
 *
 * Sheets written (all rebuilt on every run):
 *   Missing quantity   NC level 4-5 without Quantity Impacted
 *   Wrong unit         Quantity given, but UoM is not "CU" (blank counts as wrong)
 *   Update Info        run time and row counts
 *   Raw Data           every row returned by the query (hidden)
 *
 * If the query returned no rows, nothing is changed: an empty result usually
 * means the dataset failed to refresh, not that the data is perfect.
 */

type Row = { [key: string]: string | number | null };

const COLUMNS = ["Region", "Partner Type", "Partner Name", "Factory ID", "Record ID", "Source",
                 "Date Reported", "NC Level", "Status", "Quantity Impacted", "UoM"];

function clean(row: Row): Row {
  // Power BI returns keys as "Table[Column]" or "[Column]". Keep only the column name.
  const out: Row = {};
  for (const key of Object.keys(row)) {
    const name = key.replace(/^.*\[/, "").replace(/\]$/, "");
    out[name] = row[key];
  }
  return out;
}

function isBlank(v: string | number | null | undefined): boolean {
  return v === null || v === undefined || String(v).trim() === "";
}

function writeSheet(wb: ExcelScript.Workbook, name: string, rows: Row[], note: string): void {
  wb.getWorksheet(name)?.delete();
  const ws = wb.addWorksheet(name);
  ws.getRange("A1").setValue(note);
  ws.getRange("A1").getFormat().getFont().setItalic(true);
  const header = [COLUMNS];
  const body = rows.map(r => COLUMNS.map(c => (isBlank(r[c]) ? "" : r[c]) as string | number));
  const range = ws.getRangeByIndexes(2, 0, 1 + body.length, COLUMNS.length);
  range.setValues([...header, ...body]);
  const table = ws.addTable(range, true);
  table.setName(name.replace(/\W/g, "_"));
  ws.getRange().getFormat().autofitColumns();
}

function main(workbook: ExcelScript.Workbook, rowsJson: string, runTime: string): string {
  const rows: Row[] = (JSON.parse(rowsJson) as Row[]).map(clean);
  if (rows.length === 0) {
    return "No rows returned. Workbook not changed.";
  }

  const missingQty = rows.filter(r => isBlank(r["Quantity Impacted"]));
  const wrongUnit = rows.filter(r => !isBlank(r["Quantity Impacted"]) && String(r["UoM"] ?? "").trim() !== "CU");

  writeSheet(workbook, "Missing quantity", missingQty, "Withdrawals and recalls must report the impacted quantity.");
  writeSheet(workbook, "Wrong unit", wrongUnit, "Quantity impacted must be in consumer units (CU).");
  writeSheet(workbook, "Raw Data", rows, "Query result as received.");
  workbook.getWorksheet("Raw Data").setVisibility(ExcelScript.SheetVisibility.hidden);

  workbook.getWorksheet("Update Info")?.delete();
  const info = workbook.addWorksheet("Update Info");
  info.getRange("A1:B4").setValues([
    ["Last run", runTime],
    ["Rows checked", rows.length],
    ["Missing quantity", missingQty.length],
    ["Wrong unit", wrongUnit.length],
  ]);
  info.getRange("A:B").getFormat().autofitColumns();
  workbook.getWorksheet("Missing quantity").activate();

  return `Checked ${rows.length} rows: ${missingQty.length} missing quantity, ${wrongUnit.length} wrong unit.`;
}
