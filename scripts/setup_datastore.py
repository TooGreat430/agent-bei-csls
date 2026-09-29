"""Membuat data store perpustakaan (dokumen tidak terstruktur + metadata) dan skemanya.

Pemakaian:
    python scripts/setup_datastore.py            # buat data store + terapkan skema
    python scripts/setup_datastore.py --schema-only

Data store dibuat dengan layout parser + chunking, dibutuhkan untuk sitasi per halaman
(LIB_SEARCH_RESULT_MODE=CHUNKS).
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from google.api_core.exceptions import AlreadyExists  # noqa: E402
from google.cloud import discoveryengine_v1 as de  # noqa: E402

from library_agent.clients import _discovery_client_options, datastore_path  # noqa: E402
from library_agent.config import settings  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def create_datastore() -> None:
    client = de.DataStoreServiceClient(client_options=_discovery_client_options())
    dpc = de.DocumentProcessingConfig
    data_store = de.DataStore(
        display_name="Perpustakaan Dokumen",
        industry_vertical=de.IndustryVertical.GENERIC,
        solution_types=[de.SolutionType.SOLUTION_TYPE_SEARCH],
        content_config=de.DataStore.ContentConfig.CONTENT_REQUIRED,
        document_processing_config=dpc(
            default_parsing_config=dpc.ParsingConfig(
                layout_parsing_config=dpc.ParsingConfig.LayoutParsingConfig()
            ),
            chunking_config=dpc.ChunkingConfig(
                layout_based_chunking_config=dpc.ChunkingConfig.LayoutBasedChunkingConfig(
                    chunk_size=500, include_ancestor_headings=True
                )
            ),
        ),
    )
    parent = f"projects/{settings.project_id}/locations/{settings.search_location}/collections/default_collection"
    try:
        op = client.create_data_store(parent=parent, data_store=data_store, data_store_id=settings.datastore_id)
        print("Membuat data store...", op.operation.name)
        op.result(timeout=600)
        print("Data store dibuat:", datastore_path())
    except AlreadyExists:
        print("Data store sudah ada:", datastore_path())


def apply_schema() -> None:
    client = de.SchemaServiceClient(client_options=_discovery_client_options())
    with open(os.path.join(ROOT, "setup", "datastore_schema.json"), encoding="utf-8") as fh:
        schema_json = json.load(fh)
    schema = de.Schema(name=f"{datastore_path()}/schemas/default_schema", json_schema=json.dumps(schema_json))
    op = client.update_schema(schema=schema, allow_missing=True)
    print("Menerapkan skema...", op.operation.name)
    op.result(timeout=600)
    print("Skema diterapkan. Field doc_key bisa dipakai untuk filter.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--schema-only", action="store_true")
    args = parser.parse_args()
    if not args.schema_only:
        create_datastore()
    apply_schema()
