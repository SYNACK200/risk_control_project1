-- Empty database only. No CREATE DATABASE / USE / DROP statements.

CREATE TABLE app_user (
	id INTEGER NOT NULL AUTO_INCREMENT,
	username VARCHAR(64) NOT NULL,
	password_hash VARCHAR(255) NOT NULL,
	`role` VARCHAR(16) NOT NULL,
	is_admin BOOL NOT NULL DEFAULT 0,
	display_name VARCHAR(64),
	status VARCHAR(16) NOT NULL,
	created_at DATETIME NOT NULL,
	last_login_at DATETIME,
	PRIMARY KEY (id)
);

CREATE UNIQUE INDEX ix_app_user_username ON app_user (username);

CREATE TABLE audit_log (
	id INTEGER NOT NULL AUTO_INCREMENT,
	actor_id INTEGER,
	action VARCHAR(32) NOT NULL,
	object_type VARCHAR(32),
	object_id INTEGER,
	detail VARCHAR(1024),
	created_at DATETIME NOT NULL,
	PRIMARY KEY (id)
);

CREATE TABLE custom_metric (
	id INTEGER NOT NULL AUTO_INCREMENT,
	code VARCHAR(32) NOT NULL,
	name VARCHAR(64) NOT NULL,
	unit VARCHAR(16),
	group_name VARCHAR(32),
	formula VARCHAR(255),
	inputs VARCHAR(255),
	note VARCHAR(255),
	steps JSON,
	enabled BOOL NOT NULL DEFAULT 1,
	created_by INTEGER,
	created_at DATETIME NOT NULL,
	PRIMARY KEY (id)
);

CREATE UNIQUE INDEX ix_custom_metric_code ON custom_metric (code);

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
);

CREATE TABLE ocr_routing (
	id INTEGER NOT NULL AUTO_INCREMENT,
	enabled BOOL NOT NULL DEFAULT 0,
	min_images INTEGER NOT NULL DEFAULT 3,
	workers INTEGER NOT NULL DEFAULT 2,
	model VARCHAR(32) NOT NULL DEFAULT 'PP-OCRv6',
	endpoint VARCHAR(255),
	api_key VARCHAR(255),
	note VARCHAR(255),
	updated_by VARCHAR(64),
	updated_at DATETIME,
	PRIMARY KEY (id)
);

CREATE TABLE rule (
	id INTEGER NOT NULL AUTO_INCREMENT,
	rule_code VARCHAR(32) NOT NULL,
	version INTEGER NOT NULL,
	category VARCHAR(32),
	expr TEXT,
	threshold JSON,
	PRIMARY KEY (id),
	UNIQUE (rule_code)
);

CREATE TABLE staff_user (
	id INTEGER NOT NULL AUTO_INCREMENT,
	name VARCHAR(64),
	`role` VARCHAR(32) NOT NULL,
	status VARCHAR(16) NOT NULL,
	created_at DATETIME NOT NULL,
	PRIMARY KEY (id)
);

CREATE TABLE subject_decision (
	id INTEGER NOT NULL AUTO_INCREMENT,
	account_key VARCHAR(128) NOT NULL,
	subject VARCHAR(128) NOT NULL,
	action VARCHAR(16) NOT NULL,
	note VARCHAR(255),
	created_by INTEGER,
	created_at DATETIME NOT NULL,
	PRIMARY KEY (id)
);

CREATE UNIQUE INDEX ix_subject_decision_account_key ON subject_decision (account_key);

CREATE TABLE template (
	id INTEGER NOT NULL AUTO_INCREMENT,
	bank_code VARCHAR(16) NOT NULL,
	version INTEGER NOT NULL,
	status VARCHAR(16) NOT NULL,
	field_map JSON,
	header_columns JSON,
	sample_file_id INTEGER,
	layout JSON,
	deleted_at DATETIME,
	created_at DATETIME NOT NULL,
	updated_at DATETIME,
	PRIMARY KEY (id)
);

CREATE INDEX ix_template_bank_code ON template (bank_code);

CREATE TABLE threshold_profile (
	id INTEGER NOT NULL AUTO_INCREMENT,
	version INTEGER NOT NULL,
	`values` JSON NOT NULL,
	note VARCHAR(255),
	created_at DATETIME NOT NULL,
	PRIMARY KEY (id),
	UNIQUE (version)
);

CREATE TABLE task (
	id INTEGER NOT NULL AUTO_INCREMENT,
	biz_no VARCHAR(32) NOT NULL,
	task_type VARCHAR(16) NOT NULL,
	channel VARCHAR(16) NOT NULL,
	file_id INTEGER,
	carrier VARCHAR(16),
	template_id INTEGER,
	template_version INTEGER,
	field_map_override TEXT,
	status VARCHAR(24) NOT NULL,
	check_result JSON,
	period_start VARCHAR(16),
	period_end VARCHAR(16),
	hits JSON,
	failure_code VARCHAR(24),
	created_at DATETIME NOT NULL,
	finished_at DATETIME,
	deleted_at DATETIME,
	user_id INTEGER,
	FOREIGN KEY(file_id) REFERENCES file_obj (id),
	PRIMARY KEY (id),
	UNIQUE (biz_no)
);

CREATE INDEX ix_task_user_id ON task (user_id);

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
);

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
);

CREATE INDEX ix_metric_value_task_id ON metric_value (task_id);

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
	verification JSON,
	threshold_version INTEGER,
	payload JSON,
	created_at DATETIME NOT NULL,
	FOREIGN KEY(task_id) REFERENCES task (id),
	PRIMARY KEY (id)
);

CREATE INDEX ix_report_task_id ON report (task_id);

CREATE TABLE task_file (
	id INTEGER NOT NULL AUTO_INCREMENT,
	task_id INTEGER NOT NULL,
	file_id INTEGER NOT NULL,
	`role` VARCHAR(16) NOT NULL,
	seq INTEGER NOT NULL,
	created_at DATETIME NOT NULL,
	CONSTRAINT uq_task_seq UNIQUE (task_id, seq),
	FOREIGN KEY(file_id) REFERENCES file_obj (id),
	FOREIGN KEY(task_id) REFERENCES task (id),
	PRIMARY KEY (id)
);

CREATE TABLE txn (
	id INTEGER NOT NULL AUTO_INCREMENT,
	task_id INTEGER NOT NULL,
	account_id INTEGER,
	txn_date VARCHAR(16),
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
	extra JSON,
	FOREIGN KEY(account_id) REFERENCES bank_account (id),
	FOREIGN KEY(task_id) REFERENCES task (id),
	PRIMARY KEY (id)
);

CREATE INDEX ix_txn_task_id ON txn (task_id);
