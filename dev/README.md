# Homelab Developer Experience

This directory provides tools and templates for building, testing, and deploying custom services to your homelab.

## Directory Structure

```
dev/
├── templates/          # Service templates for different types
│   ├── web-app/        # Full-stack web application
│   ├── api-service/    # REST/gRPC API service
│   ├── worker/         # Background job processor
│   ├── cron-job/       # Scheduled task
│   └── dashboard/      # Custom UI or Grafana panel
├── local-overrides/    # Docker compose overrides for existing services
├── scripts/            # Helper scripts for development and deployment
└── services/           # Where you create your services
```

## Getting Started

### 1. Create a New Service

Use the `create-service.sh` script to create a new service from a template:

```bash
./dev/scripts/create-service.sh <service-name> <template-type> [language]
```

Examples:
```bash
# Create a web application
./dev/scripts/create-service.sh my-webapp web-app

# Create an API service
./dev/scripts/create-service.sh my-api api-service

# Create a worker service
./dev/scripts/create-service.sh my-worker worker

# Create a scheduled job
./dev/scripts/create-service.sh my-cron-job cron-job

# Create a dashboard
./dev/scripts/create-service.sh my-dashboard dashboard
```

### 2. Develop Locally

Each service includes a `docker-compose.dev.yml` for local development with live reload:

```bash
cd dev/services/<service-name>
docker compose -f docker-compose.dev.yml up -d
```

This will:
- Mount your source code for live reload
- Use development configuration (debug logging, lower resource limits)
- Point to local test services (if configured)
- Expose debug ports if needed

### 3. Test Your Service

A basic testing framework is provided in `dev/testing/`. You can:
- Write unit tests using your preferred framework
- Run integration tests against test databases
- Use test containers for isolating dependencies

### 4. Prepare for Deployment

Generate a docker-compose snippet for adding your service to the appropriate homelab phase:

```bash
./dev/scripts/generate-compose-snippet.sh <service-name> [phase]
```

Examples:
```bash
# Generate snippet for phase3-ai-gaming (default for most services)
./dev/scripts/generate-compose-snippet.sh my-webapp

# Specify a target phase explicitly
./dev/scripts/generate-compose-snippet.sh my-dashboard phase1-core
```

This will create a `deployment-snippet.yml` in your service directory that you can add to the phase's docker-compose.yml.

### 5. Deploy to Homelab

After adding the service to a phase's docker-compose.yml:

```bash
cd <phase-directory>
docker compose --env-file ../../.env up -d
```

Or use the helper scripts:
```bash
./scripts/toggle-ondemand.sh up   # For phase4 services
```

## Available Templates

### Web App Template (`web-app`)
- Node.js example with Express
- Multi-stage Docker build
- Development Dockerfile with nodemon for live reload
- Basic project structure with `src/` directory

### API Service Template (`api-service`)
- Python/FastAPI example
- Multi-stage Docker build with non-root user
- Development Dockerfile with live reload
- Requirements file for dependencies

### Worker Template (`worker`)
- Python example for background processing
- Multi-stage Docker build with non-root user
- Development Dockerfile
- Designed for long-running background tasks

### Cron Job Template (`cron-job`)
- Alpine Linux with cron
- Simple job script that runs on schedule
- Development version for running jobs on demand
- Configurable schedule via crontab

### Dashboard Template (`dashboard`)
- Static web server (nginx) for dashboards
- Simple volume mount for live reload of HTML/CSS/JS
- Example for custom UIs or Grafana panels

## Local Development Overrides

The `dev/local-overrides/` directory contains `docker-compose.override.yml` which can be used with existing services to enable development mode:

```bash
# Example usage with an existing service
docker compose -f phase1-core/docker-compose.yml -f dev/local-overrides/docker-compose.override.yml up -d
```

This file provides examples of how to:
- Reduce resource limits for development
- Enable debug logging
- Point to test databases or services
- Disable certain production features
- Add development-specific volume mounts

## Helper Scripts

### `create-service.sh`
Create a new service from a template
Usage: `./create-service.sh <service-name> <template-type> [language]`

### `generate-compose-snippet.sh`
Generate a docker-compose snippet for deployment
Usage: `./generate-compose-snippet.sh <service-name> [phase]`

### `deploy-to-homelab.sh`
Helper for deployment preparation
Usage: `./deploy-to-homelab.sh <service-name>`

## Best Practices

1. **Keep services small and focused** - Follow the Unix philosophy of doing one thing well
2. **Use environment variables for configuration** - Makes services portable across environments
3. **Add health checks** - Helps Docker and orchestration systems monitor your service
4. **Label your service** - Add labels for homepage, watchtower, and monitoring integration
5. **Use volumes for persistent data** - Store data under `${DATA_PATH}/dev-services/<service-name>/`
6. **Follow homelab conventions** - Use the same PUID/PGID, networks, and naming patterns
7. **Document your service** - Keep the README.md updated with usage instructions
8. **Use semantic versioning** - Tag your releases if you build and push images
9. **Consider security** - Run as non-root user when possible, drop unnecessary capabilities
10. **Test thoroughly** - Use the provided testing framework or add your own

## Integration with Homelab Systems

Your custom services can easily integrate with existing homelab systems:

- **PostgreSQL**: Use `homelab_postgres:5432` as hostname
- **Redis**: Use `homelab_redis:6379` as hostname
- **Authentik SSO**: Configure OAuth/OIDC using client ID/secret from `.env`
- **Ollama AI**: Use `http://ollama:11434` for Llama model access
- **n8n Workflows**: Call via webhook or use as a workflow step
- **Home Assistant**: Integrate via REST API or WebSocket
- **Prometheus/Grafana**: Expose metrics on `/metrics` endpoint
- **Loki**: Log to stdout/stderr in JSON format for easy ingestion
- **Vaultwarden**: Store API tokens or credentials as secure notes

## Example: Creating an AI-Powered Service

Here's how you might create a service that uses the shared Llama model:

```bash
# 1. Create a worker service for AI processing
./dev/scripts/create-service.sh ai-summarizer worker

# 2. Edit the worker.py to use the Ollama API:
#    - Make HTTP POST to http://ollama:11434/api/generate
#    - Process incoming messages from a queue or API
#    - Return AI-generated summaries

# 3. Test locally:
cd dev/services/ai-summarizer
docker compose -f docker-compose.dev.yml up -d

# 4. Prepare for deployment:
./dev/scripts/generate-compose-snippet.sh ai-summarizer phase3-ai-gaming

# 5. Add the generated snippet to phase3-ai-gaming/docker-compose.yml
#    - Make sure to configure any needed environment variables
#    - Add appropriate volume mounts for persistent data if needed

# 6. Deploy:
cd phase3-ai-gaming
docker compose --env-file ../../.env up -d
```

## Troubleshooting

- **Container won't start**: Check logs with `docker compose logs <service>`
- **Port conflicts**: Ensure your service isn't conflicting with existing services
- **Volume permissions**: Make sure `${DATA_PATH}` directories are owned by PUID:PGID
- **Network issues**: Verify the service is on the correct networks (homelab_proxy, homelab_internal)
- **Environment variables**: Check that required variables are set in .env or passed correctly

## License and Contribution

Feel free to adapt these templates for your needs. If you improve them, consider contributing back to make the homelab developer experience better for everyone.

Happy hacking! 🚀