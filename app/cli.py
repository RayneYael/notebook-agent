"""P0 command-line entry points."""

import argparse

from app.config import get_settings
from app.db import session
from app.ingest.embed import ZhipuEmbedder
from app.ingest.tasks import ingest_url
from app.retrieval.search import bm25_search, vector_search


def _print(name, hits):
    print(f"\n{name}")
    for rank, hit in enumerate(hits, 1):
        print(f"{rank:>2}. {hit.title or hit.platform_id} | {hit.url} | {hit.score:.4f}\n    {hit.text[:240]}")


def main() -> None:
    parser = argparse.ArgumentParser(prog="kb")
    commands = parser.add_subparsers(dest="command", required=True)
    ingest = commands.add_parser("ingest")
    ingest.add_argument("url")
    ingest.add_argument("--why-saved")
    search = commands.add_parser("search")
    search.add_argument("query")
    search.add_argument("-k", type=int, default=10)
    args = parser.parse_args()
    if args.command == "ingest":
        item_id, state = ingest_url(args.url, why_saved=args.why_saved)
        print(f"item={item_id} state={state}")
        return
    settings = get_settings()
    embedder = ZhipuEmbedder(
        settings.zhipu_api_key or "",
        model=settings.embedding_model,
        endpoint=settings.embedding_endpoint,
        dimensions=settings.embedding_dimensions,
        batch_size=settings.embedding_batch_size,
    )
    with session() as db:
        lexical = bm25_search(db, args.query, k=args.k)
        vector = vector_search(db, embedder.embed([args.query])[0], k=args.k)
    _print("BM25 / trigram", lexical)
    _print("Vector", vector)


if __name__ == "__main__":
    main()
