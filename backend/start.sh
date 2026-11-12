#!/bin/sh
# Démarrage de l'API. Si une base est configurée, on applique les migrations AVANT d'accepter du trafic :
# une migration qui échoue arrête le démarrage (Render garde l'ancienne version en ligne).
set -e
if [ -n "${FACTS_DATABASE_URL:-}" ]; then
  alembic upgrade head
fi
exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}" --workers 1 --no-server-header
