"""
vnstock_classifier.py — Phân Loại Ngành Doanh Nghiệp bằng AI
=============================================================
Pipeline 3 bước:
  1. sync-profiles : Tải company profile vào warehouse (gọi API 1 lần)
  2. classify      : Đọc từ warehouse → Claude API → lưu kết quả
  3. report/query  : Xem kết quả

Cấu trúc warehouse:
  data_warehouse/
  ├── prices/            ← OHLCV đã có
  ├── companies/         ← Company profiles (MỚI)
  │   ├── ticker=VCB/overview.parquet
  │   └── ticker=FPT/overview.parquet
  └── _meta/
      └── industry_classification.parquet  ← Kết quả phân loại

Run:
  python vnstock_classifier.py --sync-profiles          # Bước 1: tải profiles
  python vnstock_classifier.py --sync-profiles --limit 50  # Test 50 mã
  python vnstock_classifier.py --classify               # Bước 2: phân loại AI
  python vnstock_classifier.py --classify --limit 50    # Test 50 mã
  python vnstock_classifier.py --query VCB              # Xem kết quả 1 mã
  python vnstock_classifier.py --report                 # Báo cáo tổng hợp
  python vnstock_classifier.py --export                 # Xuất CSV
"""

import argparse
import json
import re as _re
import time
import warnings
from datetime import datetime
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import requests
from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.progress import (BarColumn, MofNCompleteColumn, Progress,
                           SpinnerColumn, TaskProgressColumn, TextColumn,
                           TimeElapsedColumn)
from rich.table import Table

warnings.filterwarnings("ignore")
console = Console()

# ── vnstock_data OR vnstock ───────────────────────────────────────────────────
from vnstock_auth import ensure_api_key, get_vnstock

try:
    from vnstock_data import Reference, Fundamental
    USE_UNIFIED = True
    ensure_api_key()
    console.log("[green]✅ Using vnstock_data[/green]")
except ImportError:
    USE_UNIFIED = False
    try:
        from vnstock import Vnstock
        ensure_api_key()
        console.log("[yellow]⚠ Using vnstock (free)[/yellow]")
    except ImportError:
        console.print("[red]❌ Install vnstock: pip install vnstock[/red]")
        raise

# ─────────────────────────────────────────────────────────────────────────────
# Symbol filter (tái sử dụng từ screener)
# ─────────────────────────────────────────────────────────────────────────────

_CW_VN  = _re.compile(r"^C[A-Z]{2,4}\d{4}$")       # Covered warrant: CVNM2101
_CW_OLD = _re.compile(r"^[A-Z]{2,4}\d{5,6}$")      # Bond dạng cũ: HDB124001
_FUT    = _re.compile(r"^[A-Z]{2,6}F\d{4}$")        # Futures: BVBF2404
_FUT2   = _re.compile(r"^[A-Z]{2}\d{2}F\d{4}$")     # Futures index: VN30F2404

def _is_stock(s: str) -> bool:
    s = s.upper().strip()
    if not s or s[0].isdigit():   # Bond bắt đầu bằng chữ số: 41I1FA000
        return False
    return not (_CW_VN.match(s) or _CW_OLD.match(s) or _FUT.match(s) or _FUT2.match(s))

# ─────────────────────────────────────────────────────────────────────────────
# Nhóm ngành chuẩn
# ─────────────────────────────────────────────────────────────────────────────

INDUSTRY_GROUPS = [
    "Ngân hàng",
    "Bảo hiểm",
    "Chứng khoán & Đầu tư tài chính",
    "Bất động sản",
    "Xây dựng & Hạ tầng",
    "Vật liệu xây dựng",
    "Thép & Kim loại",
    "Hóa chất & Phân bón",
    "Nhựa & Bao bì",
    "Dầu khí",
    "Điện & Năng lượng tái tạo",
    "Công nghệ thông tin & Phần mềm",
    "Viễn thông",
    "Bán lẻ & Thương mại",
    "Thực phẩm & Đồ uống",
    "Nông nghiệp & Thủy sản",
    "Dệt may & May mặc",
    "Gỗ & Nội thất",
    "Y tế & Dược phẩm",
    "Vận tải & Logistics",
    "Du lịch & Khách sạn",
    "Giáo dục",
    "Khai khoáng & Tài nguyên",
    "Cảng & Hạ tầng logistics",
    "In ấn & Xuất bản",
    "Dịch vụ công ích & Môi trường",
    "Cơ khí & Thiết bị công nghiệp",
    "Truyền thông & Quảng cáo",
    "Dịch vụ tư vấn & Kiểm định",
    "Thể thao & Hàng tiêu dùng",
    "Đa ngành",
    "Khác",
]

GROUPS_STR = "\n".join(f"- {g}" for g in INDUSTRY_GROUPS)

# ─────────────────────────────────────────────────────────────────────────────
# Schemas
# ─────────────────────────────────────────────────────────────────────────────

PROFILE_SCHEMA = pa.schema([
    pa.field("ticker",          pa.string()),
    pa.field("company_name",    pa.string()),
    pa.field("sector_icb",      pa.string()),  # ICB từ vnstock
    pa.field("exchange",        pa.string()),
    pa.field("charter_capital", pa.float64()),
    pa.field("issue_share",     pa.float64()),
    pa.field("profile",         pa.string()),  # company_profile / business_model
    pa.field("revenue_str",     pa.string()),  # income statement tóm tắt
    pa.field("fetched_at",      pa.string()),
])

CLASSIFY_SCHEMA = pa.schema([
    pa.field("ticker",               pa.string()),
    pa.field("company_name",         pa.string()),
    pa.field("primary_industry",     pa.string()),
    pa.field("secondary_industries", pa.string()),  # JSON list
    pa.field("revenue_breakdown",    pa.string()),  # JSON dict
    pa.field("business_summary",     pa.string()),
    pa.field("classified_at",        pa.string()),
    pa.field("model",                pa.string()),
])


# ═════════════════════════════════════════════════════════════════════════════
# BƯỚC 1 — Company Profile Warehouse
# ═════════════════════════════════════════════════════════════════════════════

class CompanyWarehouse:
    """
    Lưu company profiles vào warehouse/companies/ticker=XXX/overview.parquet
    Đọc từ đây thay vì gọi API mỗi lần.
    """

    def __init__(self, root: str = "data_warehouse"):
        self.companies_dir = Path(root) / "companies"
        self.prices_dir    = Path(root) / "prices"
        self.companies_dir.mkdir(parents=True, exist_ok=True)

    # ── Danh sách tickers từ prices warehouse ─────────────────────────────────

    def get_stock_tickers(self) -> list[str]:
        """Lấy tickers từ prices warehouse, lọc CW/Futures."""
        if not self.prices_dir.exists():
            return []
        tickers = [
            p.name.replace("ticker=", "")
            for p in self.prices_dir.iterdir()
            if p.is_dir() and p.name.startswith("ticker=")
        ]
        return sorted([t for t in tickers if _is_stock(t)])

    # ── Read / Write ───────────────────────────────────────────────────────────

    def has_profile(self, ticker: str) -> bool:
        pf = self.companies_dir / f"ticker={ticker}" / "overview.parquet"
        return pf.exists()

    def save_profile(self, data: dict):
        ticker = data["ticker"]
        ticker_dir = self.companies_dir / f"ticker={ticker}"
        ticker_dir.mkdir(exist_ok=True)
        df = pd.DataFrame([data])
        table = pa.Table.from_pandas(df, schema=PROFILE_SCHEMA, safe=False)
        pq.write_table(table, str(ticker_dir / "overview.parquet"), compression="snappy")

    def load_profile(self, ticker: str) -> dict:
        pf = self.companies_dir / f"ticker={ticker}" / "overview.parquet"
        if not pf.exists():
            return {}
        try:
            # Đọc file trực tiếp + cast về schema chuẩn, tránh type conflict
            table = pq.read_table(str(pf))
            table = table.cast(PROFILE_SCHEMA)
            df = table.to_pandas()
            return df.iloc[0].to_dict() if not df.empty else {}
        except Exception:
            # Fallback: đọc thô qua ParquetFile (bỏ qua schema)
            try:
                df = pq.ParquetFile(str(pf)).read().to_pandas()
                return df.iloc[0].to_dict() if not df.empty else {}
            except Exception:
                return {}

    def load_all_profiles(self) -> pd.DataFrame:
        """Load tất cả profiles đã lưu."""
        frames = []
        for td in self.companies_dir.iterdir():
            if not td.is_dir() or not td.name.startswith("ticker="):
                continue
            pf = td / "overview.parquet"
            if pf.exists():
                frames.append(pq.read_table(str(pf)).to_pandas())
        return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()

    def count_profiles(self) -> int:
        return sum(
            1 for td in self.companies_dir.iterdir()
            if td.is_dir() and (td / "overview.parquet").exists()
        )

    # ── Fetch từ API ──────────────────────────────────────────────────────────

    def fetch_and_save(self, ticker: str) -> bool:
        """Gọi vnstock API, lưu vào warehouse. Trả True nếu thành công."""
        try:
            data = self._fetch_from_api(ticker)
            if data:
                self.save_profile(data)
                return True
            return False
        except Exception as e:
            console.log(f"  [dim]⚠ {ticker}: {e}[/dim]")
            return False

    def _fetch_from_api(self, ticker: str) -> dict:
        base = {
            "ticker": ticker, "company_name": ticker,
            "sector_icb": "", "exchange": "",
            "charter_capital": None, "issue_share": None,
            "profile": "", "revenue_str": "",
            "fetched_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        }

        if USE_UNIFIED:
            ref = Reference()
            ov  = ref.company(ticker).info()
        else:
            ov = get_vnstock(ticker).company.overview()

        if ov is not None and not ov.empty:
            row = ov.iloc[0]
            base["company_name"] = str(row.get("organ_name",
                                    row.get("company_name", ticker)))
            base["sector_icb"]   = str(row.get("icb_name3",
                                    row.get("icb_name2", "")))
            base["exchange"]     = str(row.get("exchange",
                                    row.get("listing_exchange", "")))
            for cap_col in ("charter_capital",):
                try:
                    base["charter_capital"] = float(row.get(cap_col, 0) or 0)
                except Exception:
                    pass
            for sh_col in ("issue_share", "outstanding_shares"):
                try:
                    base["issue_share"] = float(row.get(sh_col, 0) or 0)
                    break
                except Exception:
                    pass
            for col in ("company_profile", "business_model", "history"):
                if col in ov.columns:
                    val = str(row.get(col, "")).strip()
                    if val and val not in ("nan", "None", ""):
                        base["profile"] = val[:2000]
                        break

        # Income statement (tóm tắt)
        try:
            if USE_UNIFIED:
                inc = Fundamental().equity(ticker).income_statement(period="Y")
            else:
                inc = get_vnstock(ticker)\
                               .finance.income_statement(period="year", lang="en")
            if inc is not None and not inc.empty:
                base["revenue_str"] = inc.tail(2).to_string(max_cols=8)[:600]
        except Exception:
            pass

        return base

    # ── Sync toàn bộ ─────────────────────────────────────────────────────────

    def sync(
        self,
        limit: int = 0,
        skip_existing: bool = True,
        delay: float = 0.4,
    ):
        console.rule("[bold cyan]📥 Sync Company Profiles → Warehouse[/bold cyan]")

        tickers = self.get_stock_tickers()
        console.log(f"  📋 Found {len(tickers)} stocks in prices warehouse")

        if skip_existing:
            before = len(tickers)
            tickers = [t for t in tickers if not self.has_profile(t)]
            console.log(f"  ⏭ Skipping {before - len(tickers)} already synced")

        if limit > 0:
            tickers = tickers[:limit]

        ok = errors = 0

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(), MofNCompleteColumn(),
            TaskProgressColumn(), TimeElapsedColumn(),
            console=console,
        ) as progress:
            task = progress.add_task("Syncing profiles...", total=len(tickers))

            for ticker in tickers:
                progress.update(task, description=f"[cyan]{ticker:6s}[/cyan]", advance=1)
                if self.fetch_and_save(ticker):
                    ok += 1
                else:
                    errors += 1
                time.sleep(delay)

        console.print(
            f"\n[green]✅ Synced {ok} profiles[/green] | "
            f"[red]{errors} errors[/red] | "
            f"Total in warehouse: {self.count_profiles()}"
        )


# ═════════════════════════════════════════════════════════════════════════════
# BƯỚC 2 — Claude Classifier (đọc từ warehouse)
# ═════════════════════════════════════════════════════════════════════════════

class ClassificationStore:
    """Lưu kết quả phân loại AI."""

    def __init__(self, root: str = "data_warehouse"):
        self.path = Path(root) / "_meta" / "industry_classification.parquet"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._df  = self._load()

    def _load(self) -> pd.DataFrame:
        if self.path.exists():
            df = pq.read_table(str(self.path)).to_pandas()
            console.log(f"[green]📂 {len(df)} classifications loaded[/green]")
            return df
        return pd.DataFrame(columns=[f.name for f in CLASSIFY_SCHEMA])

    def save(self):
        if self._df.empty:
            return
        table = pa.Table.from_pandas(self._df, schema=CLASSIFY_SCHEMA, safe=False)
        pq.write_table(table, str(self.path), compression="snappy")

    def is_classified(self, ticker: str) -> bool:
        return ticker in self._df["ticker"].values

    def upsert(self, row: dict):
        self._df = self._df[self._df["ticker"] != row["ticker"]]
        self._df = pd.concat([self._df, pd.DataFrame([row])], ignore_index=True)

    def get(self, ticker: str) -> dict:
        rows = self._df[self._df["ticker"] == ticker]
        return rows.iloc[0].to_dict() if not rows.empty else {}

    def all(self) -> pd.DataFrame:
        return self._df.copy()


def _ledger_record(provider: str, model: str, ok: bool,
                   usage: "dict | None" = None,
                   error: "str | None" = None) -> None:
    """Ghi sổ call LLM (vnstock_llm_ledger) — best-effort, không bao giờ raise."""
    try:
        from vnstock_llm_ledger import record
        record(provider, model, ok=ok, usage=usage, error=error)
    except Exception:
        pass


def _call_claude(prompt: str, model: str = "claude-sonnet-4-6",
                 max_tokens: int = 800) -> str:
    """Gọi Claude API, trả về text response."""
    import os
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        raise EnvironmentError(
            "ANTHROPIC_API_KEY chưa được set.\n"
            "PowerShell : $env:ANTHROPIC_API_KEY = 'sk-ant-...'\n"
            "CMD        : set ANTHROPIC_API_KEY=sk-ant-...\n"
            "Linux/Mac  : export ANTHROPIC_API_KEY=sk-ant-..."
        )
    try:
        resp = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "Content-Type":      "application/json",
                "x-api-key":         api_key,
                "anthropic-version": "2023-06-01",
            },
            json={
                "model":      model,
                "max_tokens": max_tokens,
                "messages":   [{"role": "user", "content": prompt}],
            },
            timeout=60,
        )
        resp.raise_for_status()
        body = resp.json()
    except Exception as e:
        _ledger_record("Anthropic", model, ok=False,
                       error=f"{type(e).__name__}: {str(e)[:120]}")
        raise
    _ledger_record("Anthropic", model, ok=True, usage=body.get("usage"))
    return body["content"][0]["text"]


def _build_prompt(profile: dict) -> str:
    return f"""Bạn là chuyên gia phân tích tài chính Việt Nam. Phân loại doanh nghiệp sau.

MÃ CK: {profile.get('ticker')}
TÊN: {profile.get('company_name')}
NGÀNH ICB (vnstock): {profile.get('sector_icb', 'Không có')}
SÀN: {profile.get('exchange', '')}
MÔ TẢ HOẠT ĐỘNG:
{profile.get('profile', 'Không có thông tin')[:800]}

DỮ LIỆU DOANH THU GẦN NHẤT:
{profile.get('revenue_str', 'Không có')[:400]}

DANH SÁCH NHÓM NGÀNH:
{GROUPS_STR}

Trả lời ĐÚNG định dạng JSON sau, không thêm gì khác:
{{
  "primary_industry": "Tên nhóm ngành chính (chọn chính xác từ danh sách)",
  "secondary_industries": ["Ngành phụ 1", "Ngành phụ 2"],
  "revenue_breakdown": {{
    "Tên ngành": "~X%"
  }},
  "business_summary": "Tóm tắt 1-2 câu hoạt động kinh doanh chính"
}}

Quy tắc:
- Nếu 1 ngành: secondary_industries=[], revenue_breakdown={{"Ngành chính":"~100%"}}
- Nếu đa ngành: liệt kê ngành phụ và ước tính tỷ trọng doanh thu
- Tên ngành PHẢI khớp chính xác với danh sách đã cho"""


def _parse_claude_response(text: str) -> dict:
    match = _re.search(r"\{.*\}", text, _re.DOTALL)
    if not match:
        return {"primary_industry": "Khác",
                "secondary_industries": "[]",
                "revenue_breakdown": "{}",
                "business_summary": ""}
    try:
        data = json.loads(match.group())
        # Validate primary_industry — fallback về "Khác" nếu ngoài danh sách
        pi = str(data.get("primary_industry", "Khác"))
        if pi not in INDUSTRY_GROUPS:
            pi = "Khác"
        # Validate secondary_industries — lọc chỉ giữ ngành hợp lệ
        sec_raw = data.get("secondary_industries", [])
        sec_valid = [s for s in (sec_raw if isinstance(sec_raw, list) else [])
                     if s in INDUSTRY_GROUPS]
        return {
            "primary_industry":     pi,
            "secondary_industries": json.dumps(sec_valid, ensure_ascii=False),
            "revenue_breakdown":    json.dumps(
                data.get("revenue_breakdown", {}), ensure_ascii=False),
            "business_summary":     str(data.get("business_summary", "")),
        }
    except Exception:
        return {"primary_industry": "Khác",
                "secondary_industries": "[]",
                "revenue_breakdown": "{}",
                "business_summary": ""}


def run_classify(
    company_wh: CompanyWarehouse,
    store: ClassificationStore,
    limit: int = 0,
    skip_existing: bool = True,
    delay: float = 0.5,
    model: str = "claude-sonnet-4-6",
    tickers_override: list = None,
):
    """Đọc profiles từ warehouse → Claude → lưu kết quả."""
    console.rule("[bold cyan]🤖 AI Industry Classification[/bold cyan]")

    # Lấy tickers có profile trong warehouse
    if tickers_override is not None:
        tickers = tickers_override
    else:
        tickers = [
            p.name.replace("ticker=", "")
            for p in company_wh.companies_dir.iterdir()
            if p.is_dir() and (p / "overview.parquet").exists()
        ]
        tickers = sorted([t for t in tickers if _is_stock(t)])
    console.log(f"  📋 {len(tickers)} profiles available in warehouse")

    if skip_existing:
        before = len(tickers)
        tickers = [t for t in tickers if not store.is_classified(t)]
        console.log(f"  ⏭ Skipping {before - len(tickers)} already classified")

    if limit > 0:
        tickers = tickers[:limit]

    if not tickers:
        console.print("[green]✅ All tickers already classified![/green]")
        return

    console.log(f"  🤖 Classifying {len(tickers)} tickers with Claude...")

    ok = errors = 0

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(), MofNCompleteColumn(),
        TaskProgressColumn(), TimeElapsedColumn(),
        console=console,
    ) as progress:
        task = progress.add_task("Classifying...", total=len(tickers))

        for i, ticker in enumerate(tickers):
            progress.update(task, description=f"[cyan]{ticker:6s}[/cyan]", advance=1)

            # ✅ Đọc từ warehouse — không gọi API vnstock
            profile = company_wh.load_profile(ticker)
            if not profile:
                errors += 1
                continue

            try:
                prompt   = _build_prompt(profile)
                response = _call_claude(prompt, model)
                result   = _parse_claude_response(response)

                store.upsert({
                    "ticker":               ticker,
                    "company_name":         profile.get("company_name", ticker),
                    "primary_industry":     result["primary_industry"],
                    "secondary_industries": result["secondary_industries"],
                    "revenue_breakdown":    result["revenue_breakdown"],
                    "business_summary":     result["business_summary"],
                    "classified_at":        datetime.now().strftime("%Y-%m-%d %H:%M"),
                    "model":                model,
                })
                ok += 1
            except Exception as e:
                console.log(f"  [yellow]⚠ {ticker}: {e}[/yellow]")
                errors += 1

            # Checkpoint mỗi 50
            if (i + 1) % 50 == 0:
                store.save()
                console.log(f"  💾 Checkpoint {i+1}/{len(tickers)}")

            time.sleep(delay)

    store.save()
    console.print(
        f"\n[green]✅ Done:[/green] {ok} classified | "
        f"[red]{errors} errors[/red] | "
        f"Total: {len(store.all())}"
    )


# ═════════════════════════════════════════════════════════════════════════════
# Display
# ═════════════════════════════════════════════════════════════════════════════

def print_company(store: ClassificationStore,
                  company_wh: CompanyWarehouse,
                  ticker: str):
    ticker = ticker.upper()
    row    = store.get(ticker)
    prof   = company_wh.load_profile(ticker)

    if not row and not prof:
        console.print(f"[yellow]⚠ {ticker}: không có dữ liệu[/yellow]")
        return

    title = f"🏭 {ticker}"
    if prof:
        title += f" — {prof.get('company_name', '')}"

    lines = []

    if row:
        lines.append(f"  [bold]Ngành chính:[/bold]  [cyan]{row['primary_industry']}[/cyan]")
        sec = json.loads(row.get("secondary_industries", "[]") or "[]")
        if sec:
            lines.append(f"  [bold]Ngành phụ:[/bold]    {', '.join(sec)}")
        rev = json.loads(row.get("revenue_breakdown", "{}") or "{}")
        if rev:
            lines.append("  [bold]Tỷ trọng DT:[/bold]")
            for k, v in rev.items():
                lines.append(f"    • {k}: {v}")
        if row.get("business_summary"):
            lines.append(f"  [bold]Tóm tắt:[/bold]      {row['business_summary']}")
        lines.append(f"  [dim]Phân loại: {row.get('classified_at','')} | Model: {row.get('model','')}[/dim]")
    else:
        lines.append("  [yellow]Chưa phân loại — chạy --classify[/yellow]")

    if prof:
        lines.append("")
        lines.append(f"  [bold]Ngành ICB:[/bold]    {prof.get('sector_icb','')}")
        lines.append(f"  [bold]Sàn:[/bold]          {prof.get('exchange','')}")
        cap = prof.get("charter_capital") or 0
        if cap:
            lines.append(f"  [bold]Vốn điều lệ:[/bold] {cap/1e9:.1f} tỷ VND")

    console.print(Panel("\n".join(lines), title=title, border_style="blue"))


def print_report(store: ClassificationStore):
    df = store.all()
    if df.empty:
        console.print("[yellow]⚠ Chưa có kết quả phân loại[/yellow]")
        return

    console.rule("[bold]📊 Báo Cáo Phân Loại Ngành[/bold]")

    total = len(df)
    khac  = len(df[df["primary_industry"] == "Khác"])
    multi = df[df["secondary_industries"].apply(
        lambda x: len(json.loads(x or "[]")) > 0
    )]

    # Bảng ngành chính — chỉ đếm primary_industry
    summary = (
        df.groupby("primary_industry")
          .size()
          .reset_index(name="count")
          .sort_values("count", ascending=False)
    )

    t = Table(
        title=f"Phân loại {total} doanh nghiệp  |  Chưa xác định: {khac}  |  Đa ngành: {len(multi)}",
        box=box.SIMPLE_HEAVY,
    )
    t.add_column("Ngành chính",   style="cyan")
    t.add_column("Số DN",         justify="right", style="bold")
    t.add_column("% thị trường",  justify="right")
    t.add_column("Ngành phụ phổ biến", style="dim")

    for _, row in summary.iterrows():
        industry = row["primary_industry"]
        count    = row["count"]
        pct      = count / total * 100

        # Tìm ngành phụ phổ biến nhất trong nhóm này
        sub_counts = {}
        subset = df[df["primary_industry"] == industry]
        for secs in subset["secondary_industries"]:
            for s in json.loads(secs or "[]"):
                sub_counts[s] = sub_counts.get(s, 0) + 1
        top_sub = sorted(sub_counts, key=sub_counts.get, reverse=True)[:2]
        sub_str = ", ".join(top_sub) if top_sub else ""

        # Màu đặc biệt cho "Khác"
        name_str = f"[yellow]{industry}[/yellow]" if industry == "Khác" else industry
        t.add_row(name_str, str(count), f"{pct:.1f}%", sub_str)

    console.print(t)

    # Giải thích ngắn
    console.print(
        f"  [dim]"
        f"Ngành chính = nhóm ngành chủ đạo của DN  |  "
        f"Đa ngành = DN có thêm ngành phụ ({len(multi)}/{total})  |  "
        f"'Khác' = chưa phân loại được ({khac})"
        f"[/dim]"
    )
    if khac > 0:
        others = df[df["primary_industry"] == "Khác"]["ticker"].tolist()
        console.print(
            f"  [yellow]→ Chạy --suggest-industries để Claude đề xuất ngành cho: "
            f"{', '.join(others[:10])}{'...' if len(others) > 10 else ''}[/yellow]"
        )




def suggest_industries(store: ClassificationStore, model: str = "claude-sonnet-4-6"):
    """
    Phân tích các mã bị xếp 'Khác' → Claude đề xuất ngành mới cần thêm.
    Chạy sau khi classify xong toàn bộ để cải thiện danh sách ngành.
    """
    df = store.all()
    if df.empty:
        console.print("[yellow]⚠ Chưa có dữ liệu phân loại[/yellow]")
        return

    others = df[df["primary_industry"] == "Khác"].copy()
    if others.empty:
        console.print("[green]✅ Không có mã nào bị xếp 'Khác'![/green]")
        return

    console.rule(f"[bold cyan]🔍 Phân tích {len(others)} mã bị xếp 'Khác'[/bold cyan]")

    # Tóm tắt danh sách để gửi Claude
    summaries = []
    for _, row in others.iterrows():
        s = f"- {row['ticker']} ({row['company_name']}): {row['business_summary']}"
        summaries.append(s[:200])

    prompt = f"""Bạn là chuyên gia phân loại ngành chứng khoán Việt Nam.

Dưới đây là danh sách các doanh nghiệp hiện bị xếp vào nhóm "Khác" vì danh sách ngành chưa đủ:

{chr(10).join(summaries)}

Danh sách ngành hiện có:
{GROUPS_STR}

Nhiệm vụ: Đề xuất các nhóm ngành MỚI cần thêm vào danh sách để phân loại chính xác hơn.

Yêu cầu:
- Chỉ đề xuất ngành thực sự còn thiếu, không trùng với ngành đã có
- Mỗi ngành đề xuất phải cover ít nhất 2-3 doanh nghiệp trong danh sách trên
- Tên ngành ngắn gọn, nhất quán với style hiện có (tiếng Việt, dùng & để ghép)
- Với mỗi ngành đề xuất, liệt kê các mã sẽ được xếp vào đó

Trả lời theo định dạng JSON:
{{
  "suggested_industries": [
    {{
      "name": "Tên ngành mới",
      "tickers": ["AAA", "BBB"],
      "reason": "Lý do ngắn gọn"
    }}
  ],
  "remain_other": ["Các mã thực sự không thuộc ngành nào cụ thể"]
}}"""

    console.print(f"  [dim]Gửi {len(others)} mã đến Claude để phân tích...[/dim]")
    try:
        response = _call_claude(prompt, model)
        match = _re.search(r"\{.*\}", response, _re.DOTALL)
        if not match:
            console.print("[yellow]⚠ Không parse được response[/yellow]")
            console.print(response)
            return

        data = json.loads(match.group())
        suggestions = data.get("suggested_industries", [])
        remain = data.get("remain_other", [])

        if suggestions:
            t = Table(title="💡 Đề xuất ngành mới", box=box.SIMPLE_HEAVY)
            t.add_column("Ngành đề xuất", style="cyan")
            t.add_column("Các mã", style="yellow")
            t.add_column("Lý do", style="dim")
            for s in suggestions:
                t.add_row(
                    s.get("name", ""),
                    ", ".join(s.get("tickers", [])),
                    s.get("reason", "")[:60],
                )
            console.print(t)

        if remain:
            console.print(f"\n  [dim]Thực sự là 'Khác': {', '.join(remain)}[/dim]")

        console.print(
            "\n  [bold]Để thêm ngành:[/bold] Mở file → sửa INDUSTRY_GROUPS → "
            "chạy lại:\n"
            "  [cyan]python vnstock_classifier.py --classify --rerun-others[/cyan]"
        )

    except Exception as e:
        console.print(f"[red]❌ Lỗi: {e}[/red]")




def spot_check(store: ClassificationStore, industry: str, model: str = "claude-haiku-4-5-20251001"):
    """
    Gửi business_summary của tất cả mã trong một ngành cho Claude,
    nhờ Claude gắn cờ những mã có vẻ bị phân loại sai.
    """
    df = store.all()
    if df.empty:
        console.print("[yellow]⚠ Chưa có dữ liệu phân loại[/yellow]")
        return

    # Tìm ngành gần nhất nếu nhập không chính xác
    if industry not in INDUSTRY_GROUPS:
        matches = [g for g in INDUSTRY_GROUPS if industry.lower() in g.lower()]
        if not matches:
            console.print(f"[red]❌ Không tìm thấy ngành '{industry}'[/red]")
            console.print(f"  Các ngành hiện có: {', '.join(INDUSTRY_GROUPS)}")
            return
        industry = matches[0]
        console.print(f"  [dim]→ Tìm thấy ngành gần nhất: '{industry}'[/dim]")

    subset = df[df["primary_industry"] == industry].copy()
    if subset.empty:
        console.print(f"[yellow]⚠ Không có mã nào trong ngành '{industry}'[/yellow]")
        return

    console.rule(f"[bold cyan]🔎 Spot-check: {industry} ({len(subset)} mã)[/bold cyan]")

    # Chia thành batch 50 mã để tránh prompt quá dài
    BATCH = 50
    all_suspicious = []
    all_correct    = []

    for batch_start in range(0, len(subset), BATCH):
        batch = subset.iloc[batch_start:batch_start + BATCH]
        batch_num = batch_start // BATCH + 1
        total_batches = (len(subset) + BATCH - 1) // BATCH
        console.print(f"  [dim]Batch {batch_num}/{total_batches} ({len(batch)} mã)...[/dim]")

        lines = []
        for _, row in batch.iterrows():
            sec = json.loads(row.get("secondary_industries", "[]") or "[]")
            sec_str = f" | Ngành phụ: {', '.join(sec)}" if sec else ""
            lines.append(
                f"- {row['ticker']} ({row['company_name']}): "
                f"{row['business_summary']}{sec_str}"
            )

        prompt = f"""Bạn là chuyên gia phân tích tài chính Việt Nam.

Dưới đây là danh sách các doanh nghiệp đang được xếp vào ngành "{industry}".
Hãy xem xét từng mã và xác định:
1. Mã nào được xếp ĐÚNG vào "{industry}"
2. Mã nào có vẻ xếp SAI — dựa trên mô tả hoạt động kinh doanh

{chr(10).join(lines)}

Trả lời ĐÚNG định dạng JSON sau, không thêm gì khác:
{{
  "suspicious": [
    {{
      "ticker": "XXX",
      "current": "{industry}",
      "suggested": "Ngành đúng hơn (chọn từ danh sách)",
      "reason": "Lý do ngắn gọn (1 câu)"
    }}
  ],
  "correct_count": <số mã xếp đúng>
}}

Danh sách ngành hợp lệ để suggest:
{GROUPS_STR}

Chỉ đưa vào "suspicious" những mã BẠN TỰ TIN là sai ngành.
Nếu không chắc thì bỏ qua, đừng flag nhầm."""

        try:
            # max_tokens=2000: đủ cho ~50 mã suspicious với reason đầy đủ
            response = _call_claude(prompt, model, max_tokens=2000)
            # Xóa markdown code block nếu có
            clean = _re.sub(r"```(?:json)?\s*", "", response).strip()
            match = _re.search(r"\{.*\}", clean, _re.DOTALL)
            if not match:
                console.print(f"  [yellow]⚠ Batch {batch_num}: không parse được[/yellow]")
                continue

            json_str = match.group()
            # Thay newline/tab trong string values → space để tránh JSON lỗi
            # Xử lý newline/tab trong JSON → space để tránh parse lỗi
            json_str = json_str.replace("\n", " ").replace("\t", " ").replace("\r", " ")
            try:
                data = json.loads(json_str)
            except Exception:
                console.print(f"  [yellow]⚠ Batch {batch_num}: JSON không hợp lệ, bỏ qua[/yellow]")
                continue
            suspicious = data.get("suspicious", [])
            correct    = data.get("correct_count", len(batch) - len(suspicious))

            # Validate suggested industry
            for item in suspicious:
                if item.get("suggested") not in INDUSTRY_GROUPS:
                    item["suggested"] = "Khác"

            all_suspicious.extend(suspicious)
            all_correct.append(correct)

        except Exception as e:
            console.print(f"  [yellow]⚠ Batch {batch_num}: {e}[/yellow]")

    # ── Hiển thị kết quả ─────────────────────────────────────────────────────
    total_correct    = sum(all_correct)
    total_suspicious = len(all_suspicious)
    accuracy_pct     = total_correct / len(subset) * 100 if not subset.empty else 0

    console.print()
    if not all_suspicious:
        console.print(f"[green]✅ Tất cả {len(subset)} mã trong '{industry}' có vẻ đúng![/green]")
        return

    t = Table(
        title=f"⚠ {total_suspicious} mã đáng ngờ / {len(subset)} tổng  "
              f"(~{accuracy_pct:.0f}% đúng)",
        box=box.SIMPLE_HEAVY,
    )
    t.add_column("Ticker",    style="cyan",   width=8)
    t.add_column("Tên công ty",               width=30)
    t.add_column("Ngành đề xuất", style="yellow", width=28)
    t.add_column("Lý do",     style="dim",    width=45)

    for item in all_suspicious:
        ticker  = item.get("ticker", "")
        # Lấy tên công ty từ store
        row_data = store.get(ticker)
        name = row_data.get("company_name", ticker) if row_data else ticker
        t.add_row(
            ticker,
            name[:28],
            item.get("suggested", ""),
            item.get("reason", "")[:43],
        )

    console.print(t)
    console.print(
        f"  [dim]Để re-classify các mã này, chạy:[/dim]\n"
        f"  [cyan]python vnstock_classifier.py --classify --rerun "
        + " ".join([f"  # {x['ticker']}" for x in all_suspicious[:3]])
        + "[/cyan]"
    )

    # Hỏi có muốn re-classify luôn không
    flagged_tickers = [x["ticker"] for x in all_suspicious]
    console.print(
        f"\n  [bold]Muốn re-classify {len(flagged_tickers)} mã này không?[/bold]\n"
        f"  Chạy: [cyan]python vnstock_classifier.py --rerun-flagged "
        f"{' '.join(flagged_tickers[:5])}{'...' if len(flagged_tickers)>5 else ''}[/cyan]"
    )

    return flagged_tickers


# ═════════════════════════════════════════════════════════════════════════════
# CLI
# ═════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="VnStock Industry Classifier")
    parser.add_argument("--sync-profiles", action="store_true",
                        help="Bước 1: Tải company profiles → warehouse")
    parser.add_argument("--classify",      action="store_true",
                        help="Bước 2: Phân loại AI từ warehouse profiles")
    parser.add_argument("--rerun",         action="store_true",
                        help="Bỏ qua skip_existing, chạy lại tất cả")
    parser.add_argument("--rerun-others",  action="store_true",
                        help="Chỉ chạy lại các mã bị xếp 'Khác'")
    parser.add_argument("--suggest-industries", action="store_true",
                        help="Claude đề xuất ngành mới từ các mã 'Khác'")
    parser.add_argument("--spot-check",      metavar="INDUSTRY",
                        help="Claude kiểm tra mã bị phân loại sai trong một ngành")
    parser.add_argument("--rerun-flagged",   nargs="+", metavar="TICKER",
                        help="Re-classify danh sách mã cụ thể (kết quả từ --spot-check)")
    parser.add_argument("--limit",         type=int, default=0,
                        help="Giới hạn số tickers (0 = tất cả)")
    parser.add_argument("--query",         metavar="TICKER",
                        help="Xem chi tiết một mã")
    parser.add_argument("--report",        action="store_true",
                        help="Báo cáo tổng hợp theo ngành")
    parser.add_argument("--export",        action="store_true",
                        help="Xuất CSV")
    parser.add_argument("--warehouse",     default="data_warehouse",
                        help="Đường dẫn warehouse")
    parser.add_argument("--delay",         type=float, default=0.4,
                        help="Delay giữa API calls (giây)")
    parser.add_argument("--model",         default="claude-haiku-4-5-20251001",
                        choices=["claude-haiku-4-5-20251001", "claude-sonnet-4-6"],
                        help="Model Claude dùng để phân loại (default: haiku — rẻ hơn 73%%)")
    args = parser.parse_args()

    company_wh = CompanyWarehouse(args.warehouse)
    store      = ClassificationStore(args.warehouse)

    if args.sync_profiles:
        company_wh.sync(
            limit=args.limit,
            skip_existing=not args.rerun,
            delay=args.delay,
        )

    if args.classify:
        run_classify(
            company_wh=company_wh,
            store=store,
            limit=args.limit,
            skip_existing=not args.rerun,
            delay=args.delay,
            model=args.model,
        )

    if args.rerun_others:
        # Chỉ chạy lại các mã bị xếp "Khác"
        others_tickers = store.all()
        others_tickers = others_tickers[
            others_tickers["primary_industry"] == "Khác"
        ]["ticker"].tolist()
        if not others_tickers:
            console.print("[green]✅ Không có mã nào bị xếp 'Khác'[/green]")
        else:
            console.print(f"  [cyan]Chạy lại {len(others_tickers)} mã 'Khác'...[/cyan]")
            run_classify(
                company_wh=company_wh,
                store=store,
                limit=args.limit,
                skip_existing=False,
                delay=args.delay,
                model=args.model,
                tickers_override=others_tickers,
            )

    if args.suggest_industries:
        suggest_industries(store, model=args.model)

    if args.spot_check:
        spot_check(store, industry=args.spot_check, model=args.model)

    if args.rerun_flagged:
        console.print(f"  [cyan]Re-classifying {len(args.rerun_flagged)} mã được flag...[/cyan]")
        run_classify(
            company_wh=company_wh,
            store=store,
            skip_existing=False,
            delay=args.delay,
            model=args.model,
            tickers_override=args.rerun_flagged,
        )

    if args.query:
        print_company(store, company_wh, args.query)

    if args.report:
        print_report(store)

    if args.export:
        df = store.all()
        if not df.empty:
            df = df.copy()
            df["secondary_industries"] = df["secondary_industries"].apply(
                lambda x: ", ".join(json.loads(x or "[]"))
            )
            df["revenue_breakdown"] = df["revenue_breakdown"].apply(
                lambda x: " | ".join(
                    f"{k}: {v}" for k, v in json.loads(x or "{}").items()
                )
            )
            path = f"industry_classification_{datetime.now().strftime('%Y%m%d')}.csv"
            df.to_csv(path, index=False, encoding="utf-8-sig")
            console.print(f"[green]✅ Exported → {path}[/green]")

    if not any([args.sync_profiles, args.classify, args.rerun_others,
                args.query, args.report, args.export, args.suggest_industries,
                args.spot_check, args.rerun_flagged]):
        print_report(store)
