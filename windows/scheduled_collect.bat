@echo off
REM 视频号监控定时采集 — 被 Windows 任务计划程序 6:00 调用
wsl -d Ubuntu-24.04 bash -c "cd /home/eric/social-monitor && python3 scheduled_collect.py"
