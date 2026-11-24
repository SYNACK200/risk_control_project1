"""倾斜校正：把拍照/扫描件的歪斜在坐标层掰正。

为什么在坐标层做而不是重绘图片：
- 重采样一次就多一次画质损失，还会让 OCR 置信度整体下滑；
- 下游算法（锚点扩散、切行）只吃「词 + 坐标」，把坐标转正与把图转正是等价的；
- 转坐标是纯算术，可单测，不需要图像依赖。

做法：邻近词对的斜率中位数。
同一行里横向相邻的两个词，它们连线与水平线的夹角就是版式的倾斜角；
不同行的词对会被「纵向距离必须小于一个字高」挡掉。
用中位数而不是均值：OCR 总有把两个字并成一个框、或把一个词切两半的情况，均值会被它们带跑。

为什么不用投影残差法：试过。稀疏页面上每个词自成一簇，残差恒等于 0，对角度完全没有分辨力
（实测 27 个词的图片件，-6° 到 +6° 的残差都在 0.2~0.7 之间）。
"""
from __future__ import annotations

import math
from dataclasses import replace

from .words import PageWords, Word

MAX_ANGLE = 10.0          # 超过 10 度就不是歪，是别的版式，不猜
STEP = 0.25
LINE_TOL = 3.0


def _median(values: list[float]) -> float:
    ordered = sorted(values)
    size = len(ordered)
    middle = size // 2
    if size % 2:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / 2


def _angle_from_words(words: list[Word]) -> float | None:
    """OCR 的四点框自带方向：直接取中位数，比词对斜率稳得多。

    词对斜率要靠「同一行的两个词」去反推方向，一旦字被切并或漏识别就会估反；
    而每个词自己的方向是独立测出来的，噪声只会让中位数抖一点点。
    """
    angles = [word.angle for word in words if word.angle is not None]
    if len(angles) < max(4, len(words) // 2):
        return None
    angles.sort()
    middle = len(angles) // 2
    median = angles[middle] if len(angles) % 2 else (angles[middle - 1] + angles[middle]) / 2
    return round(-median, 2)      # 词的方向取反，就是该施加的校正角


def estimate_angle(pages: list[PageWords]) -> float:
    """返回整份文件该施加的校正角（度）：正数表示逆时针掰。"""
    words = [w for page in pages for w in page.words]
    if len(words) < 8:
        return 0.0

    from_boxes = _angle_from_words(words)
    if from_boxes is not None:
        return from_boxes if abs(from_boxes) <= MAX_ANGLE else 0.0

    heights = sorted(w.bottom - w.top for w in words)
    body_height = heights[len(heights) // 2]
    # 参数是扫出来的，不是拍的：横向 20 倍字高、纵向 0.8 倍字高。
    # 纵向卡紧是为了把「不同行」的词对挡在外面——行距通常是 2~3 倍字高，0.8 倍足够安全；
    # 横向放宽是因为一行里的词可能隔得很远（日期在最左、余额在最右），卡太紧会一对都取不到。
    # 实测：文本层倾斜 ±2°/±5° 全对，OCR 旋转 3° 估成 2.7°、旋转 -4° 估成 -4.05°。
    max_dx = body_height * 20
    max_dy = body_height * 0.8

    slopes: list[float] = []
    for index, first in enumerate(words):
        for second in words[index + 1:]:
            dx = second.cx - first.cx
            dy = second.cy - first.cy
            if 0 < dx <= max_dx and abs(dy) <= max_dy:
                slopes.append(dy / dx)
    if len(slopes) < 4:
        return 0.0

    slope = _median(slopes)
    angle = -math.degrees(math.atan(slope))
    if abs(angle) > MAX_ANGLE:
        return 0.0
    return round(angle, 2)


def rotate_words(page: PageWords, angle_deg: float) -> PageWords:
    """绕页心旋转所有词框，返回新的一页（原对象不动）。"""
    if abs(angle_deg) < 1e-6:
        return page
    theta = math.radians(angle_deg)   # estimate_angle 返回的就是「该施加的角度」
    cos_t, sin_t = math.cos(theta), math.sin(theta)
    cx, cy = page.width / 2, page.height / 2

    def turn(x: float, y: float) -> tuple[float, float]:
        dx, dy = x - cx, y - cy
        return cx + dx * cos_t - dy * sin_t, cy + dx * sin_t + dy * cos_t

    turned: list[Word] = []
    for word in page.words:
        if word.oriented is None:
            x0, y0 = turn(word.x0, word.top)
            x1, y1 = turn(word.x1, word.bottom)
            turned.append(replace(
                word,
                x0=min(x0, x1), x1=max(x0, x1),
                top=min(y0, y1), bottom=max(y0, y1),
            ))
            continue
        # 有固有尺寸的词：只转中心，尺寸保持不变（掰正之后字就是横的）
        centre_x, centre_y = turn((word.x0 + word.x1) / 2, (word.top + word.bottom) / 2)
        length, thickness = word.oriented
        turned.append(replace(
            word,
            x0=centre_x - length / 2, x1=centre_x + length / 2,
            top=centre_y - thickness / 2, bottom=centre_y + thickness / 2,
            angle=0.0,
        ))
    return PageWords(page_no=page.page_no, width=page.width, height=page.height,
                     words=turned, has_text=page.has_text)


def deskew_pages(pages: list[PageWords], *, min_angle: float = 0.75) -> tuple[list[PageWords], float]:
    """估计并校正整份文件；角度太小视作噪声不动。返回 (新页列表, 实际校正角)。"""
    angle = estimate_angle(pages)
    if abs(angle) < min_angle:
        return pages, 0.0
    return [rotate_words(page, angle) for page in pages], angle
