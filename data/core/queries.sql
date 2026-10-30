-- Four measured paths; replace sample IDs with synthetic fixture IDs only.
EXPLAIN SELECT id FROM rc_demo_biz.task WHERE status='DONE' ORDER BY id LIMIT 20;
EXPLAIN SELECT id,txn_date FROM rc_demo_biz.txn WHERE task_id=1 AND txn_date>='2026-10-01' AND txn_date<'2026-11-01' ORDER BY txn_date,id LIMIT 100;
EXPLAIN SELECT metric_code,value_num FROM rc_demo_report.metric_value WHERE task_id=1 AND metric_code='DEMO' LIMIT 1;
EXPLAIN SELECT version,verdict FROM rc_demo_report.report WHERE task_id=1 ORDER BY version DESC LIMIT 1;
