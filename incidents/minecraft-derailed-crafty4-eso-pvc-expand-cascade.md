# minecraft-derailed — crafty-4 rollout: ESO + PVC-expand failure cascade

## 2026-07-03 — one deploy, four independent walls

### Summary

Deploying the self-hosted `ghcr.io/drewburr-labs/crafty-4:latest` image to
`minecraft-derailed` (pulling its GHCR token via a newly-built External Secrets
Operator distribution pipeline) surfaced **four unrelated failures in series**.
Each masked the next, so the pod stayed un-ready through the whole chain:

1. **ESO pull secret never landed** — `managedNamespaceMetadata` without
   `CreateNamespace=true` is a no-op, so the opt-in label was never written and
   the `ClusterExternalSecret` matched nothing.
2. **`ClusterSecretStore`/`ClusterExternalSecret` wouldn't apply** — manifests
   pinned `external-secrets.io/v1beta1`; the installed operator only serves `v1`.
3. **Volume wouldn't mount** — `crafty-servers` PVC was expanded 50→150Gi but the
   ext4 online resize failed (`resize2fs: Permission denied to resize
   filesystem`), blocking `NodeStageVolume` indefinitely.
4. **Offline resize didn't reach the node** — after growing the fs offline on
   storage01, the node still saw a 50G filesystem because the **nvmet namespace
   was serving a stale handle** of the backing zvol.

As of writing, all four are resolved and the pod mounts; a **fifth**, minor issue
remains: the GHCR token's `auth` field is malformed (see Follow-ups).

### Timeline

| Time (UTC) | Event |
|---|---|
| — | Built ESO pipeline: `k8s/external-secrets/` (operator + `shared-secrets` ClusterSecretStore + per-repo `ClusterExternalSecret` push by namespace label). Commits `d0d813d`, `6114f6f`. |
| — | Argo sync failed: `no matches for kind "ClusterExternalSecret" in version "external-secrets.io/v1beta1"`. **Wall #2.** Fixed to `v1` (`b9f2429`). |
| — | ESO healthy (store `Valid`, CES `Ready`) but secret absent from `minecraft-derailed`; namespace had no opt-in label. **Wall #1.** Added `CreateNamespace=true` (`50db5e7`). |
| — | Pod stuck `ContainerCreating`: `MountVolume.MountDevice failed … resize2fs: Permission denied to resize filesystem` on `/dev/nvme16n1`. **Wall #3.** |
| — | Bumped PVC to 150Gi in git to stop shrink attempts (`e8cc2ed`); switched storageClass `fsType: ext4 → xfs` for future volumes (`5433cf0`). |
| 22:2x | Offline `e2fsck -f` + `resize2fs` on storage01 grew the fs to 150G (`39321600` 4k blocks). Scaled app back up. |
| 22:42 | Node re-connected **fresh** yet `resize2fs` still read `old_desc_blocks=7` (50G fs) on a 150G device. **Wall #4.** |
| ~23:0x | Confirmed zvol=150G, fs=150G, nvmet path correct — but stale export. Toggled nvmet namespace `enable` 0→1 while scaled to 0. Node mounted cleanly. |
| ~23:0x | Pod now fails with `unable to parse auth field…` — the pull secret works, its token content is wrong. **Follow-up #1.** |

### Diagnosis & resolution, per wall

#### 1. `managedNamespaceMetadata` needs `CreateNamespace=true`

The distribution model is: a namespace opts into `ghcr-<repo>` by carrying the
label `ghcr.drewburr.com/<repo>: "true"`, and a `ClusterExternalSecret` pushes
the pull secret to every matching namespace. Apps set the label declaratively via
`managedNamespaceMetadata` in their `config.yaml` (passed through transparently by
the ApplicationSet `templatePatch`).

**Trap:** ArgoCD only writes `managedNamespaceMetadata` labels as part of the
namespace *creation/adoption* step, which runs **only when `CreateNamespace=true`
is set**. Without it the label is declared on the `Application` but never applied
to the namespace, so the CES selector matches nothing — silently. The
`Application` even showed `Synced`.

Fix: `syncOptions: [CreateNamespace=true]` alongside `managedNamespaceMetadata` in
the app's `config.yaml`. Documented in `k8s/external-secrets/README.md`.

#### 2. ESO API version `v1beta1` → `v1`

The installed ESO build serves only `external-secrets.io/v1`
(`kubectl get crd clusterexternalsecrets.external-secrets.io -o …` → `v1beta1
served=false`). Manifests were pinned to `v1beta1`. Fixed both CRs to `v1`; the
fields used are unchanged across the promotion. Verified with
`kubectl apply --dry-run=server`.

#### 3. ext4 online-resize hit a wall — but NOT for the reason the error says

`resize2fs: Permission denied to resize filesystem` is **not** a permissions or
CSI-capability problem. The `csi-driver` node container already runs
`privileged: true` (full `CAP_SYS_RESOURCE`). The error is ext4's misleading
message for an **online** resize the kernel refuses. The volume had been grown
repeatedly (`old_desc_blocks=7 → new_desc_blocks=19`); only an **offline**
(unmounted) `resize2fs` could proceed.

The migration-to-new-PVC path we first considered is a **deadlock**: rsync-ing off
the old volume requires mounting it, which re-triggers the same failing
`NodeStageVolume` resize. So an offline resize is unavoidable to get *any* access.

Cleanest place to do it: **storage01**, not the node. Scale the app to 0
(detaches the nvme-of namespace, no kubelet-retry races, no concurrent-mount
corruption risk), then operate on the zvol block device directly:

```sh
kubectl -n minecraft-derailed scale statefulset minecraft-derailed-craftycontroller --replicas=0
ssh ubuntu@storage01.drewburr.com
Z=/dev/zvol/sas-pool/k8s/nvmeof/dataset/pvc-bc2fe420-d728-4e01-90cc-37842c633a03
sudo e2fsck -f "$Z"      # recovered journal (from the failed node mounts), then clean
sudo resize2fs "$Z"      # -> 39321600 (4k) blocks = 150 GiB, offline
```

Permanent fix for the whole class: storageClass `fsType: xfs` (`5433cf0`).
`xfs_growfs` grows online with no reserved-GDT ceiling, so future expansions stay
fully online during `NodeStageVolume`. **StorageClass `parameters` are immutable**
— the SC had to be deleted once (`kubectl delete storageclass zfs-nvmeof`) for
Argo to recreate it; safe, since a StorageClass only matters at provision time and
existing PV/PVC bindings are untouched.

#### 4. nvmet served a stale view after the out-of-band resize

After the offline resize, storage01 was fully correct — `volsize 150G`, fs
`Block count 39321600` (150G), nvmet namespace path pointing at the right zvol,
`enabled`. But the freshly re-connected node saw a **150G device wrapping a 50G
filesystem**.

Cause: nvmet opened the zvol backing handle when the volume was 50G. The CSI
`ControllerExpandVolume` bumped the *advertised* namespace size to 150G, but nvmet
never re-read the backing, so it served the pre-resize on-disk image (including
the 50G ext4 superblock). Our offline `resize2fs` wrote the new superblock to the
zvol, but nvmet's stale handle didn't reflect it.

Fix — force nvmet to drop and re-open the backing, **while scaled to 0** (no
initiator connected):

```sh
NQN=nqn.2003-01.org.linux-nvme:pvc-bc2fe420-d728-4e01-90cc-37842c633a03
NS=/sys/kernel/config/nvmet/subsystems/$NQN/namespaces/1
echo 0 | sudo tee $NS/enable
echo 1 | sudo tee $NS/enable
```

Then scale back up. Node connects fresh → 150G device + 150G fs → `resize2fs`
no-op → mount succeeds.

> This stale-nvmet-view is a **side effect of resizing the zvol out-of-band**
> while nvmet held an open handle. The normal online path (once on XFS) doesn't
> hit it. If the `enable` toggle is ever insufficient, the fallback is a full
> unexport/re-export of the subsystem, or `systemctl restart nvmet` while scaled
> to 0.

### Path forward / follow-ups

1. **Fix the GHCR token `auth` field (active blocker).** kubelet:
   `unable to parse auth field, must be formatted as base64(username:password)`.
   The distributed secret's `auth` decodes to just the raw PAT (`ghp_…`), with no
   `username:` and no colon. GHCR requires `base64("<github-username>:<PAT>")`.
   Recreate the source secret in `shared-secrets`:
   ```sh
   AUTH=$(printf '%s' '<github-username>:<read:packages PAT>' | base64 -w0)
   kubectl -n shared-secrets create secret generic ghcr-crafty-4 \
     --from-literal=dockerconfigjson="{\"auths\":{\"ghcr.io\":{\"auth\":\"$AUTH\"}}}" \
     --dry-run=client -o yaml | kubectl apply -f -
   ```
   ESO re-syncs consumers within `refreshInterval`.
2. **Rotate the PAT.** The token value was printed to a terminal during
   debugging; treat it as exposed and issue a fresh `read:packages` token.
3. **XFS migration of `crafty-servers` is now optional, not urgent.** The volume
   mounts on ext4 at 150G. If we want crafty specifically on XFS (and to escape
   any future ext4 online-resize risk on *this* volume), run the runbook's Phase-2
   rsync migration into a fresh PVC (now provisions XFS) during a maintenance
   window — the source mounts now, so the deadlock in Wall #3 no longer applies.
4. **Systemic:** any future PVC expand on `zfs-nvmeof` for a pre-XFS (ext4)
   volume can repeat Walls #3+#4. Prefer migrating high-churn volumes to XFS over
   growing them. See `k8s/democratic-csi-zfs-nvmeof/volblocksize-remediation.md`
   for the migration procedure and the broader sas-pool tuning context.

### Lessons

- **`managedNamespaceMetadata` silently no-ops without `CreateNamespace=true`.**
  The `Application` reads `Synced` while the label never lands.
- **`resize2fs: Permission denied` ≠ a permissions problem.** In a privileged CSI
  container it means online-resize refused; do it offline.
- **Resize the zvol through CSI, not out-of-band.** Manual storage01 resizes leave
  nvmet serving a stale handle (Wall #4). If you must, toggle the namespace
  `enable` afterward, scaled to 0.
- **Expansion + ext4 + nvme-of is fragile end-to-end.** XFS removes the online
  resize ceiling and keeps the whole path online — the real fix.
