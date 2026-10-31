-- Fixed target guard. Execute only with the fail-fast provision runner.
SELECT IF(VERSION() REGEXP '^8[.]4[.]' AND @@port = 3307
 AND LOWER(TRIM(TRAILING '/' FROM REPLACE(@@datadir, CHAR(92), '/')))
 = 'd:/riskcontroldemo/mysql84/data',
 1, JSON_EXTRACT('DA01_TARGET_MISMATCH', '$')) AS target_guard;

-- Repeated initialization requires matching empty schemas.
SELECT IF(COUNT(*) = 0, 1, JSON_EXTRACT('DA01_SCHEMA_MISMATCH', '$'))
FROM information_schema.schemata
WHERE schema_name IN ('rc_demo_biz','rc_demo_report','rc_demo_audit')
 AND (default_character_set_name <> 'utf8mb4'
 OR default_collation_name <> 'utf8mb4_0900_ai_ci');
SELECT IF(COUNT(*) = 0, 1, JSON_EXTRACT('DA01_EXPECT_EMPTY_SCHEMAS', '$'))
FROM information_schema.tables
WHERE table_schema IN ('rc_demo_biz','rc_demo_report','rc_demo_audit');
CREATE DATABASE IF NOT EXISTS rc_demo_biz
 CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci;
CREATE DATABASE IF NOT EXISTS rc_demo_report
 CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci;
CREATE DATABASE IF NOT EXISTS rc_demo_audit
 CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci;
CREATE ROLE IF NOT EXISTS 'rc_role_app'@'localhost',
 'rc_role_reader'@'localhost', 'rc_role_audit_writer'@'localhost';
-- No schema/table privileges before DA-02.
