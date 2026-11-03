@echo off
REM Windows: double-click to start LifeOS (iPhone mode). Close the window to stop.
cd /d "%~dp0"
python -m lifeos phone
pause
