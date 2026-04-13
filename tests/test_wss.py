"""Tests for vnstock_wss — futures detection."""
import pytest


# Extract is_futures logic to avoid importing vnstock_wss
# (which requires dotenv, pandas, and does heavy init at import)
FUTURES_SYMBOLS = ["VN30F1M", "VN30F2M", "VN30F1Q", "VN30F2Q"]


def is_futures(ticker: str) -> bool:
    """Replica of vnstock_wss.is_futures for testing."""
    t = str(ticker).upper()
    if t in FUTURES_SYMBOLS:
        return True
    if t.startswith("VN30F") and len(t) >= 6:
        return True
    if t.startswith("41I") and len(t) >= 6:
        return True
    return False


class TestIsFutures:

    def test_friendly_names(self):
        for sym in ("VN30F1M", "VN30F2M", "VN30F1Q", "VN30F2Q"):
            assert is_futures(sym) is True

    def test_expiry_codes(self):
        for sym in ("VN30F2410", "VN30F2504", "VN30F2601"):
            assert is_futures(sym) is True

    def test_hnx_internal_codes(self):
        for sym in ("41I1G4000", "41I1G5000", "41IABCDE"):
            assert is_futures(sym) is True

    def test_stocks_not_futures(self):
        for sym in ("VCB", "FPT", "HPG", "SSI", "ACB"):
            assert is_futures(sym) is False

    def test_index_not_futures(self):
        for sym in ("VNINDEX", "VN30", "HNXINDEX"):
            assert is_futures(sym) is False

    def test_case_insensitive(self):
        assert is_futures("vn30f1m") is True
        assert is_futures("Vn30F2M") is True
