# CARIB-CLEAR Helm Chart

## Install

```bash
helm upgrade --install carib-clear ./helm/carib-clear \
  --namespace carib-clear --create-namespace \
  -f helm/carib-clear/values.yaml
```

## Render-only for Render.com native Kubernetes
If you are not using Tiller/Helm in-cluster, you can still generate pure manifests:

```bash
helm template carib-clear ./helm/carib-clear > /tmp/carib-clear-manifests.yaml
# then apply via kubectl or Render's Kubernetes deploy
```

## Values

### API
- Replicas: `.api.replicaCount`
- Resources: `.api.resources`
- Autoscaling: `.api.autoscaling.enabled`
- Health paths: `.api.health.readyPath`, `.api.health.livePath`
- Node selector / tolerations / affinity supported

### Worker
- Toggle: `.worker.enabled`
- Command: `.worker.command`
- Readiness exec: `python -m carib_clear.worker.health`

### Secrets
- Secret `database-url`, `api-key`, `secret-backend`, `webhook-secret` emitted from values.
- Rotate `webhook-secret` for production.

### Render recommendation
If you use a specific image tag per environment, set `pullPolicy: IfNotPresent`.
Avoid `latest` and blank tags in production values.

### Production data posture
Default `global.database.url` is SQLite for local/test runs.
For production, use a managed Postgres DSN via `global.database.url` or a secret-manager-provided `database-url`; do not run SQLite as the production database path.
