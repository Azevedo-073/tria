@echo off
cd /d C:\Users\marco\tria
set PYTHONIOENCODING=utf-8
call venv\Scripts\activate.bat
if not exist logs mkdir logs
python main.py run -v >> logs\tria.log 2>&1
