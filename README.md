# ClarityCare Assessment

Oscar Health Medical Guidelines — PDF Scraper + Initial Criteria Tree Explorer.

## Structure

```
├── oscar-app/          ← The application (backend + frontend + extraction module)
├── extraction/         ← Standalone extraction engine (CLI, testable independently)
└── full-stack-feb/     ← Assessment reference material (requirements, ground truth)
```

## Quick Start

```bash
cd oscar-app
chmod +x setup.sh
./setup.sh
```

This installs dependencies, creates the database, and starts both backend (port 8000) and frontend (port 5173).

See [oscar-app/README.md](oscar-app/README.md) for detailed setup, API docs, and Q&A notes.
