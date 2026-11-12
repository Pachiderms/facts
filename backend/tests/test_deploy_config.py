"""Garde-fous du déploiement : l'image, le blueprint Render et le comportement « prod » de l'API."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app

ROOT = Path(__file__).resolve().parents[2]
DOCKERFILE = (ROOT / "backend" / "Dockerfile").read_text(encoding="utf-8")
DOCKERIGNORE = (ROOT / "backend" / ".dockerignore").read_text(encoding="utf-8").splitlines()
START = (ROOT / "backend" / "start.sh").read_text(encoding="utf-8")
RENDER = (ROOT / "render.yaml").read_text(encoding="utf-8")
FRONT = "https://facts.pages.dev"


def test_image_runs_as_unprivileged_user_in_prod_mode_with_a_single_worker():
    assert "USER facts" in DOCKERFILE
    assert DOCKERFILE.index("USER facts") < DOCKERFILE.index("CMD")  # le serveur ne tourne jamais en root
    assert "FACTS_ENV=prod" in DOCKERFILE
    assert "--workers 1" in START  # l'état des salons est en mémoire : un seul processus
    assert "${PORT:-8000}" in START  # Render impose son port
    assert '"./start.sh"' in DOCKERFILE


def test_image_never_contains_secrets_or_dev_files():
    assert ".env" in DOCKERIGNORE and "tests" in DOCKERIGNORE and ".git" in DOCKERIGNORE
    assert "COPY . " not in DOCKERFILE and "COPY .env" not in DOCKERFILE
    assert "API_KEY" not in DOCKERFILE


def test_render_blueprint_is_free_prod_and_keeps_secrets_out_of_the_repo():
    assert "plan: free" in RENDER
    assert "healthCheckPath: /health" in RENDER
    assert "FACTS_ENV" in RENDER and "value: prod" in RENDER
    for secret in ("FACTS_LLM_API_KEY", "FACTS_TAVILY_API_KEY", "FACTS_CORS_ORIGINS"):
        block = RENDER.split(f"key: {secret}")[1].split("- key:")[0]
        assert "sync: false" in block, f"{secret} doit être saisi dans le tableau de bord, pas dans le dépôt"
    assert "gsk_" not in RENDER and "tvly-" not in RENDER  # préfixes des clés Groq / Tavily


def test_env_example_has_no_real_secret():
    example = (ROOT / "backend" / ".env.example").read_text(encoding="utf-8")
    for line in example.splitlines():
        if line.startswith(("FACTS_LLM_API_KEY=", "FACTS_TAVILY_API_KEY=")):
            assert line.split("=", 1)[1].strip() == ""


@pytest.fixture
def prod_client():
    settings = Settings(env="prod", cors_origins=FRONT, llm_api_key="x", _env_file=None)
    with TestClient(create_app(settings=settings)) as client:
        yield client


def test_prod_hides_interactive_docs_and_schema(prod_client):
    for path in ("/docs", "/redoc", "/openapi.json"):
        assert prod_client.get(path).status_code == 404


def test_prod_health_endpoint_for_the_platform_probe(prod_client):
    assert prod_client.get("/health").json()["status"] == "ok"


def test_prod_cors_only_allows_the_deployed_front(prod_client):
    ok = prod_client.get("/api/v1/rooms", headers={"Origin": FRONT})
    assert ok.headers.get("access-control-allow-origin") == FRONT
    bad = prod_client.get("/api/v1/rooms", headers={"Origin": "https://evil.example"})
    assert "access-control-allow-origin" not in bad.headers


def test_prod_websocket_refuses_foreign_or_missing_origin(prod_client):
    from starlette.websockets import WebSocketDisconnect

    room_id = prod_client.get("/api/v1/rooms").json()[0]["id"]
    for headers in ({"origin": "https://evil.example"}, {}):
        with pytest.raises(WebSocketDisconnect):
            with prod_client.websocket_connect(f"/api/v1/rooms/{room_id}/ws", headers=headers):
                pass


def test_health_reports_uptime_so_restarts_are_visible(prod_client):
    first = prod_client.get("/health").json()
    assert set(first) == {"status", "uptime_seconds"}  # rien d'autre n'est exposé
    assert isinstance(first["uptime_seconds"], int) and first["uptime_seconds"] >= 0
    prod_client.app.state.started -= 3600  # on simule une heure de fonctionnement
    assert prod_client.get("/health").json()["uptime_seconds"] >= 3600


KEEPALIVE = (ROOT / ".github" / "workflows" / "keepalive.yml").read_text(encoding="utf-8")


def test_keepalive_is_off_unless_the_repo_variable_says_true():
    # Sans la variable KEEPALIVE_ENABLED=true, le job est ignoré : aucun appel, aucune heure Render consommée.
    assert "if: ${{ vars.KEEPALIVE_ENABLED == 'true' }}" in KEEPALIVE
    assert "workflow_dispatch" in KEEPALIVE  # déclenchement manuel possible


def test_keepalive_has_no_secret_and_minimal_permissions():
    assert "secrets." not in KEEPALIVE
    assert "permissions: {}" in KEEPALIVE
    assert "actions/checkout" not in KEEPALIVE  # aucun code du dépôt n'est exécuté


def test_keepalive_passes_url_through_env_not_shell_interpolation():
    # Une variable interpolée dans le script shell permettrait d'y injecter des commandes.
    run = KEEPALIVE.split("run: |", 1)[1]
    assert "${{" not in run
    assert 'API_URL: ${{ vars.FACTS_API_URL }}' in KEEPALIVE
    assert "https://*)" in run  # refuse une URL non HTTPS


def test_keepalive_only_calls_health_with_a_timeout_and_runs_within_render_budget():
    assert "/health" in KEEPALIVE and "--max-time" in KEEPALIVE
    cron = [line for line in KEEPALIVE.splitlines() if line.strip().startswith("- cron:")]
    assert len(cron) == 1
    minute, hours, *_ = cron[0].split('"')[1].split()
    assert minute == "*/10"
    start, end = (int(h) for h in hours.split("-"))
    assert (end - start + 1) * 31 < 700  # reste sous les 750 h gratuites/mois, avec marge


def test_start_script_migrates_only_when_a_database_is_configured_and_fails_fast():
    assert "set -e" in START  # une migration qui échoue interrompt le démarrage
    assert 'if [ -n "${FACTS_DATABASE_URL:-}" ]' in START
    assert START.index("alembic upgrade head") < START.index("exec uvicorn")  # migrations AVANT le trafic
    assert "exec uvicorn" in START  # uvicorn reçoit les signaux d'arrêt de Render


def test_image_ships_migrations_but_no_database_secret():
    assert "COPY migrations" in DOCKERFILE and "alembic.ini" in DOCKERFILE
    assert "DATABASE_URL" not in DOCKERFILE
    assert "postgresql" not in (ROOT / "backend" / "alembic.ini").read_text(encoding="utf-8")  # aucune adresse versionnée


def test_render_blueprint_asks_for_the_database_url_without_a_value():
    block = RENDER.split("FACTS_DATABASE_URL", 1)[1].split("- key:", 1)[0]
    assert "sync: false" in block and "value:" not in block  # secret saisi dans le tableau de bord


def test_render_service_is_pinned_to_frankfurt():
    # Sans « region », Render crée le service à Oregon, et la région ne peut plus être modifiée ensuite.
    assert "    region: frankfurt\n" in RENDER


def test_render_service_name_differs_from_the_original_oregon_service():
    # Render refuse un nom déjà pris dans l'espace de travail, même pour un service suspendu.
    assert "    name: facts-api-eu\n" in RENDER
