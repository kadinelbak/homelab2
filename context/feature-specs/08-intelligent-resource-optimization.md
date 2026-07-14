# Intelligent Resource Optimization & Adaptive Management Feature Spec

## Overview
Implement intelligent, adaptive resource management that dynamically optimizes container resource allocation based on usage patterns, time of day, workload priority, and environmental factors. This spec moves beyond static resource limits to create a self-optimizing homelab that maximizes performance while minimizing waste and preventing resource contention.

## Core Components
- **Resource Monitor**: Continuous collection of CPU, memory, disk I/O, network, and GPU utilization per container/service
- **Predictive Scaler**: ML-driven forecasting of resource needs based on historical patterns and external factors (calendar, weather, etc.)
- **Adaptive Limiter**: Dynamic adjustment of container resource requests/limits based on real-time demand and predictions
- **Workload Scheduler**: Intelligent timing of batch jobs, ML training, and backups to off-peak hours
- **Thermal Manager**: Temperature-aware throttling to prevent overheating and hardware degradation
- **Priority Queue**: Service tiering (critical, important, background) for resource allocation during contention
- **GPU Sharing & Time-Slicing**: Fair sharing of GPU resources among AI workloads
- **Memory Compression & Swapping**: Intelligent use of zram/zswap to extend effective memory
- **Optimization Dashboard**: Visualization of resource efficiency, savings, and optimization recommendations

## Implementation Plan (Single AI Execution Focus)

### Phase 1: Comprehensive Resource Telemetry
1. **Enhance Existing Monitoring** (Build on Spec 01):
   - Ensure all containers export detailed resource metrics via cAdvisor
   - Add custom metrics for:
     - GPU utilization (`nvidia-smi` metrics via node-exporter extension)
     - Memory compression ratios (zram/zswap stats)
     - Disk I/O latency and queue depth
     - Network packet drops and retransmits
     - Container startup/shutdown frequency
     - Request latency and error rates (from service metrics)
   - Label all metrics with service tier: `tier="critical" | "important" | "background"`

2. **Deploy Extended Node Exporter**:
   - Enable additional collectors:
     - `collector.perf` (CPU performance counters)
     - `collector.pressure` (CPU/memory/io pressure stall info)
     - `collector.zram` (if using compressed swap)
     - `collector.nvidia` (GPU metrics if NVIDIA drivers present)
   - Add textfile collector for custom metrics from scripts

### Phase 2: Predictive Resource Modeling
1. **Time-Series Forecasting with Prometheus**:
   - Use Prometheus' built-in forecasting functions:
     - `predict_linear(metric[d], horizon)` for linear trends
     - `holt_winters(metric[d], "seasonal", period)` for seasonal patterns
   - Create recording rules for predicted resource needs:
     - `predict_container_cpu_seconds_total{container="jellyfin"}[1h]` 
     - `predict_container_memory_usage_bytes{container="immich_ml"}[6h]`
   - Forecast horizons: 15min, 1h, 6h, 24h for different decision types

2. **External Factor Integration**:
   - Calendar integration: Predict higher media usage during evenings/weekends
   - Weather integration: Colder weather → more indoor activity → higher usage
   - Device presence: Tailscale/Home Assistant device tracking → predict user arrival
   - Energy prices: Time-of-use electricity pricing → shift loads to off-peak

3. **Model Storage & Retraining**:
   - Store model parameters in Prometheus TSDB
   - Weekly retraining script: `scripts/retrain-resource-models.sh`
   - Simple fallback: Use historical averages if ML fails

### Phase 3: Adaptive Resource Adjustment
1. **Dynamic Resource Adjuster Service**:
   - Create a lightweight controller that:
     - Reads predicted resource needs from Prometheus
     - Compares with current container resource usage
     - Calculates optimal resource requests/limits
     - Applies changes via Docker API (update container resources)
   - Runs as a cron job or continuous loop (every 5-15 minutes)
   - Safety bounds: Never decrease below minimum viable, never increase above hard limit

2. **Implementation Approach** (Using Docker API):
   - For each managed container:
     1. `docker inspect` current HostConfig (Memory, CPUShares, etc.)
     2. Query Prometheus for predicted p95 usage over next 30min
     3. Calculate target: `predicted_usage * 1.2` (20% buffer)
     4. If target differs significantly from current → `docker update` container
   - Supported adjustments:
     - Memory: `--memory` and `--memory-reservation`
     - CPU: `--cpu-shares`, `--cpu-period`, `--cpu-quota`
     - IO: `--blkio-weight` (if needed)
     - Not supported: Changing CPU core count (requires restart)

3. **Service Tiering & Priority System**:
   - Define tiers in labels or external config:
     - `tier="critical"`: Authentik, Postgres, Redis, Vaultwarden, Homepage (never downscale)
     - `tier="important"`: Jellyfin, Audiobookshelf, Navidrome, Paperless, Immich (moderate flexibility)
     - `tier="background"`: Immich ML, backups, scans, torrents (aggressive downscaling OK)
   - During resource contention:
     - Protect critical tier first
     - Scale important tier proportionally
     - Preempt background tier if needed

### Phase 4: Intelligent Workload Scheduling
1. **Predictive Offload Scheduler**:
   - Identify deferrable workloads:
     - Immich ML processing
     - Video transcoding (Jellyfin)
     - Backup jobs
     - Vulnerability scans
     - Model downloads/pulls
     - Batch n8n workflows
   - Score each workload by:
     - Resource intensity (CPU, memory, GPU, disk)
     - Time sensitivity (how soon result needed)
     - Data freshness requirements
     - User impact if delayed

2. **Schedule Optimization Engine**:
   - Input: Forecasted resource availability over next 24h
   - Input: List of pending deferrable jobs with scores
   - Goal: Maximize value (score * completion likelihood) subject to resource constraints
   - Simple implementation: Greedy algorithm scheduling jobs in predicted low-usage windows
   - Advanced: Use OR-Tools or similar for true optimization

3. **Integration Points**:
   - n8n: Add "Schedule for Off-Peak" trigger option
   - Immich: Expose ML processing as deferrable job via API
   - Custom scripts: Provide `schedule-deferrable <command>` helper
   - Backup spec: Integrate with backup scheduler to choose optimal window

### Phase 5: Thermal & Power-Aware Management
1. **Temperature Monitoring**:
   - Via node-exporter: `lm_sensors` collector or `hwmon` textfile collector
   - Monitor: CPU temp, GPU temp, ambient (if available)
   - Set thresholds: Warning at 75°C, critical at 85°C

2. **Adaptive Throttling**:
   - When temperature approaches threshold:
     - Step 1: Notify via ntfy: "Host warming, considering throttling"
     - Step 2: Reduce CPU shares for background tier by 25%
     - Step 3: Pause non-critical ML workloads
     - Step 4: If still rising: Reduce important tier CPU by 25%
     - Step 5: Critical: Emergency throttle all non-essential services
   - Reverse actions when temperature drops

3. **Power Cost Optimization** (If utility API available):
   - Fetch real-time or forecasted electricity prices
   - Shift flexible workloads to low-price periods
   - Store excess solar energy in battery (if applicable) to power homelab during peak

### Phase 6: GPU Sharing & Time-Slicing
1. **Current State**: Ollama likely has exclusive GPU access via `gpus: all`
2. **Sharing Strategies**:
   - **Time-Based Sharing**: Schedule Ollama vs. other GPU workloads (e.g., Stable Diffusion)
   - **Fractional GPU**: Not natively supported in Docker, but can use:
     - MIG (Multi-Instance GPU) on Ampere+ cards
     - Compute preemption via CUDA contexts (complex)
   - **Priority Preemption**: Allow urgent GPU tasks to preempt Ollama with notice
   - **Batching**: Accumulate AI requests and process in batches for efficiency

3. **Simple Implementation** (Time-Based):
   - Use n8n to schedule:
     - 7AM-7PM: Ollama gets GPU (interactive AI usage)
     - 7PM-7PM: Other GPU workloads (if any) get priority
     - Or: Ollama gets GPU unless explicit request for other workload
   - Control via environment variable: `OLLAMA_GPU_PRIORITY=high|medium|low`
   - Script: `scripts/set-gpu-priority.sh` that updates Ollama's deploy/resources

### Phase 7: Memory Optimization Techniques
1. **Zram/Zswap Implementation**:
   - Create compressed swap in RAM to avoid disk swap
   - Configure via `/etc/systemd/zram-generator.conf` or script
   - Monitor compression ratio and effective memory gain
   - Alert if compression fails (fallback to disk swap)

2. **Page Cache & Buffer Optimization**:
   - Monitor `drop_caches` impact (usually not recommended to manual drop)
   - Instead: Use `vfs_cache_pressure` to balance dentry/inode vs page cache
   - Set via sysctl: `vm.vfs_cache_pressure=50` (default 100)

3. **Application-Level Caching**:
   - Ensure services use efficient caching (Redis for n8n, etc.)
   - Monitor cache hit ratios and adjust sizes

### Phase 8: Optimization Dashboard & Reporting
1. **Grafana Optimization Dashboard** (provisioned via Spec 03):
   - Panels showing:
     - Resource efficiency: (used / allocated) * 100% per service tier
     - Prediction accuracy: Forecast vs actual resource usage
     - Optimization savings: Estimated resources saved by adaptive limits
     - Workload scheduling efficiency: % of deferrable jobs run in off-peak
     - Temperature trends and throttling events
     - GPU utilization and sharing statistics
     - Memory compression ratio and effective gain
   - Include "Optimization Score" (0-100) based on:
     - Resource efficiency (40%)
     - Prediction accuracy (20%)
     - Off-peak workload % (20%)
     - Thermal stability (10%)
     - GPU utilization fairness (10%)

2. **Automated Optimization Reports**:
   - Weekly: Email summary of resource savings, prediction accuracy, recommendations
   - Monthly: Trend analysis, capacity planning suggestions
   - Include "What if" scenarios: "If we increased Ollama priority, what would happen to response times?"

## Success Criteria
- Resource telemetry covers CPU, memory, disk I/O, network, and GPU for all containers
- Predictive models achieve >80% accuracy for 1-hour resource forecasts
- Dynamic resource adjustment occurs without service disruption (within Docker API limits)
- Service tiering protects critical services during resource contention
- Deferrable workloads achieve >70% off-peak execution rate
- Thermal management prevents overheating (>85°C) while maintaining service quality
- GPU sharing enables fair access for multiple AI workloads (if present)
- Memory compression provides >1.5x effective memory gain when needed
- Optimization dashboard shows clear trends and actionable insights
- Estimated resource savings: 20-40% reduction in wasted allocation
- Mean time to detect and correct resource misallocation: < 15 minutes
- System remains responsive during peak usage periods
- No service downtime due to resource exhaustion (OOM kills, CPU starvation)
- Users perceive consistent performance despite background optimizations

## Files to Create/Modify
```
context/feature-specs/08-intelligent-resource-optimization.md  (this file)
scripts/predict-resource.sh                                   (Prometheus query helper)
scripts/adjust-resources.sh                                   (Dynamic resource adjuster)
scripts/schedule-workload.sh                                  (Workload scheduler)
scripts/monitor-thermal.sh                                    (Temperature monitoring)
scripts/set-gpu-priority.sh                                   (GPU priority controller)
scripts/enable-zram.sh                                        (Zram setup helper)
phase1-core/docker-compose.yml                                (add resource-optimizer service)
resource-optimizer/                                           (Optimizer service code)
  - main.py or main.sh
  - config/
  - requirements.txt
monitoring/node-exporter/                                     (Extended config if needed)
  - .collector.rc
monitoring/prometheus/rules/                                  (Resource prediction rules)
  - resource-forecasting.yml
monitoring/grafana/provisioning/dashboards/optimization-dashboard.json
scripts/retrain-resource-models.sh                            (Model retraining)
docs/RESOURCE-OPTIMIZATION.md                                 (Runbook/guide)
README.md                                                     (Add optimization section post-deploy)
.env                                                          (Add optimization tunables)
```

## Dependencies
- Docker API access (via socket mount or TCP with TLS)
- Prometheus with sufficient retention for historical analysis (Spec 01)
- Basic ML capabilities: Either Prometheus forecasting or simple Python stats
- For GPU monitoring: NVIDIA drivers and `nvidia-smi` available
- For zram: Linux kernel with zram module available
- Administrative privileges to adjust container resources (Docker API)
- Basic understanding of resource management and performance tuning

## Estimated Effort
Single AI execution to:
- Define comprehensive resource telemetry collection strategy
- Create predictive resource modeling using Prometheus forecasting
- Implement dynamic resource adjuster service using Docker API
- Design workload scoring and scheduling framework
- Outline thermal management and GPU sharing approaches
- Specify memory optimization techniques
- Create optimization dashboard components
Actual model tuning, scheduling algorithm refinement, and safety testing will require iteration but the foundation for intelligent resource optimization is achievable in one go.