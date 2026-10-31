import fitz

from algorithm.algo import FileBaseline, analyze_file
from algorithm.algo.file_layer import _check_incremental


LINES = [
    "中国工商银行借记账户历史明细",
    "账号：6222****1234  户名：张三",
    "2026-06-21  消费  10.00  90.00",
    "2026-06-20  工资  5000.00  5090.00",
    "2026-06-19  转账  100.00  4990.00",
    "第 1 页 / 共 1 页",
]


def make_pdf(
    *,
    producer: str = "BankCore Export 1.0",
    creator: str = "BankCore",
    hidden: bool = False,
    overlay: bool = False,
    page_sizes: list[tuple[float, float]] | None = None,
) -> bytes:
    doc = fitz.open()
    for width, height in page_sizes or [(595, 842)]:
        page = doc.new_page(width=width, height=height)
        for index, line in enumerate(LINES):
            page.insert_text((72, 80 + 20 * index), line, fontsize=12)
        if hidden:
            page.insert_text((72, 240), "hidden 9999.00", fontsize=12, render_mode=3)
        if overlay:
            page.draw_rect(fitz.Rect(70, 68, 400, 84), color=None, fill=(1, 1, 1), overlay=True)
    doc.set_metadata(
        {
            "producer": producer,
            "creator": creator,
            "author": "中国工商银行",
            "creationDate": "D:20260101120000+08'00'",
            "modDate": "D:20260101120005+08'00'",
        }
    )
    data = doc.tobytes()
    doc.close()
    return data


def make_incremental_pdf(tmp_path) -> bytes:
    path = tmp_path / "incremental.pdf"
    doc = fitz.open()
    doc.new_page()
    doc.save(path)
    doc.close()

    doc = fitz.open(path)
    doc.new_page()
    doc.save(path, incremental=True, encryption=fitz.PDF_ENCRYPT_KEEP)
    doc.close()
    return path.read_bytes()


def make_signed_bytes(append: bytes = b"") -> bytes:
    head = b"%PDF-1.3\n" + b"x" * 100 + b"\n%%EOF\nstartxref\n"
    contents = b"<" + b"0" * 40 + b">"
    tail = b"\n%%EOF\n"
    second_start = 0
    for _ in range(3):
        sigdict = b"/Type/Sig /ByteRange [0 %d %d %d]" % (len(head), second_start, len(tail))
        second_start = len(head) + len(sigdict) + len(contents)
    sigdict = b"/Type/Sig /ByteRange [0 %d %d %d]" % (len(head), second_start, len(tail))
    return head + sigdict + contents + tail + append


def make_image_pdf(rect: fitz.Rect) -> bytes:
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    for index in range(4):
        page.insert_text((80, 100 + 12 * index), f"row {index} 10.00", fontsize=8)
    pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 16, 16), False)
    pix.clear_with(200)
    page.insert_image(rect, pixmap=pix)
    doc.set_metadata(
        {
            "producer": "BankCore Export 1.0",
            "creationDate": "D:20260101120000+08'00'",
            "modDate": "D:20260101120005+08'00'",
        }
    )
    data = doc.tobytes()
    doc.close()
    return data


def check(result, code):
    return next(item for item in result.checks if item.code == code)


def test_clean_electronic_file_has_no_source_suspicion():
    result = analyze_file(make_pdf())
    assert result.status == "limited"
    assert result.outcome is None
    assert check(result, "F1").status == "pass"
    assert check(result, "F2").status == "pass"
    assert check(result, "F3").status == "pass"
    assert check(result, "F5").status == "pass"
    assert check(result, "F6").status == "pass"
    assert check(result, "F7").status == "pass"
    assert check(result, "F9").status == "pass"
    assert check(result, "F11").status == "pass"
    assert check(result, "F4").status == "skipped"
    assert check(result, "F10").status == "skipped"
    assert any("F8" in line for line in result.limitations)


def test_office_producer_is_source_suspicious():
    result = analyze_file(make_pdf(producer="Microsoft Word 2019"))
    f1 = check(result, "F1")
    assert f1.status == "fail"
    assert "办公/在线工具" in f1.detail
    assert result.status == "fail" and result.outcome == "来源可疑"


def test_pdf_editor_producer_is_partial_not_source_suspicious():
    result = analyze_file(make_pdf(producer="Foxit PDF Editor"))
    assert check(result, "F1").status == "partial"
    assert result.status == "limited"
    assert result.outcome is None


def test_incremental_update_is_source_suspicious(tmp_path):
    result = analyze_file(make_incremental_pdf(tmp_path))
    f3 = check(result, "F3")
    assert f3.status == "fail"
    assert "%%EOF" in f3.detail
    assert result.outcome == "来源可疑"


def test_signature_revision_is_partial_not_source_suspicious():
    f3 = _check_incremental(make_signed_bytes())
    assert f3.status == "partial"
    assert "数字签名" in f3.detail


def test_append_after_signature_is_source_suspicious():
    f3 = _check_incremental(make_signed_bytes(append=b"tampered" * 40))
    assert f3.status == "fail"
    assert "签名后" in f3.detail


def test_long_modification_gap_is_source_suspicious():
    doc = fitz.open()
    doc.new_page()
    doc.set_metadata(
        {
            "producer": "BankCore Export 1.0",
            "creationDate": "D:20260101120000+08'00'",
            "modDate": "D:20260103120000+08'00'",
        }
    )
    result = analyze_file(doc.tobytes())
    doc.close()
    assert check(result, "F2").status == "fail"
    assert result.outcome == "来源可疑"


def test_hidden_text_single_hit_is_recorded_not_blocking():
    result = analyze_file(make_pdf(hidden=True))
    assert check(result, "F6").status == "fail"
    assert result.status == "limited"
    assert result.outcome is None
    assert any("单项命中" in line for line in result.limitations)


def test_overlay_single_hit_is_recorded_not_blocking():
    result = analyze_file(make_pdf(overlay=True))
    assert check(result, "F7").status == "fail"
    assert result.status == "limited"
    assert result.outcome is None


def test_large_seal_image_is_recorded_not_treated_as_patch():
    result = analyze_file(make_image_pdf(fitz.Rect(70, 88, 190, 160)))
    f7 = check(result, "F7")
    assert f7.status == "partial"
    assert "印章" in f7.detail
    assert result.outcome is None


def test_small_image_patch_still_fails():
    result = analyze_file(make_image_pdf(fitz.Rect(70, 88, 160, 104)))
    assert check(result, "F7").status == "fail"
    assert result.outcome is None


def test_two_layout_hits_are_source_suspicious():
    result = analyze_file(make_pdf(hidden=True, overlay=True))
    assert check(result, "F6").status == "fail"
    assert check(result, "F7").status == "fail"
    assert result.outcome == "来源可疑"


def test_page_size_mismatch_hits_layout():
    result = analyze_file(make_pdf(page_sizes=[(595, 842), (595, 900)]))
    f9 = check(result, "F9")
    assert f9.status == "fail"
    assert "尺寸" in f9.detail
    assert result.outcome is None


def test_full_page_image_with_text_is_recorded_only():
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 64, 64), False)
    pix.clear_with(200)
    page.insert_image(page.rect, pixmap=pix)
    for index, line in enumerate(LINES):
        page.insert_text((72, 80 + 20 * index), line, fontsize=12)
    doc.set_metadata({"producer": "BankCore Export 1.0"})
    data = doc.tobytes()
    doc.close()

    result = analyze_file(data)
    assert check(result, "F11").status == "fail"
    assert result.status == "limited"
    assert result.outcome is None
    assert any("仅记录" in line for line in result.limitations)


def test_baseline_enables_structure_and_volume_checks():
    data = make_pdf()
    doc = fitz.open(stream=data, filetype="pdf")
    families = {
        font[3].split("+")[-1]
        for page in doc
        for font in page.get_fonts(full=True)
    }
    baseline = FileBaseline(
        producer="BankCore Export",
        creator="BankCore",
        page_sizes=[(595.0, 842.0)],
        font_families=sorted(families),
        bytes_per_page=len(data),
    )
    doc.close()

    result = analyze_file(data, baseline=baseline)
    assert check(result, "F4").status == "pass"
    assert check(result, "F10").status == "pass"

    mismatched = baseline.model_copy(update={"producer": "OtherBank"})
    result = analyze_file(data, baseline=mismatched)
    assert check(result, "F4").status == "fail"
    assert result.outcome == "来源可疑"


def test_image_carrier_and_non_pdf_skip_structure_forensics():
    image_result = analyze_file(b"\xff\xd8\xff", carrier="image")
    assert image_result.status == "skipped"
    assert "影像件" not in image_result.detail or "不做结构取证" in image_result.detail

    text_result = analyze_file(b"not a pdf")
    assert text_result.status == "skipped"
    assert "非 PDF" in text_result.detail


def make_multipage_pdf(*, continuation: bool, shift_top: float = 0.0, shift_left: float = 0.0) -> bytes:
    table = [
        "记账日期  交易金额  联机余额",
        "2026-08-30  1,850.00  1,850.00",
        "2026-08-31  -100.00  1,750.00",
        "2026-09-01  -500.00  1,250.00",
        "2026-09-03  -50.00  1,200.00",
        "第 1 页",
    ]
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    if continuation:
        page.insert_text((72, 60), "招商银行交易流水", fontsize=10, fontname="china-s")
    for index, line in enumerate(table):
        page.insert_text((72, 120 + 20 * index), line, fontsize=10, fontname="china-s")
    page = doc.new_page(width=595, height=842)
    if not continuation:
        page.insert_text((72, 60 + shift_top), "招商银行交易流水", fontsize=10, fontname="china-s")
    for index, line in enumerate(table):
        page.insert_text((72 + shift_left, 43 + 20 * index), line, fontsize=10, fontname="china-s")
    doc.set_metadata({"producer": "BankCore Export 1.0", "creator": "BankCore"})
    data = doc.tobytes()
    doc.close()
    return data


def test_continuation_page_without_letterhead_passes_layout():
    result = analyze_file(make_multipage_pdf(continuation=True))
    f9 = check(result, "F9")
    assert f9.status == "pass"
    assert "顶边距未比对" in f9.detail


def test_same_letterhead_shifted_fails_layout():
    result = analyze_file(make_multipage_pdf(continuation=False, shift_top=20))
    f9 = check(result, "F9")
    assert f9.status == "fail"
    assert "顶边距" in f9.detail


def test_left_margin_shift_fails_layout():
    result = analyze_file(make_multipage_pdf(continuation=True, shift_left=10))
    f9 = check(result, "F9")
    assert f9.status == "fail"
    assert "左边距" in f9.detail
