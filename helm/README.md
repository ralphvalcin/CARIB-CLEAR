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
Do not use the chart default `global.database.url` in production.
Create a production values override file, for example `values-production.yaml`:

```yaml
global:
  environment: production
  database:
    url: postgresql://<user>:<password>@<host>:<port>/<database>
  image:
    repository: carib-clear
    tag: <commit-or-release-tag>
    pullPolicy: IfNotPresent
```

Install with:
```bash
helm upgrade --install carib-clear ./helm/carib-clear \
  --namespace carib-clear --create-namespace \
  -f helm/carib-clear/values.yaml \
  -f values-production.yaml
```

If `global.database.url` is not set and `global.environment` is `production`, Helm may still deploy with an empty secret, and the application will fail at runtime. Always override before deploying production.

### Optional production hardening
All of the following are disabled by default to preserve local/Minikube behavior.

- Pod disruption budget
  - API: `.api.podDisruptionBudget.enabled`, `.api.podDisruptionBudget.minAvailable`
  - Worker: `.worker.podDisruptionBudget.enabled`, `.worker.podDisruptionBudget.minAvailable`

- Topology spread
  - API: `.api.topologySpread.enabled`, `.api.topologySpread.maxSkew`, `.api.topologySpread.whenUnsatisfiable`
  - Worker: `.worker.topologySpread.enabled`, `.worker.topologySpread.maxSkew`, `.worker.topologySpread.whenUnsatisfiable`

- HPA guardrails
  - `.api.autoscaling.minReplicas` is clamped to at least 2 when autoscaling is enabled
  - `.api.autoscaling.scaleDownStabilizationSeconds` defaults to 300
  - `.api.autoscaling.scaleDownPct` defaults to 10
