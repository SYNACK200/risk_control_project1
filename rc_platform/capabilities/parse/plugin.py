"""解析能力（兼容实现）：把文件读成逐笔明细。

M1 直接复用封存版本的 algorithm.ocr.parse（三级保底）。
M2 起多了一条 parse.layout_v2（用新版式驱动解析），两者可通过 overrides 切换对照。
"""
from __future__ import annotations

from ...compat.native import statement_from_parsed
from ...core.paths import ensure_root_on_path
from ...core.registry import capability

ensure_root_on_path()


def _template_from_config(cfg: dict | None):
    if not cfg:
        return None
    from algorithm.ocr.models import Template as ParseTemplate

    return ParseTemplate(
        bank_code=str(cfg.get("bank_code", "UNKNOWN")),
        version=int(cfg.get("version", 1)),
        field_map=dict(cfg.get("field_map") or {}),
        layout=cfg.get("layout"),
    )


@capability
class AlgorithmParser:
    """兼容层：用封存版本的三级保底解析读明细。"""

    name = "parse.algorithm_compat"
    version = "1.0"
    provides = "statement"
    requires = ("document", "profile")
    priority = 10   # M2 阶段仍是默认；parse.layout_v2 用 overrides 指定后做对照

    def run(self, ctx, inputs):
        from algorithm.ocr.parse import parse as parse_document

        doc = inputs["document"]
        template = _template_from_config(ctx.setting("parse.template"))
        parsed = parse_document(doc.data, template)
        return statement_from_parsed(parsed)
