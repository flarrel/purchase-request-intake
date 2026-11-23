import argparse
import os
from pathlib import Path

from .skill import LlamaProvider, RulesProvider
from .store import Store
from .web import serve


def main():
    parser = argparse.ArgumentParser(description="Run a local purchase-request workspace.")
    parser.add_argument("--db", type=Path, default=Path("../runtime/requests.sqlite3"))
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--model-url", default="http://127.0.0.1:8082")
    parser.add_argument("--model-key-file", type=Path)
    parser.add_argument("--rules", action="store_true", help="Use the deterministic baseline.")
    arguments = parser.parse_args()
    os.umask(0o077)
    arguments.db.parent.mkdir(parents=True, exist_ok=True)
    key = arguments.model_key_file.read_text().strip() if arguments.model_key_file else None
    provider = RulesProvider() if arguments.rules else LlamaProvider(arguments.model_url, api_key=key)
    serve(Store(arguments.db), provider, arguments.port)


if __name__ == "__main__":
    main()
