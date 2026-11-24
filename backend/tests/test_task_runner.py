from types import SimpleNamespace

from services.task_runner import _build_material_manifest


def test_report_material_manifest_preserves_original_and_supplement_lineage():
    materials = _build_material_manifest([
        ("original", b"not-a-pdf", SimpleNamespace(id=11, sha256="origin-sha")),
        ("supplement", b"also-not-a-pdf", SimpleNamespace(id=22, sha256="supplement-sha")),
    ])

    assert materials == [
        {"file_id": 11, "role": "original", "pages": 1, "sha256": "origin-sha"},
        {"file_id": 22, "role": "supplement", "pages": 1, "sha256": "supplement-sha"},
    ]
