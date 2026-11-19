-- ============================================================
-- Fix v2: word boundary categories (no substring false positives like FLASHLIGHT
-- matching the "ash" in fly ash). Rebuild material, edge, substitute, re-run 3 hop.
-- Run all.
-- ============================================================

CREATE OR REPLACE TABLE workspace.gold.mara_material AS
SELECT
  concat('MAT', lpad(cast(dense_rank() OVER (ORDER BY material_description) + 99999 AS string), 6, '0')) AS material_id,
  material_description, commodity_category, base_uom, avg_unit_cost
FROM (
  SELECT material_description,
    CASE
      WHEN d RLIKE '\\b(CEMENT|AGGREGATE|ASH|GRAVEL|SAND|CONCRETE|BRICK|LUMBER|REBAR|STAKE|BLOCK|LIMESTONE)\\b' THEN 'Construction Materials'
      WHEN d RLIKE '\\b(PIPE|VALVE|FITTING|HOSE|COUPLING|GASKET|FAUCET|DRAIN|SEWER)\\b'                        THEN 'Plumbing'
      WHEN d RLIKE '\\b(WIRE|ELECTRIC|ELECTRICAL|CABLE|CONDUIT|BREAKER|OUTLET|LAMP|BULB|BATTERY|FLASHLIGHT|FLASHIGHT|LED)\\b' THEN 'Electrical'
      WHEN d RLIKE '\\b(BOOT|BOOTS|GLOVE|GLOVES|HELMET|SAFETY|VEST|GOGGLE|MASK|RESPIRATOR|EYE WASH)\\b'        THEN 'Safety Gear'
      WHEN d RLIKE '\\b(CLEAN|CLEANER|SOLVENT|LYSOL|DAWN|SOAP|DISINFECT|DISINFECTANT|DETERGENT|WIPE|MOP|BROOM|DEODORIZING)\\b' THEN 'Cleaning and Janitorial'
      WHEN d RLIKE '\\b(DRILL|WRENCH|HAMMER|SAW|BLADE|TOOL|TAPE|SHOVEL|SHOVELS)\\b'                            THEN 'Tools'
      WHEN d RLIKE '\\b(BOLT|NUT|SCREW|NAIL|WASHER|ANCHOR|CAP|CAPS)\\b'                                        THEN 'Fasteners'
      WHEN d RLIKE '\\b(CHEMICAL|ACID|LUBRICANT|OIL|GREASE|PAINT|ADHESIVE|SEALANT)\\b'                         THEN 'Chemicals'
      WHEN d RLIKE '\\b(PAPER|PEN|INK|TONER|FOLDER|BINDER)\\b'                                                 THEN 'Office'
      ELSE 'Other'
    END AS commodity_category,
    base_uom, avg_unit_cost
  FROM (
    SELECT material_description, upper(material_description) AS d,
           max(uom) AS base_uom, round(avg(unit_cost), 2) AS avg_unit_cost
    FROM workspace.silver.po_line GROUP BY material_description
  )
);

CREATE OR REPLACE TABLE workspace.gold.kg_supplier_material AS
SELECT DISTINCT
  h.supplier_id, s.supplier_name, s.country,
  l.material_id, m.material_description, m.commodity_category
FROM workspace.gold.ekpo_po_line l
JOIN workspace.gold.ekko_po_header h ON l.po_number = h.po_number
JOIN workspace.gold.lfa1_supplier  s ON h.supplier_id = s.supplier_id
JOIN workspace.gold.mara_material   m ON l.material_id = m.material_id
WHERE l.material_id IS NOT NULL;

CREATE OR REPLACE TABLE workspace.gold.kg_substitute AS
SELECT DISTINCT
  a.material_id, a.material_description,
  b.material_id AS substitute_id, b.material_description AS substitute_description,
  a.commodity_category
FROM workspace.gold.mara_material a
JOIN workspace.gold.mara_material b
  ON a.commodity_category = b.commodity_category AND a.material_id <> b.material_id
WHERE a.commodity_category <> 'Other';

-- Category spread, to confirm most materials now carry a real category
SELECT commodity_category, count(*) AS materials
FROM workspace.gold.mara_material
GROUP BY commodity_category
ORDER BY materials DESC;

-- The three hop alternative sourcing path, cleaned
WITH single_src AS (
  SELECT material_id, material_description, min(supplier_id) AS sole_supplier
  FROM workspace.gold.kg_supplier_material
  GROUP BY material_id, material_description
  HAVING count(DISTINCT supplier_id) = 1
)
SELECT
  fs.supplier_name           AS failing_supplier,
  ss.material_description     AS at_risk_material,
  sub.substitute_description  AS substitute_material,
  alt.supplier_name           AS alternative_supplier,
  alt.country                 AS alt_country
FROM single_src ss
JOIN workspace.gold.lfa1_supplier        fs  ON ss.sole_supplier = fs.supplier_id
JOIN workspace.gold.kg_substitute        sub ON ss.material_id = sub.material_id
JOIN workspace.gold.kg_supplier_material alt ON sub.substitute_id = alt.material_id
WHERE alt.supplier_id <> ss.sole_supplier
ORDER BY failing_supplier, at_risk_material
LIMIT 30;
