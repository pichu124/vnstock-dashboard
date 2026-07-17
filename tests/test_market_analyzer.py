"""Tests cho vnstock_market_analyzer — hiện mới có regression zero-âm
(conviction "-0.00" trên dashboard/brief, lộ 17/07)."""
from __future__ import annotations

import pandas as pd

from vnstock_market_analyzer import market_regime


def test_market_regime_conviction_no_negative_zero():
    # composite trung bình -0.001 → round(…, 2) = -0.0 → format "+.2f" từng
    # hiện "conviction -0.00"; nay khử về 0.0 dương sạch
    r = market_regime(pd.DataFrame({"composite": [0.199, -0.201]}))
    assert f"{r['conviction']:+.2f}" == "+0.00"
    # giá trị khác 0 giữ nguyên
    r2 = market_regime(pd.DataFrame({"composite": [0.5, 0.9]}))
    assert r2["conviction"] == 0.7
    # âm thật vẫn âm
    r3 = market_regime(pd.DataFrame({"composite": [-0.5, -0.9]}))
    assert r3["conviction"] == -0.7


def test_market_regime_empty_scores():
    r = market_regime(pd.DataFrame())
    assert r["conviction"] == 0 and "Không đủ dữ liệu" in r["regime"]
