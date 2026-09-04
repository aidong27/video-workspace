# Video Workspace 1.0.0-beta.6 production runbook

This runbook covers the first public-readiness slice only:

- exit the complete local-ASR child after an idle timeout and rebuild it on demand;
- add an explicit administrator allowlist and a read-only diagnostic page;
- aggregate cloud-ASR failures without retaining raw provider responses;
- create and verify a restorable application/configuration/SQLite backup.

It does not cover DNS, Cloudflare policy changes, object storage, payments,
YouTube/X workers, or public search-engine submission.

## Safety gates

Do not start a maintenance window unless all of these are true:

1. The target is the Video Workspace host and `/opt/bili-subtitle-tool`, not an
   unrelated server.
2. SSH host-key verification succeeds through a dedicated key or another
   authenticated console channel. Never place passwords in commands or files.
3. There are no queued or running jobs, and no upload is in progress.
4. The local branch is clean and the complete test suite passes.
5. Application deployment and Ubuntu package updates are scheduled as separate
   windows so a regression has one likely cause.

## Window A: recovery gate

1. Record the current Git commit, service state, and public health response.
2. Wait for the queue to drain, then stop only the application:

   ```bash
   sudo systemctl stop bili-subtitle-tool.service
   sudo systemctl show --property=ActiveState --value bili-subtitle-tool.service
   ```

   The second command must report exactly `inactive` before continuing. The
   backup script also fails closed on any other state and checks that the target
   filesystem has room for the application and complete runtime `var/` tree.

3. Run the version-controlled backup script as root:

   ```bash
   cd /opt/bili-subtitle-tool
   sudo ./ops/production-backup
   ```

4. Preserve the printed `backup_complete` path. Confirm it contains
   `BACKUP_COMPLETE`, `SHA256SUMS`, three database files, their source-path
   manifest, the private environment file, and the application archive. The
   archive includes models, browser runtime, cookie state, retained results, and
   temporary media under `var/`; do not accept a backup that omits that tree.
   `host-config/` must also contain the application unit plus complete Nginx and
   cloudflared configuration archives. When the short-lived IP certificate
   renewal units are installed, both units and the Let's Encrypt configuration
   archive are mandatory; a missing required host configuration prevents
   `BACKUP_COMPLETE` from being written.
5. Restart the unchanged application and verify `/api/health` before ending this
   window. If backup verification fails, do not deploy or update packages.

## Window B: Ubuntu security updates

Keep the current application release unchanged for this window.

1. Refresh package metadata and review, but do not assume an older audit count is
   still current:

   ```bash
   sudo apt-get update
   apt list --upgradable
   sudo apt-get --simulate upgrade
   test -f /var/run/reboot-required && cat /var/run/reboot-required.pkgs || true
   ```

2. Apply the reviewed security updates in the approved maintenance window.
3. Reboot only when required. Afterward verify the application, Nginx,
   cloudflared, certificate-renewal timer, failed units, disk, memory, and public
   HTTPS health before testing media.
4. Observe the unchanged application before opening the separate release window.

## Window C: beta.6 application release

1. Repeat Window A if the verified backup is no longer current.
2. Deploy only the reviewed source changes. Do not overwrite `.env`, `var/`,
   databases, models, Playwright data, or existing backups.
3. Add these private environment settings without printing their values:

   ```env
   SERVICE_VERSION=1.0.0-beta.6
   ASR_MODEL_IDLE_SECONDS=900
   ASR_WORKER_EXIT_ON_IDLE=true
   ADMIN_USERNAMES=<existing-owner-username>
   ```

4. Restart the service and validate configuration before public testing:

   ```bash
   sudo systemctl daemon-reload
   sudo systemctl restart bili-subtitle-tool.service
   sudo systemctl is-active bili-subtitle-tool.service
   sudo nginx -t
   ```

5. Sign in as the allowlisted owner and open `/admin`. Confirm that an ordinary
   account receives `403`; a signed-out browser request redirects to `/login`,
   while signed-out `/api/admin/diagnostics` receives `401`.

## Acceptance checks

- `/api/health` remains exactly `{"status":"ok"}` and returns `no-store`.
- `/api/admin/diagnostics` is `no-store`, `noindex`, and contains no API key,
  Cookie, invite code, source URL, signed URL, media content, transcript text,
  username list, or absolute private path.
- A short controlled local-ASR task succeeds.
- After the configured idle interval, the ASR child process exits and its RSS is
  returned to the OS while Uvicorn stays healthy.
- A second controlled task automatically starts a new ASR child and succeeds.
- Repeat the start/task/idle-exit cycle three times without zombies or rising RSS.
- One controlled provider failure appears only under a normalized error code.
- Bilibili and Douyin each pass an authorized end-to-end sample.
- Cancellation, restart recovery, owner isolation, and temporary-file cleanup
  still pass.
- A near-30-minute authorized sample records elapsed time, peak memory, disk
  growth, artifact size, and cleanup recovery.

Observe the release for at least 24 hours for OOM events, service restarts,
orphaned children, failed units, and unexpected disk growth.

## Rollback

The fastest ASR-only rollback is to set `ASR_WORKER_EXIT_ON_IDLE=false` and
restart the application; this restores the previous model-unload-only behavior.

For an application rollback:

1. Stop accepting new work and drain the queue.
2. Stop the application.
3. Preserve the failed release separately.
4. Extract the previous application archive into a new staging directory, verify
   its manifest and inspect the diff, then restore only the affected source files.
5. Restore the backed-up private environment file only when its configuration was
   part of the failure.
6. Do not overwrite `auth.db`, `cloud-usage.db`, `jobs.db`, models, or user
   artifacts during an ordinary code rollback. The beta.6 usage migration adds
   an index and a separate failure-events table; existing tables remain readable
   by the prior release.
7. Start the previous release and repeat public health, login, queue, and one
   controlled media check.

Use database copies only for confirmed corruption and only after preserving all
newer production data created since the backup.
