# deploy/ — file index

**Current (Vinbot, use these):**
- `DEPLOY.md` — the deployment guide for DEV/UAT/PROD.
- `vinbot-dev.service`, `vinbot-uat.service`, `vinbot-prod.service` — systemd units.
- `nginx-vinbot-dev.conf`, `nginx-vinbot-uat.conf`, `nginx-vinbot-prod.conf` — Nginx site configs.

**Inherited from the baseline project (kept for reference, not part of the
Vinbot DEV/UAT/PROD procedure):**
- `uhbvn.service`, `generic-bot.service`, `nginx-uhbvn.conf` — the original
  single-environment deployment artifacts this project was copied from.
- `install-service.sh`, `deploy.sh` — the original install/deploy scripts
  (single-environment, two-server topology). Retained as working reference
  scripts; not yet parameterised for the three Vinbot environments.
- `deploy_2026-07-02.sh`, `deploy_2026-07-05.sh` — dated historical release
  scripts documenting specific past feature releases to the baseline system.
  Kept as genuine project history; not applicable to a fresh Vinbot install.
