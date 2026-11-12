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
COPY migrations ./migrations
COPY alembic.ini start.sh ./

# Utilisateur sans privilèges (le code n'a besoin d'écrire nulle part : tout vit en mémoire).
RUN useradd --system --no-create-home --uid 10001 facts
USER facts

ENV FACTS_ENV=prod
EXPOSE 8000

# start.sh : migrations Alembic si une base est configurée, puis uvicorn (Render fournit $PORT ; 8000 par défaut).
# Un seul worker : l'état des salons est en mémoire.
CMD ["./start.sh"]
