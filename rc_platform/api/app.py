"""特征 Lab 的最小 API：算子目录、内置特征目录、表达式试算。

为什么先只做这三件事：特征 Lab 要回答的是「这个口径写出来是什么值」，
不需要任务、报告、权限那一整套。等 M6-7 把正式 API 接起来，这几个路由会挂进同一个应用。

安全边界：仅监听 127.0.0.1，只对**合成样本**试算，不接触真实客户流水；没有鉴权。
正式上线前必须换成带鉴权的路由，并只允许登录用户对自己有权的数据试算。
"""
from __future__ import annotations

import pathlib
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from rc_platform.capabilities.features import expr as expr_mod
from rc_platform.capabilities.features.library import feature_catalog, operator_catalog
from rc_platform.capabilities.features.operators import Frame, Series
from rc_platform.core.context import JobContext
from rc_platform.core.contracts import DocumentProfile, SourceDocument
from rc_platform.core.pipeline import Pipeline
from rc_platform.core.registry import default_registry
from rc_platform.lab import store as lab_store

ROOT = pathlib.Path(__file__).resolve().parents[2]
SAMPLES = ROOT / "algorithm" / "inputs" / "samples" / "synthetic"

router = APIRouter()
app = FastAPI(title="特征 Lab", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:5175", "http://localhost:5175"],
    allow_methods=["*"],
    allow_headers=["*"],
)

_STATEMENT_CACHE: dict[str, Any] = {}


class EvaluateRequest(BaseModel):
    sample: str
    expr: str | None = None
    code: str | None = None        # 也可以直接跑一条已保存的自定义特征


class CustomFeatureRequest(BaseModel):
    code: str
    name: str
    expr: str
    unit: str = ""
    description: str = ""


def _sample_path(name: str) -> pathlib.Path:
    candidate = (SAMPLES / name).resolve()
    if not str(candidate).startswith(str(SAMPLES.resolve())) or not candidate.exists():
        raise HTTPException(404, detail={"code": "E_NOT_FOUND", "message": f"样本不存在：{name}"})
    return candidate


def _statement(name: str):
    """解析一份样本并缓存：表达式试算要反复跑，不能每次都重新解析。"""
    if name in _STATEMENT_CACHE:
        return _STATEMENT_CACHE[name]
    path = _sample_path(name)
    statement = _statement_from_bytes(path.read_bytes(), name)
    _STATEMENT_CACHE[name] = statement
    return statement


def _dated_ratio(statement) -> float:
    rows = list(getattr(statement, "rows", []) or [])
    if not rows:
        return 0.0
    return sum(1 for r in rows if getattr(r, "txn_date", None)) / len(rows)


def _statement_from_bytes(data: bytes, name: str):
    registry = default_registry()
    plan = registry.plan("statement", overrides={"statement": "parse.layout_v2"})
    result = Pipeline(registry, plan, on_error="degrade").run(
        JobContext(job_id=name),
        {"document": SourceDocument(data=data, filename=name), "profile": DocumentProfile(carrier="electronic")},
    )
    statement = result.get("statement")
    if statement is None:
        raise HTTPException(422, detail={"code": "E_PARSE", "message": "这份文件解析失败：" + "；".join(result.degradation)})

    # layout_v2 对部分真实银行件只能切出行、抓不到日期列（实测建行 30 页件 txn_date 全空），
    # 一旦没日期，所有时间类特征（夜间/月度/休眠/近 N 天）都算不出，Lab 里看着像坏的。
    # 这类件改用主项目那套解析器兜底——它带模板与表头定位，日期列认得出来。
    if data[:4] == b"%PDF" and _dated_ratio(statement) < 0.5:
        recovered = _statement_from_legacy(data, statement)
        if recovered is not None and _dated_ratio(recovered) > _dated_ratio(statement):
            return recovered
    return statement


def _statement_from_legacy(data: bytes, current):
    """用主项目解析器再解析一遍，转成平台侧 Statement；失败返回 None。"""
    from decimal import Decimal

    from rc_platform.core.contracts import Statement, TxnRow

    try:
        from algorithm.ocr.parse import parse as parse_pdf  # noqa: PLC0415
    except Exception:  # noqa: BLE001
        return None
    try:
        parsed = parse_pdf(data, None)
    except Exception:  # noqa: BLE001
        return None
    txns = list(getattr(parsed, "transactions", []) or [])
    if not txns:
        return None
    rows = []
    for item in txns:
        amount = getattr(item, "amount", None)
        balance = getattr(item, "balance", None)
        rows.append(
            TxnRow(
                txn_date=getattr(item, "txn_date", None),
                trade_time=getattr(item, "trade_time", None),
                reference_no=getattr(item, "reference_no", None),
                summary=getattr(item, "summary", None),
                counterparty_name=getattr(item, "counterparty_name", None),
                direction=getattr(item, "direction", None),
                amount=None if amount in (None, "") else Decimal(str(amount)),
                balance=None if balance in (None, "") else Decimal(str(balance)),
            )
        )
    return Statement(rows=rows)


def _json_safe(value):
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, Series):
        return [_json_safe(item) for item in value.values]
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, dict):
        return {key: _json_safe(item) for key, item in value.items()}
    return value


# --------------------------------------------------------------------------
# 特征 API：把「所有特征」做成对外接口
#
# 三层：目录（有哪些）/ 详情（怎么算）/ 计算（算出值）。
# 内置 24 个与自定义特征走同一套返回结构，调用方不需要知道哪个是内置的。
# --------------------------------------------------------------------------


class ComputeRequest(BaseModel):
    codes: list[str] | None = None            # 空 = 全部
    rows: list[dict[str, Any]] | None = None  # 直接给交易行，省一次解析
    sample: str | None = None                 # 或给合成样本名（仅本地试用）


def _feature_defs():
    from rc_platform.capabilities.features.defs import FeatureDef, builtin_features

    defs = list(builtin_features())
    for record in lab_store.list_features():
        try:
            defs.append(FeatureDef(code=record["code"], name=record["name"], expr=record["expr"],
                                   unit=record.get("unit") or "", version=str(record.get("version", 1))))
        except Exception:  # noqa: BLE001 - 坏定义不该让整个目录挂掉
            continue
    return defs


def _rows_from_payload(rows: list[dict[str, Any]]):
    from decimal import Decimal

    from rc_platform.core.contracts import TxnRow

    out = []
    for raw in rows:
        amount = raw.get("amount")
        balance = raw.get("balance")
        out.append(
            TxnRow(
                txn_date=raw.get("txn_date"),
                trade_time=raw.get("trade_time"),
                reference_no=raw.get("reference_no"),
                summary=raw.get("summary"),
                counterparty_name=raw.get("counterparty_name") or raw.get("counterparty"),
                direction=raw.get("direction"),
                amount=None if amount in (None, "") else Decimal(str(amount)),
                balance=None if balance in (None, "") else Decimal(str(balance)),
            )
        )
    return out


@router.get("/api/v1/features")
def list_feature_defs():
    from rc_platform.capabilities.features.defs import compute  # noqa: F401  确保包已注册算子

    items = []
    for definition in _feature_defs():
        try:
            items.append(definition.describe())
        except Exception:  # noqa: BLE001
            continue
    return {"count": len(items), "items": items}


@router.get("/api/v1/features/{code}")
def get_feature_def(code: str):
    for definition in _feature_defs():
        if definition.code == code:
            return definition.describe()
    raise HTTPException(404, detail={"code": "E_NOT_FOUND", "message": f"没有这个特征：{code}"})


@router.post("/api/v1/features/compute")
def compute_features(request: ComputeRequest):
    """给一批交易行（或一份合成样本）算特征；算不出来的把原因写在 reason 里。"""
    from rc_platform.capabilities.features.defs import compute
    from rc_platform.core.contracts import Statement

    if request.rows is None and request.sample is None:
        raise HTTPException(422, detail={"code": "E_PARAM", "message": "rows 与 sample 至少给一个"})

    rows = _rows_from_payload(request.rows) if request.rows is not None else list(_statement(request.sample).rows)
    defs = _feature_defs()
    if request.codes:
        wanted = set(request.codes)
        defs = [item for item in defs if item.code in wanted]
        missing = wanted - {item.code for item in defs}
        if missing:
            raise HTTPException(404, detail={"code": "E_NOT_FOUND", "message": "没有这些特征：" + "、".join(sorted(missing))})

    result = compute(defs, Statement(rows=rows))
    return {
        "rows": len(rows),
        "count": len(result.records),
        "version": result.version,
        "features": [
            {**record, "value": _json_safe(record.get("value"))} for record in result.records
        ],
    }


@router.post("/api/v1/features/compute-file")
async def compute_features_from_file(
    file: UploadFile,
    codes: str | None = Form(None),
    password: str | None = Form(None),
):
    """上传一份流水（PDF）直接算特征：解析 + 计算一次完成（支持加密 PDF 口令）。"""
    from rc_platform.capabilities.features.defs import compute

    data = await file.read()
    if not data:
        raise HTTPException(400, detail={"code": "E_PARAM", "message": "文件为空"})
    if data[:4] == b"%PDF":
        try:
            import pymupdf as _fitz  # noqa: PLC0415

            doc = _fitz.open(stream=data, filetype="pdf")
            try:
                if doc.needs_pass:
                    if not password or doc.authenticate(password) <= 0:
                        raise HTTPException(400, detail={"code": "E_ENCRYPT", "message": "PDF 受口令保护，请提供正确口令"})
                    data = doc.tobytes(encryption=_fitz.PDF_ENCRYPT_NONE)
            finally:
                doc.close()
        except HTTPException:
            raise
        except Exception:  # noqa: BLE001
            pass
    statement = _statement_from_bytes(data, file.filename or "upload.pdf")
    defs = _feature_defs()
    if codes:
        wanted = {item.strip() for item in codes.split(",") if item.strip()}
        defs = [item for item in defs if item.code in wanted]
    result = compute(defs, statement)
    return {
        "rows": len(statement.rows),
        "count": len(result.records),
        "version": result.version,
        "features": [{**record, "value": _json_safe(record.get("value"))} for record in result.records],
    }


@router.get("/api/v1/lab/operators")
def list_operators():
    return {"items": operator_catalog()}


@router.get("/api/v1/lab/features")
def list_features():
    return {"items": feature_catalog()}


@router.get("/api/v1/lab/samples")
def list_samples():
    if not SAMPLES.exists():
        return {"items": []}
    return {
        "items": [
            {
                "name": path.relative_to(SAMPLES).as_posix(),
                "group": path.parent.name,
            }
            for path in sorted(SAMPLES.rglob("*.pdf"))
        ]
    }


@router.post("/api/v1/lab/inspect-file")
async def inspect_upload(file: UploadFile, password: str | None = Form(None), ocr_page: int = Form(0)):
    from rc_platform.capabilities.layout import inspect as layout_inspect

    data = await file.read()
    if not data:
        raise HTTPException(400, detail={"code": "E_PARAM", "message": "文件为空"})
    try:
        return layout_inspect.inspect(data, password, ocr_page=max(0, ocr_page))
    except ValueError as exc:
        # 口令问题单独一个码：前端据此弹口令输入框，而不是报「版式分析失败」
        raise HTTPException(400, detail={"code": "E_ENCRYPT", "message": str(exc)}) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(422, detail={"code": "E_INSPECT", "message": f"版式分析失败：{exc}"}) from exc


@router.post("/api/v1/lab/spread-file")
async def spread_upload(
    file: UploadFile,
    keyword: str = Form(...),
    password: str | None = Form(None),
    page_index: int | None = Form(None),
):
    from rc_platform.capabilities.layout import inspect as layout_inspect

    data = await file.read()
    if not data:
        raise HTTPException(400, detail={"code": "E_PARAM", "message": "文件为空"})
    try:
        return layout_inspect.spread(data, keyword, page_index=page_index, password=password)
    except ValueError as exc:
        raise HTTPException(400, detail={"code": "E_ENCRYPT", "message": str(exc)}) from exc


@router.get("/api/v1/lab/sample-file")
def sample_file(sample: str):
    from fastapi.responses import FileResponse

    path = _sample_path(sample)
    return FileResponse(path, media_type="application/pdf")


@router.get("/api/v1/lab/inspect")
def inspect_sample(sample: str, ocr_page: int = 0):
    from rc_platform.capabilities.layout import inspect as layout_inspect

    data = _sample_path(sample).read_bytes()
    return layout_inspect.inspect(data, ocr_page=max(0, ocr_page))


@router.get("/api/v1/lab/spread")
def spread_keyword(sample: str, keyword: str, page_index: int | None = None):
    from rc_platform.capabilities.layout import inspect as layout_inspect

    data = _sample_path(sample).read_bytes()
    return layout_inspect.spread(data, keyword, page_index=page_index)


@router.get("/api/v1/lab/custom")
def list_custom(include_history: bool = False):
    return {"items": lab_store.list_features(include_history=include_history)}


@router.post("/api/v1/lab/custom")
def save_custom(request: CustomFeatureRequest):
    try:
        return lab_store.save_feature(
            request.code, request.name, request.expr, unit=request.unit, description=request.description
        )
    except lab_store.LabFeatureError as exc:
        raise HTTPException(422, detail={"code": "E_FEATURE", "message": str(exc)}) from exc


@router.delete("/api/v1/lab/custom/{code}")
def delete_custom(code: str):
    return {"code": code, "deleted": lab_store.delete_feature(code)}


@router.post("/api/v1/lab/evaluate")
def evaluate(request: EvaluateRequest):
    expression = request.expr
    if not expression and request.code:
        record = lab_store.current(request.code)
        if record is None:
            raise HTTPException(404, detail={"code": "E_NOT_FOUND", "message": f"没有这条自定义特征：{request.code}"})
        expression = record["expr"]
    if not expression:
        raise HTTPException(422, detail={"code": "E_PARAM", "message": "expr 与 code 至少给一个"})

    statement = _statement(request.sample)
    frame = Frame(list(statement.rows))
    notes: list[str] = []
    try:
        value = expr_mod.eval_expr(expression, frame, notes=notes)
    except expr_mod.ExprError as exc:
        raise HTTPException(422, detail={"code": "E_EXPR", "message": str(exc)}) from exc
    except Exception as exc:  # noqa: BLE001 - 算子层面的错误要原样告诉调用方
        raise HTTPException(422, detail={"code": "E_OP", "message": str(exc)}) from exc

    preview = None
    if isinstance(value, Series):
        preview = [_json_safe(item) for item in value.values[:20]]

    return {
        "expr": expression,
        "value": _json_safe(value),
        "type": type(value).__name__,
        "notes": notes,
        "preview": preview,
        "rows": len(statement.rows),
    }


app.include_router(router)
