@echo off
:: VnStock Daily Pipeline — manual trigger
:: Same as the scheduled task: sync + validate + audit
:: Run this any time to force a full refresh.

cd /d "%~dp0.."
python run.py --warehouse data_warehouse all
pause
