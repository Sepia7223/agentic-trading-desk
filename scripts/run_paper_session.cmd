@echo off
rem Daily paper-trading session wrapper (invoked by Windows Task Scheduler).
cd /d "%~dp0.."
set PYTHONPATH=src;scripts
python scripts\paper_trade.py >> data\paper\session.log 2>&1
