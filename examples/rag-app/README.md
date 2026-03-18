# Example: RAG Application

This example demonstrates how to use AI Dev Team to build a **Retrieval-Augmented Generation (RAG)** application from scratch — fully autonomously.

## What Gets Built

A production-ready RAG system with:
- **FastAPI backend** — document upload, chunking, embedding, semantic search, chat
- **Angular 18 frontend** — document management UI, chat interface
- **MongoDB** — document metadata, chat history
- **ChromaDB** — vector store for embeddings
- **Claude API** — answer generation with source citations
- **Docker Compose** — full containerized setup
- **CI/CD** — GitHub Actions pipeline with linting, tests, and Docker build

## Quick Start

```bash
# 1. Initialize the project
python3 scripts/init_project.py "RAG App" \
  "Production-ready RAG system. Upload PDF/TXT/MD documents, chunk and embed them, \
   store in ChromaDB, query via natural language with Claude API. \
   FastAPI backend, Angular 18 frontend, MongoDB, Docker Compose."

# 2. (Optional) Write a detailed brief to the PO
cp examples/rag-app/po-brief.md board/inbox/po.md

# 3. (Optional) Set up GitLab/GitHub integration
cp config/.env.example config/.env
# Edit config/.env with your tokens
python3 scripts/init_integrations.py

# 4. Run the team
./scripts/orchestrator_cli.sh dev-team

# 5. Set up automated runs (optional)
crontab ai-team.crontab
```

## What Happens

After the first cycle (~15-30 minutes):
- PO creates 8-10 user stories with acceptance criteria
- PM assigns stories to developers
- Dev1/Dev2 start implementing the backend scaffolding
- DevOps creates Dockerfile and docker-compose.yml

After 5-6 sprints (~50 cycles, ~1 night with 40-min cron):
- Full backend with 18+ services, 8 routers, middleware
- Angular frontend with chat, upload, collections UI
- 400+ tests with 80%+ coverage
- Docker Compose setup with health checks
- CI/CD pipeline
- Security audit completed

## The PO Brief

See [po-brief.md](po-brief.md) for the initial brief that was sent to the Product Owner agent. This is the **only human input** — everything else is autonomous.

## Results

After running overnight, the team produced:
- **28 user stories** across 6 sprints
- **26 completed**, 2 in backlog
- **~3,600 lines** of backend code
- **407+ tests** across 39 test files
- **10 merged MRs** on GitLab
- **0 agent failures**

All managed through the GitLab board with issues, labels, and merge requests.
