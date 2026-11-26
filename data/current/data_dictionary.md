# 当前后端物理数据字典

由 data/tools/current_schema.py 生成；与历史 v2 Demo 分开。

## app_user

| 字段 | MySQL 类型 | 可空 |
| --- | --- | --- |
| id | INTEGER | False |
| username | VARCHAR(64) | False |
| password_hash | VARCHAR(255) | False |
| role | VARCHAR(16) | False |
| is_admin | BOOL | False |
| display_name | VARCHAR(64) | True |
| status | VARCHAR(16) | False |
| created_at | DATETIME | False |
| last_login_at | DATETIME | True |

## audit_log

| 字段 | MySQL 类型 | 可空 |
| --- | --- | --- |
| id | INTEGER | False |
| actor_id | INTEGER | True |
| action | VARCHAR(32) | False |
| object_type | VARCHAR(32) | True |
| object_id | INTEGER | True |
| detail | VARCHAR(1024) | True |
| created_at | DATETIME | False |

## custom_metric

| 字段 | MySQL 类型 | 可空 |
| --- | --- | --- |
| id | INTEGER | False |
| code | VARCHAR(32) | False |
| name | VARCHAR(64) | False |
| unit | VARCHAR(16) | True |
| group_name | VARCHAR(32) | True |
| formula | VARCHAR(255) | True |
| inputs | VARCHAR(255) | True |
| note | VARCHAR(255) | True |
| steps | JSON | True |
| enabled | BOOL | False |
| created_by | INTEGER | True |
| created_at | DATETIME | False |

## file_obj

| 字段 | MySQL 类型 | 可空 |
| --- | --- | --- |
| id | INTEGER | False |
| sha256 | VARCHAR(64) | False |
| mime | VARCHAR(64) | True |
| carrier | VARCHAR(16) | True |
| width | INTEGER | True |
| height | INTEGER | True |
| pages | INTEGER | True |
| has_text_layer | BOOL | True |
| storage_path | VARCHAR(255) | True |
| created_at | DATETIME | False |

## ocr_routing

| 字段 | MySQL 类型 | 可空 |
| --- | --- | --- |
| id | INTEGER | False |
| enabled | BOOL | False |
| min_images | INTEGER | False |
| workers | INTEGER | False |
| model | VARCHAR(32) | False |
| endpoint | VARCHAR(255) | True |
| api_key | VARCHAR(255) | True |
| note | VARCHAR(255) | True |
| updated_by | VARCHAR(64) | True |
| updated_at | DATETIME | True |

## rule

| 字段 | MySQL 类型 | 可空 |
| --- | --- | --- |
| id | INTEGER | False |
| rule_code | VARCHAR(32) | False |
| version | INTEGER | False |
| category | VARCHAR(32) | True |
| expr | TEXT | True |
| threshold | JSON | True |

## staff_user

| 字段 | MySQL 类型 | 可空 |
| --- | --- | --- |
| id | INTEGER | False |
| name | VARCHAR(64) | True |
| role | VARCHAR(32) | False |
| status | VARCHAR(16) | False |
| created_at | DATETIME | False |

## subject_decision

| 字段 | MySQL 类型 | 可空 |
| --- | --- | --- |
| id | INTEGER | False |
| account_key | VARCHAR(128) | False |
| subject | VARCHAR(128) | False |
| action | VARCHAR(16) | False |
| note | VARCHAR(255) | True |
| created_by | INTEGER | True |
| created_at | DATETIME | False |

## template

| 字段 | MySQL 类型 | 可空 |
| --- | --- | --- |
| id | INTEGER | False |
| bank_code | VARCHAR(16) | False |
| version | INTEGER | False |
| status | VARCHAR(16) | False |
| field_map | JSON | True |
| header_columns | JSON | True |
| sample_file_id | INTEGER | True |
| layout | JSON | True |
| deleted_at | DATETIME | True |
| created_at | DATETIME | False |
| updated_at | DATETIME | True |

## threshold_profile

| 字段 | MySQL 类型 | 可空 |
| --- | --- | --- |
| id | INTEGER | False |
| version | INTEGER | False |
| values | JSON | False |
| note | VARCHAR(255) | True |
| created_at | DATETIME | False |

## task

| 字段 | MySQL 类型 | 可空 |
| --- | --- | --- |
| id | INTEGER | False |
| biz_no | VARCHAR(32) | False |
| task_type | VARCHAR(16) | False |
| channel | VARCHAR(16) | False |
| file_id | INTEGER | True |
| carrier | VARCHAR(16) | True |
| template_id | INTEGER | True |
| template_version | INTEGER | True |
| field_map_override | TEXT | True |
| status | VARCHAR(24) | False |
| check_result | JSON | True |
| period_start | VARCHAR(16) | True |
| period_end | VARCHAR(16) | True |
| hits | JSON | True |
| failure_code | VARCHAR(24) | True |
| created_at | DATETIME | False |
| finished_at | DATETIME | True |
| deleted_at | DATETIME | True |
| user_id | INTEGER | True |

## bank_account

| 字段 | MySQL 类型 | 可空 |
| --- | --- | --- |
| id | INTEGER | False |
| task_id | INTEGER | False |
| account_no | VARCHAR(64) | True |
| bank_name | VARCHAR(64) | True |
| period_start | VARCHAR(16) | True |
| period_end | VARCHAR(16) | True |
| opening_balance | NUMERIC(18, 2) | True |
| closing_balance | NUMERIC(18, 2) | True |

## metric_value

| 字段 | MySQL 类型 | 可空 |
| --- | --- | --- |
| id | INTEGER | False |
| task_id | INTEGER | False |
| metric_code | VARCHAR(16) | False |
| metric_name | VARCHAR(64) | False |
| value_num | NUMERIC(18, 4) | True |
| unit | VARCHAR(16) | True |
| note | VARCHAR(255) | True |
| caliber_version | INTEGER | False |

## report

| 字段 | MySQL 类型 | 可空 |
| --- | --- | --- |
| id | INTEGER | False |
| task_id | INTEGER | False |
| version | INTEGER | False |
| carrier | VARCHAR(16) | True |
| verdict | VARCHAR(32) | True |
| verdict_reason | VARCHAR(255) | True |
| layers | JSON | True |
| limitations | JSON | True |
| evidence | JSON | True |
| materials | JSON | True |
| metric_set_version | INTEGER | True |
| verification | JSON | True |
| threshold_version | INTEGER | True |
| payload | JSON | True |
| created_at | DATETIME | False |

## task_file

| 字段 | MySQL 类型 | 可空 |
| --- | --- | --- |
| id | INTEGER | False |
| task_id | INTEGER | False |
| file_id | INTEGER | False |
| role | VARCHAR(16) | False |
| seq | INTEGER | False |
| created_at | DATETIME | False |

## txn

| 字段 | MySQL 类型 | 可空 |
| --- | --- | --- |
| id | INTEGER | False |
| task_id | INTEGER | False |
| account_id | INTEGER | True |
| txn_date | VARCHAR(16) | True |
| direction | VARCHAR(8) | True |
| amount | NUMERIC(18, 2) | True |
| balance | NUMERIC(18, 2) | True |
| summary | VARCHAR(255) | True |
| counterparty_name | VARCHAR(255) | True |
| page_no | INTEGER | True |
| coord_x | NUMERIC(10, 4) | True |
| coord_y | NUMERIC(10, 4) | True |
| confidence | NUMERIC(5, 4) | True |
| drop_reason | VARCHAR(64) | True |
| extra | JSON | True |
