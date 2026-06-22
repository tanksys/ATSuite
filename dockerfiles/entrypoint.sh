#!/bin/bash

USER_ID=${CONTAINER_UID}
GROUP_ID=${CONTAINER_GID}
USER=${CONTAINER_USER}

if [ "$(id -u)" -eq 0 ] && command -v useradd >/dev/null 2>&1 && command -v groupmod >/dev/null 2>&1; then
  useradd --non-unique -m -u ${USER_ID} ${USER}
  groupmod --non-unique -g ${GROUP_ID} ${USER}
  mkdir -p /mnt/function && chown -R ${USER}:${USER} /mnt/function
  export HOME=/home/${USER}
  echo "Running as ${USER}, with ${USER_ID} and ${GROUP_ID}"
  USE_GOSU=1
else
  if [ "$(id -u)" -ne 0 ]; then
    echo "Running as uid $(id -u) (non-root); skipping useradd/groupmod"
  else
    echo "useradd/groupmod not available; running as root"
  fi
  USE_GOSU=0
fi

if [ ! -z "$CMD" ]; then
  if [ "$USE_GOSU" -eq 1 ]; then
    gosu ${USER} $CMD
  else
    $CMD
  fi
fi

if [ "$USE_GOSU" -eq 1 ]; then
  exec gosu ${USER} "$@"
else
  exec "$@"
fi