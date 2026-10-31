"""Approved V2 deployment and synthetic-only acceptance via the existing secure pipe."""
import hashlib
import contextlib
import json
from pathlib import Path
import sys
import uuid
sys.path[:0]=[str(Path(__file__).resolve().parents[1]),str(Path(__file__).resolve().parents[1]/'bootstrap')]
from authenticate_pipe import dependencies
from provision_core import emit,request_secret,read_response
from v2.migration import guard,upgrade
from v2.models import build_ddl

DATA = Path(__file__).resolve().parents[1]
PHRASE = 'DEPLOY V2 DEMO 3307'
STATE = {'stage':'v2:prepare','writes_started':False}
GRANTS = {t:{'SELECT','INSERT'} for t in ('file_obj','task','task_file','bank_account','txn','metric_value','report')}
GRANTS['task'].add('UPDATE')
GRANTS.update(template={'SELECT'},rule={'SELECT'},audit_log={'INSERT'})


def connect(driver,user,secret,database=None):
    return driver.connect(host='127.0.0.1',port=3307,user=user,password=secret.encode('utf-8'),
        database=database,charset='utf8mb4',local_infile=False,autocommit=False,
        connect_timeout=5,read_timeout=30,write_timeout=30)


def grant_role(cursor):
    for table,privileges in GRANTS.items():
        cursor.execute('GRANT '+', '.join(sorted(privileges))+' ON `rc_demo_v2`.`'+table+"` TO 'rc_role_app'@'localhost'")
    cursor.execute("SHOW GRANTS FOR 'rc_role_app'@'localhost'")
    import re
    actual = {}
    for row in cursor.fetchall():
        statement = row[0]
        if statement.startswith('GRANT USAGE ON *.*'): continue
        match = re.fullmatch(r"GRANT ([A-Z, ]+) ON `rc_demo_v2`\.`([a-z_]+)` TO `rc_role_app`@`localhost`",statement)
        if not match: raise RuntimeError('Unexpected application role privilege')
        actual[match[2]] = {p.strip() for p in match[1].split(',')}
    if actual != GRANTS: raise RuntimeError('Application role differs from approved grants')


def backup_sample(cursor,task_id):
    cursor.execute('SELECT id,txn_date,amount,balance FROM rc_demo_v2.txn WHERE task_id=%s ORDER BY id',(task_id,))
    rows = cursor.fetchall()
    encoded = [[r[0],r[1],str(r[2]),str(r[3])] for r in rows]
    path = DATA/'evidence'/('v2-synthetic-backup-'+uuid.uuid4().hex+'.json')
    with path.open('x',encoding='utf-8') as file: json.dump(encoded,file)
    restored = json.loads(path.read_text(encoding='utf-8'))
    # Session-local restoration sample, not a permanent twelfth business table.
    cursor.execute('CREATE TEMPORARY TABLE rc_demo_v2.demo_restore_txn (id INT,txn_date VARCHAR(16),amount DECIMAL(18,2),balance DECIMAL(18,2))')
    for row in restored: cursor.execute('INSERT INTO rc_demo_v2.demo_restore_txn VALUES (%s,%s,%s,%s)',row)
    cursor.execute('SELECT id,txn_date,amount,balance FROM rc_demo_v2.demo_restore_txn ORDER BY id')
    checked = [[r[0],r[1],str(r[2]),str(r[3])] for r in cursor.fetchall()]
    if checked != encoded or len(checked)!=3: raise RuntimeError('Synthetic backup sample mismatch')
    return path.name


def run(root):
    _,generated = build_ddl(root)
    ddl = (DATA/'v2/schema.sql').read_text(encoding='utf-8')
    if generated != ddl: raise RuntimeError('V2 DDL differs from reviewed backend metadata')
    driver = dependencies()
    admin_secret = request_secret('root','login')
    admin = connect(driver,'root',admin_secret); admin_secret=None
    app_secret = None
    try:
        with admin.cursor() as cursor:
            guard(cursor)
            cursor.execute('SELECT CURRENT_USER()')
            if cursor.fetchone()[0]!='root@localhost': raise RuntimeError('Wrong administrator identity')
            cursor.execute('SELECT schema_name FROM information_schema.schemata WHERE schema_name=%s',('rc_demo_v2',))
            if cursor.fetchone() is not None: raise RuntimeError('V2 target exists; stop')
            cursor.execute("SHOW GRANTS FOR 'rc_role_app'@'localhost'")
            if any(not r[0].startswith('GRANT USAGE ON *.*') for r in cursor.fetchall()):
                raise RuntimeError('Unexpected existing application role grants')
        app_secret=request_secret('rc_demo_app','login')
        STATE['stage']='v2:app_authentication'
        with connect(driver,'rc_demo_app',app_secret) as connection:
            with connection.cursor() as cursor:
                guard(cursor)
                cursor.execute('SELECT CURRENT_USER(),CURRENT_ROLE()')
                matched,active=cursor.fetchone()
                if matched!='rc_demo_app@localhost' or active.replace('`',"'")!="'rc_role_app'@'localhost'":
                    raise RuntimeError('Wrong application identity or role')
        emit({'type':'confirm'})
        if read_response(sys.stdin.buffer)!=PHRASE: raise RuntimeError('Confirmation cancelled')
        baseline=DATA/'evidence'/('v2-before-'+uuid.uuid4().hex+'.json')
        with baseline.open('x',encoding='utf-8') as file:
            json.dump({'database':'rc_demo_v2','exists':False,'ddl_sha256':hashlib.sha256(ddl.encode()).hexdigest()},file)
        STATE.update(stage='v2:schema',writes_started=True)
        upgrade(admin,approved=True)
        emit({'type':'progress','stage':'schema_ready'})
        with admin.cursor() as cursor:
            cursor.execute("SELECT table_name FROM information_schema.tables WHERE table_schema='rc_demo_v2' AND table_type='BASE TABLE'")
            names={r[0] for r in cursor.fetchall()}
            contract=json.loads((DATA/'v2/contract.json').read_text(encoding='utf-8'))['tables']
            if names!=set(contract): raise RuntimeError('V2 table count mismatch')
            for table,fields in contract.items():
                cursor.execute('SELECT column_name FROM information_schema.columns WHERE table_schema=%s AND table_name=%s',('rc_demo_v2',table))
                if set(fields)-{r[0] for r in cursor.fetchall()}: raise RuntimeError('V2 missing contract field')
            STATE['stage']='v2:grants'
            grant_role(cursor)
        admin.commit()
        emit({'type':'progress','stage':'grants_ready'})
        from sqlalchemy import create_engine
        from sqlalchemy.pool import NullPool
        from v2.runtime import e2e
        engine=create_engine('mysql+pymysql://',creator=lambda:connect(driver,'rc_demo_app',app_secret,'rc_demo_v2'),
                             poolclass=NullPool,hide_parameters=True)
        try:
            STATE['stage']='v2:e2e'
            emit({'type':'progress','stage':'e2e_running'})
            with contextlib.redirect_stdout(sys.stderr):
                report=e2e(root,engine)
        finally: engine.dispose()
        STATE['stage']='v2:backup_sample'
        with admin.cursor() as cursor: backup=backup_sample(cursor,report['task_id'])
        admin.commit()
        report.update(tables=11,contract_fields=89,grants_ok=True,backup_sample_roundtrip=True,backup_file=backup)
        return report
    finally:
        app_secret=None
        admin.close()


if __name__=='__main__':
    try:
        if '--apply' not in sys.argv: raise RuntimeError('Approval switch required')
        root=Path(sys.argv[sys.argv.index('--v2-root')+1])
        result=run(root)
        emit({'type':'result','mode':'V2Deploy','ok':True,'v2_report':result})
        sys.exit(0)
    except (Exception,KeyboardInterrupt) as error:
        original=getattr(error,'orig',error)
        code=original.args[0] if original.args and type(original.args[0]) is int else None
        emit({'type':'result','mode':'V2Deploy','ok':False,'category':'CORE_EXECUTION_FAILED','code':code,
              'stage':STATE['stage'],'writes_started':STATE['writes_started']})
        sys.exit(1)
