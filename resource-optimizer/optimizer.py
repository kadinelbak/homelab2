#!/usr/bin/env python3
"""
Resource Optimizer for Homelab
Dynamically optimizes container resource allocation based on usage patterns,
time of day, workload priority, and environmental factors.
"""

import os
import time
import json
import logging
import docker
import requests
from datetime import datetime, timedelta
from collections import defaultdict
import yaml

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Configuration from environment variables
INTERVAL = int(os.getenv('OPTIMIZER_INTERVAL', '300'))  # 5 minutes
SAFETY_MARGIN = float(os.getenv('OPTIMIZER_SAFETY_MARGIN', '0.2'))  # 20%
HISTORY_DAYS = int(os.getenv('OPTIMIZER_HISTORY_DAYS', '7'))
ENABLE_PREDICTION = os.getenv('OPTIMIZER_ENABLE_PREDICTION', 'true').lower() == 'true'
ENABLE_THERMAL = os.getenv('OPTIMIZER_ENABLE_THERMAL', 'true').lower() == 'true'
ENABLE_GPU_SHARING = os.getenv('OPTIMIZER_ENABLE_GPU_SHARING', 'true').lower() == 'true'

# Docker client
client = docker.from_env()

# Prometheus endpoint for querying metrics
PROMETHEUS_URL = os.getenv('PROMETHEUS_URL', 'http://prometheus:9090')

# Service tiers for priority management
SERVICE_TIERS = {
    'critical': ['postgres', 'redis', 'vaultwarden', 'authentik_server', 'homepage'],
    'important': ['jellyfin', 'audiobookshelf', 'navidrome', 'paperless', 'immich_server', 'openwebui'],
    'background': ['immich_machine_learning', 'backup', 'trivy-scan', 'metadata', 'resource-optimizer']
}

def get_service_labels(container):
    """Extract labels from a container."""
    labels = container.labels or {}
    return labels

def is_service_managed(labels):
    """Check if a service should be managed by the optimizer."""
    # Skip optimizer itself and system containers
    service_name = labels.get('homelab.service.name', '')
    if service_name in ['resource-optimizer'] or service_name.startswith('homelab_'):
        return False
    return True

def get_service_tier(labels):
    """Determine the tier of a service based on labels or name."""
    # Check for explicit tier label
    tier = labels.get('homelab.service.tier')
    if tier in SERVICE_TIERS:
        return tier
    
    # Infer from service name
    service_name = labels.get('homelab.service.name', '')
    for tier, services in SERVICE_TIERS.items():
        if service_name in services:
            return tier
    
    # Default to background if unknown
    return 'background'

def query_prometheus(query):
    """Query Prometheus for metric data."""
    try:
        response = requests.get(f'{PROMETHEUS_URL}/api/v1/query', params={'query': query})
        response.raise_for_status()
        data = response.json()
        if data['status'] == 'success':
            return data['data']['result']
        else:
            logger.error(f"Prometheus query failed: {data}")
            return []
    except Exception as e:
        logger.error(f"Error querying Prometheus: {e}")
        return []

def get_container_metrics(container_name, metric_name, duration='5m'):
    """Get recent metric values for a container."""
    # This is a simplified version - in practice, you'd use more specific queries
    query = f'{metric_name}{{container="{container_name}"}}'
    results = query_prometheus(query)
    values = []
    for result in results:
        for timestamp, value in result['values']:
            values.append(float(value))
    return values

def predict_resource_need(current_usage, history_data):
    """Predict future resource need based on historical data."""
    if not ENABLE_PREDICTION or len(history_data) < 3:
        return current_usage
    
    # Simple prediction: average of recent usage with trend
    if len(history_data) >= 3:
        # Calculate simple linear trend
        recent = history_data[-3:]
        if len(recent) >= 2:
            trend = (recent[-1] - recent[0]) / len(recent)
            predicted = recent[-1] + (trend * 2)  # Predict 2 steps ahead
            return max(current_usage, predicted)
    
    return current_usage

def get_container_current_limits(container):
    """Get current resource limits for a container."""
    host_config = container.host_config
    limits = {
        'memory': host_config.memory if host_config.memory else 0,
        'memory_swap': host_config.memory_swap if host_config.memory_swap else 0,
        'cpu_shares': host_config.cpu_shares if host_config.cpu_shares else 0,
        'cpu_period': host_config.cpu_period if host_config.cpu_period else 100000,
        'cpu_quota': host_config.cpu_quota if host_config.cpu_quota else 0
    }
    return limits

def update_container_limits(container, new_limits):
    """Update resource limits for a container."""
    try:
        # Note: Docker API doesn't support live update of all resource limits
        # Some require container restart. We'll log what we would change.
        current_limits = get_container_current_limits(container)
        changes = {}
        
        for key, new_value in new_limits.items():
            current_value = current_limits.get(key, 0)
            if abs(new_value - current_value) > 0.01:  # Significant change
                changes[key] = (current_value, new_value)
        
        if changes:
            logger.info(f"Would update {container.name} limits: {changes}")
            # In a full implementation, we would use docker.update() here
            # but many resource updates require container restart
        else:
            logger.debug(f"No significant changes needed for {container.name}")
            
    except Exception as e:
        logger.error(f"Error updating limits for {container.name}: {e}")

def optimize_resources():
    """Main optimization function."""
    logger.info("Starting resource optimization cycle")
    
    try:
        # Get all containers
        containers = client.containers.list()
        
        for container in containers:
            if not is_service_managed(get_service_labels(container)):
                continue
                
            labels = get_service_labels(container)
            service_name = labels.get('homelab.service.name', container.name)
            tier = get_service_tier(labels)
            
            logger.debug(f"Processing {service_name} (tier: {tier})")
            
            # Get current resource usage (simplified)
            # In practice, you'd query Prometheus for specific metrics
            current_memory = 0  # Placeholder
            current_cpu_shares = 0  # Placeholder
            
            # For now, we'll just log what we would do
            logger.info(f"Optimizing {service_name}: current usage would be analyzed here")
            
            # In a full implementation:
            # 1. Get historical usage data
            # 2. Predict future needs
            # 3. Apply safety margins
            # 4. Adjust limits based on tier priority
            # 5. Update container via Docker API (where possible)
            
    except Exception as e:
        logger.error(f"Error in optimization cycle: {e}")

def main():
    """Main entry point."""
    logger.info("Starting Homelab Resource Optimizer")
    
    while True:
        try:
            optimize_resources()
            time.sleep(INTERVAL)
        except KeyboardInterrupt:
            logger.info("Shutting down resource optimizer")
            break
        except Exception as e:
            logger.error(f"Unexpected error: {e}")
            time.sleep(INTERVAL)

if __name__ == "__main__":
    main()