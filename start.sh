#!/bin/sh
# 启动 cron（每日 15:10 跑 daily_update.py）+ 静态站点服务
crontab /app/crontab
crond
cd /app/site && exec python3 -m http.server 8000
