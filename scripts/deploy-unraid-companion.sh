#!/usr/bin/env bash
# Execute on the Unraid host after building a tested, commit-tagged fork image.
set -Eeuo pipefail
umask 077
if [[ "$#" -ne 1 ]]; then
    echo "Usage: deploy-unraid-companion.sh DOCKER_IMAGE_TAG" >&2
    exit 2
fi
image="$1"
container="homebox-companion"
appdata="/mnt/user/appdata/homebox-companion"
template="/boot/config/plugins/dockerMan/templates-user/my-homebox-companion.xml"
backup_root="/mnt/cache/appdata/.homebox-migration-backups"
timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
rollback_name="homebox-companion-rollback-$timestamp"
backup="$backup_root/companion-$timestamp"
env_file=""
renamed=0
for tool in docker jq curl tar; do
    command -v "$tool" >/dev/null || { echo "Missing: $tool" >&2; exit 1; }
done
[[ "$image" =~ ^[a-zA-Z0-9_./:@-]+$ ]]
docker image inspect "$image" >/dev/null
docker inspect "$container" >/dev/null
test -f "$template"
test -d "$appdata"
test "$(docker inspect "$container" --format '{{.HostConfig.NetworkMode}}')" = bridge

restore() {
    if [[ "$renamed" -eq 1 ]]; then
        echo "FAILED deployment: restoring old container and DockerMan template." >&2
        docker rm -f "$container" >/dev/null 2>&1 || true
        docker rename "$rollback_name" "$container"
        docker start "$container" >/dev/null
        cp -a "$backup/dockerMan-template.xml" "$template"
    fi
}
on_exit() {
    result="$?"
    [[ -z "$env_file" ]] || rm -f "$env_file"
    if [[ "$result" -ne 0 ]]; then restore; fi
}
trap on_exit EXIT

mkdir -p "$backup"
chmod 700 "$backup"
cp -a "$template" "$backup/dockerMan-template.xml"
# SENSITIVE backups: Docker inspection and settings contain credentials.
docker inspect "$container" > "$backup/container-inspect-SENSITIVE.json"
tar -czf "$backup/appdata-SENSITIVE.tar.gz" -C /mnt/user/appdata homebox-companion
chmod 600 "$backup"/*

# Keep all existing environment settings without printing or persisting them
# in a process command line or Git. This short-lived env file resides in RAM.
env_file="$(mktemp /dev/shm/hbc-deploy-env.XXXXXXXX)"
docker inspect "$container" | jq -r '.[0].Config.Env[]' > "$env_file"
chmod 600 "$env_file"

echo "Backups saved: $backup"
docker stop --timeout 25 "$container" >/dev/null
docker rename "$container" "$rollback_name"
renamed=1

docker run -d \
    --name "$container" \
    --restart unless-stopped \
    --network bridge \
    --user appuser \
    --log-driver json-file \
    --log-opt max-file=1 \
    --log-opt max-size=50m \
    --env-file "$env_file" \
    -p 8000:8000 \
    -v "$appdata":/app/data:rw \
    --label net.unraid.docker.managed=dockerman \
    --label 'net.unraid.docker.webui=http://[IP]:[PORT:8000]' \
    --label 'net.unraid.docker.icon=https://raw.githubusercontent.com/Duelion/homebox-companion/main/.github/assets/images/homebox-companion-icon.png' \
    "$image" >/dev/null

healthy=0
for attempt in $(seq 1 75); do
    state="$(docker inspect "$container" --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}')"
    if [[ "$state" = healthy ]] && curl -fsS --max-time 4 http://127.0.0.1:8000/api/version >/dev/null; then
        healthy=1
        break
    fi
    sleep 2
done
if [[ "$healthy" -ne 1 ]]; then
    echo "New image did not become healthy." >&2
    exit 1
fi
grep -q '<Repository>' "$template"
sed -i "s|<Repository>[^<]*</Repository>|<Repository>$image</Repository>|" "$template"
grep -Fq "<Repository>$image</Repository>" "$template"
echo "Deployment healthy: $image"
echo "Retained old container for rollback: $rollback_name"
echo "Keep $backup until end-to-end tests pass."
renamed=0
