# V2数据字典（复用团队后端模型）

契约来源：e9baadf；11表89关键字段。额外列为已有后端实现，不是本轮新增公共字段。

## audit_log

| 字段 | MySQL类型 | 可空 | 契约关键字段 |
| --- | --- | --- | --- |
| id | INTEGER | False | True |
| actor_id | INTEGER | True | True |
| action | VARCHAR(32) | False | True |
| object_type | VARCHAR(32) | True | True |
| object_id | INTEGER | True | True |
| detail | VARCHAR(255) | True | False |
| created_at | DATETIME | False | True |

## file_obj

| 字段 | MySQL类型 | 可空 | 契约关键字段 |
| --- | --- | --- | --- |
| id | INTEGER | False | True |
| sha256 | VARCHAR(64) | False | True |
| mime | VARCHAR(64) | True | True |
| carrier | VARCHAR(16) | True | True |
| width | INTEGER | True | True |
| height | INTEGER | True | True |
| pages | INTEGER | True | True |
| has_text_layer | BOOL | True | True |
| storage_path | VARCHAR(255) | True | True |
| created_at | DATETIME | False | False |

## rule

| 字段 | MySQL类型 | 可空 | 契约关键字段 |
| --- | --- | --- | --- |
| id | INTEGER | False | True |
| rule_code | VARCHAR(32) | False | True |
| version | INTEGER | False | True |
| category | VARCHAR(32) | True | True |
| expr | TEXT | True | True |
| threshold | JSON | True | True |

## staff_user

| 字段 | MySQL类型 | 可空 | 契约关键字段 |
| --- | --- | --- | --- |
| id | INTEGER | False | True |
| name | VARCHAR(64) | True | True |
| role | VARCHAR(32) | False | True |
| status | VARCHAR(16) | False | True |
| created_at | DATETIME | False | False |

## template

| 字段 | MySQL类型 | 可空 | 契约关键字段 |
| --- | --- | --- | --- |
| id | INTEGER | False | True |
| bank_code | VARCHAR(16) | False | True |
| version | INTEGER | False | True |
| status | VARCHAR(16) | False | True |
| field_map | JSON | True | True |
| header_columns | JSON | True | False |
| created_at | DATETIME | False | False |

## txn

| 字段 | MySQL类型 | 可空 | 契约关键字段 |
| --- | --- | --- | --- |
| id | INTEGER | False | True |
| task_id | INTEGER | False | True |
| account_id | INTEGER | True | True |
| txn_date | VARCHAR(16) | False | True |
| direction | VARCHAR(8) | True | True |
| amount | NUMERIC(18, 2) | True | True |
| balance | NUMERIC(18, 2) | True | True |
| summary | VARCHAR(255) | True | True |
| counterparty_name | VARCHAR(255) | True | True |
| page_no | INTEGER | True | True |
| coord_x | NUMERIC(10, 4) | True | True |
| coord_y | NUMERIC(10, 4) | True | True |
| confidence | NUMERIC(5, 4) | True | True |
| drop_reason | VARCHAR(64) | True | True |

## task

| 字段 | MySQL类型 | 可空 | 契约关键字段 |
| --- | --- | --- | --- |
| id | INTEGER | False | True |
| biz_no | VARCHAR(32) | False | True |
| task_type | VARCHAR(16) | False | True |
| channel | VARCHAR(16) | False | True |
| file_id | INTEGER | True | True |
| carrier | VARCHAR(16) | True | True |
| template_id | INTEGER | True | True |
| template_version | INTEGER | True | True |
| status | VARCHAR(24) | False | True |
| check_result | JSON | True | True |
| period_start | VARCHAR(16) | True | True |
| period_end | VARCHAR(16) | True | True |
| hits | JSON | True | True |
| failure_code | VARCHAR(24) | True | False |
| created_at | DATETIME | False | False |
| finished_at | DATETIME | True | False |

## bank_account

| 字段 | MySQL类型 | 可空 | 契约关键字段 |
| --- | --- | --- | --- |
| id | INTEGER | False | True |
| task_id | INTEGER | False | True |
| account_no | VARCHAR(64) | True | True |
| bank_name | VARCHAR(64) | True | True |
| period_start | VARCHAR(16) | True | True |
| period_end | VARCHAR(16) | True | True |
| opening_balance | NUMERIC(18, 2) | True | True |
| closing_balance | NUMERIC(18, 2) | True | True |

## metric_value

| 字段 | MySQL类型 | 可空 | 契约关键字段 |
| --- | --- | --- | --- |
| id | INTEGER | False | True |
| task_id | INTEGER | False | True |
| metric_code | VARCHAR(16) | False | True |
| metric_name | VARCHAR(64) | False | True |
| value_num | NUMERIC(18, 4) | True | True |
| unit | VARCHAR(16) | True | True |
| note | VARCHAR(255) | True | True |
| caliber_version | INTEGER | False | True |

## report

| 字段 | MySQL类型 | 可空 | 契约关键字段 |
| --- | --- | --- | --- |
| id | INTEGER | False | True |
| task_id | INTEGER | False | True |
| version | INTEGER | False | True |
| carrier | VARCHAR(16) | True | True |
| verdict | VARCHAR(32) | True | True |
| verdict_reason | VARCHAR(255) | True | False |
| layers | JSON | True | True |
| limitations | JSON | True | True |
| evidence | JSON | True | True |
| materials | JSON | True | False |
| metric_set_version | INTEGER | True | True |
| threshold_version | INTEGER | True | True |
| payload | JSON | True | False |
| created_at | DATETIME | False | False |

## task_file

| 字段 | MySQL类型 | 可空 | 契约关键字段 |
| --- | --- | --- | --- |
| id | INTEGER | False | True |
| task_id | INTEGER | False | True |
| file_id | INTEGER | False | True |
| role | VARCHAR(16) | False | True |
| seq | INTEGER | False | True |
| created_at | DATETIME | False | True |
