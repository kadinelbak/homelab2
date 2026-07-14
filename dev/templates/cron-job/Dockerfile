# Dockerfile for production cron job
# Uses alpine linux with cron

FROM alpine:latest

# Install cron and bash
RUN apk add --no-cache cronie bash

# Create a directory for our job scripts
RUN mkdir -p /usr/local/bin

# Copy the job script
COPY job.sh /usr/local/bin/job.sh
RUN chmod +x /usr/local/bin/job.sh

# Copy the crontab file
# This crontab runs the job every day at 2:30 AM
# Adjust as needed in the actual deployment
COPY crontab /etc/crontabs/root

# Run cron in foreground
CMD ["crond", "-f", "-L", "/dev/stdout"]