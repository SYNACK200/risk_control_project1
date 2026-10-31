"""OCR 包入口：默认只暴露解析与数据模型。

影像件才需要的引擎（numpy/onnx 依赖）改为惰性加载，
这样纯电子件环境（如服务器）装最小依赖也能跑通解析。
"""
from .models import (
    HeaderField,
    MetaBox,
    PageHeader,
    PageSummary,
    ParseResult,
    Template,
    Transaction,
)
from .parse import OcrUnavailable, parse
from .template_convert import ConversionResult, convert_annotation

_LAZY = {
    "OcrEngine",
    "OcrPage",
    "OcrResult",
    "OcrWord",
    "RapidOCREngine",
    "get_default_engine",
}

__all__ = [
    "ConversionResult",
    "HeaderField",
    "MetaBox",
    "OcrUnavailable",
    "PageHeader",
    "PageSummary",
    "ParseResult",
    "Template",
    "Transaction",
    "convert_annotation",
    "parse",
    *_LAZY,
]


def __getattr__(name: str):
    if name in _LAZY:
        from . import engine

        return getattr(engine, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
