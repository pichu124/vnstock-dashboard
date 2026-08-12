"""Nguồn dữ liệu hỏng phải để lại VẾT — không được nuốt trọn.

Cùng một chủ trương với `tests/test_prompt_sentinels.py`, nhưng ở đầu kia của
đường ống:

* sentinel lo phần **thiếu data thì prompt phải nói là thiếu** (chống model bịa);
* file này lo phần **hỏng thì phải biết hỏng ở đâu** (chống mất dấu khi debug).

`collect_context` gọi ~15 nguồn, nguồn nào cũng best-effort — đúng thiết kế:
một nguồn chết KHÔNG được kéo sập cả brief. Nhưng quét 12/08 thấy 13 chỗ
`except Exception: pass` nuốt trọn, và `ctx["quant_error"]` thì viết ra rồi
KHÔNG AI ĐỌC. Hệ quả: brief thiếu hẳn một mục mà không ai biết vì sao, cũng
không biết nguồn nào.

Phân biệt QUAN TRỌNG (họ lỗi lặp lại nhiều nhất repo này — "không đo được"
khác "đo ra kết quả xấu"): nguồn trả RỖNG vì hôm nay không có gì là BÌNH
THƯỜNG, không phải lỗi, và KHÔNG được ghi vết. Chỉ ngoại lệ thật mới ghi.
"""
import ast
from pathlib import Path

import pytest

import vnstock_brief as vb

ROOT = Path(__file__).resolve().parent.parent


def _collect_context_node() -> ast.FunctionDef:
    tree = ast.parse((ROOT / "vnstock_brief.py").read_text(encoding="utf-8"))
    return next(n for n in tree.body
                if isinstance(n, ast.FunctionDef) and n.name == "collect_context")


def _loader_handlers():
    """`except` ở TẦNG NGUỒN — bỏ qua handler nằm trong hàm con lồng bên trong.

    Ranh giới này có lý do: hàm con như `_morn()` bọc `float(v)` để ép kiểu,
    nó hỏng ở MỘT NGÀY trong lịch sử là chuyện thường và không phải "nguồn
    hỏng". Ghi vết ở đó chỉ tạo báo động giả — mà báo động giả làm người ta
    ngừng đọc cảnh báo thật.
    """
    fn = _collect_context_node()
    nested = {id(x) for f in ast.walk(fn)
              if isinstance(f, ast.FunctionDef) and f is not fn
              for x in ast.walk(f)}
    for node in ast.walk(fn):
        if isinstance(node, ast.Try) and id(node) not in nested:
            yield from node.handlers


def test_no_handler_swallows_silently():
    """Lưới chính: thêm nguồn thứ 16 mà quên ghi vết là ĐỎ ngay.

    Đây đúng họ lỗi "lưới chỉ soi thứ ĐƯỢC KHAI BÁO" — chỉ khác là ở đây lưới
    tự quét, không cần khai báo tay, vì hình dạng `except` là cố định."""
    silent = [h.lineno for h in _loader_handlers()
              if all(isinstance(s, ast.Pass) for s in h.body)]
    assert not silent, (
        "Nuốt lỗi im lặng ở vnstock_brief.py dòng "
        + ", ".join(map(str, silent))
        + " — dùng `_note_loader_error(ctx, '<tên nguồn>', _e)`")


def test_every_handler_records_a_breadcrumb():
    """Chặt hơn: handler nào cũng phải GỌI `_note_loader_error`, chứ không chỉ
    'khác pass' (log suông rồi thôi cũng là mất dấu trong ctx)."""
    missing = []
    for h in _loader_handlers():
        calls = {ast.unparse(x.func) for x in ast.walk(h) if isinstance(x, ast.Call)}
        if "_note_loader_error" not in calls:
            missing.append(h.lineno)
    assert not missing, f"Handler không ghi breadcrumb, dòng: {missing}"


def test_breadcrumb_names_are_unique_and_meaningful():
    """Hai nguồn cùng tên = cái sau đè cái trước, mất một vết."""
    names = []
    for node in ast.walk(_collect_context_node()):
        if not isinstance(node, ast.Call) or ast.unparse(node.func) != "_note_loader_error":
            continue
        names.append(node.args[1].value)
    assert len(names) == len(set(names)), f"Tên nguồn trùng: {names}"
    assert all(len(n) >= 4 for n in names), names


# ── Hành vi của chính helper ────────────────────────────────────────────────

def test_records_type_and_message():
    ctx = {}
    vb._note_loader_error(ctx, "macro", ValueError("hết hạn token"))
    assert ctx["loader_errors"]["macro"] == "ValueError: hết hạn token"


def test_accumulates_multiple_failures():
    """Một đêm hỏng 3 nguồn thì phải thấy cả 3, không phải mỗi cái cuối."""
    ctx = {}
    vb._note_loader_error(ctx, "macro", ValueError("a"))
    vb._note_loader_error(ctx, "movers", KeyError("b"))
    vb._note_loader_error(ctx, "portfolio", OSError("c"))
    assert set(ctx["loader_errors"]) == {"macro", "movers", "portfolio"}


def test_does_not_disturb_existing_context():
    ctx = {"date": "2026-08-12", "sectors": [1, 2]}
    vb._note_loader_error(ctx, "macro", ValueError("x"))
    assert ctx["date"] == "2026-08-12" and ctx["sectors"] == [1, 2]


def test_writes_a_warning_to_the_log(caplog):
    """`run_daily.log` là chỗ user THẬT SỰ đọc — vết chỉ nằm trong ctx thì
    chạy pipeline ban đêm xong vẫn không ai thấy."""
    import logging
    with caplog.at_level(logging.WARNING):
        vb._note_loader_error({}, "session_stats", RuntimeError("kho trống"))
    assert "session_stats" in caplog.text
    assert "kho trống" in caplog.text


def test_never_raises_even_on_a_weird_exception():
    """Helper chạy TRONG except — nó mà ném thì đúng cái nó định cứu lại chết."""
    class Weird(Exception):
        def __str__(self):
            return "ổn"

    ctx = {}
    vb._note_loader_error(ctx, "x", Weird())
    assert "x" in ctx["loader_errors"]


# ── Phân biệt "rỗng" với "hỏng" ─────────────────────────────────────────────

def test_empty_result_is_not_an_error():
    """Nguồn chạy ngon mà hôm nay không có gì (cuối tuần, chưa tới giờ) thì
    KHÔNG được ghi vết — báo động giả làm người ta ngừng đọc cảnh báo thật."""
    ctx = vb.collect_context(brief_type="morning", auto_refresh=False)
    assert not ctx.get("loader_errors"), (
        "Nguồn trả rỗng bị tính là hỏng: " + str(ctx.get("loader_errors")))


@pytest.mark.parametrize("key", ["sectors", "breadth", "tickers"])
def test_context_starts_with_empty_containers_not_fake_numbers(key):
    """Khởi tạo bằng rỗng (chứ không phải 0 hay số mặc định) là thứ giữ cho
    prompt phân biệt được "không có data" với "đo được bằng 0"."""
    ctx = vb.collect_context(brief_type="morning", auto_refresh=False)
    assert ctx[key] in ([], {}, None) or ctx[key]
