-- ============================================================
-- Phase 1: Medallion ingestion for the real procurement data
-- Run in the Databricks SQL editor or a SQL notebook, top to bottom.
-- Catalog: workspace   Layers as schemas: bronze, silver, gold
-- ============================================================

-- 0. One schema per medallion layer
CREATE SCHEMA IF NOT EXISTS workspace.bronze;
CREATE SCHEMA IF NOT EXISTS workspace.silver;
CREATE SCHEMA IF NOT EXISTS workspace.gold;

-- 0a. A Volume to land the raw file. Upload the CSV here first (see the UI steps).
CREATE VOLUME IF NOT EXISTS workspace.bronze.raw_files;

-- ============================================================
-- 1. BRONZE: raw landing. Everything stays string, nothing cleaned.
--    Immutable and replayable. This is the audit copy of what arrived.
-- ============================================================
CREATE OR REPLACE TABLE workspace.bronze.po_raw AS
SELECT *
FROM read_files(
  '/Volumes/workspace/bronze/raw_files/br_purchase_orders_num.csv',
  format      => 'csv',
  header      => true,
  inferSchema => false      -- keep raw as string; typing belongs in silver
);

-- ============================================================
-- 2. SILVER: cleaned and typed. The single place data quality is fixed.
-- ============================================================
CREATE OR REPLACE TABLE workspace.silver.po_line AS
SELECT DISTINCT
  trim(`DOCUMENT NUMBER`)                        AS po_number,
  trim(`REQUISITION NUMBER`)                     AS requisition_number,
  upper(trim(`ITEM DESCRIPTION`))                AS material_description,
  try_cast(`INPUT DATE` AS date)                 AS po_date,
  trim(`DEPARTMENT NAME`)                        AS department,
  trim(`COST CENTER NAME`)                       AS cost_center,
  try_cast(`ITEM NUMBER` AS int)                 AS line_number,
  try_cast(`ITEM QUANTITY ORDERED` AS double)    AS quantity,
  trim(`ITEM UNIT OF MEASURE`)                   AS uom,
  try_cast(`ITEM UNIT COST` AS double)           AS unit_cost,
  try_cast(`ITEM TOTAL COST` AS double)          AS line_total,
  CASE
    WHEN upper(`ITEM DESCRIPTION`) LIKE '%CEMENT%'
      OR upper(`ITEM DESCRIPTION`) LIKE '%AGGREGATE%'
      OR upper(`ITEM DESCRIPTION`) LIKE '%ASH%'
      OR upper(`ITEM DESCRIPTION`) LIKE '%STAKE%'     THEN 'Construction Materials'
    WHEN upper(`ITEM DESCRIPTION`) LIKE '%PIPE%'
      OR upper(`ITEM DESCRIPTION`) LIKE '%VALVE%'     THEN 'Plumbing'
    WHEN upper(`ITEM DESCRIPTION`) LIKE '%WIRE%'
      OR upper(`ITEM DESCRIPTION`) LIKE '%ELECTRIC%'  THEN 'Electrical'
    ELSE 'Other'
  END                                            AS commodity_category
FROM workspace.bronze.po_raw
WHERE `DOCUMENT NUMBER` IS NOT NULL
  AND `ITEM DESCRIPTION` IS NOT NULL;

-- ============================================================
-- 3. GOLD: business ready, stable contracts the semantic layer and graph trust.
-- ============================================================

-- 3a. Material dimension (MARA shaped). Surrogate id by distinct description,
--     numbered from MAT100000 to match the series scheme.
CREATE OR REPLACE TABLE workspace.gold.mara_material AS
SELECT
  concat('MAT', lpad(cast(dense_rank() OVER (ORDER BY material_description) + 99999 AS string), 6, '0')) AS material_id,
  material_description,
  max(commodity_category)   AS commodity_category,
  max(uom)                  AS base_uom,
  round(avg(unit_cost), 2)  AS avg_unit_cost
FROM workspace.silver.po_line
GROUP BY material_description;

-- 3b. PO line fact (EKPO shaped), joined to the material id.
CREATE OR REPLACE TABLE workspace.gold.ekpo_po_line AS
SELECT
  concat(s.po_number, '-', cast(s.line_number AS string)) AS po_line_id,
  s.po_number,
  s.line_number,
  m.material_id,
  s.material_description,
  s.quantity,
  s.uom,
  s.unit_cost,
  s.line_total,
  s.commodity_category,
  s.department,
  s.cost_center,
  s.po_date,
  s.requisition_number
FROM workspace.silver.po_line s
JOIN workspace.gold.mara_material m
  ON s.material_description = m.material_description;

-- ============================================================
-- 4. Quick checks (each should return sensible counts)
-- ============================================================
SELECT 'bronze.po_raw'      AS layer, count(*) AS rows FROM workspace.bronze.po_raw
UNION ALL SELECT 'silver.po_line',      count(*) FROM workspace.silver.po_line
UNION ALL SELECT 'gold.mara_material',  count(*) FROM workspace.gold.mara_material
UNION ALL SELECT 'gold.ekpo_po_line',   count(*) FROM workspace.gold.ekpo_po_line;
