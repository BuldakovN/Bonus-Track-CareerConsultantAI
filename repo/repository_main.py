import os
from repository import DEFAULT_SQLITE_FILENAME, Repository, RepositoryConfig


def main():
    db_url = os.getenv("SQLITE_URL", f"sqlite:///{DEFAULT_SQLITE_FILENAME}")
    repo = Repository(RepositoryConfig(db_url=db_url, echo=False))
    repo.create_schema()
    print(f"OK: schema created in {db_url}")

if __name__ == "__main__":
    main()
