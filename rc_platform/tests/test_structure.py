"""结构守卫的测试：能力包缺说明书要能被自动发现。

这条测试存在的理由不是「检查 README」，而是把「交付物清点」变成机器能做的动作——
M3 那次就是代码与测试都在、文档没落盘，测试全绿却交付不完整。
"""
from __future__ import annotations

from rc_platform.core.registry import discover
from rc_platform.tools.check_structure import check


def test_every_capability_package_documents_itself():
    discover()
    problems = check()
    assert problems == [], "能力包缺少说明书：\n" + "\n".join(problems)
