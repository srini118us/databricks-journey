-- ============================================================
-- Phase 5: Govern. Classification, masking, least privilege, lineage.
-- Runs on the gold schema. Run all, then the verification SELECT shows the mask working.
-- ============================================================

-- 1. CLASSIFICATION. Know what the data is: layer, class, certification.
ALTER TABLE workspace.gold.lfa1_supplier        SET TAGS ('layer' = 'gold', 'data_class' = 'synthetic_supplier', 'certified' = 'true');
ALTER TABLE workspace.gold.mara_material         SET TAGS ('layer' = 'gold', 'data_class' = 'real_material', 'certified' = 'true');
ALTER TABLE workspace.gold.kg_supplier_material  SET TAGS ('layer' = 'gold', 'data_class' = 'derived_graph_edge', 'certified' = 'true');
ALTER TABLE workspace.gold.kg_substitute         SET TAGS ('layer' = 'gold', 'data_class' = 'derived_graph_edge');
ALTER TABLE workspace.gold.lfa1_supplier ALTER COLUMN supplier_name SET TAGS ('sensitivity' = 'confidential');

-- 2. MASKING. Supplier identity is the sensitive piece. A privileged group sees the
--    real name, everyone else sees REDACTED. The policy lives in Unity Catalog, enforced at read time.
CREATE OR REPLACE FUNCTION workspace.gold.mask_supplier_name(name STRING)
RETURNS STRING
RETURN CASE WHEN is_account_group_member('procurement_admins') THEN name ELSE 'REDACTED' END;

ALTER TABLE workspace.gold.lfa1_supplier       ALTER COLUMN supplier_name SET MASK workspace.gold.mask_supplier_name;
ALTER TABLE workspace.gold.kg_supplier_material ALTER COLUMN supplier_name SET MASK workspace.gold.mask_supplier_name;

-- 3. VERIFY the mask. Not a member of procurement_admins, so supplier_name returns REDACTED.
SELECT supplier_id, supplier_name, country
FROM workspace.gold.lfa1_supplier
LIMIT 5;

-- 4. LEAST PRIVILEGE (pattern). Grant only read on the graph to an analyst group.
--    Uncomment once the group exists; this mirrors the run capable token at the gateway.
-- GRANT SELECT ON TABLE workspace.gold.kg_supplier_material TO `analysts`;
-- GRANT SELECT ON TABLE workspace.gold.lfa1_supplier        TO `analysts`;

-- 5. LINEAGE. Already captured by Unity Catalog, no SQL needed.
--    Catalog Explorer, open gold.kg_supplier_material, Lineage tab, to see
--    bronze to silver to gold to the graph to the Genie space, end to end.

-- To revert the mask after the screenshot:
-- ALTER TABLE workspace.gold.lfa1_supplier       ALTER COLUMN supplier_name DROP MASK;
-- ALTER TABLE workspace.gold.kg_supplier_material ALTER COLUMN supplier_name DROP MASK;
