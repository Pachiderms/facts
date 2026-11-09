# Image du backend Facts : petite, sans privilèges, sans secret.
FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /srv

# Dépendances d'abord : cette couche reste en cache tant que requirements.txt ne change pas.
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY app ./app

# Utilisateur sans privilèges (le code n'a besoin d'écrire nulle part : tout vit en mémoire).
RUN useradd --system --no-create-home --uid 10001 facts
USER facts

ENV FACTS_ENV=prod
EXPOSE 8000

# Render fournit $PORT ; 8000 par défaut en local. Un seul worker : l'état des salons est en mémoire.
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --workers 1 --no-server-header"]
