@echo off
chcp 65001 >nul
cd /d "C:\Users\skyhu\Documents\Obsidian Vault\_pipeline\scripts"
"C:\Users\skyhu\AppData\Local\Programs\Python\Python310\python.exe" "C:\Users\skyhu\Documents\Obsidian Vault\_pipeline\scripts\scheduler.py" run-now
