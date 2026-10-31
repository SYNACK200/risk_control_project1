-- Fixed target guard. Execute only with the fail-fast provision runner.
SELECT IF(VERSION() REGEXP '^8[.]4[.]' AND @@port = 3307
 AND LOWER(TRIM(TRAILING '/' FROM REPLACE(@@datadir, CHAR(92), '/')))
 = 'd:/riskcontroldemo/mysql84/data',
 1, JSON_EXTRACT('DA01_TARGET_MISMATCH', '$')) AS target_guard;

SELECT CURRENT_USER() AS matched_account, CURRENT_ROLE() AS active_role;
SHOW GRANTS;
-- Does not claim table/view permission verification.
