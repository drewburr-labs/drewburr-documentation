#!/bin/bash
# Restore everything scale-down.sh scaled to zero, in reverse order, then re-enable ArgoCD auto-sync.
set -euo pipefail
cd "$(dirname "$0")"
STATE=state/replicas.txt
[ -s "$STATE" ] || { echo "no $STATE; nothing to restore" >&2; exit 1; }

echo "== scaling workloads back up"
tac "$STATE" | while read -r kind ns name r; do
  if [ "$r" != "0" ]; then
    kubectl -n "$ns" scale "$kind" "$name" --replicas="$r"
  fi
done

echo "== resuming CronJobs"
grep -v '^#' cronjobs.txt | while read -r ns name; do
  [ -z "$ns" ] && continue
  kubectl -n "$ns" patch cronjob "$name" -p '{"spec":{"suspend":false}}'
done

echo "== re-enabling ArgoCD automated sync on prometheus"
pol=$(cat state/prometheus-syncpolicy.json)
[ -z "$pol" ] && pol='{}'
kubectl -n argocd patch application prometheus --type=json -p "[{\"op\":\"add\",\"path\":\"/spec/syncPolicy/automated\",\"value\":$pol}]"

echo "== restarting the ArgoCD applicationset controller"
kubectl -n argocd scale deploy argocd-applicationset-controller --replicas="$(cat state/applicationset-controller-replicas.txt)"

mv "$STATE" "state/replicas-restored-$(date +%F-%H%M).txt"
echo "== done. Watch: kubectl get pods -A | grep -vE 'Running|Completed'"
