@echo off
:: VnStock Daily Pipeline — manual trigger
:: Same as the scheduled task: 14 buoc sync -> ... -> doctor -> brief chieu
:: (brief co guard chong gui trung trong ngay). Run any time for full refresh.

cd /d "%~dp0.."
python run.py --warehouse data_warehouse all
pause
