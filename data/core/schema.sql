-- OFFLINE DEMO DDL. Execute only after approved instance verification.
SET SESSION time_zone = '+08:00';

CREATE TABLE `rc_demo_biz`.`staff_user` (
  `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `name` VARCHAR(255) NULL,
  `role` VARCHAR(255) NULL,
  `status` VARCHAR(255) NULL,
  PRIMARY KEY (`id`),
  CHECK (`role` IN ('审批人','模板管理员','运营管理员','系统管理员')),
  CHECK (`name` IS NULL OR REGEXP_LIKE(`name`, '^.[*]+$'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE `rc_demo_biz`.`file_obj` (
  `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `sha256` CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  `mime` VARCHAR(255) NULL,
  `carrier` VARCHAR(255) NULL,
  `width` INT UNSIGNED NULL,
  `height` INT UNSIGNED NULL,
  `pages` INT UNSIGNED NULL,
  `has_text_layer` BOOLEAN NULL,
  `storage_path` TEXT NULL,
  PRIMARY KEY (`id`),
  CHECK (`carrier` IN ('electronic','image','screenshot')),
  UNIQUE KEY uq_file_sha256 (`sha256`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE `rc_demo_biz`.`task` (
  `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `biz_no` VARCHAR(255) NOT NULL,
  `task_type` VARCHAR(255) NULL,
  `channel` VARCHAR(255) NULL,
  `file_id` BIGINT UNSIGNED NULL,
  `carrier` VARCHAR(255) NULL,
  `template_id` BIGINT UNSIGNED NULL,
  `template_version` INT UNSIGNED NULL,
  `status` VARCHAR(255) NULL,
  `check_result` JSON NULL,
  `period_start` DATETIME(6) NULL,
  `period_end` DATETIME(6) NULL,
  `hits` JSON NULL,
  PRIMARY KEY (`id`),
  CHECK (`carrier` IN ('electronic','image','screenshot')),
  CHECK (`task_type` IN ('credit','batch')),
  UNIQUE KEY uq_task_biz_no (`biz_no`),
  KEY ix_task_status (`status`, `id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE `rc_demo_biz`.`bank_account` (
  `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `task_id` BIGINT UNSIGNED NULL,
  `account_no` VARCHAR(255) NULL,
  `bank_name` VARCHAR(255) NULL,
  `period_start` DATETIME(6) NULL,
  `period_end` DATETIME(6) NULL,
  `opening_balance` DECIMAL(18,2) NULL,
  `closing_balance` DECIMAL(18,2) NULL,
  PRIMARY KEY (`id`),
  CHECK (`account_no` IS NULL OR REGEXP_LIKE(`account_no`, '^[0-9]{4}[*]+[0-9]{4}$|^[*]{1,8}$'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE `rc_demo_biz`.`txn` (
  `id` BIGINT UNSIGNED NOT NULL,
  `task_id` BIGINT UNSIGNED NULL,
  `account_id` BIGINT UNSIGNED NULL,
  `txn_date` DATETIME(6) NOT NULL,
  `direction` VARCHAR(255) NULL,
  `amount` DECIMAL(18,2) NOT NULL,
  `balance` DECIMAL(18,2) NULL,
  `summary` TEXT NULL,
  `counterparty_name` VARCHAR(255) NULL,
  `page_no` INT UNSIGNED NULL,
  PRIMARY KEY (`id`, `txn_date`),
  CHECK (`amount` > 0),
  KEY ix_txn_task_date (`task_id`, `txn_date`, `id`),
  CHECK (`counterparty_name` IS NULL OR REGEXP_LIKE(`counterparty_name`, '^.[*]+$'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
PARTITION BY RANGE COLUMNS (`txn_date`) (
 PARTITION p_before VALUES LESS THAN ('2026-10-01'),
 PARTITION p202610 VALUES LESS THAN ('2026-11-01'),
 PARTITION p202611 VALUES LESS THAN ('2026-12-01'),
 PARTITION p202612 VALUES LESS THAN ('2027-01-01'),
 PARTITION p_future VALUES LESS THAN (MAXVALUE)
);

CREATE TABLE `rc_demo_report`.`metric_value` (
  `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `task_id` BIGINT UNSIGNED NULL,
  `metric_code` VARCHAR(255) NULL,
  `metric_name` VARCHAR(255) NULL,
  `value_num` DECIMAL(30,8) NULL,
  `unit` VARCHAR(255) NULL,
  `note` TEXT NULL,
  `caliber_version` INT UNSIGNED NULL,
  PRIMARY KEY (`id`),
  KEY ix_metric_task_code (`task_id`, `metric_code`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE `rc_demo_report`.`report` (
  `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `task_id` BIGINT UNSIGNED NULL,
  `version` INT UNSIGNED NULL,
  `carrier` VARCHAR(255) NULL,
  `verdict` VARCHAR(255) NULL,
  `layers` JSON NULL,
  `limitations` JSON NULL,
  `evidence` JSON NULL,
  PRIMARY KEY (`id`),
  CHECK (`carrier` IN ('electronic','image','screenshot')),
  KEY ix_report_task_version (`task_id`, `version`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE `rc_demo_biz`.`template` (
  `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `bank_code` VARCHAR(255) NULL,
  `version` INT UNSIGNED NULL,
  `status` VARCHAR(255) NULL,
  `field_map` JSON NULL,
  PRIMARY KEY (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE `rc_demo_biz`.`rule` (
  `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `rule_code` VARCHAR(255) NULL,
  `version` INT UNSIGNED NULL,
  `category` VARCHAR(255) NULL,
  `expr` TEXT NULL,
  `threshold` JSON NULL,
  PRIMARY KEY (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE `rc_demo_biz`.`appeal` (
  `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `task_id` BIGINT UNSIGNED NULL,
  `txn_id` BIGINT UNSIGNED NULL,
  `status` VARCHAR(255) NULL,
  `resolution` JSON NULL,
  PRIMARY KEY (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE `rc_demo_audit`.`audit_log` (
  `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `actor_id` BIGINT UNSIGNED NULL,
  `action` VARCHAR(255) NULL,
  `object_type` VARCHAR(255) NULL,
  `object_id` BIGINT UNSIGNED NULL,
  `created_at` DATETIME(6) NULL,
  PRIMARY KEY (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
