#!/bin/sh
# Container entrypoint.
#
# Runs as root only long enough to make the data volume writable by the
# unprivileged runtime user, then drops privileges and execs whatever command it
# was given (uvicorn by default -- see CMD in the Dockerfile).
#
# It is the ENTRYPOINT rather than the CMD so that one-off maintenance commands
# get the same privilege drop:
#
#     docker compose run --rm mosaic python -m cli verify
#
# Without that, a maintenance command would run as root and could leave
# root-owned files in the volume that the app itself could no longer write.
set -e

DATA_DIR="${DATA_DIR:-/app/data}"
APP_USER=mosaic
APP_UID=10001

mkdir -p "${DATA_DIR}/audit"
mkdir -p "${DATA_DIR}/backups"
mkdir -p "${DATA_DIR}/uploads/avatars"

if [ "$(id -u)" = "0" ]; then
    # A volume created by Mosaic v2.0.0 or earlier is root-owned, because those
    # images ran as root. Take ownership so the upgrade is transparent instead of
    # failing with permission errors on first write.
    #
    # Guarded on the directory's own owner rather than run unconditionally: a
    # recursive chown of every backup on every restart is wasted work once the
    # ownership is already correct.
    if [ "$(stat -c %u "${DATA_DIR}")" != "${APP_UID}" ]; then
        echo "start.sh: taking ownership of ${DATA_DIR} for uid ${APP_UID}"
        chown -R "${APP_UID}:${APP_UID}" "${DATA_DIR}"
    fi

    # BACKUP_PATH is deliberately NOT chown'd. It is an external mount (a NAS
    # share, a OneDrive-synced folder, a rclone mount) whose ownership belongs to
    # whoever mounted it, and chown on such a filesystem either fails or does
    # something surprising. It must be made writable by uid 10001 on the host
    # side; main.py checks that at startup and refuses to boot if it isn't.

    exec gosu "${APP_USER}" "$@"
fi

# Already running unprivileged (e.g. `docker run --user`), so nothing to drop.
exec "$@"
