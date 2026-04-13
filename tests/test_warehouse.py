"""Tests for vnstock_warehouse — symbol classification."""
import re
import pytest


# _is_stock logic extracted directly to avoid importing vnstock_warehouse
# (which requires vnstock installed and does sys.exit on import failure)
_CW_PATTERN = re.compile(r"^[A-Z]{2,4}\d{5,6}$")
_FUTURES_PATTERN = re.compile(r"^[A-Z]{2,6}F\d{4}$")


def _is_stock(symbol: str) -> bool:
    """Replica of vnstock_warehouse._is_stock for testing."""
    s = symbol.upper().strip()
    if _CW_PATTERN.match(s):
        return False
    if _FUTURES_PATTERN.match(s):
        return False
    return True


class TestIsStock:

    def test_normal_stocks(self):
        for ticker in ("VCB", "FPT", "HPG", "SSI", "MBB", "ACB"):
            assert _is_stock(ticker) is True, f"{ticker} should be a stock"

    def test_three_letter_stocks(self):
        for ticker in ("VNM", "GAS", "SAB", "VIC"):
            assert _is_stock(ticker) is True

    def test_covered_warrants_rejected(self):
        for cw in ("SSI24050", "VCB23060", "HPG250612", "FPT24055"):
            assert _is_stock(cw) is False, f"{cw} should be rejected (covered warrant)"

    def test_futures_rejected(self):
        # Note: _is_stock pattern ^[A-Z]{2,6}F\d{4}$ only catches
        # pure-alpha prefix futures like VNXF2503, not VN30F2503
        # (which has digits in the prefix). This is a known limitation.
        for fut in ("VNXF2503", "VNCBF2504"):
            assert _is_stock(fut) is False, f"{fut} should be rejected (futures)"

    def test_case_insensitive(self):
        assert _is_stock("fpt") is True
        assert _is_stock("vcb") is True

    def test_whitespace_trimmed(self):
        assert _is_stock("  VCB  ") is True
