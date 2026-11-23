-- Monthly customer retention by acquisition cohort (Databricks / Spark SQL).
-- Input: first_look_lines (product sales and cancellations after integrity checks),
-- written by databricks/first_look_notebook.py.
-- Matches src/firstlook/cohorts.py: cohorts from SALES only; month 0 = 100%.

WITH sales AS (
  SELECT customer_id, invoice, DATE_TRUNC('MONTH', invoice_date) AS order_month
  FROM first_look_lines
  WHERE kind = 'sale' AND customer_id IS NOT NULL
    AND invoice_date < '2011-12-01'                     -- drop the partial final month
),
cohorts AS (
  SELECT customer_id, MIN(order_month) AS cohort_month
  FROM sales
  GROUP BY customer_id
),
activity AS (
  SELECT DISTINCT s.customer_id, c.cohort_month,
         CAST(MONTHS_BETWEEN(s.order_month, c.cohort_month) AS INT) AS month_number
  FROM sales s
  JOIN cohorts c USING (customer_id)
),
counts AS (
  SELECT cohort_month, month_number, COUNT(DISTINCT customer_id) AS active_customers
  FROM activity
  GROUP BY cohort_month, month_number
)
SELECT cohort_month,
       month_number,
       active_customers,
       ROUND(active_customers / FIRST_VALUE(active_customers)
             OVER (PARTITION BY cohort_month ORDER BY month_number), 4) AS retention
FROM counts
ORDER BY cohort_month, month_number;
