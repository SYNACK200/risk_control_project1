"""任务分析执行器：在任意进程内把一次「解析 + 核验 + 指标 + 报告 + 落库」跑完。

设计要点
- 自身不带全局状态：子进程里调用时会先 init_db() 建自己的连接池；
- 失败一律把任务置 FAILED 并写审计，不静默；
- 与 routers/tasks.py 解耦，便于放到进程池里跑（绕过 GIL）。
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from pathlib import Path


def _page_count(blob: bytes, password: str | None = None) -> int:
    """Return a material's page count without trusting client-supplied metadata."""
    if not blob.startswith(b"%PDF"):
        return 1
    try:
        import pymupdf  # noqa: PLC0415

        document = pymupdf.open(stream=blob, filetype="pdf")
        try:
            if document.needs_pass and password:
                document.authenticate(password)
            return len(document)
        finally:
            document.close()
    except Exception:  # noqa: BLE001 - a failed count must not discard a valid material
        return 1


def _build_material_manifest(
    material_blobs: list[tuple[str, bytes, object]], password: str | None = None
) -> list[dict]:
    """Convert persisted task materials to the report's traceable contract shape."""
    return [
        {
            "file_id": file_obj.id,
            "role": role,
            "pages": _page_count(blob, password),
            "sha256": file_obj.sha256,
        }
        for role, blob, file_obj in material_blobs
    ]


def _commit_with_retry(session, attempts: int = 3) -> None:
    """并发写 metric_value 可能触发 1213 死锁，退避重试。"""
    import time as _time

    from sqlalchemy.exc import OperationalError as _OpErr

    for i in range(attempts):
        try:
            session.commit()
            return
        except _OpErr as exc:
            if i == attempts - 1 or "1213" not in str(exc) and "Deadlock" not in str(exc):
                raise
            session.rollback()
            _time.sleep(0.05 * (i + 1))


def warmup() -> str:
    """进程预热：让子进程提前加载算法与数据库依赖，避免首个任务慢 1s+。"""
    from algorithm.algo.preread import run_preread  # noqa: F401
    from services.analysis import run_analysis  # noqa: F401
    from db import session as db_session

    db_session.init_db()
    return "ok"


def run_task(task_id: int, password: str | None = None) -> dict:
    """执行一次任务分析；返回 {"task_id", "status", "txn_count"}。异常时任务置 FAILED 后重新抛出。"""
    from db import session as db_session

    db_session.init_db()
    assert db_session.SessionLocal is not None
    session = db_session.SessionLocal()

    from db.models import (  # noqa: PLC0415
        AuditLog, FileObj, MetricValue, Report, Task, Template, Txn,
    )
    from algorithm.algo.preread import run_preread
    from services.analysis import run_analysis
    from services.workflow import transition
    from services import thresholds as threshold_service

    try:
        from sqlalchemy import text as _sql

        # 降低并发插入 metric_value 时的间隙锁冲突
        session.execute(_sql("SET SESSION TRANSACTION ISOLATION LEVEL READ COMMITTED"))
    except Exception:  # noqa: BLE001
        pass

    task = session.get(Task, task_id)
    if task is None:
        session.close()
        return {"task_id": task_id, "status": "MISSING", "txn_count": 0}
    try:
        from db.models import TaskFile  # noqa: PLC0415

        file_row = session.get(FileObj, task.file_id) if task.file_id else None
        if file_row is None or not file_row.storage_path:
            raise RuntimeError("任务没有可用的原始文件")
        path = Path(file_row.storage_path)
        if not path.exists():
            raise RuntimeError("原始文件已被清理，无法分析")
        data = path.read_bytes()

        # 读取该任务的全部材料（含补件 task_file），若全为 PDF 则按 seq 合并页流统一分析
        tf_rows = (
            session.query(TaskFile)
            .filter(TaskFile.task_id == task.id)
            .order_by(TaskFile.seq.asc())
            .all()
        )
        material_blobs: list[tuple[str, bytes, FileObj]] = []
        if tf_rows:
            for tf in tf_rows:
                fobj = session.get(FileObj, tf.file_id)
                if fobj and fobj.storage_path and Path(fobj.storage_path).exists():
                    material_blobs.append((tf.role or "original", Path(fobj.storage_path).read_bytes(), fobj))
        if not material_blobs:
            material_blobs = [("original", data, file_row)]
        if len(material_blobs) > 1 and all(b[:4] == b"%PDF" for _, b, _ in material_blobs):
            try:
                import pymupdf as _fitz  # noqa: PLC0415

                merged_doc = _fitz.open()
                try:
                    for _, blob, _ in material_blobs:
                        src_doc = _fitz.open(stream=blob, filetype="pdf")
                        try:
                            if src_doc.needs_pass and password:
                                src_doc.authenticate(password)
                            merged_doc.insert_pdf(src_doc)
                        finally:
                            src_doc.close()
                    data = merged_doc.tobytes()
                finally:
                    merged_doc.close()
            except Exception:  # noqa: BLE001 - 合并失败时回退主文件不阻断
                pass

        template = None
        template_row = None
        temp_template = False

        # 临时模板优先：支持新版交互式 {field_map, layout} 与旧版 marks 列表，不写回模板库
        if getattr(task, "field_map_override", None):
            try:
                import json as _json

                override_obj = _json.loads(task.field_map_override)
                bank_hint = "UNKNOWN"
                try:
                    bank_hint = (((task.check_result or {}).get("preread") or {}).get("bank_code") or "UNKNOWN")
                except Exception:  # noqa: BLE001
                    bank_hint = "UNKNOWN"

                if isinstance(override_obj, dict) and override_obj.get("field_map"):
                    template = {
                        "bank_code": str(override_obj.get("bank_code") or bank_hint),
                        "version": 0,
                        "field_map": override_obj["field_map"],
                        "layout": override_obj.get("layout"),
                    }
                    temp_template = True
                elif isinstance(override_obj, list):
                    from services.analysis import infer_from_marks
                    from services import template_layout as tlayout

                    inferred = infer_from_marks(data, override_obj, bank_code=bank_hint)
                    if inferred.get("valid") and inferred.get("field_map"):
                        built_layout = None
                        try:
                            built_layout = tlayout.build_layout(
                                data, override_obj, inferred.get("columns") or [], inferred["field_map"]
                            )
                        except Exception:  # noqa: BLE001
                            built_layout = None
                        template = {
                            "bank_code": bank_hint,
                            "version": 0,
                            "field_map": inferred["field_map"],
                            "layout": built_layout,
                        }
                        temp_template = True
                    else:
                        task.check_result = dict(task.check_result or {})
                        task.check_result["temp_template_error"] = {
                            "warnings": (inferred.get("warnings") or [])[:5],
                            "used": False,
                        }
            except Exception as exc:  # noqa: BLE001 - 临时模板失败不阻断主流程
                task.check_result = dict(task.check_result or {})
                task.check_result["temp_template_error"] = {"error": str(exc), "used": False}

        if template is None and task.template_id:
            template_row = session.get(Template, task.template_id)
            if template_row is not None and template_row.deleted_at is None:
                template = {"bank_code": template_row.bank_code,
                            "version": template_row.version,
                            "field_map": template_row.field_map,
                            # 有框画范围就带上：解析优先用它切列，比按表头词中心推算稳
                            "layout": template_row.layout,
                            # 必需列：缺了要在报告里点名，而不是让指标一片「不可算」
                            "required_fields": template_row.required_fields}

        transition(task, "CHECKING")
        transition(task, "PARSING")
        session.commit()

        preread = run_preread(data, password=password)
        # 接入 OCR 路由配置（should_use_api），按图片/页数决定本地或云端并发路由
        ocr_route: tuple[bool, dict] | None = None
        try:
            from services import ocr_routing as _ocr_routing  # noqa: PLC0415

            img_count = max(len(material_blobs), int(getattr(preread, "pages", 1) or 1))
            ocr_route = _ocr_routing.should_use_api(session, img_count)
        except Exception:  # noqa: BLE001
            ocr_route = None
        result = run_analysis(
            data, password=password, template=template, preread=preread,
            thresholds=threshold_service.build_config(session),
            ocr_route=ocr_route,
        )

        # 临时标注没被采用时，必须在报告里说明——否则用户会以为解析用的是他那份标注
        temp_err = (task.check_result or {}).get("temp_template_error")
        if temp_err:
            reasons = list(temp_err.get("warnings") or [])
            if temp_err.get("error"):
                reasons.append(str(temp_err["error"]))
            head = (
                "本次指定的临时标注未通过校验，已改用模板库/通用解析（结论与手工标注口径可能不同）："
                if reasons else "本次指定的临时标注未生效，已改用模板库/通用解析"
            )
            note = head + ("；".join(reasons[:3]) if reasons else "")
            report_payload = result.get("report") or {}
            existing = list(report_payload.get("limitations") or [])
            report_payload["limitations"] = [note, *existing]

        file_row.carrier = result["carrier"]
        file_row.pages = result["pages"]
        file_row.has_text_layer = result["has_text_layer"]
        if not file_row.storage_path:
            file_row.storage_path = str(path)

        task.carrier = result["carrier"]
        header_meta = result.get("header_meta") or {}
        if not task.period_start and header_meta.get("period_start"):
            task.period_start = str(header_meta["period_start"])[:16]
        if not task.period_end and header_meta.get("period_end"):
            task.period_end = str(header_meta["period_end"])[:16]
        task.check_result = {
            **(task.check_result or {}),
            "warnings": result["warnings"],
            "self_check": result.get("self_check"),
            "preread": result.get("preread"),
            "header_meta": header_meta or None,
            "footer_count": result.get("footer_count"),
            "parse_coverage": result.get("parse_coverage"),
            "material_count": len(material_blobs),
            "ocr_route": result.get("ocr_route"),
        }
        task.finished_at = datetime.now()

        transition(task, "VERIFYING")
        transition(task, "REPORTING")

        session.query(Txn).filter(Txn.task_id == task.id).delete()
        session.query(MetricValue).filter(MetricValue.task_id == task.id).delete()

        for t in result["transactions"]:
            session.add(Txn(
                task_id=task.id, txn_date=t["txn_date"], direction=t["direction"],
                amount=None if t["amount"] is None else Decimal(t["amount"]),
                balance=None if t["balance"] is None else Decimal(t["balance"]),
                summary=t["summary"], counterparty_name=t["counterparty_name"],
                page_no=t["page_no"],
                confidence=None if t["confidence"] is None else Decimal(t["confidence"]),
                # 模板自定义字段的原始值（没有专列，只能存这里）
                extra=t.get("extra"),
            ))
        for m in result["metrics"]:
            session.add(MetricValue(
                task_id=task.id, metric_code=m["code"], metric_name=m["name"],
                value_num=None if m["value"] is None else Decimal(m["value"]),
                unit=m["unit"], note=m["note"], caliber_version=m["caliber_version"],
            ))
        # 模板不匹配检测：模板解析成功不代表模板适用。
        # 命中信号时标记出来，前端才能提示「可以临时标注补救」。
        try:
            from services.template_mismatch import detect_mismatch  # noqa: PLC0415
            from algorithm.ocr.models import Template as _T  # noqa: PLC0415

            _mm = detect_mismatch(result, template if isinstance(template, dict) else None)
            if _mm:
                task.check_result = dict(task.check_result or {})
                task.check_result["template_mismatch"] = _mm
        except Exception as _exc:  # noqa: BLE001
            pass

        report_row = result["report"]
        # run_analysis only sees a merged byte stream, so its default manifest cannot
        # identify supplements.  Restore the persisted material lineage here.
        report_row["materials"] = _build_material_manifest(material_blobs, password)
        from sqlalchemy import func as _sa_func  # noqa: PLC0415
        prev_ver = session.query(_sa_func.max(Report.version)).filter(Report.task_id == task.id).scalar() or 0
        session.add(Report(
            task_id=task.id, version=int(prev_ver) + 1, carrier=report_row["carrier"],
            verdict=report_row["verdict"], verdict_reason=report_row["verdict_reason"],
            layers=report_row["layers"], limitations=report_row["limitations"],
            evidence=report_row["evidence"], materials=report_row["materials"],
            metric_set_version=report_row["metric_set_version"],
            threshold_version=report_row["threshold_version"], payload=report_row,
            # 快通道出结果。慢通道（另一个引擎）会在系统空闲时复核，见 docs/快慢双通道解析设计.md
            verification={"status": "pending"},
        ))
        # 临时模板用完即弃：消费完成后清空 field_map_override，防止劫持后续正式模板重跑
        if getattr(task, "field_map_override", None):
            check_copy = dict(task.check_result or {})
            reparse_info = dict(check_copy.get("reparse") or {})
            reparse_info["temp_template_used"] = temp_template
            reparse_info["consumed"] = True
            check_copy["reparse"] = reparse_info
            task.check_result = check_copy
            task.field_map_override = None
        transition(task, "DONE")
        session.add(AuditLog(action="analyze_done", object_type="task", object_id=task.id,
                             detail=f"txn={result['txn_count']}"))
        _commit_with_retry(session)
        return {"task_id": task.id, "status": task.status, "txn_count": result["txn_count"]}
    except Exception as exc:  # noqa: BLE001
        session.rollback()
        try:
            task = session.get(Task, task_id)
            if task is not None:
                target = "FAILED"
                if str(getattr(task, "status")) in ("QUEUED", "CHECKING", "PARSING",
                                                    "VERIFYING", "REPORTING", "NEED_SUPPLEMENT"):
                    try:
                        transition(task, target)
                    except Exception:  # noqa: BLE001
                        task.status = target
                session.add(AuditLog(action="analyze_failed", object_type="task",
                                     object_id=task_id, detail=str(exc)[:200]))
                session.commit()
        except Exception:  # noqa: BLE001
            session.rollback()
        raise
    finally:
        session.close()
