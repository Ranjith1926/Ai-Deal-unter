#!/bin/sh
# Restore drill: restores a dump into a scratch database and compares row counts with the live database.
# Usage: restore-check.sh /backups/<file>.dump    (needs PGHOST/PGUSER/PGPASSWORD/PGDATABASE set)
# Never touches the live database: the scratch database is created and dropped by this script.
set -eu

DUMP="${1:?path to a .dump file}"
SCRATCH="${PGDATABASE}_restore_check"
LIVE="$PGDATABASE"
TABLES="users products product_platforms product_prices product_scores deal_events price_alerts"

psql -d postgres -qc "DROP DATABASE IF EXISTS \"$SCRATCH\"" -c "CREATE DATABASE \"$SCRATCH\""
pg_restore --no-owner --exit-on-error -d "$SCRATCH" "$DUMP"

status=0
printf '%-20s %12s %12s\n' table live restored
for t in $TABLES; do
  live="$(psql -d "$LIVE" -Atc "select count(*) from $t")"
  rest="$(psql -d "$SCRATCH" -Atc "select count(*) from $t")"
  mark=""
  [ "$live" = "$rest" ] || mark="  <-- differs (new rows since the dump are expected)"
  printf '%-20s %12s %12s%s\n' "$t" "$live" "$rest" "$mark"
  [ "$rest" -gt 0 ] || [ "$live" -eq 0 ] || status=1
done
ver="$(psql -d "$SCRATCH" -Atc 'select version_num from alembic_version')"
echo "restored schema revision: $ver"

psql -d postgres -qc "DROP DATABASE \"$SCRATCH\""
[ "$status" -eq 0 ] && echo "RESTORE CHECK PASSED" || { echo "RESTORE CHECK FAILED"; exit 1; }
