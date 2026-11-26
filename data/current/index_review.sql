-- DA-22 proposal only. Check SHOW INDEX before applying; MySQL DDL auto-commits.
-- Not included in current/schema.sql because these are additional optimizations.
CREATE INDEX ix_txn_task_date_id ON txn (task_id, txn_date, id);
CREATE INDEX ix_metric_task_code ON metric_value (task_id, metric_code);
CREATE INDEX ix_report_task_version ON report (task_id, version);
-- Reverse order after approval, if and only if added by this revision:
-- DROP INDEX ix_report_task_version ON report;
-- DROP INDEX ix_metric_task_code ON metric_value;
-- DROP INDEX ix_txn_task_date_id ON txn;
