"""Reuse V2 backend models without importing its auto-creating session module."""
import importlib.util
import json
from pathlib import Path
import sys


def stable_constraints(sql):
    """Canonicalize single-line table constraints, preserving their SQL meaning."""
    lines = sql.splitlines()
    positions = [i for i, line in enumerate(lines) if line.lstrip().startswith(
        ('PRIMARY KEY ', 'FOREIGN KEY', 'CONSTRAINT ', 'UNIQUE ', 'CHECK '))]
    if positions:
        if positions != list(range(positions[0], positions[-1] + 1)):
            raise ValueError('Unexpected table constraint layout')
        constraints = sorted(lines[i].rstrip().rstrip(',') for i in positions)
        for offset, position in enumerate(positions):
            lines[position] = constraints[offset] + (',' if offset < len(positions)-1 else '')
    return '\n'.join(lines)


def load_backend_models(v2_root):
    path = Path(v2_root) / 'backend/db/models.py'
    name = 'data_v2_backend_models'
    spec = importlib.util.spec_from_file_location(name, str(path))
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    contract = json.loads((Path(__file__).parent / 'contract.json').read_text(encoding='utf-8'))['tables']
    tables = module.Base.metadata.tables
    if set(tables) != set(contract): raise ValueError('Backend table list differs from V2 contract')
    for table, fields in contract.items():
        if set(fields) - set(tables[table].columns.keys()):
            raise ValueError('Backend missing V2 contract fields')
    return module


def build_ddl(v2_root):
    from sqlalchemy import MetaData, PrimaryKeyConstraint, UniqueConstraint, CheckConstraint
    from sqlalchemy.schema import CreateTable
    from sqlalchemy.dialects.mysql import dialect
    source = load_backend_models(v2_root)
    metadata = MetaData()
    for table in source.Base.metadata.sorted_tables:
        table.to_metadata(metadata)
    txn = metadata.tables['txn']
    # MySQL monthly partitions cannot coexist with InnoDB foreign keys on txn.
    for constraint in list(txn.foreign_key_constraints):
        for element in constraint.elements:
            element.parent.foreign_keys.discard(element)
            txn.foreign_keys.discard(element)
        txn.constraints.remove(constraint)
    txn.constraints.remove(txn.primary_key)
    txn.c.id.primary_key = False
    txn.c.txn_date.nullable = False
    txn.append_constraint(PrimaryKeyConstraint('id','txn_date'))
    metadata.tables['task_file'].append_constraint(UniqueConstraint('task_id','file_id',name='uq_task_file'))
    metadata.tables['task_file'].append_constraint(CheckConstraint("role IN ('original','supplement')",name='ck_task_file_role'))
    txn.append_constraint(CheckConstraint('amount > 0',name='ck_txn_amount'))
    from sqlalchemy import Index
    Index('ix_txn_task_date',txn.c.task_id,txn.c.txn_date)
    Index('ix_metric_task_code',metadata.tables['metric_value'].c.task_id,metadata.tables['metric_value'].c.metric_code)
    statements = []
    mysql = dialect()
    for table in metadata.sorted_tables:
        table.dialect_options['mysql']['engine'] = 'InnoDB'
        table.dialect_options['mysql']['charset'] = 'utf8mb4'
        table.dialect_options['mysql']['collate'] = 'utf8mb4_0900_ai_ci'
        sql = stable_constraints(str(CreateTable(table).compile(dialect=mysql)).strip())
        if table.name == 'txn':
            sql += "\nPARTITION BY RANGE COLUMNS (txn_date) (\nPARTITION p_before VALUES LESS THAN ('2026-10-01'),\nPARTITION p202610 VALUES LESS THAN ('2026-11-01'),\nPARTITION p202611 VALUES LESS THAN ('2026-12-01'),\nPARTITION p202612 VALUES LESS THAN ('2027-01-01'),\nPARTITION p_future VALUES LESS THAN (MAXVALUE))"
        statements.append(sql + ';')
    from sqlalchemy.schema import CreateIndex
    for table in metadata.sorted_tables:
        for index in sorted(table.indexes,key=lambda i:i.name):
            statements.append(str(CreateIndex(index).compile(dialect=mysql)) + ';')
    return metadata, '\n'.join(line.rstrip() for line in '\n\n'.join(statements).splitlines()) + '\n'
