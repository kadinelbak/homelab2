# Dockerfile for dashboard service (e.g., Grafana panel, custom UI)
# Using a simple static web server for dashboard examples

FROM nginx:alpine

# Remove default nginx static files
RUN rm -rf /usr/share/nginx/html/*

# Copy dashboard files
COPY . /usr/share/nginx/html

# Expose port
EXPOSE 80

# Start nginx
CMD ["nginx", "-g", "daemon off;"]