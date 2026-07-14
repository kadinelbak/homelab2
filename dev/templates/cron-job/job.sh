#!/bin/bash
# Simple cron job script that logs the current timestamp
echo "[$(date)] Cron job executed" >> /var/log/cron.log 2>&1
# Add your actual job logic here
# For example, you could call a script to process data, backup, etc.