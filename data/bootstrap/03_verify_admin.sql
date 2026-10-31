-- Fixed target guard. Execute only with the fail-fast provision runner.
SELECT IF(VERSION() REGEXP '^8[.]4[.]' AND @@port = 3307
 AND LOWER(TRIM(TRAILING '/' FROM REPLACE(@@datadir, CHAR(92), '/')))
 = 'd:/riskcontroldemo/mysql84/data',
 1, JSON_EXTRACT('DA01_TARGET_MISMATCH', '$')) AS target_guard;

SELECT IF(COUNT(*) = 3, 1, JSON_EXTRACT('DA01_SCHEMA_COUNT_OR_CHARSET', '$'))
FROM information_schema.schemata
WHERE schema_name IN ('rc_demo_biz','rc_demo_report','rc_demo_audit')
 AND default_character_set_name = 'utf8mb4'
 AND default_collation_name = 'utf8mb4_0900_ai_ci';
SELECT IF(COUNT(*) = 0, 1, JSON_EXTRACT('DA01_EXPECT_EMPTY_SCHEMAS', '$'))
FROM information_schema.tables
WHERE table_schema IN ('rc_demo_biz','rc_demo_report','rc_demo_audit');
SELECT schema_name, default_character_set_name, default_collation_name
FROM information_schema.schemata
WHERE schema_name IN ('rc_demo_biz','rc_demo_report','rc_demo_audit')
ORDER BY schema_name;
-- Never read authentication_string or SHOW CREATE USER.
SELECT user, host, account_locked FROM mysql.user
WHERE user IN ('rc_role_app','rc_role_reader','rc_role_audit_writer',
 'rc_demo_app','rc_demo_reader','rc_demo_audit_writer')
ORDER BY user, host;
-- Runner also asserts exact grants, role edges and default roles.
