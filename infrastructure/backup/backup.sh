#!/bin/sh
# Logical Postgres backups (custom format, compressed). Usage: backup.sh once|loop
# Writes /backups/<db>-<UTC timestamp>.dump atomically and prunes files older than BACKUP_KEEP_DAYS.
set -eu

BACKUP_DIR="${BACKUP_DIR:-/backups}"
KEEP_DAYS="${BACKUP_KEEP_DAYS:-14}"
INTERVAL="${BACKUP_INTERVAL_SECONDS:-86400}"

run_backup() {
  stamp="$(date -u +%Y%m%dT%H%M%SZ)"
  tmp="$BACKUP_DIR/.${PGDATABASE}-${stamp}.partial"
  final="$BACKUP_DIR/${PGDATABASE}-${stamp}.dump"
  pg_dump --format=custom --compress=6 --no-owner --file="$tmp"
  mv "$tmp" "$final"
  # A dump that cannot be listed is not a backup.
  pg_restore --list "$final" > /dev/null
  find "$BACKUP_DIR" -name "${PGDATABASE}-*.dump" -mtime "+${KEEP_DAYS}" -exec rm -f {} +
  echo "backup ok: $final ($(wc -c < "$final") bytes)"
}

case "${1:-once}" in
  once) run_backup ;;
  loop) while true; do run_backup || echo "backup FAILED" >&2; sleep "$INTERVAL"; done ;;
  *) echo "usage: $0 once|loop" >&2; exit 2 ;;
esac
