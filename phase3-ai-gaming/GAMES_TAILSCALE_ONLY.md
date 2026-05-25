# Web Games (Tailscale/Port Only)

This setup keeps the games service off Nginx Proxy Manager and limits access to your Tailscale group.

## Service Details

- Compose service: `web-games`
- Host port: `8092`
- URL pattern: `http://<tailnet-host>:8092`
- Content path: `phase3-ai-gaming/games-portal/`

## 1) Start the service

```bash
cd phase3-ai-gaming
docker compose --env-file ../.env up -d web-games
```

## 2) Verify local service

```bash
docker compose --env-file ../.env ps web-games
curl -I http://127.0.0.1:8092
```

Expected: `HTTP/1.1 200 OK` from nginx.

## 3) Restrict access to tailscale0 with UFW

If UFW is enabled, use these rules:

```bash
sudo ufw deny 8092/tcp
sudo ufw allow in on tailscale0 proto tcp to any port 8092
sudo ufw status numbered
```

Notes:
- The deny rule blocks LAN/WAN access.
- The allow rule permits Tailscale clients.

## 4) Restrict to a specific Tailscale group (ACL)

Add/update ACL policy in Tailscale admin (ACL file):

```json
{
  "groups": {
    "group:homelab-games": [
      "alice@example.com",
      "bob@example.com"
    ]
  },
  "tagOwners": {
    "tag:homelab": ["autogroup:admin"]
  },
  "acls": [
    {
      "action": "accept",
      "src": ["group:homelab-games"],
      "dst": ["tag:homelab:8092"]
    }
  ]
}
```

Apply `tag:homelab` to your server node in Tailscale admin.

## 5) Validate policy behavior

Test from three clients:

1. Allowed group member on Tailscale: should load games.
2. Tailnet member outside group: should be blocked.
3. Non-Tailscale LAN device: should be blocked by host firewall.

## 6) Optional hardening

If you want to prevent accidental host-wide binds, set the published port to the host Tailscale IP only:

1. Find host Tailscale IP:

```bash
tailscale ip -4
```

2. Update compose mapping from `8092:80` to `<TAILSCALE_IP>:8092:80`.
3. Restart service.

This is optional; firewall + ACL is already sufficient for most homelabs.
