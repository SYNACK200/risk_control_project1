# Demo physical dictionary

Technical proposal, not a replacement for contract.md or PR #3.
Source reviewed: feat/data-schema commit 137e199; no commits merged or copied.
Only 11 tables / 82 existing fields. Business meanings remain in PR #3.

## staff_user

| Field | Physical definition |
| --- | --- |
| id | BIGINT UNSIGNED NOT NULL AUTO_INCREMENT |
| name | VARCHAR(255) NULL |
| role | VARCHAR(255) NULL |
| status | VARCHAR(255) NULL |

## file_obj

| Field | Physical definition |
| --- | --- |
| id | BIGINT UNSIGNED NOT NULL AUTO_INCREMENT |
| sha256 | CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL |
| mime | VARCHAR(255) NULL |
| carrier | VARCHAR(255) NULL |
| width | INT UNSIGNED NULL |
| height | INT UNSIGNED NULL |
| pages | INT UNSIGNED NULL |
| has_text_layer | BOOLEAN NULL |
| storage_path | TEXT NULL |

## task

| Field | Physical definition |
| --- | --- |
| id | BIGINT UNSIGNED NOT NULL AUTO_INCREMENT |
| biz_no | VARCHAR(255) NOT NULL |
| task_type | VARCHAR(255) NULL |
| channel | VARCHAR(255) NULL |
| file_id | BIGINT UNSIGNED NULL |
| carrier | VARCHAR(255) NULL |
| template_id | BIGINT UNSIGNED NULL |
| template_version | INT UNSIGNED NULL |
| status | VARCHAR(255) NULL |
| check_result | JSON NULL |
| period_start | DATETIME(6) NULL |
| period_end | DATETIME(6) NULL |
| hits | JSON NULL |

## bank_account

| Field | Physical definition |
| --- | --- |
| id | BIGINT UNSIGNED NOT NULL AUTO_INCREMENT |
| task_id | BIGINT UNSIGNED NULL |
| account_no | VARCHAR(255) NULL |
| bank_name | VARCHAR(255) NULL |
| period_start | DATETIME(6) NULL |
| period_end | DATETIME(6) NULL |
| opening_balance | DECIMAL(18,2) NULL |
| closing_balance | DECIMAL(18,2) NULL |

## txn

| Field | Physical definition |
| --- | --- |
| id | BIGINT UNSIGNED NOT NULL |
| task_id | BIGINT UNSIGNED NULL |
| account_id | BIGINT UNSIGNED NULL |
| txn_date | DATETIME(6) NOT NULL |
| direction | VARCHAR(255) NULL |
| amount | DECIMAL(18,2) NOT NULL |
| balance | DECIMAL(18,2) NULL |
| summary | TEXT NULL |
| counterparty_name | VARCHAR(255) NULL |
| page_no | INT UNSIGNED NULL |

## metric_value

| Field | Physical definition |
| --- | --- |
| id | BIGINT UNSIGNED NOT NULL AUTO_INCREMENT |
| task_id | BIGINT UNSIGNED NULL |
| metric_code | VARCHAR(255) NULL |
| metric_name | VARCHAR(255) NULL |
| value_num | DECIMAL(30,8) NULL |
| unit | VARCHAR(255) NULL |
| note | TEXT NULL |
| caliber_version | INT UNSIGNED NULL |

## report

| Field | Physical definition |
| --- | --- |
| id | BIGINT UNSIGNED NOT NULL AUTO_INCREMENT |
| task_id | BIGINT UNSIGNED NULL |
| version | INT UNSIGNED NULL |
| carrier | VARCHAR(255) NULL |
| verdict | VARCHAR(255) NULL |
| layers | JSON NULL |
| limitations | JSON NULL |
| evidence | JSON NULL |

## template

| Field | Physical definition |
| --- | --- |
| id | BIGINT UNSIGNED NOT NULL AUTO_INCREMENT |
| bank_code | VARCHAR(255) NULL |
| version | INT UNSIGNED NULL |
| status | VARCHAR(255) NULL |
| field_map | JSON NULL |

## rule

| Field | Physical definition |
| --- | --- |
| id | BIGINT UNSIGNED NOT NULL AUTO_INCREMENT |
| rule_code | VARCHAR(255) NULL |
| version | INT UNSIGNED NULL |
| category | VARCHAR(255) NULL |
| expr | TEXT NULL |
| threshold | JSON NULL |

## appeal

| Field | Physical definition |
| --- | --- |
| id | BIGINT UNSIGNED NOT NULL AUTO_INCREMENT |
| task_id | BIGINT UNSIGNED NULL |
| txn_id | BIGINT UNSIGNED NULL |
| status | VARCHAR(255) NULL |
| resolution | JSON NULL |

## audit_log

| Field | Physical definition |
| --- | --- |
| id | BIGINT UNSIGNED NOT NULL AUTO_INCREMENT |
| actor_id | BIGINT UNSIGNED NULL |
| action | VARCHAR(255) NULL |
| object_type | VARCHAR(255) NULL |
| object_id | BIGINT UNSIGNED NULL |
| created_at | DATETIME(6) NULL |
