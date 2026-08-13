-- =============================================================================
-- Central PostgreSQL Initialization
-- Runs automatically on first container start.
-- Creates one database per service that needs it.
-- The POSTGRES_USER (homelab) is the superuser and owns all databases.
-- =============================================================================

-- Core / Identity
CREATE DATABASE authentik;
CREATE DATABASE vaultwarden;

-- Media
CREATE DATABASE paperless;

-- Automation & Utility
CREATE DATABASE n8n;
CREATE DATABASE jarvis_core;

-- On-Demand Services
CREATE DATABASE gitea;
CREATE DATABASE nextcloud;
CREATE DATABASE outline;
CREATE DATABASE calcom;
CREATE DATABASE nocodb;
CREATE DATABASE guacamole;
