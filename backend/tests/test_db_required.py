"""En CI, ne jamais laisser les tests PostgreSQL être ignorés par oubli de configuration."""

import os


def test_database_tests_are_not_silently_skipped_when_required():
    if os.environ.get("FACTS_REQUIRE_DB_TESTS") == "1":
        assert os.environ.get("FACTS_TEST_DATABASE_URL"), "FACTS_TEST_DATABASE_URL manquant : les tests de base seraient ignorés"
