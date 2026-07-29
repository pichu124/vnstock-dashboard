@echo off
:: VnStock Weekend Pipeline — manual trigger
:: Gop 3 viec cuoi tuan: rates-weekly (Telegram) -> vietstock corp actions
:: -> fundamentals --force (~30-40 phut). Same as task '09:00 Saturday'.

cd /d "%~dp0.."
python run.py --warehouse data_warehouse weekend
pause
