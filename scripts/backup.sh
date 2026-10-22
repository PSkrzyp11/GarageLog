#!/bin/sh
# Database backups; runs in the "backup" service from compose.yaml.
#
#   (no argument)   every BACKUP_INTERVAL_HOURS: a dump, then dumps older than
#                   BACKUP_KEEP_DAYS are deleted (only after a successful dump)
#   once            a single dump now:  docker compose run --rm backup once
#   restore FILE    replace the database with a dump from the backup folder:
#                   docker compose run --rm backup restore garagelog-2026-10-22_210000.dump
#
# The connection comes from the standard PG* variables (PGHOST, PGUSER, ...).
set -u

BACKUP_DIR=/backups

dump() {
    # Seconds in the name, and never an existing name: two dumps started close together
    # (e.g. a manual one and the one at container start) must not replace each other.
    file="$BACKUP_DIR/garagelog-$(date +%Y-%m-%d_%H%M%S).dump"
    while [ -e "$file" ] || [ -e "$file.partial" ]; do
        sleep 1
        file="$BACKUP_DIR/garagelog-$(date +%Y-%m-%d_%H%M%S).dump"
    done
    # Written under a temporary name, so a half-written file never looks like a backup.
    if pg_dump --format=custom --file="$file.partial"; then
        mv "$file.partial" "$file"
        echo "Backup saved: $file"
    else
        rm -f "$file.partial"
        echo "Backup FAILED" >&2
        return 1
    fi
}

restore() {
    # One transaction: if anything fails, the database stays as it was.
    pg_restore --clean --if-exists --no-owner --single-transaction \
        --dbname="$PGDATABASE" "$BACKUP_DIR/$1" && echo "Restored: $1"
}

case "${1:-}" in
    once)
        dump
        ;;
    restore)
        restore "${2:?usage: restore FILE (a file name from the backup folder)}"
        ;;
    *)
        while true; do
            dump && find "$BACKUP_DIR" -name 'garagelog-*.dump' -mtime +"$BACKUP_KEEP_DAYS" -delete
            sleep "$((BACKUP_INTERVAL_HOURS * 3600))"
        done
        ;;
esac
