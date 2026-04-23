@echo off
:: VnStock Weekly Corp Actions — manual trigger
:: Scrapes Vietstock for new dividends/splits and registers them.
:: Run this any time after hearing about a new corporate action.

cd /d "%~dp0.."
python run.py --warehouse data_warehouse vietstock --bulk --register
pause
