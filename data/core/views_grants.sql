-- Apply only through an approved guarded migration after all core tables exist.

CREATE SQL SECURITY DEFINER VIEW `rc_demo_biz`.`v_staff_user` AS SELECT `id` AS `id`, CONCAT(LEFT(`name`,1),'***') AS `name`, `role` AS `role`, `status` AS `status` FROM `rc_demo_biz`.`staff_user`;

GRANT SELECT, INSERT, UPDATE ON `rc_demo_biz`.`staff_user` TO 'rc_role_app'@'localhost';

GRANT SELECT ON `rc_demo_biz`.`v_staff_user` TO 'rc_role_reader'@'localhost';

CREATE SQL SECURITY DEFINER VIEW `rc_demo_biz`.`v_file_obj` AS SELECT `id` AS `id`, `sha256` AS `sha256`, `mime` AS `mime`, `carrier` AS `carrier`, `width` AS `width`, `height` AS `height`, `pages` AS `pages`, `has_text_layer` AS `has_text_layer`, NULL AS `storage_path` FROM `rc_demo_biz`.`file_obj`;

GRANT SELECT, INSERT, UPDATE ON `rc_demo_biz`.`file_obj` TO 'rc_role_app'@'localhost';

GRANT SELECT ON `rc_demo_biz`.`v_file_obj` TO 'rc_role_reader'@'localhost';

CREATE SQL SECURITY DEFINER VIEW `rc_demo_biz`.`v_task` AS SELECT `id` AS `id`, `biz_no` AS `biz_no`, `task_type` AS `task_type`, `channel` AS `channel`, `file_id` AS `file_id`, `carrier` AS `carrier`, `template_id` AS `template_id`, `template_version` AS `template_version`, `status` AS `status`, NULL AS `check_result`, `period_start` AS `period_start`, `period_end` AS `period_end`, NULL AS `hits` FROM `rc_demo_biz`.`task`;

GRANT SELECT, INSERT, UPDATE ON `rc_demo_biz`.`task` TO 'rc_role_app'@'localhost';

GRANT SELECT ON `rc_demo_biz`.`v_task` TO 'rc_role_reader'@'localhost';

CREATE SQL SECURITY DEFINER VIEW `rc_demo_biz`.`v_bank_account` AS SELECT `id` AS `id`, `task_id` AS `task_id`, CASE WHEN account_no IS NULL THEN NULL WHEN CHAR_LENGTH(account_no)<=8 THEN REPEAT('*',CHAR_LENGTH(account_no)) ELSE CONCAT(LEFT(account_no,4),REPEAT('*',CHAR_LENGTH(account_no)-8),RIGHT(account_no,4)) END AS `account_no`, `bank_name` AS `bank_name`, `period_start` AS `period_start`, `period_end` AS `period_end`, `opening_balance` AS `opening_balance`, `closing_balance` AS `closing_balance` FROM `rc_demo_biz`.`bank_account`;

GRANT SELECT, INSERT, UPDATE ON `rc_demo_biz`.`bank_account` TO 'rc_role_app'@'localhost';

GRANT SELECT ON `rc_demo_biz`.`v_bank_account` TO 'rc_role_reader'@'localhost';

CREATE SQL SECURITY DEFINER VIEW `rc_demo_biz`.`v_txn` AS SELECT `id` AS `id`, `task_id` AS `task_id`, `account_id` AS `account_id`, `txn_date` AS `txn_date`, `direction` AS `direction`, `amount` AS `amount`, `balance` AS `balance`, NULL AS `summary`, CONCAT(LEFT(`counterparty_name`,1),'***') AS `counterparty_name`, `page_no` AS `page_no` FROM `rc_demo_biz`.`txn`;

GRANT SELECT, INSERT, UPDATE ON `rc_demo_biz`.`txn` TO 'rc_role_app'@'localhost';

GRANT SELECT ON `rc_demo_biz`.`v_txn` TO 'rc_role_reader'@'localhost';

CREATE SQL SECURITY DEFINER VIEW `rc_demo_report`.`v_metric_value` AS SELECT `id` AS `id`, `task_id` AS `task_id`, `metric_code` AS `metric_code`, `metric_name` AS `metric_name`, `value_num` AS `value_num`, `unit` AS `unit`, NULL AS `note`, `caliber_version` AS `caliber_version` FROM `rc_demo_report`.`metric_value`;

GRANT SELECT, INSERT ON `rc_demo_report`.`metric_value` TO 'rc_role_app'@'localhost';

GRANT SELECT ON `rc_demo_report`.`v_metric_value` TO 'rc_role_reader'@'localhost';

CREATE SQL SECURITY DEFINER VIEW `rc_demo_report`.`v_report` AS SELECT `id` AS `id`, `task_id` AS `task_id`, `version` AS `version`, `carrier` AS `carrier`, `verdict` AS `verdict`, NULL AS `layers`, NULL AS `limitations`, NULL AS `evidence` FROM `rc_demo_report`.`report`;

GRANT SELECT, INSERT ON `rc_demo_report`.`report` TO 'rc_role_app'@'localhost';

GRANT SELECT ON `rc_demo_report`.`v_report` TO 'rc_role_reader'@'localhost';

CREATE SQL SECURITY DEFINER VIEW `rc_demo_biz`.`v_template` AS SELECT `id` AS `id`, `bank_code` AS `bank_code`, `version` AS `version`, `status` AS `status`, NULL AS `field_map` FROM `rc_demo_biz`.`template`;

GRANT SELECT, INSERT ON `rc_demo_biz`.`template` TO 'rc_role_app'@'localhost';

GRANT SELECT ON `rc_demo_biz`.`v_template` TO 'rc_role_reader'@'localhost';

CREATE SQL SECURITY DEFINER VIEW `rc_demo_biz`.`v_rule` AS SELECT `id` AS `id`, `rule_code` AS `rule_code`, `version` AS `version`, `category` AS `category`, NULL AS `expr`, NULL AS `threshold` FROM `rc_demo_biz`.`rule`;

GRANT SELECT, INSERT ON `rc_demo_biz`.`rule` TO 'rc_role_app'@'localhost';

GRANT SELECT ON `rc_demo_biz`.`v_rule` TO 'rc_role_reader'@'localhost';

CREATE SQL SECURITY DEFINER VIEW `rc_demo_biz`.`v_appeal` AS SELECT `id` AS `id`, `task_id` AS `task_id`, `txn_id` AS `txn_id`, `status` AS `status`, NULL AS `resolution` FROM `rc_demo_biz`.`appeal`;

GRANT SELECT, INSERT, UPDATE ON `rc_demo_biz`.`appeal` TO 'rc_role_app'@'localhost';

GRANT SELECT ON `rc_demo_biz`.`v_appeal` TO 'rc_role_reader'@'localhost';

CREATE SQL SECURITY DEFINER VIEW `rc_demo_audit`.`v_audit_log` AS SELECT `id` AS `id`, `actor_id` AS `actor_id`, `action` AS `action`, `object_type` AS `object_type`, `object_id` AS `object_id`, `created_at` AS `created_at` FROM `rc_demo_audit`.`audit_log`;

GRANT INSERT ON rc_demo_audit.audit_log TO 'rc_role_audit_writer'@'localhost';
