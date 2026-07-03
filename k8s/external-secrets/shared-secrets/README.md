# shared-secrets (local, uncommitted)

Real source secrets for the `shared-secrets` namespace live here. **They are
git-ignored** — nothing in this folder except this README and `*.example` /
`*.template` files is tracked. You create the material here and apply it by hand;
ESO distributes it (see `../README.md`).

The `shared-secrets` namespace itself + RBAC + the `ClusterSecretStore` are
managed by the `external-secrets` chart via ArgoCD. Only the secret *values* are
manual, and only they belong in this folder.

## GHCR pull tokens

Each repo `<repo>` needs one source secret named `ghcr-<repo>`. Create it with a
`read:packages` PAT (base64 of `user:PAT`):

```sh
kubectl -n shared-secrets create secret generic ghcr-<repo> \
  --from-literal=dockerconfigjson='{"auths":{"ghcr.io":{"auth":"<base64 user:PAT>"}}}'
```

Or write a manifest here (e.g. `ghcr-<repo>.yaml`, ignored) and
`kubectl apply -f ghcr-<repo>.yaml`. See `ghcr.yaml.example`.

## Rotating

Re-apply the source secret with the new value; ESO re-syncs consumers within the
`refreshInterval`. Nothing else to change.

## Conventions

- One file per secret, named after the secret (`<secret-name>.yaml`).
- Never rename a file to drop the ignore (no committing real values).
- Track a redacted `*.example` when a secret's shape is worth documenting.
