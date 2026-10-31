CREATE TABLE audit_log (
	id INTEGER NOT NULL AUTO_INCREMENT,
	actor_id INTEGER,
	action VARCHAR(32) NOT NULL,
	object_type VARCHAR(32),
	object_id INTEGER,
	detail VARCHAR(255),
	created_at DATETIME NOT NULL,
	PRIMARY KEY (id)
)ENGINE=InnoDB CHARSET=utf8mb4 COLLATE utf8mb4_0900_ai_ci;

CREATE TABLE file_obj (
	id INTEGER NOT NULL AUTO_INCREMENT,
	sha256 VARCHAR(64) NOT NULL,
	mime VARCHAR(64),
	carrier VARCHAR(16),
	width INTEGER,
	height INTEGER,
	pages INTEGER,
	has_text_layer BOOL,
	storage_path VARCHAR(255),
	created_at DATETIME NOT NULL,
	PRIMARY KEY (id),
	UNIQUE (sha256)
)ENGINE=InnoDB CHARSET=utf8mb4 COLLATE utf8mb4_0900_ai_ci;

CREATE TABLE rule (
	id INTEGER NOT NULL AUTO_INCREMENT,
	rule_code VARCHAR(32) NOT NULL,
	version INTEGER NOT NULL,
	category VARCHAR(32),
	expr TEXT,
	threshold JSON,
	PRIMARY KEY (id),
	UNIQUE (rule_code)
)ENGINE=InnoDB CHARSET=utf8mb4 COLLATE utf8mb4_0900_ai_ci;

CREATE TABLE staff_user (
	id INTEGER NOT NULL AUTO_INCREMENT,
	name VARCHAR(64),
	`role` VARCHAR(32) NOT NULL,
	status VARCHAR(16) NOT NULL,
	created_at DATETIME NOT NULL,
	PRIMARY KEY (id)
)ENGINE=InnoDB CHARSET=utf8mb4 COLLATE utf8mb4_0900_ai_ci;

CREATE TABLE template (
	id INTEGER NOT NULL AUTO_INCREMENT,
	bank_code VARCHAR(16) NOT NULL,
	version INTEGER NOT NULL,
	status VARCHAR(16) NOT NULL,
	field_map JSON,
	header_columns JSON,
	created_at DATETIME NOT NULL,
	PRIMARY KEY (id)
)ENGINE=InnoDB CHARSET=utf8mb4 COLLATE utf8mb4_0900_ai_ci;

CREATE TABLE txn (
	id INTEGER NOT NULL AUTO_INCREMENT,
	task_id INTEGER NOT NULL,
	account_id INTEGER,
	txn_date VARCHAR(16) NOT NULL,
	direction VARCHAR(8),
	amount NUMERIC(18, 2),
	balance NUMERIC(18, 2),
	summary VARCHAR(255),
	counterparty_name VARCHAR(255),
	page_no INTEGER,
	coord_x NUMERIC(10, 4),
	coord_y NUMERIC(10, 4),
	confidence NUMERIC(5, 4),
	drop_reason VARCHAR(64),
	CONSTRAINT ck_txn_amount CHECK (amount > 0),
	PRIMARY KEY (id, txn_date)
)ENGINE=InnoDB CHARSET=utf8mb4 COLLATE utf8mb4_0900_ai_ci
PARTITION BY RANGE COLUMNS (txn_date) (
PARTITION p_before VALUES LESS THAN ('2026-10-01'),
PARTITION p202610 VALUES LESS THAN ('2026-11-01'),
PARTITION p202611 VALUES LESS THAN ('2026-12-01'),
PARTITION p202612 VALUES LESS THAN ('2027-01-01'),
PARTITION p_future VALUES LESS THAN (MAXVALUE));

CREATE TABLE task (
	id INTEGER NOT NULL AUTO_INCREMENT,
	biz_no VARCHAR(32) NOT NULL,
	task_type VARCHAR(16) NOT NULL,
	channel VARCHAR(16) NOT NULL,
	file_id INTEGER,
	carrier VARCHAR(16),
	template_id INTEGER,
	template_version INTEGER,
	status VARCHAR(24) NOT NULL,
	check_result JSON,
	period_start VARCHAR(16),
	period_end VARCHAR(16),
	hits JSON,
	failure_code VARCHAR(24),
	created_at DATETIME NOT NULL,
	finished_at DATETIME,
	FOREIGN KEY(file_id) REFERENCES file_obj (id),
	PRIMARY KEY (id),
	UNIQUE (biz_no)
)ENGINE=InnoDB CHARSET=utf8mb4 COLLATE utf8mb4_0900_ai_ci;

CREATE TABLE bank_account (
	id INTEGER NOT NULL AUTO_INCREMENT,
	task_id INTEGER NOT NULL,
	account_no VARCHAR(64),
	bank_name VARCHAR(64),
	period_start VARCHAR(16),
	period_end VARCHAR(16),
	opening_balance NUMERIC(18, 2),
	closing_balance NUMERIC(18, 2),
	FOREIGN KEY(task_id) REFERENCES task (id),
	PRIMARY KEY (id)
)ENGINE=InnoDB CHARSET=utf8mb4 COLLATE utf8mb4_0900_ai_ci;

CREATE TABLE metric_value (
	id INTEGER NOT NULL AUTO_INCREMENT,
	task_id INTEGER NOT NULL,
	metric_code VARCHAR(16) NOT NULL,
	metric_name VARCHAR(64) NOT NULL,
	value_num NUMERIC(18, 4),
	unit VARCHAR(16),
	note VARCHAR(255),
	caliber_version INTEGER NOT NULL,
	FOREIGN KEY(task_id) REFERENCES task (id),
	PRIMARY KEY (id)
)ENGINE=InnoDB CHARSET=utf8mb4 COLLATE utf8mb4_0900_ai_ci;

CREATE TABLE report (
	id INTEGER NOT NULL AUTO_INCREMENT,
	task_id INTEGER NOT NULL,
	version INTEGER NOT NULL,
	carrier VARCHAR(16),
	verdict VARCHAR(32),
	verdict_reason VARCHAR(255),
	layers JSON,
	limitations JSON,
	evidence JSON,
	materials JSON,
	metric_set_version INTEGER,
	threshold_version INTEGER,
	payload JSON,
	created_at DATETIME NOT NULL,
	FOREIGN KEY(task_id) REFERENCES task (id),
	PRIMARY KEY (id)
)ENGINE=InnoDB CHARSET=utf8mb4 COLLATE utf8mb4_0900_ai_ci;

CREATE TABLE task_file (
	id INTEGER NOT NULL AUTO_INCREMENT,
	task_id INTEGER NOT NULL,
	file_id INTEGER NOT NULL,
	`role` VARCHAR(16) NOT NULL,
	seq INTEGER NOT NULL,
	created_at DATETIME NOT NULL,
	CONSTRAINT ck_task_file_role CHECK (role IN ('original','supplement')),
	CONSTRAINT uq_task_file UNIQUE (task_id, file_id),
	CONSTRAINT uq_task_seq UNIQUE (task_id, seq),
	FOREIGN KEY(file_id) REFERENCES file_obj (id),
	FOREIGN KEY(task_id) REFERENCES task (id),
	PRIMARY KEY (id)
)ENGINE=InnoDB CHARSET=utf8mb4 COLLATE utf8mb4_0900_ai_ci;

CREATE INDEX ix_template_bank_code ON template (bank_code);

CREATE INDEX ix_txn_task_date ON txn (task_id, txn_date);

CREATE INDEX ix_txn_task_id ON txn (task_id);

CREATE INDEX ix_metric_task_code ON metric_value (task_id, metric_code);

CREATE INDEX ix_metric_value_task_id ON metric_value (task_id);

CREATE INDEX ix_report_task_id ON report (task_id);
