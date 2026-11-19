-- ============================================================
-- Phase 2b: Supplier risk questions as graph traversals on the gold knowledge graph
-- Each is a self join across edges, which is how a relational store walks a graph.
-- Run each separately in the Databricks SQL editor and read the result.
-- ============================================================

-- Q1. Concentration risk: materials supplied by exactly one supplier (single sourced).
--     A metric view totals spend; it cannot count distinct suppliers per material and filter.
SELECT count(*) AS single_sourced_materials
FROM (
  SELECT material_id
  FROM workspace.gold.kg_supplier_material
  GROUP BY material_id
  HAVING count(DISTINCT supplier_id) = 1
);

-- Q1b. The single sourced materials with their only supplier and its country.
SELECT k.material_description, k.supplier_name, k.country
FROM workspace.gold.kg_supplier_material k
JOIN (
  SELECT material_id
  FROM workspace.gold.kg_supplier_material
  GROUP BY material_id
  HAVING count(DISTINCT supplier_id) = 1
) ss ON k.material_id = ss.material_id
ORDER BY k.country, k.material_description
LIMIT 25;

-- Q2. Geographic risk: materials whose every supplier is outside the US.
SELECT m.material_description, collect_set(m.country) AS supplier_countries
FROM workspace.gold.kg_supplier_material m
GROUP BY m.material_id, m.material_description
HAVING sum(CASE WHEN m.country = 'US' THEN 1 ELSE 0 END) = 0
ORDER BY m.material_description
LIMIT 25;

-- Q3. Single point of failure: which supplier, if it failed, leaves the most
--     materials with no other direct source. Ranks the disruption impact.
WITH single_src AS (
  SELECT material_id, min(supplier_id) AS sole_supplier
  FROM workspace.gold.kg_supplier_material
  GROUP BY material_id
  HAVING count(DISTINCT supplier_id) = 1
)
SELECT s.supplier_name, s.country, count(*) AS materials_at_risk_if_fails
FROM single_src ss
JOIN workspace.gold.lfa1_supplier s ON ss.sole_supplier = s.supplier_id
GROUP BY s.supplier_name, s.country
ORDER BY materials_at_risk_if_fails DESC
LIMIT 10;

-- Q4. The three hop alternative sourcing path. For each material that is single
--     sourced to Delta, walk: material -> substitute material -> a supplier of that
--     substitute. This is the question flat analytics cannot reach, and where the
--     substitute relationship earns its place. Swap the supplier name to test others.
WITH single_src AS (
  SELECT material_id, material_description, min(supplier_id) AS sole_supplier
  FROM workspace.gold.kg_supplier_material
  GROUP BY material_id, material_description
  HAVING count(DISTINCT supplier_id) = 1
)
SELECT
  ss.material_description      AS at_risk_material,
  sub.substitute_description   AS substitute_material,
  alt.supplier_name            AS alternative_supplier,
  alt.country                  AS alt_country
FROM single_src ss
JOIN workspace.gold.lfa1_supplier failing ON ss.sole_supplier = failing.supplier_id
JOIN workspace.gold.kg_substitute sub      ON ss.material_id = sub.material_id
JOIN workspace.gold.kg_supplier_material alt ON sub.substitute_id = alt.material_id
WHERE failing.supplier_name = 'Delta Aggregates LLC'
  AND alt.supplier_id <> ss.sole_supplier
ORDER BY at_risk_material, alternative_supplier
LIMIT 25;
