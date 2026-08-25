"""
Lưới cho vòng lấy Net Buy-Sell (bước screener).

Bản cũ: `for tk in ~1.000 mã: order_stats(tk); sleep(0.15)`. Ba khiếm khuyết
cùng lúc:

1. **Sàn 150 giây chỉ để NGỦ**, cộng round-trip mạng cũng nối tiếp ⇒ vài trăm
   giây nữa — trong khi hạn mức Sponsor là 600 req/phút = 10 req/s, tức đường
   tuần tự dùng chưa tới 1/10 quota mà vẫn chậm.
2. `except Exception: pass` — mã bị hạn mức chặn **biến mất khỏi `nb_data`
   không dấu vết**. Mất data im lặng.
3. Không có gì đo được: dòng log chỉ in tổng giây, không nói tốc độ hay số lỗi.

Bất biến phải giữ: **tổng tốc độ không được vượt hạn mức**, dù chạy bao nhiêu
luồng. Vượt quota là bị nhà cung cấp chặn — mất nhiều hơn được.
"""
from __future__ import annotations

import threading
import time

import vnstock_runner as r


class TestRatePacer:
    def test_aggregate_rate_is_capped_across_threads(self):
        """Nhiều luồng KHÔNG được cộng dồn tốc độ — đây là điểm sống chết."""
        pacer = r._RatePacer(20.0)          # 20/s ⇒ 20 lượt ≈ 0,95s
        t0 = time.monotonic()

        def _work():
            for _ in range(5):
                pacer.wait()

        ts = [threading.Thread(target=_work) for _ in range(4)]
        for t in ts:
            t.start()
        for t in ts:
            t.join()
        elapsed = time.monotonic() - t0
        assert elapsed >= 0.85, f"nhanh hơn hạn mức: {elapsed:.2f}s"
        assert elapsed < 2.5, f"chậm bất thường: {elapsed:.2f}s"

    def test_a_single_caller_is_not_slowed_below_the_rate(self):
        pacer = r._RatePacer(100.0)
        t0 = time.monotonic()
        for _ in range(10):
            pacer.wait()
        assert time.monotonic() - t0 < 0.5

    def test_the_first_call_does_not_sleep(self):
        t0 = time.monotonic()
        r._RatePacer(1.0).wait()
        assert time.monotonic() - t0 < 0.05

    def test_a_silly_rate_does_not_divide_by_zero(self):
        r._RatePacer(0).wait()             # không được ném


class TestPoolSize:
    def test_default(self, monkeypatch):
        monkeypatch.delenv(r._NB_WORKERS_ENV, raising=False)
        assert r._nb_pool_size() == r._NB_WORKERS_DEFAULT

    def test_env_override(self, monkeypatch):
        monkeypatch.setenv(r._NB_WORKERS_ENV, "4")
        assert r._nb_pool_size() == 4

    def test_one_is_allowed_that_is_the_serial_escape_hatch(self, monkeypatch):
        monkeypatch.setenv(r._NB_WORKERS_ENV, "1")
        assert r._nb_pool_size() == 1

    def test_garbage_falls_back_to_the_default(self, monkeypatch):
        monkeypatch.setenv(r._NB_WORKERS_ENV, "tám")
        assert r._nb_pool_size() == r._NB_WORKERS_DEFAULT

    def test_absurd_values_are_clamped(self, monkeypatch):
        monkeypatch.setenv(r._NB_WORKERS_ENV, "999")
        assert r._nb_pool_size() == 32
        monkeypatch.setenv(r._NB_WORKERS_ENV, "-5")
        assert r._nb_pool_size() == 1

    def test_the_rate_stays_under_the_sponsor_quota(self):
        # 600 req/phút = 10 req/s. Phải chừa biên vì bước khác cũng gọi mạng.
        assert r._NB_RATE_PER_SEC < 10.0


class TestWiring:
    def test_the_loop_is_parallel_and_paced(self):
        """Ai gỡ pool hoặc gỡ bộ nhịp là đỏ: gỡ pool → chậm lại vài trăm giây,
        gỡ nhịp → vượt hạn mức và bị chặn."""
        import inspect
        src = inspect.getsource(r.compute_market_overview)
        assert "ThreadPoolExecutor" in src and "_RatePacer" in src
        assert "_nb_pacer.wait()" in src

    def test_failures_are_counted_not_swallowed(self):
        import inspect
        src = inspect.getsource(r.compute_market_overview)
        assert "_nb_fail" in src
        assert "call_with_rate_limit_retry" in src

    def test_the_log_line_reports_rate_and_failures(self):
        import inspect
        src = inspect.getsource(r.compute_market_overview)
        assert "req/s" in src and "LỖI" in src

    def test_the_cache_ttl_is_left_alone_on_purpose(self):
        """TTL 12h < nhịp 24h nên cache LUÔN nguội ở đường đêm — và đó là
        ĐÚNG: `Net BS 1T` là tổng 5 phiên, xài lại cache hôm qua là thiếu mất
        phiên hôm nay, một lỗi số liệu IM LẶNG. Ai nâng TTL để 'tối ưu' là
        đang đổi tốc độ lấy số sai."""
        import inspect
        src = inspect.getsource(r.compute_market_overview)
        assert "_NB_CACHE_TTL_H = 12" in src
