@echo off
cd /d E:\work\digitalfusion-release
set PYTHONPATH=E:\work\digitalfusion-release
powershell.exe -ExecutionPolicy Bypass -NoProfile -File "E:\work\digitalfusion-release\.task\run_stellarator_task.ps1"
