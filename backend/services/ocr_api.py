"""PaddleOCR 云端 API 的并发封装。

为什么值得用云端 API：**它是 I/O 密集的**。
本地 PaddleOCR 跑模型是 CPU 密集，受 GIL 卡死，并行只有开销没有收益（2026-11-07 实测过，见 CHANGELOG）。
换成 HTTP 请求后，线程在等网络时会让出 GIL，多张图/多页并发提交才有真正的加速。

API 是异步任务制：POST 提交拿 jobId → 轮询 GET 拿 resultUrl → 下载 JSON。
凭据在 ~/.dsh/ocr/paddle.json，**不入库、不进仓库**。
"""
from __future__ import annotations

import json
import os
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import requests

BASE = os.environ.get("PADDLEOCR_BASE_URL", "https://paddleocr.aistudio-app.com").rstrip("/")
JOBS = BASE + "/api/v2/ocr/jobs"
CONF = Path(os.path.expanduser("~")) / ".dsh" / "ocr" / "paddle.json"

# 并发上限。2026-11-07 实测：
#   并发 1 → 8.6s/张；并发 2 → 4.4s/张（提速 95%）；并发 4 → 188s 且出现 180s 轮询超时。
# 结论：服务端对并发敏感，2 是这里的甜点，4 会排队到超时。不要凭直觉往上加。
MAX_WORKERS = int(os.environ.get("PADDLEOCR_WORKERS", "2"))
POLL_INTERVAL = 2.0
POLL_TIMEOUT = float(os.environ.get("PADDLEOCR_TIMEOUT", "180"))


class OcrApiError(RuntimeError):
    pass


def _token() -> str:
    tok = os.environ.get("PADDLEOCR_ACCESS_TOKEN")
    if tok:
        return tok
    try:
        return json.loads(CONF.read_text(encoding="utf-8")).get("token") or ""
    except Exception as exc:  # noqa: BLE001
        raise OcrApiError("读不到 PaddleOCR 凭据（~/.dsh/ocr/paddle.json）") from exc


def _session() -> requests.Session:
    s = requests.Session()
    s.headers["Authorization"] = "Bearer " + _token()
    return s


def _check(resp: requests.Response) -> dict:
    if resp.status_code in (401, 403):
        raise OcrApiError("PaddleOCR token 无效或过期")
    if resp.status_code == 429:
        raise OcrApiError("PaddleOCR 限流（429），降低并发或稍后重试")
    if resp.status_code >= 400:
        raise OcrApiError("PaddleOCR HTTP %d: %s" % (resp.status_code, resp.text[:200]))
    payload = resp.json()
    if payload.get("code") not in (0, None):
        raise OcrApiError("PaddleOCR 返回错误：" + str(payload.get("msg") or payload)[:200])
    data = payload.get("data")
    if not isinstance(data, dict):
        raise OcrApiError("PaddleOCR 响应缺少 data")
    return data


def submit(session: requests.Session, name: str, content: bytes, model: str = "PP-OCRv6",
           pages: str | None = None) -> str:
    data = {"model": model, "optionalPayload": "{}"}
    if pages:
        data["pageRanges"] = pages
    resp = session.post(JOBS, data=data, files={"file": (name, content)}, timeout=120)
    job_id = _check(resp).get("jobId")
    if not job_id:
        raise OcrApiError("PaddleOCR 没有返回 jobId")
    return str(job_id)


def wait(session: requests.Session, job_id: str, timeout: float = POLL_TIMEOUT) -> str:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        data = _check(session.get(JOBS + "/" + job_id, timeout=60))
        state = (data.get("state") or "").lower()
        if state == "failed":
            raise OcrApiError("PaddleOCR 任务失败：" + str(data.get("errorMsg") or "")[:200])
        if state == "done":
            url = (data.get("resultUrl") or {}).get("jsonUrl")
            if not url:
                raise OcrApiError("PaddleOCR 完成但没有 resultUrl")
            return url
        time.sleep(POLL_INTERVAL)
    raise OcrApiError("PaddleOCR 轮询超时（%.0fs）" % timeout)


def fetch_lines(url: str) -> list[dict]:
    """下载结果 JSON，抽出文本行（text / 坐标 / 置信度）。"""
    resp = requests.get(url, timeout=120)
    resp.raise_for_status()
    raw = resp.json()
    lines: list[dict] = []
    # 结果可能是 jsonl 或 {result: {layoutParsingResults: [...]}}
    items = raw if isinstance(raw, list) else raw.get("result", {}).get("ocrResults") or []
    if not isinstance(items, list):
        items = []
    for item in items:
        for entry in (item.get("ocrResult") or []) if isinstance(item, dict) else []:
            pass
        pr = item.get("prunedResult") if isinstance(item, dict) else None
        if isinstance(pr, dict):
            for text, conf in zip(pr.get("rec_texts") or [], pr.get("rec_scores") or []):
                lines.append({"text": str(text), "confidence": float(conf)})
    return lines


def ocr_one(content: bytes, name: str = "page.jpg", model: str = "PP-OCRv6",
            pages: str | None = None) -> list[dict]:
    s = _session()
    try:
        job_id = submit(s, name, content, model, pages=pages)
        return fetch_lines(wait(s, job_id))
    finally:
        s.close()


def ocr_many(items: list[tuple[str, bytes]], model: str = "PP-OCRv6",
             workers: int = MAX_WORKERS) -> list[list[dict]]:
    """并发识别多张图/多页。

    这是整个模块存在的理由：HTTP 等待期间线程让出 GIL，
    8 张图串行约 8×15s，并发 4 大约只要 2 轮 ≈ 30s。
    """
    if not items:
        return []
    out: list[list[dict]] = [None] * len(items)  # type: ignore[list-item]

    def one(idx: int) -> None:
        name, content = items[idx]
        try:
            out[idx] = ocr_one(content, name, model)
        except Exception as exc:  # noqa: BLE001
            out[idx] = [{"text": "", "confidence": 0.0, "error": str(exc)[:120]}]

    with ThreadPoolExecutor(max_workers=max(1, min(workers, len(items)))) as ex:
        list(ex.map(one, range(len(items))))
    return out


def available() -> bool:
    return CONF.exists() or bool(os.environ.get("PADDLEOCR_ACCESS_TOKEN"))