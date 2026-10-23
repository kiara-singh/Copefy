"""Allow `python -m rag` as an alias for the ingest CLI."""

from rag.ingest import main

raise SystemExit(main())
