# Deployment (Terraform + GitHub Actions)

One `t3.micro` Ubuntu instance runs the bot under systemd. Create, preview and destroy the server by running the
**Infrastructure** workflow from the Actions tab (`plan`, `apply` or `destroy`).

**Auto-update:** a push to `main` that touches `src/`, `requirements.txt` or `infra/` checks whether the server exists.
If it is up, the server is rebuilt fresh from the pushed commit. If it is destroyed, the push does nothing
(a push never creates the server; run `apply` manually for that).

## One-time setup
1. `./infra/bootstrap.sh` (local admin AWS creds): creates the state bucket and the OIDC deploy role.
2. In GitHub > Settings > Secrets and variables > Actions:
   - Secrets: `AWS_ROLE_ARN`, `DISCORD_TOKEN`, `DISCORD_CLIENT_ID`, `DISCORD_GUILD_ID`, `MONGODB_URI`, `OLLAMA_API_KEY`
     (optional: `NEVER_LATE_TOKEN` for real trip times from students' saved home addresses)
   - Variable: `TF_STATE_BUCKET` (optional overrides: `LLM_MODEL`, `VISION_MODEL`, `LLM_REASONING`, `MONGODB_DATABASE`, ...)
3. The workflow file must be on `main` (workflow_dispatch and the AWS role are limited to `main`).

## Use
- **apply**: stores the `.env` in SSM (SecureString), then builds the instance. `git_ref` picks the branch/tag/commit to run; blank means the commit the run
  started from, so every `apply` after a code change replaces the instance (= redeploy, a few minutes of downtime).
- **destroy**: removes the instance, role, security group and the SSM parameter.
- **Shell / logs**: `aws ssm start-session --target <instance_id>` then `sudo journalctl -u transitbuddy -f`
  (no SSH, no inbound ports). Bootstrap log: `/var/log/transitbuddy-bootstrap.log`.

Run only one copy of the bot per Discord token. Atlas must allow the instance's IP (or `0.0.0.0/0`).
