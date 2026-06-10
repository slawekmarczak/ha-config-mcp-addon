#!/usr/bin/env bash
set -e

# Wczytaj opcje z konfiguracji addona (HA dostarcza przez /data/options.json)
GIT_REMOTE=$(bashio::config 'git_remote')
GIT_BRANCH=$(bashio::config 'git_branch')
GIT_USER_NAME=$(bashio::config 'git_user_name')
GIT_USER_EMAIL=$(bashio::config 'git_user_email')

export GIT_REMOTE GIT_BRANCH

# Konfiguruj git
git config --global user.name "${GIT_USER_NAME}"
git config --global user.email "${GIT_USER_EMAIL}"
git config --global --add safe.directory /config

# Pobierz token HA z zmiennej środowiskowej (HA Supervisor dostarcza SUPERVISOR_TOKEN)
export HA_TOKEN="${SUPERVISOR_TOKEN}"
export HA_URL="http://supervisor/core"
export HA_CONFIG_DIR="/config"

bashio::log.info "Starting HA Config MCP Server on port 8765..."
bashio::log.info "Git remote: ${GIT_REMOTE}, branch: ${GIT_BRANCH}"

exec python3 /server.py
