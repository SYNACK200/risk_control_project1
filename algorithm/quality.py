"""上传件质量评估：判断这份材料「能不能被可靠识别」，并给出可执行的处置建议。

为什么需要：
    模板外推、OCR、列切分都假设材料是「正、直、清晰」的。现实里的拍照件常常倾斜、
    带透视、光线不均。以前把这些问题暴露成识别失败，等于把责任甩给客户；
    正确做法是先量出来，能在容忍范围内的自己纠正（纠偏/透视校正），超出范围的明确告知。

检测什么（都不依赖 OCR，纯图像几何）：
    1. 框线笔直度与倾斜角  —— 表单框线应当水平/垂直，偏差即倾斜
    2. 透视程度            —— 左右两组竖线是否平行，不平行说明是斜拍
    3. 框线完整度          —— 横线总长占图像宽度比例，太低说明线条断裂/缺失
    4. 清晰度              —— 拉普拉斯方差，过低说明模糊
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np


@dataclass
class QualityReport:
    """一份材料的质量体检结果。"""
    level: str = "unknown"           # good / fair / poor / unknown
    score: float = 0.0               # 0-100
    skew_deg: float = 0.0            # 表格整体倾斜角，正=顺时针
    perspective: float = 0.0         # 左右竖线夹角差（度），越大越像斜拍
    line_coverage: float = 0.0       # 横线总长 / 图像宽度
    sharpness: float = 0.0           # 拉普拉斯方差
    h_lines: int = 0
    v_lines: int = 0
    issues: list[str] = field(default_factory=list)
    recommended: str = "ok"          # ok / deskew / perspective / reshoot
    corrected_deg: float = 0.0       # 已自动纠正的角度（0 表示没纠正）

    def to_dict(self) -> dict:
        return {
            "level": self.level,
            "score": round(self.score, 1),
            "skew_deg": round(self.skew_deg, 2),
            "perspective": round(self.perspective, 2),
            "line_coverage": round(self.line_coverage, 3),
            "sharpness": round(self.sharpness, 1),
            "h_lines": self.h_lines,
            "v_lines": self.v_lines,
            "issues": self.issues,
            "recommended": self.recommended,
            "corrected_deg": round(self.corrected_deg, 2),
        }


# 阈值（经验值，后续可用真实样本调）
SKEW_OK = 0.6          # 倾斜 <= 0.6 度视为正
SKEW_FIXABLE = 5.0     # 倾斜 <= 5 度可以自动纠偏
PERSPECTIVE_OK = 0.8   # 左右竖线夹角差 <= 0.8 度视为无透视
PERSPECTIVE_FIXABLE = 4.0
COVERAGE_MIN = 0.55    # 横线覆盖度低于此值说明框线很弱
SHARPNESS_MIN = 60.0   # 拉普拉斯方差低于此值认为偏糊


def _decode(image_bytes: bytes) -> "np.ndarray | None":
    import cv2

    arr = np.frombuffer(image_bytes, dtype=np.uint8)
    return cv2.imdecode(arr, cv2.IMREAD_COLOR)


def _page_image(file_bytes: bytes, page: int = 0, dpi: int = 150) -> "np.ndarray | None":
    """取某一页的图像：图片直接解码，PDF 渲染首页（无文字层时才需要，这里统一渲染）。"""
    if not file_bytes:
        return None
    if file_bytes[:4] == b"%PDF":
        try:
            import pymupdf

            with pymupdf.open(stream=file_bytes, filetype="pdf") as doc:
                if not doc:
                    return None
                pg = doc[min(page, len(doc) - 1)]
                pix = pg.get_pixmap(dpi=dpi)
                import cv2

                arr = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)
                if pix.n == 4:
                    return cv2.cvtColor(arr, cv2.COLOR_RGBA2BGR)
                if pix.n == 3:
                    return cv2.cvtColor(arr, cv2.COLOR_RGB2BGR)
                return cv2.cvtColor(arr, cv2.COLOR_GRAY2BGR)
        except Exception:  # noqa: BLE001
            return None
    return _decode(file_bytes)


def _line_angles(gray: "np.ndarray") -> tuple[list[float], list[float], float]:
    """返回 (横线角度列表, 竖线角度列表, 横线总长/图宽)。角度单位为度。"""
    import cv2

    edges = cv2.Canny(gray, 60, 180, apertureSize=3)
    h, w = gray.shape[:2]
    min_len = max(40, int(w * 0.12))
    lines = cv2.HoughLinesP(edges, 1, np.pi / 180, threshold=80,
                            minLineLength=min_len, maxLineGap=8)
    h_angles: list[float] = []
    v_angles: list[float] = []
    h_len = 0.0
    if lines is None:
        return h_angles, v_angles, 0.0
    # 不同 OpenCV 版本返回形状不一致（(N,1,4) / (N,4) / 扁平），统一成 (N,4)
    segs = np.asarray(lines, dtype=np.float64).reshape(-1, 4)
    for x1, y1, x2, y2 in segs:
        dx, dy = float(x2 - x1), float(y2 - y1)
        if dx == 0 and dy == 0:
            continue
        angle = float(np.degrees(np.arctan2(dy, dx)))
        if abs(dx) >= abs(dy):
            # 横线：角度归一到 ±90
            a = angle if angle <= 90 else angle - 180
            a = a if a >= -90 else a + 180
            h_angles.append(a)
            h_len += abs(dx)
        else:
            # 竖线：相对垂直方向的偏差
            a = angle - 90 if angle > 0 else angle + 90
            v_angles.append(a)
    return h_angles, v_angles, min(1.0, h_len / w)


def assess(file_bytes: bytes, page: int = 0) -> QualityReport:
    """评估一份材料（PDF 首屏或单张图片）的质量。"""
    import cv2

    report = QualityReport()
    img = _page_image(file_bytes, page=page)
    if img is None:
        report.level = "unknown"
        report.issues.append("无法解码图像，质量未评估")
        return report

    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    h_angles, v_angles, coverage = _line_angles(gray)
    report.h_lines = len(h_angles)
    report.v_lines = len(v_angles)
    report.line_coverage = coverage
    report.sharpness = float(cv2.Laplacian(gray, cv2.CV_64F).var())

    if len(h_angles) >= 3:
        report.skew_deg = float(np.median(h_angles))
    if len(v_angles) >= 4:
        # 左半与右半竖线的中位角度差 → 透视程度
        left = np.median(v_angles[: len(v_angles) // 2])
        right = np.median(v_angles[len(v_angles) // 2:])
        report.perspective = float(abs(left - right))

    issues: list[str] = []
    skew = abs(report.skew_deg)
    if skew > SKEW_FIXABLE:
        issues.append(f"倾斜 {skew:.1f}°，超出可自动纠正范围（≤{SKEW_FIXABLE:.0f}°）")
    elif skew > SKEW_OK:
        issues.append(f"轻微倾斜 {skew:.1f}°，可自动纠正")
    if report.perspective > PERSPECTIVE_FIXABLE:
        issues.append(f"透视 {report.perspective:.1f}°，左右竖线明显不平行（斜拍）")
    elif report.perspective > PERSPECTIVE_OK:
        issues.append(f"轻微透视 {report.perspective:.1f}°，可自动校正")
    if coverage < COVERAGE_MIN:
        issues.append(f"框线覆盖度 {coverage:.0%}，表格线可能断裂或被遮挡")
    if report.sharpness < SHARPNESS_MIN:
        issues.append(f"清晰度偏低（Laplacian {report.sharpness:.0f}），文字可能糊")
    if report.h_lines < 3:
        issues.append("几乎检测不到横线：可能不是表单/表格，或线条太淡")

    report.issues = issues

    # 评分：倾斜、透视、框线、清晰度四项加权
    score = 100.0
    score -= min(40.0, skew * 6)
    score -= min(30.0, report.perspective * 5)
    score -= max(0.0, (COVERAGE_MIN - coverage) * 80)
    score -= max(0.0, (SHARPNESS_MIN - report.sharpness) / SHARPNESS_MIN * 25)
    report.score = max(0.0, min(100.0, score))

    if report.score >= 80:
        report.level = "good"
        report.recommended = "ok"
    elif report.score >= 55:
        report.level = "fair"
        report.recommended = "deskew" if skew <= SKEW_FIXABLE else "perspective"
    else:
        report.level = "poor"
        report.recommended = "reshoot" if (skew > SKEW_FIXABLE or report.perspective > PERSPECTIVE_FIXABLE) else "deskew"
    return report


def deskew(file_bytes: bytes, max_deg: float = 5.0) -> tuple[bytes, float]:
    """按检测到的倾斜角把图像转正，返回 (新图片字节, 实际纠正角度)。

    只处理图片；PDF 由调用方先渲染成图片再判断是否需要纠偏。
    """
    import cv2

    img = _page_image(file_bytes)
    if img is None:
        return file_bytes, 0.0
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    h_angles, _v, _c = _line_angles(gray)
    if len(h_angles) < 3:
        return file_bytes, 0.0
    angle = float(np.median(h_angles))
    if abs(angle) < SKEW_OK or abs(angle) > max_deg:
        return file_bytes, 0.0
    h, w = img.shape[:2]
    matrix = cv2.getRotationMatrix2D((w / 2, h / 2), angle, 1.0)
    rotated = cv2.warpAffine(img, matrix, (w, h), flags=cv2.INTER_CUBIC,
                             borderMode=cv2.BORDER_REPLICATE)
    ok, buf = cv2.imencode(".png", rotated)
    if not ok:
        return file_bytes, 0.0
    return buf.tobytes(), angle