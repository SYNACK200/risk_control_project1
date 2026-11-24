"""文本比较：contains / matches / in_lexicon。

它们都产出「一列真假」，与 where= 组合——和 zscore 的安排一样：
算子只负责「哪些行命中」，至于命中之后求和还是计数，交给聚合算子。

缺列时返回全空，不返回全假：没读到摘要 ≠ 摘要里没有这些词。
"""
from __future__ import annotations

import re

from . import lexicon
from .operators import NUMERIC, OperatorError, Series, operator
from .operators import column as column_of


def _rows(x) -> list:
    from .operators import Frame

    if isinstance(x, Frame):
        return list(x.rows)
    raise OperatorError(f"这个算子需要数据帧，收到 {type(x).__name__}")


def _texts(rows, column_name: str) -> list[str | None]:
    return [getattr(row, column_name, None) for row in rows]


def _mask(values: list[bool | None], *, name: str, total: int, notes) -> Series:
    if values and all(value is None for value in values):
        if notes is not None:
            notes.append(f"缺列：{name}（该列在全部交易上都没有值）")
        return Series(name="mask", values=[None] * total, frame=None)
    return Series(name="mask", values=values, frame=None)


@operator("contains", family=NUMERIC, kind="window", unit="笔", compat=False,
          detail="文本列是否包含某个词（忽略大小写与空白）；任一列空则该行返回空。",
          params=[{"name": "word", "type": "str", "default": ""},
                  {"name": "column", "type": "str", "default": "summary"}])
def op_contains(x, *, word="", column="summary", notes=None):
    rows = _rows(x)
    target = (word or "").strip().lower()
    if not target:
        raise OperatorError("contains 需要 word 参数")
    values: list[bool | None] = []
    for text in _texts(rows, column):
        if text is None or str(text).strip() == "":
            values.append(None)
            continue
        values.append(target in str(text).replace(" ", "").lower())
    return _mask(values, name=column, total=len(rows), notes=notes)


@operator("matches", family=NUMERIC, kind="window", unit="笔", compat=False,
          detail="文本列是否匹配正则（用于「贷[\s\S]{0,4}款」这类模糊写法）；正则写错直接报错。",
          params=[{"name": "pattern", "type": "str", "default": ""},
                  {"name": "column", "type": "str", "default": "summary"}])
def op_matches(x, *, pattern="", column="summary", notes=None):
    rows = _rows(x)
    if not pattern:
        raise OperatorError("matches 需要 pattern 参数")
    try:
        regex = re.compile(pattern)
    except re.error as exc:
        raise OperatorError(f"正则写错了：{exc}") from exc
    values: list[bool | None] = []
    for text in _texts(rows, column):
        if text is None or str(text).strip() == "":
            values.append(None)
            continue
        values.append(bool(regex.search(str(text))))
    return _mask(values, name=column, total=len(rows), notes=notes)


@operator("in_lexicon", family=NUMERIC, kind="window", unit="笔", compat=False,
          detail="文本列是否命中词库（词库可本地覆盖，带版本）；词库名见 library。",
          params=[{"name": "name", "type": "str", "default": "salary"},
                  {"name": "column", "type": "str", "default": "summary"}])
def op_in_lexicon(x, *, name="salary", column="summary", notes=None):
    rows = _rows(x)
    try:
        words = lexicon.resolve(name)
    except KeyError as exc:
        raise OperatorError(f"没有这个词库：{name}") from exc
    lowered = [word.replace(" ", "").lower() for word in words]

    values: list[bool | None] = []
    for text in _texts(rows, column):
        if text is None or str(text).strip() == "":
            values.append(None)
            continue
        body = str(text).replace(" ", "").lower()
        values.append(any(word in body for word in lowered))
    return _mask(values, name=column, total=len(rows), notes=notes)
