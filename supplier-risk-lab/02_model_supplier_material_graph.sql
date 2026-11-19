-- ============================================================
-- Phase 2a: Supplier risk ontology and knowledge graph on gold
-- Builds on Phase 1 gold (mara_material, ekpo_po_line).
-- Classes: Supplier, Material. Relationships: supplies, substitute_for, located_in (country on supplier).
-- Run in the Databricks SQL editor, Run all.
-- ============================================================

-- Synthetic note: the 18 suppliers, their countries, and which supplier fills
-- each PO are synthetic. Delta, Zachary, and BuildRight are kept for continuity
-- with the earlier labs. The hash based assignment means some materials end up
-- single sourced and others gain alternatives, which is what the risk questions need.

-- 1. Supplier class, with country (the located_in relationship folded in as an attribute)
CREATE OR REPLACE TABLE workspace.gold.lfa1_supplier AS
SELECT concat('SUP', cast(1000 + id AS string)) AS supplier_id, name AS supplier_name, country
FROM VALUES
  (0,'Delta Aggregates LLC','US'),
  (1,'Zachary Ready Mix','US'),
  (2,'BuildRight Materials','US'),
  (3,'Gulf Coast Supply','US'),
  (4,'Bayou Procurement Partners','US'),
  (5,'Nortec Industrial','CA'),
  (6,'Maple Valve Works','CA'),
  (7,'Monterrey Materials SA','MX'),
  (8,'Baja Supply Co','MX'),
  (9,'Rhine Fittings GmbH','DE'),
  (10,'Bavaria Components','DE'),
  (11,'Shenzhen Hardware Ltd','CN'),
  (12,'Guangzhou Supply Group','CN'),
  (13,'Voltec Electrical Supply','US'),
  (14,'Pacific Pipe and Valve','US'),
  (15,'Summit Safety Gear','US'),
  (16,'Ironclad Fasteners','US'),
  (17,'Clearwater Chemicals','US')
AS t(id, name, country);

-- 2. PO header (EKKO shaped), one supplier per PO, assigned deterministically
CREATE OR REPLACE TABLE workspace.gold.ekko_po_header AS
SELECT
  po_number,
  concat('SUP', cast(1000 + (abs(hash(po_number)) % 18) AS string)) AS supplier_id,
  min(po_date)        AS po_date,
  max(department)     AS department,
  max(cost_center)    AS cost_center,
  round(sum(line_total), 2) AS po_total_value
FROM workspace.gold.ekpo_po_line
GROUP BY po_number;

-- 3. Knowledge graph edge: supplier supplies material (with country carried for risk)
CREATE OR REPLACE TABLE workspace.gold.kg_supplier_material AS
SELECT DISTINCT
  h.supplier_id, s.supplier_name, s.country,
  l.material_id, l.material_description, l.commodity_category
FROM workspace.gold.ekpo_po_line l
JOIN workspace.gold.ekko_po_header h ON l.po_number = h.po_number
JOIN workspace.gold.lfa1_supplier  s ON h.supplier_id = s.supplier_id
WHERE l.material_id IS NOT NULL;

-- 4. Substitute relationship: materials in the same category can substitute, generic bucket excluded
CREATE OR REPLACE TABLE workspace.gold.kg_substitute AS
SELECT DISTINCT
  a.material_id          AS material_id,
  a.material_description  AS material_description,
  b.material_id          AS substitute_id,
  b.material_description  AS substitute_description,
  a.commodity_category
FROM workspace.gold.mara_material a
JOIN workspace.gold.mara_material b
  ON a.commodity_category = b.commodity_category
 AND a.material_id <> b.material_id
WHERE a.commodity_category <> 'Other';

-- 5. Counts
SELECT 'lfa1_supplier'        AS object, count(*) AS rows FROM workspace.gold.lfa1_supplier
UNION ALL SELECT 'ekko_po_header',       count(*) FROM workspace.gold.ekko_po_header
UNION ALL SELECT 'kg_supplier_material', count(*) FROM workspace.gold.kg_supplier_material
UNION ALL SELECT 'kg_substitute',        count(*) FROM workspace.gold.kg_substitute;
