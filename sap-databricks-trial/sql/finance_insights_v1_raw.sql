-- Anomaly detection: ask LLM to flag suspicious months
WITH monthly_totals AS (
  SELECT 
    DATE_TRUNC('MONTH', PostingDate) AS month,
    CompanyCode,
    ROUND(SUM(AmountInGlobalCurrency), 2) AS monthly_total
  FROM bdc_share_cash_flow.cashflow.cashflow
  WHERE PostingDate >= '2025-01-01'
  GROUP BY month, CompanyCode
)
SELECT 
  month,
  CompanyCode,
  monthly_total,
  ai_query(
    'databricks-meta-llama-3-3-70b-instruct',
    CONCAT('Company ', CompanyCode, ' had ', monthly_total, ' EUR in ', month, '. Rate this from 1-5 how anomalous this is for a corporate cash flow. Answer with just the number and one sentence why.')
  ) AS anomaly_score
FROM monthly_totals
ORDER BY month DESC, CompanyCode
LIMIT 12;