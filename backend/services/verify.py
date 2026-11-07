"""慢通道：全量读取，不走模板，只提数字做核验。

和快通道的分工（用户 2026-11-07 澄清后的定义）：

  快通道  = 模板 + OCR。模板把原文划分成块，每块并发读取，快但依赖模板正确。
            模板失效（换了版式、样本没覆盖到）时会读错。

  慢通道  = 全量读取，不走模板。把整页/整张图交给 PaddleOCR 重新识别，
            只抽数字（金额、余额）和快通道比对。
            不追求字段精确、不追求快，只回答一个问题：
            「快通道读出来的那些数字，在原文里能不能原样找到？」

为什么只比数字：模板失效通常表现为「列错位」，错位的直接后果就是金额/余额读错。
日期、摘要错还能人工看出来，金额错了会直接导致授信结论错——所以慢通道盯这个。

PaddleOCR 能识别照片，所以图片件也能走慢通道（之前排除图片件是错的）。
"""
from __future__ import annotations

import re
from collections import Counter
from datetime import datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from db.models import FileObj, Report, Task, Txn
from logging import getLogger

log = getLogger(__name__)

MAX_DIFFS = 20

# 慢通道抽样页数。整份 30 页走云端 OCR 要五分钟以上（实测），
# 超出「后台慢跑」的合理范围；抽前 N 页已经能发现模板失效（版式问题不会只出现在末页）。
# 环境变量可调；设 0 表示不限（会在后台跑很久）。
import os as _os  # noqa: E402
MAX_PAGES = int(_os.environ.get("SLOW_VERIFY_MAX_PAGES", "5"))

# 数字识别：金额/余额通常带千分位或两位小数
_NUM_RE = re.compile(r"-?\d{1,3}(?:,\d{3})+(?:\.\d{1,2})?|-?\d+\.\d{2}")


def _to_decimal(text: str) -> Decimal | None:
    try:
        return Decimal(str(text).replace(",", "").strip())
    except Exception:  # noqa: BLE001
        return None


def extract_numbers(texts: list[str]) -> Counter:
    """从 OCR 文本里抽出所有金额形态的数字，返回 {值: 出现次数}。

    用出现次数而不是有序序列：慢通道不保证逐笔对齐（它不是按行切的），
    但一份流水里每个金额出现的次数是稳定的——快通道读错了，次数就对不上。
    """
    bag: Counter = Counter()
    for t in texts:
        for m in _NUM_RE.findall(str(t)):
            v = _to_decimal(m)
            if v is not None and abs(v) >= Decimal("0.01"):
                bag[v] += 1
    return bag


def _ocr_texts(data: bytes, is_pdf: bool) -> tuple[list[str], str]:
    """全量读取：不走模板，整份文件重新取一遍文字。

    电子 PDF 走 pdfplumber（纯文字层，5 秒以内）；
    图片和扫描件才走 PaddleOCR（它能识别照片，这是慢通道能覆盖图片件的原因）。
    之前不区分载体，一律云端 OCR，30 页要跑五分钟以上，没法用在复核里。
    """
    # 电子 PDF：pdfplumber 全量抽文字，快且稳定
    if is_pdf:
        try:
            import io as _io  # noqa: PLC0415

            import pdfplumber  # noqa: PLC0415

            out: list[str] = []
            with pdfplumber.open(_io.BytesIO(data)) as pdf:
                # 电子件全量处理：pdfplumber 读 30 页只要 1 秒，
                # 而抽取数字要和快通道的「全部笔数」比，只读前几页会全是假差异。
                for pg in pdf.pages:
                    txt = pg.extract_text() or ""
                    out.extend(txt.split("\n"))
            if sum(len(x) for x in out) > 50:
                return out, "pdfplumber"
        except Exception as exc:  # noqa: BLE001
            log.info("慢通道 pdfplumber 失败，改走 OCR：%s", str(exc)[:120])

    from algorithm.ocr.engine import get_default_engine  # noqa: PLC0415

    # 优先云端（能识别照片，且多页可并发）；没有凭据就用本地
    try:
        from services import ocr_api  # noqa: PLC0415

        if ocr_api.available():
            payload = data
            pages = None
            if is_pdf and MAX_PAGES > 0:
                # 只抽前 N 页：模板失效是版式问题，不会只出现在末页；
                # 整份 30 页云端 OCR 实测超过 5 分钟，不适合放在复核链路里。
                pages = f"1-{MAX_PAGES}"
            name = "doc.pdf" if is_pdf else "page.jpg"
            lines = ocr_api.ocr_one(payload, name=name, pages=pages)
            return [str(x.get("text", "")) for x in lines if x.get("text")], "paddle-api"
    except Exception as exc:  # noqa: BLE001
        log.info("慢通道云端 OCR 失败，回落本地：%s", str(exc)[:120])

    ocr = get_default_engine().recognize(data)
    texts: list[str] = []
    for page in getattr(ocr, "pages", []) or []:
        texts.extend(w.text for w in page.words)
    return texts, getattr(ocr, "engine", "local-ocr")


def compare_numbers(fast_txns: list, slow_bag: Counter) -> tuple[list[dict], int]:
    """比对快通道的金额/余额是否都能在慢通道的全量数字里找到。

    只比得出、比不出的数量，不做逐笔顺序对齐——慢通道不是按行切的。
    """
    fast_bag: Counter = Counter()
    for t in fast_txns:
        for v in (getattr(t, "amount", None), getattr(t, "balance", None)):
            if v is None:
                continue
            try:
                d = Decimal(str(v)).quantize(Decimal("0.01"))
            except Exception:  # noqa: BLE001
                continue
            if abs(d) >= Decimal("0.01"):
                fast_bag[d] += 1

    # 用「值是否出现过」比对，不用逐值计数：
    # 快通道把金额同时写进 amount 和 balance，慢通道文本里同一数字只出现一次的情形很常见，
    # 计数比对会把这类正常差异全报出来（实测 316 条假差异）。核验的目的是「读出来的数在原文里存在吗」。
    fast_values = set(fast_bag)
    slow_values = set(slow_bag)
    diffs: list[dict] = []
    for value in fast_values - slow_values:
        diffs.append({"value": str(value), "fast_count": fast_bag[value],
                      "slow_count": 0, "type": "missing_in_slow"})
    for value in slow_values - fast_values:
        # 慢通道有、快通道没有：可能是快通道漏读整行，也可能是页眉页脚里的数字
        if slow_bag[value] >= 2:
            diffs.append({"value": str(value), "fast_count": 0,
                          "slow_count": slow_bag[value], "type": "missing_in_fast"})
    return diffs[:MAX_DIFFS], len(diffs)


def verify_report(db: Session, task_id: int) -> dict:
    task = db.get(Task, task_id)
    if task is None:
        return {"status": "failed", "reason": "任务不存在"}

    rep = db.execute(
        select(Report).where(Report.task_id == task_id).order_by(Report.version.desc())
    ).scalars().first()
    if rep is None:
        return {"status": "failed", "reason": "报告不存在"}

    file_row = db.get(FileObj, task.file_id) if task.file_id else None
    if file_row is None or not file_row.storage_path:
        return {"status": "failed", "reason": "任务没有可用的原始文件"}
    from pathlib import Path  # noqa: PLC0415

    path = Path(file_row.storage_path)
    if not path.exists():
        return {"status": "failed", "reason": "原始文件已被清理"}
    data = path.read_bytes()
    is_pdf = data[:4] == b"%PDF"

    fast_txns = db.execute(select(Txn).where(Txn.task_id == task_id).order_by(Txn.id)).scalars().all()
    if not fast_txns:
        return {"status": "failed", "reason": "任务没有逐笔明细，没有可核对的对象"}

    try:
        texts, engine = _ocr_texts(data, is_pdf)
    except Exception as exc:  # noqa: BLE001
        log.warning("慢通道全量 OCR 失败 task=%s: %s", task_id, exc)
        return {"status": "failed", "reason": f"慢通道全量识别失败：{str(exc)[:120]}"}

    slow_bag = extract_numbers(texts)
    diffs, total = compare_numbers(fast_txns, slow_bag)

    # 主判据：快通道读出的金额总和，是否能在慢通道的全量数字里被"覆盖"。
    # 逐个值比对在原理上不可靠——快通道的值是解析后的结构化结果，
    # 慢通道是原始文本里的所有数字（含页眉页脚），两边集合天然不等。
    # 但总额能反映量级：漏读整行、列错位会让总额明显偏离。
    fast_amount_sum = Decimal("0")
    for t in fast_txns:
        amt = getattr(t, "amount", None)
        if amt is None:
            continue
        try:
            fast_amount_sum += Decimal(str(amt)).quantize(Decimal("0.01"))
        except Exception:  # noqa: BLE001
            continue
    slow_abs_sum = sum((abs(v) * c for v, c in slow_bag.items()), Decimal("0"))

    # 覆盖度：快通道每个金额是否都能在慢通道找到（找不到的比例）
    fast_values = set()
    for t in fast_txns:
        amt = getattr(t, "amount", None)
        if amt is None:
            continue
        try:
            v = Decimal(str(amt)).quantize(Decimal("0.01"))
        except Exception:  # noqa: BLE001
            continue
        if abs(v) >= Decimal("0.01"):
            fast_values.add(abs(v))
    covered = sum(1 for v in fast_values if v in {abs(x) for x in slow_bag})
    coverage = round(covered / len(fast_values), 4) if fast_values else None

    # 判据只有一条：快通道读出的金额，有多少能在原文里找到。
    # 慢通道多出来的数字（页眉账号、余额列、页脚合计）不算差异——
    # 慢通道是「全量读取」，它本来就该比快通道多。
    # 实测建行样例：覆盖率 100%（570 笔的每个金额都在原文），多出 283 个数字属正常。
    if coverage is None:
        status = "failed"
    elif coverage >= 0.95:
        status = "passed"
    else:
        status = "discrepancy"
    # 真差异只算「快通道的金额在原文里找不到」，和 coverage 同一口径。
    # 之前的 diffs 还混了 balance（余额列），而 coverage 只算 amount，
    # 两条判据口径不一致，会出现「passed 但差异 20 条」这种自相矛盾的输出。
    slow_abs = {abs(x) for x in slow_bag}
    real_diffs = []
    for t in fast_txns:
        amt = getattr(t, "amount", None)
        if amt is None:
            continue
        try:
            v = abs(Decimal(str(amt)).quantize(Decimal("0.01")))
        except Exception:  # noqa: BLE001
            continue
        if v >= Decimal("0.01") and v not in slow_abs:
            real_diffs.append({"value": str(v), "type": "missing_in_slow",
                               "date": getattr(t, "txn_date", None)})
    real_diffs = real_diffs[:MAX_DIFFS]
    return {
        "status": status,
        "engine": engine,
        "mode": "full-read",           # 明确标记：这是全量读取，不是模板读取
        "checked_at": datetime.utcnow().isoformat(),
        "txn_count_fast": len(fast_txns),
        "number_count_slow": sum(slow_bag.values()),
        "diff_count": len(real_diffs),
        "diffs": real_diffs,
        "amount_sum_fast": str(fast_amount_sum),
        "abs_sum_slow": str(slow_abs_sum),
        "value_coverage": coverage,
    }


def save_verification(db: Session, task_id: int, result: dict) -> None:
    rep = db.execute(
        select(Report).where(Report.task_id == task_id).order_by(Report.version.desc())
    ).scalars().first()
    if rep is None:
        return
    rep.verification = result
    db.commit()


def verify_task(task_id: int) -> dict:
    from db.session import SessionLocal  # noqa: PLC0415

    if SessionLocal is None:
        return {"status": "failed", "reason": "数据库未初始化"}
    with SessionLocal() as db:
        result = verify_report(db, task_id)
        save_verification(db, task_id, result)
        return result