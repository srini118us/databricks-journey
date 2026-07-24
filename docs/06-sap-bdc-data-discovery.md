# Use Case 6 — SAP BDC Data Discovery

**Purpose.** The shared foundation for the SAP finance tracks (7-9): find and
profile the SAP data delivered into Databricks via BDC Delta Share, and confirm
write permissions before building anything.

## Files

- `step_0a.ipynb` — `SHOW CATALOGS` to locate the SAP `bdc_share_*` shared data.
- `step_0b.ipynb` — lists schemas/tables in each SAP catalog (`bdc_share_cash_flow`,
  `bdc_share_costcenter`, `bdc_share_customer`, `bdc_share_glaccount`,
  `bdc_share_journal_entry`, `bdc_share_supplier`, `bdc_share_vendorperformance`,
  plus two data-product catalogs).
- `step_0c.ipynb` — `DESCRIBE TABLE` + row counts for the four source tables Lab 1
  builds on (cashflow, cashflowforecast, supplier, vendorperformance).
- `cataflog_identify_with_permission.ipynb` — (filename misspells "catalog") a
  write-permission probe: prints current user/catalog/schema, tests `CREATE TABLE`
  in `workspace.default`.
- `Procurement_Intelligence/01_explore_and_gold.ipynb` — **explore-only** (row
  counts + `DESCRIBE` of vendorperformance & supplier). Despite "and_gold" in the
  name it builds no gold table — the real build is in Use Case 8's
  `01_procurement_gold.ipynb`. Treat this as a superseded stub.

## Outputs

No tables — this is discovery/verification. It establishes which SAP shares exist
and that the workspace can write gold tables into `workspace.default`.
