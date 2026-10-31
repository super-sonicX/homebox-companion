# Maintained Homebox Companion fork (super-sonicX)

This fork is the **production source of truth** for the customised Companion
running on Unraid. The fork's main branch contains tested local features.
Duelion/homebox-companion upstream remains a fetch-only integration source.

**Never** reset or force-push the fork's main branch to upstream. Never deploy
upstream's unmodified image over the local customisations. The upstream review
process and upstream PRs are separate from this private deployment decision.

## Fork-specific features to preserve

- Library inventory browsing, 40-item pagination, Compact/Standard/Medium/Large
  views, lazy thumbnails, item details and attachment management.
- Sort: Newest first (default), Oldest first, Name A-Z and Name Z-A, over the
  complete server-side result set. Sort is remembered per browser/device.
- Explicit Google Images Lite and eBay Search, gallery reorder and primary-photo
  selection, white-composited transparent catalogue images.
- LAN/HTTP-compatible browser UUID generation, identity-safe review imports,
  and Android camera-first and gallery-first regression tests.
- Compatibility with Homebox 0.26.x and 0.27.x, including correct reversed
  sorting on legacy versions with no orderDirection API support.

## Updating when upstream has changes

1. Review upstream releases and main branch changes; note the current deployed
   fork SHA and Homebox API/server version.

       git remote add upstream https://github.com/Duelion/homebox-companion.git
       git fetch upstream main --tags
       git switch main
       git pull --ff-only origin main
       git switch -c maintenance/upstream-YYYYMMDD
       git merge --no-ff upstream/main

   Add the upstream remote only once. Work on an update branch: never directly
   merge upstream into production main without review.

2. Check for merge conflicts and semantic changes in routes, API schemas,
   Homebox endpoints, image uploads, security, storage, migrations, Dockerfile,
   the lockfiles and existing fork-specific features.
3. Run regression tests from the merged fork source:

       uv sync --locked
       uv run pytest -q -m "not live"
       cd frontend
       npm ci
       npm run check
       npm run lint
       npm run format:check
       npm run test:unit
       npm run build
       npx playwright test tests/browser/library-views.spec.ts tests/browser/library-images.spec.ts tests/browser/library-item-editor.spec.ts

   For Homebox API-related changes, also run the disposable Docker integration
   tests for both supported Homebox versions. Never run destructive integration
   tests against real inventory.

4. Open a PR from the update branch to super-sonicX/homebox-companion main.
   Address CodeRabbit and other review findings, including any compatibility
   regressions, and rerun affected tests. Explicitly justify false positives
   rather than removing supported features. Merge only after validation.
5. Build a versioned image from the merged fork source. Use a clean Git
   archive from main, not a copied upstream Docker image plus undocumented
   application overlays. A possible host build sequence is:

       git switch main
       git pull --ff-only origin main
       git rev-parse --short=12 HEAD
       git archive HEAD | ssh your-tower-host 'mkdir -p /mnt/cache/appdata/hbc-fork-source && tar -xf - -C /mnt/cache/appdata/hbc-fork-source'
       ssh your-tower-host 'docker build -f Dockerfile -t homebox-companion:super-sonicx-COMMIT /mnt/cache/appdata/hbc-fork-source'

   Replace COMMIT with that exact Git SHA. Use a clean build directory on each
   update and never include local credentials or an .env file in the archive.
6. On Tower, execute scripts/deploy-unraid-companion.sh with the tested image
   tag. It checks health, preserves existing environment and appdata, updates
   the Unraid DockerMan image, and retains a stopped rollback container and
   root-restricted backup.
7. Post-deployment checks: health, Homebox connectivity, collection and
   inventory counts, all four sort modes over multiple pages, thumbnails,
   item editing, gallery operations, explicit SerpApi provider actions,
   Android camera-first and gallery-first imports, and creating a Homebox
   location with its first camera photo. Confirm logs show no new failures.
8. Record the upstream SHA, fork SHA, Homebox version, image tag, test results
   and rollback location in the update PR or release notes.

## Rollback and security

The deploy script retains the old container under a name starting
homebox-companion-rollback- followed by a UTC timestamp. On a failed health
check, the script restores the old container and DockerMan template.

For a later regression, manually stop and remove the new container, rename
the matching rollback container back to homebox-companion, start it, and restore
the backed-up DockerMan template. Leave the persistent appdata mount intact.

Backups are located under the root-only
/mnt/cache/appdata/.homebox-migration-backups/companion-TIMESTAMP directory.
The settings archive and Docker inspection output contain credentials: **never
publish them**, upload them to a PR, or expose them in deployment logs.

## Update policy

Upstream updates and Docker deployments are **not automatic**. Each release
requires explicit compatibility verification, review and deployment approval.
The GitHub fork is currently public; credentials, user data, inventory photos
and backups must never be committed.
