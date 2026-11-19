WITH monthly_totals AS (
  SELECT 
    DATE_TRUNC('MONTH', PostingDate) AS month,
    CompanyCode,
    ROUND(SUM(AmountInGlobalCurrency), 2) AS monthly_total
  FROM bdc_share_cash_flow.cashflow.cashflow
  WHERE PostingDate >= '2025-01-01'
  GROUP BY month, CompanyCode
),
baseline AS (
  SELECT 
    CompanyCode,
    ROUND(AVG(monthly_total), 2) AS avg_monthly,
    ROUND(STDDEV(monthly_total), 2) AS stddev_monthly
  FROM monthly_totals
  GROUP BY CompanyCode
)
SELECT 
  m.month,
  m.CompanyCode,
  m.monthly_total,
  b.avg_monthly,
  ROUND((m.monthly_total - b.avg_monthly) / NULLIF(b.stddev_monthly, 0), 2) AS z_score,
  ai_query(
    'databricks-meta-llama-3-3-70b-instruct',
    CONCAT('Company ', m.CompanyCode, ' had ', m.monthly_total, ' EUR in ', m.month, 
           '. Its average is ', b.avg_monthly, ' with stddev ', b.stddev_monthly, 
           '. Given this baseline, is this value anomalous? Answer in one sentence.')
  ) AS grounded_insight
FROM monthly_totals m
JOIN baseline b ON m.CompanyCode = b.CompanyCode
ORDER BY m.month DESC
LIMIT 12;