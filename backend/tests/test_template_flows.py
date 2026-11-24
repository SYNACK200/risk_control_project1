"""回归测试：模板画布保存/试跑/发布/导入导出、布局渲染、账号管理与统一入口路由。"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pymupdf
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from db.models import AuditLog, Base, FileObj, Report, Task, Template, User  # noqa: E402
from db.session import get_session  # noqa: E402
from helpers.security import hash_password, issue_token  # noqa: E402
from main import app  # noqa: E402
from services.template_layout import render_page_png  # noqa: E402


def _make_sample_pdf_bytes() -> bytes:
    doc = pymupdf.open()
    page = doc.new_page(width=595, height=842)
    page.insert_text((48, 60), "Bank Statement Sample", fontsize=14)
    page.insert_text((48, 120), "Date        Summary       Amount      Balance", fontsize=11)
    page.insert_text((48, 150), "2025-01-02  Salary       +5000.00    15000.00", fontsize=11)
    page.insert_text((48, 175), "2025-01-05  Transfer      -320.00    14680.00", fontsize=11)
    data = doc.tobytes()
    doc.close()
    return data


def _make_sample_png_bytes() -> bytes:
    doc = pymupdf.open()
    page = doc.new_page(width=300, height=200)
    page.insert_text((20, 40), "2025-01-02 +100.00 500.00", fontsize=12)
    pix = page.get_pixmap()
    data = pix.tobytes("png")
    doc.close()
    return data


@pytest.fixture()
def isolated_client():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    TestingSession = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    seed = TestingSession()
    admin = User(
        username="test_admin",
        password_hash=hash_password("Admin@123"),
        role="banker",
        display_name="测试管理员",
        is_admin=True,
        status="active",
    )
    staff = User(
        username="test_staff",
        password_hash=hash_password("Staff@123"),
        role="banker",
        display_name="测试员工",
        is_admin=False,
        status="active",
    )
    seed.add_all([admin, staff])
    seed.commit()
    seed.refresh(admin)
    seed.refresh(staff)
    admin_token = issue_token(SimpleNamespace(id=admin.id, role="banker"))
    staff_token = issue_token(SimpleNamespace(id=staff.id, role="banker"))
    seed.close()

    def _override_session():
        db: Session = TestingSession()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_session] = _override_session
    try:
        with TestClient(app) as client:
            yield client, TestingSession, admin_token, staff_token
    finally:
        app.dependency_overrides.pop(get_session, None)
        engine.dispose()


def test_save_from_canvas_atomic_publish_duplicate_export_import(isolated_client):
    client, TestingSession, admin_token, _ = isolated_client
    admin_hdr = {"Authorization": f"Bearer {admin_token}"}
    pdf_bytes = _make_sample_pdf_bytes()
    layout_payload = {
        "page_size": {"w": 595, "h": 842},
        "page_count": 1,
        "tables": [
            {
                "page": 0,
                "slot": "first",
                "area": {"x": 0.05, "y": 0.12, "w": 0.9, "h": 0.7},
                "headerY": 0.16,
                "columns": [
                    {"field": "txn_date", "fields": ["txn_date"], "label": "交易日期", "x": 0.06, "w": 0.18},
                    {"field": "summary", "fields": ["summary"], "label": "摘要", "x": 0.25, "w": 0.22},
                    {"field": "amount", "fields": ["amount"], "label": "交易金额", "x": 0.48, "w": 0.18},
                    {"field": "balance", "fields": ["balance"], "label": "余额", "x": 0.68, "w": 0.18},
                ],
            }
        ],
        "meta_boxes": [],
        "custom_fields": [{"key": "channel", "label": "交易渠道"}],
    }
    field_map = {"txn_date": "交易日期", "summary": "摘要", "amount": "交易金额", "balance": "余额"}

    res = client.post(
        "/api/v1/templates/save-from-canvas",
        headers=admin_hdr,
        data={
            "bank_code": "CCB",
            "field_map": json.dumps(field_map),
            "layout": json.dumps(layout_payload),
            "required_fields": json.dumps(["txn_date", "amount", "balance"]),
            "publish": "true",
        },
        files={"file": ("ccb-sample.pdf", pdf_bytes, "application/pdf")},
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["bank_code"] == "CCB"
    assert body["version"] == 1
    assert body["status"] == "enabled"
    assert body["has_sample"] is True
    tid = body["id"]

    # 列表包含 has_layout / has_sample
    lst = client.get("/api/v1/templates", headers=admin_hdr)
    assert lst.status_code == 200
    row = next(r for r in lst.json() if r["id"] == tid)
    assert row["has_layout"] is True
    assert row["has_sample"] is True

    # 详情与样本下载
    sample = client.get(f"/api/v1/templates/{tid}/sample", headers=admin_hdr)
    assert sample.status_code == 200
    assert sample.content.startswith(b"%PDF")

    # 导出 + 导入保留 layout 与 required_fields
    exp = client.get(f"/api/v1/templates/{tid}/export", headers=admin_hdr)
    assert exp.status_code == 200
    exp_json = exp.json()
    assert exp_json["layout"]["tables"][0]["columns"][0]["field"] == "txn_date"
    assert exp_json["required_fields"] == ["txn_date", "amount", "balance"]

    imp = client.post("/api/v1/templates/import", headers=admin_hdr, json=exp_json)
    assert imp.status_code == 200
    imp_tid = imp.json()["id"]
    imp_detail = client.get(f"/api/v1/templates/{imp_tid}", headers=admin_hdr).json()
    assert imp_detail["layout"]["tables"][0]["headerY"] == 0.16
    assert imp_detail["required_fields"] == ["txn_date", "amount", "balance"]

    # 复制模板保留 layout 与 sample_file_id
    dup = client.post(f"/api/v1/templates/{tid}/duplicate", headers=admin_hdr)
    assert dup.status_code == 200
    dup_tid = dup.json()["id"]
    dup_detail = client.get(f"/api/v1/templates/{dup_tid}", headers=admin_hdr).json()
    assert dup_detail["sample_file_id"] is not None
    assert len(dup_detail["layout"]["tables"]) == 1

    # 发布 draft 模板仅写 1 条 publish_template 审计
    pub = client.post(f"/api/v1/templates/{dup_tid}/publish", headers=admin_hdr)
    assert pub.status_code == 200
    with TestingSession() as db:
        pub_logs = (
            db.query(AuditLog)
            .filter(AuditLog.action == "publish_template", AuditLog.object_id == dup_tid)
            .all()
        )
        assert len(pub_logs) == 1


def test_preview_draft_and_layout_png_for_pdf_and_image(isolated_client):
    client, _, _, staff_token = isolated_client
    staff_hdr = {"Authorization": f"Bearer {staff_token}"}
    pdf_bytes = _make_sample_pdf_bytes()
    png_bytes = _make_sample_png_bytes()

    layout_payload = {
        "page_count": 1,
        "tables": [
            {
                "page": 0,
                "slot": "first",
                "area": {"x": 0.04, "y": 0.10, "w": 0.90, "h": 0.70},
                "headerY": 0.16,
                "columns": [
                    {"field": "txn_date", "label": "交易日期", "x": 0.06, "w": 0.18},
                    {"field": "amount", "label": "交易金额", "x": 0.45, "w": 0.18},
                    {"field": "balance", "label": "余额", "x": 0.65, "w": 0.18},
                ],
            }
        ],
        "meta_boxes": [
            {"field": "account_no", "label": "卡号", "page": 0, "x": 0.1, "y": 0.05, "w": 0.25, "h": 0.03}
        ],
    }

    res = client.post(
        "/api/v1/templates/preview-draft",
        headers=staff_hdr,
        data={
            "bank_code": "CMB",
            "field_map": json.dumps({"txn_date": "日期", "amount": "金额", "balance": "余额"}),
            "layout": json.dumps(layout_payload),
            "required_fields": json.dumps(["txn_date", "amount", "balance"]),
        },
        files={"file": ("sample.pdf", pdf_bytes, "application/pdf")},
    )
    assert res.status_code == 200, res.text
    data = res.json()
    assert data["page_count"] == 1
    assert "meta" in data

    # render_page_png 支持 PDF 与 PNG 图片且能绘制新版 tables + meta_boxes
    rendered_pdf = render_page_png(pdf_bytes, layout_payload, page_no=0)
    assert rendered_pdf.startswith(b"\x89PNG")
    rendered_png = render_page_png(png_bytes, layout_payload, page_no=0)
    assert rendered_png.startswith(b"\x89PNG")


def test_user_crud_and_lab_proxy_auth(isolated_client, tmp_path: Path):
    client, TestingSession, admin_token, staff_token = isolated_client
    admin_hdr = {"Authorization": f"Bearer {admin_token}"}
    staff_hdr = {"Authorization": f"Bearer {staff_token}"}

    # 统一入口里 /api/v1/lab/operators 受银行侧登录保护
    assert client.get("/api/v1/lab/operators").status_code == 401
    lab_res = client.get("/api/v1/lab/operators", headers=staff_hdr)
    assert lab_res.status_code == 200
    assert len(lab_res.json().get("items", [])) > 0

    # 创建管理员、修改显示名与管理员标志、停用与恢复启用
    created = client.post(
        "/api/v1/auth/users",
        headers=admin_hdr,
        json={"username": "new_mgr", "password": "Password1", "display_name": "张经理", "role": "banker", "is_admin": True},
    )
    assert created.status_code in (200, 201), created.text
    uid = created.json()["user"]["id"]
    assert created.json()["user"]["is_admin"] is True

    patched = client.patch(f"/api/v1/auth/users/{uid}", headers=admin_hdr, json={"display_name": "李总监", "is_admin": False})
    assert patched.status_code == 200
    assert patched.json()["user"]["display_name"] == "李总监"
    assert patched.json()["user"]["is_admin"] is False

    disabled = client.delete(f"/api/v1/auth/users/{uid}", headers=admin_hdr)
    assert disabled.status_code == 200
    assert disabled.json()["status"] == "disabled"

    enabled = client.post(f"/api/v1/auth/users/{uid}/enable", headers=admin_hdr)
    assert enabled.status_code == 200
    assert enabled.json()["status"] == "active"

    # 已删除模板禁止用于 reanalyze
    pdf_file = tmp_path / "dummy.pdf"
    pdf_file.write_bytes(_make_sample_pdf_bytes())
    with TestingSession() as db:
        from datetime import datetime as _dt

        f_row = FileObj(sha256="a" * 64, carrier="pdf", storage_path=str(pdf_file), pages=1, has_text_layer=True)
        db.add(f_row)
        db.flush()
        t_row = Template(bank_code="ICBC", version=1, status="disabled", field_map={"txn_date": 0}, deleted_at=_dt.utcnow())
        task_row = Task(biz_no="BIZ_DEL_TPL_1", user_id=1, status="DONE", file_id=f_row.id)
        db.add_all([t_row, task_row])
        db.commit()
        db.refresh(t_row)
        db.refresh(task_row)
        reanalyze = client.post(
            f"/api/v1/tasks/{task_row.id}/reanalyze",
            headers=admin_hdr,
            data={"template_id": str(t_row.id)},
        )
        assert reanalyze.status_code == 404


def test_spa_root_serves_built_web_dist():
    with TestClient(app) as client:
        root = client.get("/")
        assert root.status_code == 200
        assert '<div id="root">' in root.text or "index-" in root.text
        health = client.get("/api/v1/health")
        assert health.status_code == 200


def test_borrower_isolation_and_state_guards(isolated_client, tmp_path: Path):
    from datetime import datetime as _dt

    client, TestingSession, admin_token, staff_token = isolated_client
    admin_hdr = {"Authorization": f"Bearer {admin_token}"}
    staff_hdr = {"Authorization": f"Bearer {staff_token}"}

    pdf_file = tmp_path / "iso.pdf"
    pdf_file.write_bytes(_make_sample_pdf_bytes())

    with TestingSession() as db:
        b1 = User(
            username="borrower_a",
            password_hash=hash_password("Pass123!"),
            role="borrower",
            display_name="借款人A",
            status="active",
        )
        b2 = User(
            username="borrower_b",
            password_hash=hash_password("Pass123!"),
            role="borrower",
            display_name="借款人B",
            status="active",
        )
        db.add_all([b1, b2])
        db.flush()

        f1 = FileObj(sha256="b" * 64, carrier="pdf", storage_path=str(pdf_file), pages=1, has_text_layer=True)
        db.add(f1)
        db.flush()

        t_done = Task(
            biz_no="BIZ_ISO_DONE",
            user_id=b1.id,
            status="DONE",
            carrier="pdf",
            file_id=f1.id,
            failure_code="E_INTERNAL_PARSE",
            check_result={"preread": {"bank_name": "招商银行"}, "internal_debug": "secret"},
        )
        t_need = Task(
            biz_no="BIZ_ISO_NEED",
            user_id=b1.id,
            status="NEED_SUPPLEMENT",
            carrier="pdf",
            file_id=f1.id,
            failure_code="E_ENCRYPT",
        )
        t_parsing = Task(
            biz_no="BIZ_ISO_RUN",
            user_id=b1.id,
            status="PARSING",
            carrier="pdf",
            file_id=f1.id,
        )
        t_trashed = Task(
            biz_no="BIZ_ISO_TRASH",
            user_id=b1.id,
            status="DONE",
            carrier="pdf",
            file_id=f1.id,
            deleted_at=_dt.utcnow(),
        )
        db.add_all([t_done, t_need, t_parsing, t_trashed])
        db.flush()

        db.add(
            Report(
                task_id=t_done.id,
                version=1,
                verdict="HIGH_RISK",
                payload={"verdict": "HIGH_RISK", "custom_field_stats": [{"field": "channel", "count": 2, "numeric": 0, "sum": None, "avg": None, "samples": ["ATM"]}]},
            )
        )
        active_tpl = Template(
            bank_code="SPDB",
            version=1,
            status="enabled",
            field_map={"txn_date": 0, "amount": 1, "balance": 2},
            required_fields=["txn_date", "amount", "balance"],
        )
        db.add(active_tpl)
        db.commit()

        b1_hdr = {"Authorization": f"Bearer {issue_token(SimpleNamespace(id=b1.id, role='borrower'))}"}
        b2_hdr = {"Authorization": f"Bearer {issue_token(SimpleNamespace(id=b2.id, role='borrower'))}"}
        done_id = t_done.id
        need_id = t_need.id
        parsing_id = t_parsing.id
        trashed_id = t_trashed.id
        active_tpl_id = active_tpl.id

    # 1. Borrower forbidden from reports / metrics / transactions / banker actions
    assert client.get(f"/api/v1/reports/{done_id}", headers=b1_hdr).status_code == 403
    assert client.get(f"/api/v1/tasks/{done_id}/metrics", headers=b1_hdr).status_code == 403
    assert client.get(f"/api/v1/tasks/{done_id}/transactions", headers=b1_hdr).status_code == 403
    assert client.get(f"/api/v1/tasks/{done_id}/export.json", headers=b1_hdr).status_code == 403
    assert client.get(f"/api/v1/tasks/{done_id}/file", headers=b1_hdr).status_code == 403
    assert client.post(f"/api/v1/tasks/{done_id}/reanalyze", headers=b1_hdr).status_code == 403
    assert client.post(f"/api/v1/tasks/{done_id}/whitelist", headers=b1_hdr, data={"reason": "test"}).status_code == 403
    assert client.post("/api/v1/tasks/merge", headers=b1_hdr, json={"task_ids": [done_id, need_id], "mode": "net_internal"}).status_code == 403

    # 2. Borrower GET /tasks sanitizes payload and ignores trash=1
    lst = client.get("/api/v1/tasks?trash=1", headers=b1_hdr)
    assert lst.status_code == 200
    body = lst.json()
    assert body["facets"] == {}
    listed_ids = {item["id"] for item in body["items"]}
    assert done_id in listed_ids
    assert trashed_id not in listed_ids
    for item in body["items"]:
        # consent_at / consent_version 是后续批次加的授权留痕字段，属预期新增
        assert set(item.keys()) == {
            "id", "biz_no", "status", "carrier", "created_at", "bank_name",
            "period_start", "period_end", "consent_at", "consent_version",
        }
        assert "verdict" not in item
        assert "risk" not in item

    # 3. Borrower GET /tasks/{id} masks internal check_result & non-safe failure_code
    detail_done = client.get(f"/api/v1/tasks/{done_id}", headers=b1_hdr).json()
    assert "check_result" not in detail_done
    assert detail_done["failure_code"] is None
    detail_need = client.get(f"/api/v1/tasks/{need_id}", headers=b1_hdr).json()
    assert detail_need["failure_code"] == "E_ENCRYPT"
    assert client.get(f"/api/v1/tasks/{trashed_id}", headers=b1_hdr).status_code == 404

    # 4. Cross-user supplement rejected with 404
    sup_cross = client.post(
        f"/api/v1/tasks/{need_id}/supplement",
        headers=b2_hdr,
        files={"file": ("sup.pdf", _make_sample_pdf_bytes(), "application/pdf")},
    )
    assert sup_cross.status_code == 404

    # 5. Banker trash=1 returns soft-deleted tasks; reparse validates task state
    trash_res = client.get("/api/v1/tasks?trash=1", headers=admin_hdr)
    assert trash_res.status_code == 200
    assert any(item["id"] == trashed_id for item in trash_res.json()["items"])

    bad_running = client.post(
        f"/api/v1/tasks/{parsing_id}/reparse",
        headers=admin_hdr,
        data={"marks": json.dumps([{"field": "txn_date", "x": 0.1, "y": 0.2}])},
    )
    assert bad_running.status_code == 409

    bad_transition = client.post(
        f"/api/v1/tasks/{need_id}/reparse",
        headers=admin_hdr,
        data={"marks": json.dumps([{"field": "txn_date", "x": 0.1, "y": 0.2}])},
    )
    # 第二批 B4 起，NEED_SUPPLEMENT -> QUEUED 是合法迁移（补件后重跑），
    # 所以从「需补件」状态发起重解析不再是 400，而应被受理
    assert bad_transition.status_code in (200, 202)

    # 6. Non-admin save-from-canvas draft must not disable existing enabled template
    layout_spdb = {
        "page_count": 1,
        "tables": [
            {
                "page": 0,
                "slot": "first",
                "area": {"x": 0.04, "y": 0.1, "w": 0.9, "h": 0.7},
                "headerY": 0.16,
                "columns": [
                    {"field": "txn_date", "label": "日期", "x": 0.06, "w": 0.18},
                    {"field": "amount", "label": "金额", "x": 0.45, "w": 0.18},
                    {"field": "balance", "label": "余额", "x": 0.65, "w": 0.18},
                    {"field": "counterparty_name", "label": "对手户名", "x": 0.25, "w": 0.18},
                ],
            }
        ],
        "meta_boxes": [],
    }
    staff_save = client.post(
        "/api/v1/templates/save-from-canvas",
        headers=staff_hdr,
        data={
            "bank_code": "SPDB",
            "template_id": str(active_tpl_id),
            "field_map": json.dumps({"txn_date": 0, "amount": 1, "balance": 2, "counterparty_name": 3}),
            "layout": json.dumps(layout_spdb),
            "required_fields": json.dumps(["txn_date", "amount", "balance", "counterparty"]),
            "publish": "true",
        },
    )
    assert staff_save.status_code == 200, staff_save.text
    assert staff_save.json()["status"] == "draft"
    active_after = client.get(f"/api/v1/templates/{active_tpl_id}", headers=admin_hdr).json()
    assert active_after["status"] == "enabled"
