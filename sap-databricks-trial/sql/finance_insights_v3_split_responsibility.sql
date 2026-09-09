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
),
scored AS (
  SELECT 
    m.month,
    m.CompanyCode,
    m.monthly_total,
    b.avg_monthly,
    ROUND((m.monthly_total - b.avg_monthly) / NULLIF(b.stddev_monthly, 0), 2) AS z_score,
    CASE 
      WHEN ABS((m.monthly_total - b.avg_monthly) / NULLIF(b.stddev_monthly, 0)) >= 2 THEN 'ANOMALY'
      WHEN ABS((m.monthly_total - b.avg_monthly) / NULLIF(b.stddev_monthly, 0)) >= 1 THEN 'WATCH'
      ELSE 'NORMAL'
    END AS classification
  FROM monthly_totals m
  JOIN baseline b ON m.CompanyCode = b.CompanyCode
)
SELECT 
  month,
  CompanyCode,
  monthly_total,
  z_score,
  classification,
  ai_query(
    'databricks-meta-llama-3-3-70b-instruct',
    CONCAT('SAP company code ', CompanyCode, ' had cash flow of ', monthly_total, 
           ' EUR in ', month, ', classified as ', classification, 
           ' (z-score ', z_score, '). In one sentence, what business context might explain this? Do not repeat calculations.')
  ) AS business_context
FROM scored
ORDER BY month DESC
LIMIT 12;