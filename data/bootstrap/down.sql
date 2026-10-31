-- Fixed target guard. Execute only with the fail-fast provision runner.
SELECT IF(VERSION() REGEXP '^8[.]4[.]' AND @@port = 3307
 AND LOWER(TRIM(TRAILING '/' FROM REPLACE(@@datadir, CHAR(92), '/')))
 = 'd:/riskcontroldemo/mysql84/data',
 1, JSON_EXTRACT('DA01_TARGET_MISMATCH', '$')) AS target_guard;

-- SAFE DEFAULT: inventory only. No executable destructive statements.
SELECT 'NO CHANGES: separate explicit teardown approval required' AS teardown_status;
SELECT schema_name FROM information_schema.schemata
WHERE schema_name IN ('rc_demo_biz','rc_demo_report','rc_demo_audit');
SELECT table_schema, COUNT(*) AS object_count FROM information_schema.tables
WHERE table_schema IN ('rc_demo_biz','rc_demo_report','rc_demo_audit')
GROUP BY table_schema;
-- After separate approval, recheck target, emptiness and ownership.
-- Prepare a reviewed inverse for the six identities and three EMPTY schemas.
-- Never remove any service or directory from SQL. Do not auto-run cleanup.
-- Review-only inverse order, NOT executable or approved by this file:
-- 1. Disconnect Demo runtime clients and confirm no dependent sessions/jobs.
-- 2. Remove rc_demo_app, rc_demo_reader, rc_demo_audit_writer at localhost.
-- 3. Remove rc_role_app, rc_role_reader, rc_role_audit_writer at localhost.
-- 4. Remove rc_demo_biz, rc_demo_report, rc_demo_audit ONLY if still empty.
-- No account removal if its ownership or grants differ from this bootstrap.
