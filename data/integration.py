"""Optional backend adapter. No connection at import, no embedded credential."""
from contextlib import contextmanager


def make_engine(username, password):
    from sqlalchemy import create_engine
    from sqlalchemy.engine import URL
    return create_engine(URL.create('mysql+pymysql', username=username, password=password,
                                   host='127.0.0.1', port=3307, database='rc_demo_biz'),
                         pool_size=5, max_overflow=0, pool_timeout=10,
                         pool_pre_ping=True, pool_recycle=1800, hide_parameters=True,
                         connect_args={'charset': 'utf8mb4', 'connect_timeout': 5,
                                       'read_timeout': 30, 'write_timeout': 30})


@contextmanager
def transaction(engine):
    # Guard every checked-out connection before any caller SQL. Context closes on failure.
    from sqlalchemy import text
    with engine.begin() as conn:
        version, port, directory = conn.execute(text('SELECT VERSION(), @@port, @@datadir')).one()
        if not version.startswith('8.4.') or port != 3307 or directory.replace('\\', '/').rstrip('/').lower() != 'd:/riskcontroldemo/mysql84/data':
            raise RuntimeError('Unexpected Demo target')
        conn.execute(text("SET SESSION time_zone='+08:00'"))
        yield conn


def insert_batches(conn, statement, records, size=1000):
    """statement must be a caller-reviewed SQLAlchemy insert, never user-supplied SQL."""
    if type(size) is not int or not 1 <= size <= 1000: raise ValueError('Batch size outside Demo limit')
    if not getattr(statement, 'is_insert', False): raise ValueError('Only a reviewed SQLAlchemy insert is accepted')
    batch = []
    for record in records:
        batch.append(record)
        if len(batch) == size: conn.execute(statement, batch); batch = []
    if batch: conn.execute(statement, batch)


def validated_records(table, records):
    """Optional caller stream adapter; no business rules, role checks or DB access."""
    from validation import validate_record
    from privacy import prepare_for_storage
    shape = None
    for record in records:
        validated = validate_record(table, prepare_for_storage(table, record))
        keys = frozenset(validated)
        if shape is None: shape = keys
        if keys != shape: raise ValueError('Batch records must have consistent field sets')
        yield validated


def validated_v2_records(table, records):
    """V2 contract fields only; backend model extra columns remain caller-owned."""
    from v2.records import prepare_record
    for record in records:
        yield prepare_record(table, record)
