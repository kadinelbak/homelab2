# Shared Llama Model Availability Feature Spec

## Overview
Make the Llama (or any Ollama-hosted) language model available as a shared service across all homelab containers. This enables AI-powered features in services like n8n workflows, Home Assistant automations, Open WebUI, and custom scripts without requiring each service to manage its own model instance. The spec ensures low-latency internal access, efficient GPU utilization, and simple configuration for AI integration.

## Core Components
- **Ollama Service** (existing in phase3-ai-gaming): Runs the Llama model and provides an OpenAI-compatible API endpoint.
- **Internal Network Access**: Utilize the existing `homelab_internal` Docker network for secure, low-latency communication between containers.
- **Model Caching**: Persistent storage for model files to avoid repeated downloads.
- **GPU Resource Management**: If using NVIDIA Ollama, ensure proper GPU access and prevent contention.
- **AI Integration Points**: Pre-configured environment variables or config snippets for services to point to the shared Ollama instance.

## Implementation Plan (Single AI Execution)

### Phase 1: Optimize Ollama for Internal Sharing
1. **Ensure Ollama is on `homelab_internal` network**:
   - Verify the ollama service in `phase3-ai-gaming/docker-compose.yml` is attached to `homelab_internal` (it should already be, as it needs to talk to the central postgres for OpenWebUI? Actually OpenWebUI uses Ollama directly, so it needs internal access).
   - If not, add:
     ```yaml
     ollama:
       networks:
         - homelab_internal
     ```
   - Remove any port publishing if not needed for external access (though keeping `11434:11434` on host is useful for testing).

2. **Configure Persistent Model Storage**:
   - Ollama already uses `${DATA_PATH}/phase3-ai-gaming/data/ollama` for models. Ensure this is a named volume or bind mount with sufficient space.
   - Consider optimizing for performance if on slower storage (e.g., use SSD/NVMe path).

3. **Expose Ollama Internally via Service Name**:
   - Ollama is already accessible at `http://ollama:11434` within the Docker network due to service name resolution.
   - Confirm no firewall rules block internal traffic on port 11434.

### Phase 2: Pre-Configure Common AI Integration Patterns
Create a standardized way for services to discover and use the shared Ollama instance.

#### Method 1: Environment Variables (Recommended for simplicity)
Deploy a shared `.env` file or script that services can source. However, since each service has its own env, we'll document the standard variables.

Define these as the **shared Ollama connection details**:
- `OLLAMA_HOST=http://ollama:11434`
- `OLLAMA_API_BASE_URL=http://ollama:11434/api`
- `OLLAMA_MODEL=llama3` (or whatever default model is pulled)

#### Method 2: DNS/Service Discovery
Leverage Docker's internal DNS: `ollama` resolves to the Ollama container's IP on `homelab_internal`.

#### Method 3: Shared Configuration Volume (Advanced)
Less necessary but possible: mount a shared config file with connection details.

### Phase 3: Integrate Ollama with Key Services
Document and/or automate the configuration for major services to use the shared Ollama.

#### A. n8n (AI Workflows)
- **Integration**: Use Ollama node or HTTP Request node to call Ollama API.
- **Config**: In n8n, set up Ollama credentials:
  - Base URL: `http://ollama:11434`
  - Model Name: `llama3` (configurable per node)
- **Automation**: Create a workflow credential template or n8n workflow that sets default Ollama settings.
- **Example Node Prompt** (for AI workflows):
  ```
  Summarize the following text: {{$json["text"]}}
  Model: llama3
  Base URL: http://ollama:11434
  ```

#### B. Open WebUI (Already Configured)
- **Integration**: Open WebUI in phase3-ai-gaming is designed to use Ollama.
- **Config**: Ensure `OLLAMA_BASE_URL=http://ollama:11434` is set in Open WebUI's environment (it should be prewired per README).
- **Verification**: Check that Open WebUI can list and pull models from the shared Ollama instance.

#### C. Home Assistant
- **Integration**: Use the Ollama conversation agent or custom HTTP commands.
- **Config**:
  - Add Ollama Conversation Agent (via HACS or built-in if available):
    - URL: `http://ollama:11434`
    - Model: `llama3`
  - Or use REST Command to call `/api/generate`.
- **Automation**: Create automations that trigger Ollama for voice responses, summarization, etc.

#### D. Custom Scripts & Automation (n8n, shell scripts)
- Provide a helper script or function:
  ```bash
  # ollama-query.sh
  # Usage: ollama-query.sh "prompt text"
  OLLAMA_HOST=${OLLAMA_HOST:-http://ollama:11434}
  curl -s -X POST $OLLAMA_HOST/api/generate \
    -d "{\"model\": \"llama3\", \"prompt\": \"$1\", \"stream\": false}" |
    jq -r '.response'
  ```
- Place in `/usr/local/bin/` or make available via a shared volume.

#### E. Other Services with AI Capabilities
- **Stirling PDF / IT-Tools**: If they have LLM features, point to `http://ollama:11434`.
- **Actual Budget**: Check for AI categorization features.
- **Spoolman**: Potential for AI-powered wine/book suggestions.
- **Docmost / Cal.com**: AI-assisted note-taking or scheduling.
- **Nextcloud**: With Ollama integration app for AI features in files, notes, etc.
- **Gitea**: Potential for AI-assisted code reviews (if integrated).

### Phase 4: Model Management & Pre-loading
Ensure the desired Llama model is available and ready.

1. **Pre-populate Model on First Start**:
   - Add an init script to the Ollama container (or use a sidecar) that pulls the model if not present.
   - Example Ollama Docker run command override:
     ```yaml
     ollama:
       command: ["serve", "&&", "ollama", "pull", "llama3"]
       # Actually, better to use an entrypoint script:
       # command: ["/bin/sh", "-c", "ollama serve & sleep 5 && ollama pull llama3 && wait"]
     ```
   - Simpler: Rely on the first request to trigger the pull, but add a post-deploy step to pre-warm.

2. **Post-Deploy Model Warm-up** (in `scripts/post-deploy.sh`):
   ```bash
   # Wait for Ollama to be ready
   until curl -s http://ollama:11434/api/tags; do sleep 1; done
   # Pull the default model if not present
   if ! curl -s http://ollama:11434/api/tags | grep -q "llama3"; then
     echo "Pulling llama3 model..."
     curl -s -X POST http://ollama:11434/api/pull -d '{"name": "llama3"}'
   fi
   ```

3. **Model Selection Mechanism**:
   - Allow overriding via `.env`: `OLLAMA_MODEL=llama3` or `OLLAMA_MODEL=mistral`
   - Provide a script to change models: `scripts/set-ollama-model.sh <model-name>`

### Phase 5: GPU Sharing & Resource Management (If Applicable)
If using NVIDIA Ollama container:
- **Verify GPU Access**: Ensure `gpus: all` or specific device IDs are set.
- **Prevent Contention**: Ollama is generally efficient; monitor via `nvidia-smi`.
- **Alternative**: Consider time-scheduling or prioritization if multiple AI workloads (though currently Ollama is the main consumer).
- **Documentation**: Note in README that GPU is dedicated to Ollama by default; other services use CPU fallbacks or external APIs.

### Phase 6: Security & Access Control
- **Internal-Only Option**: For maximum security, remove port publishing (`11434:11434`) and rely solely on internal network. Services must be on `homelab_internal` or use host network mode to access.
- **Network Policies**: If using advanced Docker networking, ensure `homelab_internal` allows traffic to ollama:11434.
- **Authentication**: Ollama does not have built-in auth. Trust the internal network. If needed, place a simple auth proxy (like Authelia) in front—but this adds latency. For homelab, internal trust is usually acceptable.
- **API Key Simulation**: Some services expect an API key. Ollama doesn't use one, but you can set a dummy value if required (e.g., `OLLAMA_API_KEY=ollama`).

### Phase 7: Documentation & Automation
- **Auto-generated README Section**: Post-deploy script adds a section to README.md:
  ```
  ## 🦙 Shared Llama Model (via Ollama)
  The Ollama service is available internally at `http://ollama:11434` with the `llama3` model pre-loaded.
  
  To use in your workflows or scripts:
  - Base URL: `http://ollama:11434`
  - API Endpoint: `http://ollama:11434/api/generate`
  - Default Model: llama3 (configure via OLLAMA_MODEL env var)
  
  Example curl:
  curl -X POST http://ollama:11434/api/generate -d '{"model":"llama3","prompt":"Hello!"}'
  ```
- **n8n Workflow Template**: Include a sample workflow that uses the Ollama node.
- **Helper Scripts**: Add `scripts/ollama-query.sh` and `scripts/set-ollama-model.sh`.

## Success Criteria
- The Ollama service (`http://ollama:11434`) is reachable from any container attached to `homelab_internal` or `homelab_proxy`.
- A default Llama model (e.g., `llama3`) is pre-loaded and ready for inference.
- Services like n8n, Open WebUI, and Home Assistant can be configured with minimal effort to use the shared model.
- Model pulling/caching is handled automatically on first deploy or via post-deploy script.
- GPU resources (if used) are properly allocated to the Ollama container.
- Users can switch models via a simple script or environment variable.
- No duplicate model storage; all services share the same model files under `${DATA_PATH}/phase3-ai-gaming/data/ollama`.

## Files to Create/Modify
```
context/feature-specs/05-llama-model-sharing.md          (this file)
scripts/post-deploy.sh                                   (add model warm-up)
scripts/ollama-query.sh                                  (helper CLI tool)
scripts/set-ollama-model.sh                              (model switching helper)
config/editable-models.txt                               (optional: list of available models)
phase3-ai-gaming/docker-compose.yml                      (ensure ollama on internal networks, check model volume)
<service>-specific docs:                                 (e.g., n8n workflow examples, HA config snippets)
README.md                                                (updated post-deploy with Ollama usage instructions)
```

## Dependencies
- Ollama service running in phase3-ai-gaming.
- Sufficient storage under `${DATA_PATH}` for model files (several GB per model).
- If using GPU: NVIDIA drivers, container toolkit, and `nvidia` Ollama image.
- Basic tools: `curl`, `jq` (for helper scripts).
- Services that support LLM integration (n8n, Open WebUI, Home Assistant, etc.)—most are already present.

## Estimated Effort
Single AI execution to:
- Verify Ollama network configuration.
- Create model warm-up and helper scripts.
- Document integration patterns for key services (n8n, Open WebUI, Home Assistant).
- Update post-deploy script to pre-warm the model.
- Add usage instructions to README.
Actual service-level configuration may be done manually or via further automation, but the foundation for sharing is set.