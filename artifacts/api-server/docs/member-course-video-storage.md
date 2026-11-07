# Member course video storage

The member lesson library is separate from the Owner's Telegram Education-video publisher.
Uploads are MP4 files written by the API to a private local directory; the directory is
never exposed as a static web root. Member playback is streamed through an authenticated
API route with byte-range support.

## Development

Development uses `smh_test` and a temporary directory under the operating system's temp
directory unless `MEMBER_VIDEO_STORAGE_DIR` is set. Temporary Development uploads are for
isolated testing and should not be treated as durable content.

Apply `migrations/portal-development/027_member_course_videos.sql` only to `smh_test`.

## Hostinger configuration (not applied)

Before enabling this on the VPS:

1. Back up the `smh` database and review `migrations/portal-production/001_member_course_videos.sql`.
2. Create a private persistent directory such as `/var/lib/smh/member-course-videos`.
   It must be writable by the API's systemd service account and must not be inside the
   Nginx document root.
3. Set `MEMBER_VIDEO_STORAGE_DIR` in the protected systemd environment.
4. Keep `SMH_MEMBER_VIDEOS_ENABLED=false` until the migration, API release, disk permissions,
   and member authorization tests pass.
5. Configure the Nginx API location to accept MP4 uploads up to 250 MB (for example,
   `client_max_body_size 260m` on that location), then run `nginx -t` before any reload.
6. Enable the feature only after explicit Production approval.

Production migration SQL has been prepared but has not been applied. No VPS, Nginx,
Production database, or Production authentication settings were changed.

## Routes

- `GET /api/member/videos` — verified signed-in members; returns only published lesson metadata.
- `GET /api/member/videos/:videoId/file` — verified signed-in members; streams only published MP4 files.
- `/api/portal/member-course-videos...` — Owner-only upload, preview, publish, and unpublish actions.

Every video request checks the current session. Unpublishing immediately blocks subsequent
member list and stream requests. Video bytes are not sent to Telegram.

## Rollback

Set `SMH_MEMBER_VIDEOS_ENABLED=false` and redeploy the previous API release. This disables
the new Production routes without deleting video rows or files. Keep the additive table and
the private storage directory until the rollback decision is reviewed; do not drop the table
or remove uploaded files as part of an application rollback.
