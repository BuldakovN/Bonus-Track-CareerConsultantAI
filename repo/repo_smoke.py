"""
Локальная проверка репозитория (новая схема: app_user, identity, who_user, conversation, dialog_state).

    cd repo && set PYTHONPATH=.. && python repo_smoke.py
"""
import os
import sys
from pathlib import Path

# корень проекта в PYTHONPATH
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from repo.repository import DEFAULT_SQLITE_FILENAME, Repository, RepositoryConfig  # noqa: E402


def main():
    db_url = os.getenv("SQLITE_URL", f"sqlite:///{DEFAULT_SQLITE_FILENAME}")
    repo = Repository(RepositoryConfig(db_url=db_url, echo=False))
    repo.create_schema()

    provider, ext = "telegram", "999001"
    aid = repo.put_session_bundle(
        provider,
        ext,
        user_state="talk",
        user_type="student",
        user_metadata={
            "who_user": "Кратко: студент.",
            "about_user": "Любит код.",
            "ai_recommendation": "текст",
        },
        conversation_history=[
            {"role": "system", "text": "sys"},
            {"role": "user", "text": "привет"},
        ],
    )
    assert aid > 0

    b = repo.get_session_bundle(provider, ext)
    assert b["user_state"] == "talk"
    assert b["user_type"] == "student"
    assert b["user_metadata"]["who_user"] == "Кратко: студент."
    assert b["user_metadata"]["about_user"] == "Любит код."
    assert len(b["conversation_history"]) == 2

    assert repo.get_app_user_id(provider, ext) == aid

    repo.clear_identity_session(provider, ext)
    b2 = repo.get_session_bundle(provider, ext)
    assert b2["conversation_history"] == []
    assert b2["user_metadata"] == {}

    print("repo_smoke OK, app_user_id=", aid)


if __name__ == "__main__":
    main()
