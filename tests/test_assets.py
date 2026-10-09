"""vnstock_assets — kho đa tài sản vàng · dầu · USD (U82, 09/10).

Hermetic: kho/meta/khoá về tmp + mạng chặn (conftest `_assets_hermetic_anywhere`); nguồn Python
tiêm qua `tasks`. Kiểm: luật gộp (trong ngày bản MỚI thắng, quá khứ theo ưu tiên), cờ lệch
nguồn, kho theo năm + bản Dropbox trùng, ước tính trong ngày (USD rộng, WTI ≤3 phiên), trạng
thái, khoá, giờ MCP, badge doctor, nối run.py + móc mỗi giờ."""
from __future__ import annotations

import json
import subprocess
from datetime import date, datetime
from types import SimpleNamespace

import pandas as pd
import pytest

import vnstock_assets as va

TODAY = date(2026, 10, 9)
NOW = datetime(2026, 10, 9, 20, 0)
T = "2026-10-09T20:00:00"


def _rows(key):
    return va.load(key).to_dict("records")


# ── registry ────────────────────────────────────────────────────────────────
def test_registry_shape():
    assert sum(1 for k in va.REGISTRY if k.startswith("GOLD_")) == 10
    for k, s in va.REGISTRY.items():
        if s.display == "est":
            assert f"{k}_EST" in va.REGISTRY            # chuỗi chậm phải có bản ước tính
    assert va.REGISTRY["BRENT_SPOT"].display == "hide"
    assert va.REGISTRY["USD_CENTRAL"].sources == ("mbk", "sbv-weekly")   # SBVN ≠ trung tâm (10/10)
    assert va.REGISTRY["USD_SBV_REF"].sources == ("ssi",)


# ── gộp ─────────────────────────────────────────────────────────────────────
def _merge(rows, key="BRENT", existing=None, at=T):
    return va.merge(existing if existing is not None else va._empty(), rows, va.REGISTRY[key], TODAY, at)


def test_merge_rejects_out_of_range_and_weekend():
    df, flags = _merge([{"date": "2026-10-08", "close": 9999, "source": "yahoo"},
                        {"date": "2026-10-04", "close": 100, "source": "yahoo"},      # Chủ nhật
                        {"date": "2026-10-08", "close": 100, "source": "yahoo"}])
    assert list(df["date"]) == ["2026-10-08"] and flags[0]["kind"] == "sanity"
    gold, _ = _merge([{"date": "2026-10-04", "close": 144_800_000, "source": "finhay"}], key="GOLD_SJC_BAR")
    assert list(gold["date"]) == ["2026-10-04"]                        # vàng nội có giá cuối tuần


def test_merge_rejects_undeclared_source_and_purges_old_rows():
    """Luật 1 bằng code: nguồn không khai trong Spec.sources không vào chuỗi; dòng cũ của nguồn
    đã gỡ (USD_CENTRAL "ssi-sbvn" trước 10/10) rơi khỏi file ở lượt ghi kế tiếp."""
    old = pd.DataFrame([{**{c: None for c in va.COLUMNS}, "date": "2026-10-09", "close": 25629.0,
                         "source": "ssi-sbvn", "contract": "", "fetched_at": T}], columns=va.COLUMNS)
    df, flags = _merge([{"date": "2026-10-08", "close": 25634.0, "source": "mbk"},
                        {"date": "2026-10-07", "close": 25645.0, "source": "ssi"}],
                       key="USD_CENTRAL", existing=old)
    assert list(df["source"]) == ["mbk"] and list(df["date"]) == ["2026-10-08"]
    assert flags == [{"key": "USD_CENTRAL", "date": "2026-10-07", "kind": "source", "source": "ssi"}]


def test_registry_sources_cover_every_writer():
    """Mỗi nguồn mà code ghi phải có trong Spec.sources của khoá nó ghi vào (không thì luật trên
    nuốt mất dữ liệu thật)."""
    import inspect
    import vnstock_assets_mcp as am
    text = inspect.getsource(va)
    for key, src_name in (("XAU", "gold-api"), ("BRENT", "yahoo"), ("CURVE_WTI", "yahoo"),
                          ("WTI_SPOT", "fred"), ("USD_BROAD", "fred"), ("USDVND", "er-api"),
                          ("USDVND", "currency-api"), ("USDVND", "yahoo"), ("USDVND_VCB", "vcb"),
                          ("GOLD_SJC_BAR", "sjc"), ("USD_CENTRAL", "mbk"), ("DXY", "yahoo")):
        assert f'"{src_name}"' in text and src_name in va.REGISTRY[key].sources, (key, src_name)
    for key, _, _ in am.DAILY:
        assert "finhay" in va.REGISTRY[key].sources, key
    for key, _ in am.SSI_BANKS:
        assert "ssi" in va.REGISTRY[key].sources, key


def test_merge_past_follows_priority_and_flags_mismatch():
    base, _ = _merge([{"date": "2026-10-01", "close": 100.0, "source": "finhay"}], at="2026-10-02T09:00:00")
    df, flags = _merge([{"date": "2026-10-01", "close": 102.5, "source": "yahoo"}], existing=base)
    assert df.iloc[0]["close"] == 100.0 and df.iloc[0]["source"] == "finhay"   # yahoo thấp hơn
    assert flags and flags[0]["kind"] == "xcheck" and flags[0]["dev_pct"] == 2.5
    df2, _ = _merge([{"date": "2026-10-01", "close": 100.3, "source": "finhay"}], existing=df)
    assert df2.iloc[0]["close"] == 100.3                                # cùng nguồn ⇒ ghi đè


def test_merge_recent_fresher_wins_and_xcheck_only_when_close_in_time():
    base, _ = _merge([{"date": "2026-10-09", "close": 103.0, "source": "finhay"}], at="2026-10-09T09:00:00")
    df, flags = _merge([{"date": "2026-10-09", "close": 105.0, "source": "yahoo"}], existing=base)
    assert df.iloc[0]["close"] == 105.0 and not flags                    # 11 giờ sau: giá đã chạy
    df, flags = _merge([{"date": "2026-10-09", "close": 105.0, "source": "yahoo"}], existing=base,
                       at="2026-10-09T10:00:00")
    assert flags and flags[0]["a_src"] == "finhay"                       # 1 giờ sau mà lệch 1,9%


def test_write_load_roundtrip_by_year_and_conflicted_copy(tmp_path):
    va.write("BRENT", [{"date": "2025-12-31", "close": 90.0, "source": "yahoo"},
                       {"date": "2026-10-08", "close": 101.0, "source": "yahoo"}], today=TODAY, fetched_at=T)
    kdir = va.key_dir("BRENT")
    assert sorted(p.name for p in kdir.glob("*.parquet")) == ["2025.parquet", "2026.parquet"]
    dup = pd.read_parquet(kdir / "2026.parquet")
    dup.loc[0, "close"], dup.loc[0, "fetched_at"] = 101.5, "2026-10-09T21:00:00"
    dup.to_parquet(kdir / "2026 (PICHU's conflicted copy).parquet")
    assert va.series("BRENT") == {"2025-12-31": 90.0, "2026-10-08": 101.5}     # bản mới nhất thắng
    va.write("BRENT", [{"date": "2026-10-09", "close": 102.0, "source": "yahoo"}], today=TODAY, fetched_at=T)
    assert sorted(p.name for p in kdir.glob("2026*.parquet")) == ["2026.parquet"]


def test_curve_latest_sorted_by_month_and_spreads():
    va.write("CURVE_BRENT", [{"date": "2026-10-09", "close": c, "contract": k, "source": "yahoo"}
                             for k, c in (("BZF27", 99.88), ("BZZ26", 103.17), ("BZK27", 92.90),
                                          ("BZG27", 97.36), ("BZH27", 95.29), ("BZJ27", 93.90))],
             today=TODAY, fetched_at=T)
    lt = va.latest("CURVE_BRENT")
    assert [p["contract"] for p in lt["points"]][:2] == ["BZZ26", "BZF27"]
    cs = va.curve_spreads("CURVE_BRENT")
    assert cs["m1_m2"]["usd"] == 3.29 and cs["m1_m6"]["to"] == "BZK27" and cs["shape"] == "backwardation"


# ── ước tính ────────────────────────────────────────────────────────────────
def test_wti_spot_estimate_hidden_after_three_sessions():
    spot = {"2026-10-06": 96.24}
    fut = {"2026-10-06": 89.44, "2026-10-07": 88.28, "2026-10-08": 91.49, "2026-10-09": 90.69}
    est, why = va.estimate_wti_spot(spot, fut)
    assert why is None and est["h"] == 3 and est["value"] == pytest.approx(96.24 * 90.69 / 89.44)
    est, why = va.estimate_wti_spot(spot, {**fut, "2026-10-12": 92.0})
    assert est is None and "4 phiên" in why


def test_usd_broad_estimate_uses_weights_and_shift():
    w = {"eur": 0.5, "cny": 0.5}
    fx = {"2026-10-03": {"eur": 0.86, "cny": 7.1}, "2026-10-09": {"eur": 0.86 * 1.01, "cny": 7.1 * 1.01}}
    est, why = va.estimate_usd_broad({"2026-10-02": 121.38}, fx, w)
    assert why is None and est["anchor_date"] == "2026-10-02" and est["band_pct"] == va.USD_BROAD_BAND_PCT
    assert est["value"] == pytest.approx(121.38 * 1.01) and est["date"] == "2026-10-08"   # file 09/10 ↔ Fed 08/10


def test_usd_broad_estimate_dated_on_fed_weekday_and_counts_sessions():
    """10/10 🖥️: file currency-api thứ Bảy (↔ Fed thứ Sáu) làm ước tính mang ngày thứ Bảy ⇒ kho
    cuối tuần bỏ, `--show` "chưa có dữ liệu"; `h=7` đếm cả file cuối tuần. Nay: ngày Fed, h = phiên."""
    w = {"eur": 1.0}
    fx = {f"2026-10-{d:02d}": {"eur": 0.86 + d / 1000} for d in range(3, 11)}   # 03 (T7) … 10 (T7)
    est, why = va.estimate_usd_broad({"2026-10-02": 121.38}, fx, w)
    assert why is None and est["date"] == "2026-10-09" and est["h"] == 5
    out, _ = va.refresh_estimates(TODAY, T, fx_days=fx)
    assert "hidden" in out["USD_BROAD_EST"]                                # conftest chặn trọng số Fed
    va._write_json(va.WEIGHTS_CACHE_NAME, {"fetched": TODAY.isoformat(), "year": 2026, "weights": w})
    va.write("USD_BROAD", [va._row("2026-10-02", 121.38, "fred")], today=TODAY, fetched_at=T)
    out, _ = va.refresh_estimates(date(2026, 10, 10), T, fx_days=fx)
    assert out["USD_BROAD_EST"]["date"] == "2026-10-09" and "2026-10-09" in va.series("USD_BROAD_EST")


def test_fx_cache_keys_latest_by_file_date_and_refetches_recent(monkeypatch):
    va._write_json(va.FX_CACHE_NAME, {"2026-10-10": {"eur": 0.111}, "2026-10-01": {"eur": 0.8}})
    got = []
    monkeypatch.setattr(va.src, "fetch_fx_day", lambda d: got.append(d) or {"eur": 0.86})
    monkeypatch.setattr(va.src, "fetch_fx_latest_dated", lambda: ("2026-10-09", {"eur": 0.87}))
    cache = va.refresh_fx_cache(date(2026, 10, 10), days=10)
    assert "2026-10-01" not in got and {"2026-10-07", "2026-10-10"} <= set(got)   # cũ giữ, gần tải lại
    assert cache["2026-10-10"] == {"eur": 0.86} and cache["2026-10-09"] == {"eur": 0.87}


def test_usd_broad_hidden_reason_names_the_broken_step():
    """10/10 🖥️: ước tính ẩn mà lý do chung chung ⇒ không biết sửa gì. Mỗi khâu một lý do."""
    w = {"eur": 0.5, "cny": 0.5}
    fx = {"2026-10-03": {"eur": 0.86, "cny": 7.1}, "2026-10-09": {"eur": 0.87, "cny": 7.2}}
    off = {"2026-10-02": 121.38}
    assert "trọng số Fed (HTTPError: 403)" in va.estimate_usd_broad(off, fx, {}, "HTTPError: 403")[1]
    assert "currency-api" in va.estimate_usd_broad(off, {}, w)[1]
    assert "chỉ số tự tính rỗng" in va.estimate_usd_broad(off, {"2026-10-03": {"eur": 0.86}}, w)[1]
    assert "chưa có số Fed" in va.estimate_usd_broad({}, fx, w)[1]
    why = va.estimate_usd_broad({"2026-10-06": 121.0}, fx, w)[1]
    assert "2026-10-06 chưa có tỷ giá ngày +1" in why and "2026-10-03→2026-10-09" in why


# ── một lượt Python ─────────────────────────────────────────────────────────
def _tasks(fail=False):
    def boom():
        raise ConnectionError("api_key=SECRET down")
    return [("gold-api", lambda: {"XAU": [va._row("2026-10-09", 4180.2, "gold-api")]}),
            ("yahoo-wti", lambda: {"WTI": [va._row(d, c, "yahoo") for d, c in
                                           (("2026-10-06", 89.44), ("2026-10-07", 88.28),
                                            ("2026-10-08", 91.49), ("2026-10-09", 90.69))]}),
            ("fred", lambda: {"WTI_SPOT": [va._row("2026-10-06", 96.24, "fred")],
                              "BRENT_SPOT": [va._row("2026-10-06", 125.44, "fred")]}),
            ("vcb", boom if fail else lambda: {"USDVND_VCB": [va._row("2026-10-09", 26070, "vcb",
                                                                       bid=25690, ask=26070)]})]


def test_refresh_python_writes_status_and_estimates():
    res = va.refresh_python(NOW, tasks=_tasks(fail=True))
    assert res["status"] == "partial" and res["ok"] == 3
    st = va.read_status()
    assert st["python"]["tasks"]["vcb"]["ok"] is False and "SECRET" not in st["python"]["tasks"]["vcb"]["error"]
    assert st["estimates"]["WTI_SPOT_EST"]["h"] == 3
    assert "hidden" in st["estimates"]["USD_BROAD_EST"]                  # chưa có trọng số Fed (mạng chặn)
    assert va.series("WTI_SPOT_EST")["2026-10-09"] == pytest.approx(96.24 * 90.69 / 89.44)
    assert va.series("XAU") == {"2026-10-09": 4180.2}


def test_refresh_python_busy_when_lock_held():
    with va.machine_lock() as got:
        assert got
        assert va.refresh_python(NOW, tasks=_tasks())["status"] == "busy"
    assert va.refresh_python(NOW, tasks=_tasks())["status"] == "ok"


def test_disabled_by_env(monkeypatch):
    monkeypatch.setenv("VNSTOCK_ASSETS", "0")
    assert va.refresh_python(NOW, tasks=_tasks())["status"] == "disabled"
    assert va.hourly(NOW)["status"] == "disabled"


def test_update_status_dedupes_repeated_flags():
    f = {"key": "BRENT", "date": "2026-10-01", "kind": "xcheck", "a_src": "finhay", "b_src": "yahoo"}
    va.update_status("python", {}, [f])
    va.update_status("python", {}, [f, {**f, "date": "2026-10-02"}])
    assert [x["date"] for x in va.read_status()["xcheck"]] == ["2026-10-01", "2026-10-02"]


def test_derived_premium_and_ceiling_room():
    va.write("GOLD_SJC_BAR", [va._row("2026-10-09", 144_800_000, "finhay", bid=141_800_000, ask=144_800_000)],
             today=TODAY, fetched_at=T)
    va.write("XAU", [va._row("2026-10-09", 4182.09, "finhay")], today=TODAY, fetched_at=T)
    va.write("USDVND", [va._row("2026-10-09", 25881, "finhay")], today=TODAY, fetched_at=T)
    va.write("USD_CENTRAL", [va._row("2026-10-09", 25629, "mbk")], today=TODAY, fetched_at=T)
    va.write("USDVND_VCB", [va._row("2026-10-09", 26090, "ssi", ask=26090)], today=TODAY, fetched_at=T)
    assert va.sjc_premium_pct()["pct"] == pytest.approx(10.96, abs=0.05)
    room = va.usd_ceiling_room_pct()
    assert room["ceiling"] == 26910 and room["pct"] == pytest.approx(3.14, abs=0.01)
    text = va.show(today=TODAY)
    assert "SJC miếng đắt hơn" in text and "còn cách trần 26,910 (trung tâm 25,629" in text
    sjc = next(ln for ln in text.splitlines() if "SJC miếng " in ln and "VND/lượng" in ln)
    assert "144,800,000 VND/lượng" in sjc and ".00" not in sjc            # VND không phần lẻ


def test_show_columns_align_for_locked_rows():
    va.write("WTI_SPOT", [va._row("2026-10-06", 96.24, "fred")], today=TODAY, fetched_at=T)
    va.write("DXY", [va._row("2026-10-09", 98.7, "yahoo")], today=TODAY, fetched_at=T)
    lines = va.show(today=TODAY).splitlines()
    spot = next(ln for ln in lines if "WTI giao ngay EIA" in ln)
    dxy = next(ln for ln in lines if "DXY (ICE)" in ln)
    assert spot.index("96.24") == dxy.index("98.70") and "chỉ hiện qua ước tính" in spot


# ── giờ MCP + mỗi giờ ───────────────────────────────────────────────────────
def test_mcp_due_by_hours_and_gap(monkeypatch):
    assert va.mcp_due(datetime(2026, 10, 9, 9, 5), {})
    assert not va.mcp_due(datetime(2026, 10, 9, 10, 5), {})
    assert not va.mcp_due(datetime(2026, 10, 9, 9, 50), {"mcp": {"run_at": "2026-10-09T09:05:00"}})
    monkeypatch.setenv(va.ENV_MCP_HOURS, "10,22")
    assert va.mcp_hours() == (10, 22) and va.mcp_due(datetime(2026, 10, 9, 22, 1), {})
    monkeypatch.setenv(va.ENV_MCP, "0")
    assert not va.mcp_due(datetime(2026, 10, 9, 22, 1), {})


def test_hourly_runs_mcp_only_when_due(monkeypatch):
    import vnstock_assets_mcp as am
    monkeypatch.setenv(va.ENV_HOURLY, "1")
    monkeypatch.setattr(va, "refresh_python", lambda now=None: {"status": "ok"})
    seen = []
    monkeypatch.setattr(am, "refresh", lambda now=None, **k: seen.append(now) or {"status": "ok"})
    assert "mcp" not in va.hourly(datetime(2026, 10, 9, 10, 0))
    assert va.hourly(datetime(2026, 10, 9, 14, 0))["mcp"]["status"] == "ok" and len(seen) == 1


# ── doctor ──────────────────────────────────────────────────────────────────
def test_doctor_badge(monkeypatch, tmp_path):
    import vnstock_doctor as doc
    meta = tmp_path / "wh" / "_meta"
    meta.mkdir(parents=True)
    monkeypatch.setattr(doc, "_META", meta)
    assert doc.check_assets(NOW)["status"] == "warn"                    # chưa chạy lượt nào
    monkeypatch.setattr(va, "ASSETS_DIR", meta.parent / "assets")
    monkeypatch.setattr(va, "META_DIR", meta)
    for key, spec in va.REGISTRY.items():
        if spec.display != "show":
            continue
        row = va._row("2026-10-09", spec.lo + 1 if spec.lo else 1, spec.sources[0], contract="C1" if spec.curve else "")
        va.write(key, [row], today=TODAY, fetched_at=T)
    va.update_status("python", {"run_at": "2026-10-09T19:30:00", "status": "ok"})
    va.update_status("mcp", {"run_at": "2026-10-09T14:00:00", "status": "ok"})
    va.update_status("estimates", {"USD_BROAD_EST": {"value": 121.23, "band_pct": 0.3}})
    r = doc.check_assets(NOW)
    assert r["status"] == "ok" and "USD rộng ước tính 121.23 ±0.3%" in r["message"]
    r = doc.check_assets(datetime(2026, 10, 14, 20, 0))
    assert r["status"] == "warn" and "lượt Python cuối" in r["message"] and "chưa có số trong ngày" in r["message"]
    monkeypatch.setenv("VNSTOCK_ASSETS", "0")
    assert doc.check_assets(NOW)["status"] == "off"


# ── run.py ──────────────────────────────────────────────────────────────────
def test_runpy_assets_commands_never_hard_fail(monkeypatch):
    import run as runpy
    seen = []
    monkeypatch.setattr(runpy, "_run", lambda cmd: seen.append(cmd) or 2)
    assert runpy.cmd_assets(SimpleNamespace()) == 1 and seen[-1][-1] == "--refresh"
    runpy.cmd_assets(SimpleNamespace(backfill=True, with_mcp=True, vcb_days=30))
    assert seen[-1][-4:] == ["--backfill", "--with-mcp", "--vcb-days", "30"]
    runpy.cmd_assets(runpy.build_parser().parse_args(["assets", "--backfill", "--steps", "mbk"]))
    assert seen[-1][-3:] == ["--backfill", "--steps", "mbk"]
    assert runpy.cmd_assets_mcp(SimpleNamespace()) == 1 and seen[-1][-2:] == ["--mcp-stale", "6"]
    args = runpy.build_parser().parse_args(["assets", "--backfill", "--with-mcp"])
    assert args.backfill and args.with_mcp and runpy._DISPATCH["assets"] is runpy.cmd_assets
    names = [n for n, _ in runpy._all_steps(SimpleNamespace())]
    assert names.index("assets") == names.index("gold") + 1 and names[-1] == "assets-mcp"
    args = runpy.build_parser().parse_args(["assets", "--mcp-backfill", "--only", "GOLD_SJC_BAR,USD_SBV_REF"])
    runpy.cmd_assets(args)
    assert seen[-1][-3:] == ["--mcp-backfill", "--only", "GOLD_SJC_BAR,USD_SBV_REF"]


def test_cli_mcp_backfill_rejects_unknown_key(capsys):
    assert va.main(["--mcp-backfill", "--only", "SJC"]) == 2
    assert "khoá không có trong registry" in capsys.readouterr().out
    assert va.main(["--backfill", "--steps", "mbk,abc"]) == 2
    assert "bước không có: ['abc']" in capsys.readouterr().out


def test_backfill_steps_runs_only_selected(monkeypatch):
    calls = []
    monkeypatch.setattr(va.src, "fetch_mbk_central",
                        lambda a, b, **k: calls.append((a, b, k)) or [("2026-10-07", 25634.0),
                                                                     ("2026-10-08", 25629.0)])
    monkeypatch.setattr(va.src, "fetch_fred", lambda *a, **k: pytest.fail("fred không được gọi"))
    logs = []
    rep = va.backfill(now=NOW, log=logs.append, tasks=_tasks(), steps={"mbk"})
    assert set(rep) == {"mbk", "python"} and calls[0] == ("2016-01-01", "2026-10-09", {"shift": False})
    assert va.series("USD_CENTRAL") == {"2026-10-08": 25634.0, "2026-10-09": 25629.0}   # đã dời
    assert any("mbk THÔ theo thứ (T2…CN): 0 · 0 · 1 · 1 · 0 · 0 · 0" in ln and "2026-10-08(T5)=25,629" in ln
               for ln in logs)


def test_central_dating_live_in_show_and_doctor(tmp_path, monkeypatch):
    """Kho lệch 1 phiên so giá tham khảo NHNN ⇒ `--show` in "LÙI 1 phiên" và doctor réo; kho đúng
    ngày ⇒ im (10/10: thước trễ lẫn từng làm doctor réo nhầm khi kho ĐÃ đúng)."""
    import vnstock_doctor as doc
    from tests.test_assets_mcp import ruler_case
    meta = tmp_path / "wh" / "_meta"
    meta.mkdir(parents=True)
    monkeypatch.setattr(doc, "_META", meta)
    monkeypatch.setattr(va, "ASSETS_DIR", meta.parent / "assets")
    monkeypatch.setattr(va, "META_DIR", meta)
    va.update_status("python", {"run_at": "2026-10-09T19:30:00", "status": "ok"})
    sbvn, lagged = ruler_case(1)
    va.write("USD_SBV_REF", sbvn, today=TODAY, fetched_at=T)
    va.write("USD_CENTRAL", [va._row(d, v, "mbk") for d, v in lagged.items()], today=TODAY, fetched_at=T)
    assert "LÙI 1 phiên · giả thuyết lệch -1" in va.show(today=TODAY)
    r = doc.check_assets(NOW)
    assert "tỷ giá trung tâm lệch ngày" in r["message"] and "--steps mbk" in r["fix"]
    _, ok = ruler_case(0)
    va.write("USD_CENTRAL", [va._row(d, v, "mbk") for d, v in ok.items()], today=TODAY, fetched_at=T)
    assert va.central_dating()["verdict"] == "mbk ĐÚNG ngày"
    assert "lệch ngày" not in doc.check_assets(NOW)["message"]


def test_backfill_ends_with_python_pass_so_doctor_sees_a_run():
    """10/10 🖥️: backfill đầy kho mà `status.python` trống ⇒ doctor "chưa có lượt nào", không có
    đường cong HĐTL, lý do ẩn ước tính không in ra. Nay backfill chốt bằng một lượt Python."""
    logs = []
    rep = va.backfill(now=NOW, log=logs.append, tasks=_tasks(), vcb_days=7)
    assert rep["python"]["status"] == "ok"
    st = va.read_status()
    assert st["python"]["run_at"] == T and st["estimates"]["WTI_SPOT_EST"]["h"] == 3
    assert any(ln.startswith("  USD_BROAD_EST: ẩn: thiếu trọng số Fed") for ln in logs)


def test_news_alert_hourly_hook(monkeypatch):
    import run as runpy
    import vnstock_news_alert as na
    monkeypatch.setattr(na, "run", lambda **kw: 0)
    calls = []
    monkeypatch.setattr(subprocess, "run", lambda cmd, **kw: calls.append((cmd, kw)))
    args = SimpleNamespace(dry_run=False, force=False, sources=None, list_sources=False)
    assert runpy.cmd_news_alert(args) == 0 and calls == []              # conftest tắt móc
    monkeypatch.setenv("VNSTOCK_ASSETS_HOURLY", "1")
    assert runpy.cmd_news_alert(args) == 0
    assert calls[-1][0][-1] == "--hourly" and calls[-1][1]["timeout"] == runpy.ASSETS_HOURLY_TIMEOUT_S
    runpy.cmd_news_alert(SimpleNamespace(**{**vars(args), "dry_run": True}))
    assert len(calls) == 1                                               # dry-run: không móc


def test_cli_show_without_data():
    out = va.show(today=TODAY)
    assert "chưa có dữ liệu" in out and "chưa đủ dữ liệu" in out
