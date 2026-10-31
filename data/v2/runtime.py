"""Reuse the team's real HTTP/analysis code with an injected Demo session, no auto-DDL."""
import importlib
import importlib.util
from pathlib import Path
import sys
import types


def synthetic_pdf():
    import pymupdf
    doc = pymupdf.open()
    page = doc.new_page(width=800,height=1000)
    page.insert_text((40,60),'银行账户交易明细（纯模拟）',fontsize=12,fontname='china-s')
    xs = [40,200,380,480,560,660]
    header = ['交易日期','摘要','对方户名','借贷标志','交易金额','余额']
    rows = [['2026-10-01','工资','模拟公司','贷','12,500.00','13,200.00'],
            ['2026-10-02','消费','模拟商户','借','300.50','12,899.50'],
            ['2026-10-03','转账','模拟客户','借','1,000.00','11,899.50']]
    for i,row in enumerate([header]+rows):
        for x,text in zip(xs,row): page.insert_text((x,90+18*i),text,fontsize=7,fontname='china-s')
    page.insert_text((40,190),'共 3 笔记录',fontsize=7,fontname='china-s')
    data = doc.tobytes(); doc.close()
    return data


def load_app(v2_root, engine):
    from sqlalchemy.orm import Session,sessionmaker
    from sqlalchemy import text
    from v2.session import install_privacy
    root = Path(v2_root)
    sys.path[:0] = [str(root/'backend'),str(root)]
    importlib.import_module('db.models')  # Models only; never imports auto-creating db.session.
    class DataSession(Session): pass
    install_privacy(DataSession)
    factory = sessionmaker(bind=engine,class_=DataSession,expire_on_commit=False)
    def get_session():
        with factory() as session: yield session
    def init_db():
        with engine.connect() as connection:
            row = connection.execute(text('SELECT VERSION(),@@port,@@datadir,DATABASE()')).one()
            if not (row[0].startswith('8.4.') and row[1]==3307 and
                    row[2].replace('\\','/').rstrip('/').lower()=='d:/riskcontroldemo/mysql84/data' and row[3]=='rc_demo_v2'):
                raise RuntimeError('Wrong application Demo target')
    shim = types.ModuleType('db.session')
    shim.get_session, shim.init_db, shim.SessionLocal = get_session,init_db,factory
    sys.modules['db.session'] = shim
    spec = importlib.util.spec_from_file_location('data_v2_app',str(root/'backend/main.py'))
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module.app


def e2e(v2_root, engine):
    from fastapi.testclient import TestClient
    from sqlalchemy import text
    app = load_app(v2_root,engine)
    tasks = importlib.import_module('routers.tasks')
    folder=Path(__file__).resolve().parents[1]/'inputs/demo_v2_uploads'
    folder.mkdir(parents=True,exist_ok=True)
    tasks.STORAGE=folder
    with TestClient(app) as client:
            response = client.post('/api/v1/tasks',files={'file':('synthetic-statement.pdf',synthetic_pdf(),'application/pdf')})
            if response.status_code != 200: raise RuntimeError('Synthetic HTTP upload failed')
            task_id = response.json()['task_id']
            transactions = client.get('/api/v1/tasks/'+str(task_id)+'/transactions')
            metrics = client.get('/api/v1/tasks/'+str(task_id)+'/metrics')
            report = client.get('/api/v1/reports/'+str(task_id))
            if any(r.status_code!=200 for r in (transactions,metrics,report)):
                raise RuntimeError('Synthetic result query failed')
            if len(transactions.json())!=3 or not metrics.json() or not report.json().get('layers'):
                raise RuntimeError('Synthetic pipeline content mismatch')
    with engine.connect() as connection:
        rows = connection.execute(text('SELECT counterparty_name,amount,balance FROM txn WHERE task_id=:id'),{'id':task_id}).all()
        if len(rows)!=3 or any(name and '*' not in name for name,amount,balance in rows):
            raise RuntimeError('Stored privacy check failed')
    return {'task_id':task_id,'transactions':3,'metrics':len(metrics.json()),
            'report_version':report.json().get('version',1),'http_upload_ok':True,'report_read_ok':True,'privacy_ok':True}
