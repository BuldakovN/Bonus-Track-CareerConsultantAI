from __future__ import annotations

import argparse
import json
from typing import Iterable
from datetime import datetime
from pathlib import Path

from .parsers_stepik import iterate_stepik_courses
from .parsers_postupi import iterate_postupi_programs, iterate_postupi_programs_from_urls
from .parsers_netology import iterate_netology_programs, iterate_netology_programs_from_urls
from .parsers_skillfactory import iterate_skillfactory_courses, iterate_skillfactory_courses_from_urls


def write_ndjson(filename: str, items: Iterable[dict]) -> int:
    count = 0
    with open(filename, "w", encoding="utf-8") as f:
        for obj in items:
            f.write(json.dumps(obj, ensure_ascii=False) + "\n")
            count += 1
    return count


def main() -> None:
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except Exception:
        pass
    parser = argparse.ArgumentParser(description="Fetch education programs and normalize to JSON")
    parser.add_argument("provider", choices=["stepik", "postupi", "netology", "skillfactory"], help="Источник данных")
    parser.add_argument("--pages", type=int, default=1)
    parser.add_argument("--page-size", type=int, default=50)
    parser.add_argument("--language", type=str, default=None)
    parser.add_argument("--query", type=str, default=None)
    parser.add_argument("--cities", type=str, default=None, help="Список городов через запятую: msk,spb,kazan,nnov,tomsk")
    parser.add_argument("--urls", type=str, default=None, help="Явный список ссылок программ через запятую")
    parser.add_argument("--out", type=str, default=None)
    args = parser.parse_args()

    if args.provider == "stepik":
        items = (p.to_json() for p in iterate_stepik_courses(pages=args.pages, page_size=args.page_size, language=args.language))
    elif args.provider == "postupi":
        if args.urls:
            urls = [u.strip() for u in args.urls.split(",") if u.strip()]
            items = (p.to_json() for p in iterate_postupi_programs_from_urls(urls))
        else:
            cities = None
            if args.cities:
                cities = [c.strip() for c in args.cities.split(",") if c.strip()]
            items = (p.to_json() for p in iterate_postupi_programs(cities=cities))
    elif args.provider == "netology":
        if args.urls:
            urls = [u.strip() for u in args.urls.split(",") if u.strip()]
            items = (p.to_json() for p in iterate_netology_programs_from_urls(urls))
        else:
            items = (p.to_json() for p in iterate_netology_programs())
    elif args.provider == "skillfactory":
        if args.urls:
            urls = [u.strip() for u in args.urls.split(",") if u.strip()]
            items = (p.to_json() for p in iterate_skillfactory_courses_from_urls(urls))
        else:
            items = (p.to_json() for p in iterate_skillfactory_courses())

    out_path = args.out
    if not out_path:
        today = datetime.utcnow().strftime("%Y%m%d")
        out_path = f"data/education/{args.provider}.ndjson"

    out_file = Path(out_path)
    out_file.parent.mkdir(parents=True, exist_ok=True)

    written = write_ndjson(str(out_file), items)
    print(f"Saved {written} records to {out_file}")


if __name__ == "__main__":
    main()


