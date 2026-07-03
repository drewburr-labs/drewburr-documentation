# external-secrets

External Secrets Operator (ESO) + a shared-secrets distribution store.

Manually-created secrets live in ONE namespace (`shared-secrets`) and ESO copies
them into whichever app namespaces need them. Nothing in this repo contains the
secret material — only the distribution rules.

## One-time bootstrap

ESO authenticates to the shared-secrets namespace as a ServiceAccount using the
built-in `kubernetes` provider (no external vault). Everything it needs
(namespace, SA, RBAC, `ClusterSecretStore`) is created by this chart.

## Granting a namespace a GHCR pull token

Distribution is by a **dedicated label** — a namespace opts itself in, there is
no central namespace list.

1. Register the repo once here (creates the `ClusterExternalSecret`). In this
   chart's `values.yaml`:

   ```yaml
   pullSecrets:
     - name: <repo>
   ```

2. Create the real token in `shared-secrets` once (a `read:packages` PAT,
   base64 of `user:PAT`):

   ```sh
   kubectl -n shared-secrets create secret generic ghcr-<repo> \
     --from-literal=dockerconfigjson='{"auths":{"ghcr.io":{"auth":"<base64 user:PAT>"}}}'
   ```

3. Opt a namespace in by labeling it `ghcr.drewburr.com/<repo>: "true"`. For an
   Argo-managed app, set it in that app's `config.yaml` — the ApplicationSet
   passes `managedNamespaceMetadata` straight through to the Application.
   `CreateNamespace=true` is **required**: Argo only applies
   `managedNamespaceMetadata` as part of namespace auto-creation, so without it
   the labels are declared but never written to the namespace.

   ```yaml
   syncOptions:
     - CreateNamespace=true
   managedNamespaceMetadata:
     labels:
       ghcr.drewburr.com/<repo>: "true"
   ```

   (A namespace can carry several such labels for several repos.) Ad hoc:
   `kubectl label ns <ns> ghcr.drewburr.com/<repo>=true`.

ESO then creates a `kubernetes.io/dockerconfigjson` secret named `ghcr-<repo>`
in every labeled namespace. Reference it as an `imagePullSecrets` entry (name
`ghcr-<repo>`).

To revoke, drop the label. To rotate, update only the source secret in
`shared-secrets`; ESO re-syncs within `refreshInterval`.

## Distributing other (non-pull) secrets

Same store works for any secret: create it in `shared-secrets`, then add an
`ExternalSecret` (per namespace) or another `ClusterExternalSecret` referencing
`ClusterSecretStore/shared-secrets`.
