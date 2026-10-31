"""Attach privacy at SQLAlchemy's actual flush boundary, without changing backend routes."""
from privacy import prepare_for_storage


def complete_report_mapping(session, report):
    """Persist existing report payload fields and real material references, no recalculation."""
    payload=dict(report.payload or {})
    for field in ('carrier','verdict','verdict_reason','layers','limitations','evidence','metric_set_version','threshold_version'):
        if getattr(report,field,None) is None and field in payload: setattr(report,field,payload[field])
    classes={mapper.local_table.name:mapper.class_ for mapper in report.__class__.registry.mappers}
    materials=[obj for obj in session.new if getattr(obj,'__tablename__',None)=='task_file' and obj.task_id==report.task_id]
    if not materials:
        from sqlalchemy import select
        model=classes['task_file']
        materials=list(session.execute(select(model).where(model.task_id==report.task_id).order_by(model.seq)).scalars())
    resolved=[]
    for material in sorted(materials,key=lambda m:m.seq):
        file=next((obj for obj in session.new if getattr(obj,'__tablename__',None)=='file_obj' and obj.id==material.file_id),None)
        if file is None: file=session.get(classes['file_obj'],material.file_id)
        if file is None: raise ValueError('Report material reference missing')
        resolved.append({'file_id':file.id,'role':material.role,'pages':file.pages,'sha256':file.sha256})
    if resolved:
        report.materials=resolved
        payload['materials']=resolved
    report.payload=payload


def protect_pending_records(session, flush_context, instances):
    for obj in list(session.new) + list(session.dirty):
        table = getattr(obj, '__table__', None)
        if table is None: continue
        if table.name=='report': complete_report_mapping(session,obj)
        row = {column.name:getattr(obj,column.name) for column in table.columns}
        protected = prepare_for_storage(table.name,row)
        if table.name == 'audit_log' and 'detail' in protected:
            protected['detail'] = 'event=' + str(protected.get('action') or 'operation')
        for field, value in protected.items():
            if row[field] != value: setattr(obj,field,value)


def install_privacy(session_class):
    from sqlalchemy import event
    if not event.contains(session_class,'before_flush',protect_pending_records):
        event.listen(session_class,'before_flush',protect_pending_records)
