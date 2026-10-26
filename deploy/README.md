# Deploy

The service:

```bash
cp deploy/yatta.service ~/.config/systemd/user/
systemctl --user daemon-reload && systemctl --user enable --now yatta
```

To publish it, add the Cloudflare Tunnel ingress for the canonical host and create the DNS route:

```yaml
  - hostname: yatta.enrica.ai
    service: http://localhost:8790
```

```bash
cloudflared tunnel route dns <tunnel-id> yatta.enrica.ai
```

Other hosts in `YATTA_HOSTS` (for example the old `avatar.enrica.ai`) can keep their tunnel routes to the same port; Yatta redirects them to the canonical host.

After a code change, rebuild the web app (`cd web && npm run build`) and run `systemctl --user restart yatta`.
