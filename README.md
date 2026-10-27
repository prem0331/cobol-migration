# COBOL to FastAPI Migration Pipeline

A multi-agent pipeline (Analyst → Architect → Developer) that converts COBOL programs to FastAPI microservices using LLMs via LangChain LCEL. **Phase 2 adds batch processing, copybook resolution, CALL graph analysis, dependency graphs, and migration planning.**

## Architecture

### Phase 1: Single Program Migration
```
┌─────────────┐     ┌──────────────┐     ┌────────────────┐     ┌──────────────────┐
│   COBOL     │────▶│  Analyst     │────▶│   Architect    │────▶│  Developer       │
│   Source    │     │  (Agent 1)   │     │  (Agent 2)     │     │  (Agent 3)       │
└─────────────┘     └──────────────┘     └────────────────┘     └──────────────────┘
                         │                    │                        │
                         ▼                    ▼                        ▼
                  business_rules.json    pydantic_schema.py      fastapi_app/
```

### Phase 2: Batch Migration with Dependency Analysis
```
┌─────────────────────────────────────────────────────────────────────────────┐
│                        PHASE 2 PIPELINE                                      │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  ┌──────────────┐    ┌────────────────┐    ┌────────────────────────────┐  │
│  │ COBOL File   │    │ Copybook       │    │ Dependency Graph Builder   │  │
│  │ Discovery    │───▶│ Resolution     │───▶│ (CALL, COPY, SHARED FILE)  │  │
│  │ (scan dirs)  │    │ (COPY stmts)   │    └─────────────┬─────────────┘  │
│  └──────────────┘    └────────────────┘                  │                │
│                                                          ▼                │
│                                               ┌─────────────────────┐     │
│                                               │ Migration Planner   │     │
│                                               │ (groups by dep.)    │     │
│                                               └──────────┬──────────┘     │
│                                                          │                │
│                    ┌────────────────────────────────────┘                │
│                    ▼                                                     │
│           ┌─────────────────────────┐                                    │
│           │ Batch Pipeline          │                                    │
│           │ Orchestrator            │                                    │
│           └───────────┬─────────────┘                                    │
│                       │                                                  │
│        ┌──────────────┼──────────────┐                                  │
│        ▼              ▼              ▼                                  │
│  ┌───────────┐ ┌───────────┐ ┌───────────┐                              │
│  │ Pipeline  │ │ Pipeline  │ │ Pipeline  │  ...                         │
│  │ Group 1   │ │ Group 2   │ │ Group 3   │                              │
│  │ (3-agent) │ │ (3-agent) │ │ (3-agent) │                              │
│  └───────────┘ └───────────┘ └───────────┘                              │
│        │              │              │                                   │
│        └──────────────┼──────────────┘                                   │
│                       ▼                                                  │
│           ┌─────────────────────┐                                       │
│           │ Integration         │                                       │
│           │ Validator           │                                       │
│           │ (semantic equiv)    │                                       │
│           └─────────────────────┘                                       │
│                                                                          │
└──────────────────────────────────────────────────────────────────────────┘
```

### Agent Roles

1. **Analyst** - Reads COBOL, extracts structured business rules (data definitions, logic, I/O)
2. **Architect** - Converts business rules to Pydantic models with proper types, enums, validation
3. **Developer** - Generates complete FastAPI application (routes, services, models, main)

---

## Quick Start

### Prerequisites
- Python 3.10+
- **Gemini API key** (get from [aistudio.google.com/apikey](https://aistudio.google.com/apikey))

### Installation

```bash
# Clone and enter project
cd cobol

# Install dependencies (uses uv for speed)
uv pip install -e ".[dev]"

# Or with pip
pip install -e ".[dev]"

# Copy environment template
cp .env.example .env
# Edit .env with your GEMINI_API_KEY
```

### Phase 1: Single Program Migration

```bash
# Migrate a COBOL file to FastAPI
python -m src.pipeline.runner migrate examples/sample.cbl -o ./output

# Preview extracted COBOL sections
python -m src.pipeline.runner preview examples/sample.cbl

# Test Gemini API connectivity
python -m src.pipeline.runner test-gemini
```

### Phase 2: Batch Migration (NEW)

```bash
# Build dependency graph and migration plan
python -m src.pipeline.runner graph tests/fixtures/phase2_coupled -o ./output/graph.json

# View migration plan
python -m src.pipeline.runner plan tests/fixtures/phase2_coupled -o ./output/plan.json

# Run batch migration with grouped strategy
python -m src.pipeline.runner batch tests/fixtures/phase2_coupled \
  --copybook-dirs tests/fixtures/phase2_coupled \
  --strategy grouped \
  -o ./migration-output

# Or with independent strategy (one service per program)
python -m src.pipeline.runner batch tests/fixtures/phase2_coupled \
  --copybook-dirs tests/fixtures/phase2_coupled \
  --strategy independent \
  -o ./migration-output-independent
```

### Run the Generated Services

```bash
# Group-0: Customer Service (coupled programs)
cd migration-output/group-0
pip install -r requirements.txt
uvicorn main:app --reload --port 8000

# Group-1: Report Service (independent)
cd migration-output/group-1
pip install -r requirements.txt
uvicorn main:app --reload --port 8001
```

Visit http://localhost:8000/docs and http://localhost:8001/docs for Swagger UI.

---

## Configuration

Environment variables (`.env`):

```env
# =============================================================================
# GEMINI API Configuration (Required)
# =============================================================================
GEMINI_API_KEY=your_api_key_here

# =============================================================================
# GLOBAL DEFAULTS (used if agent-specific not set)
# =============================================================================
GEMINI_MODEL=gemini-2.0-flash-exp
GEMINI_TEMPERATURE=0.1
GEMINI_MAX_TOKENS=8192

# =============================================================================
# AGENT-SPECIFIC OVERRIDES (Multi-Provider Support)
# Each agent can use a different model optimized for its task
# =============================================================================

# Agent 1: ANALYST - COBOL extraction & business rules
# Use fast, cost-effective model for high-volume extraction
GEMINI_ANALYST_MODEL=gemini-2.0-flash-exp
GEMINI_ANALYST_TEMPERATURE=0.1
GEMINI_ANALYST_MAX_TOKENS=16384

# Agent 2: ARCHITECT - Pydantic schema design
# Use higher-quality model for complex reasoning
GEMINI_ARCHITECT_MODEL=gemini-2.0-flash-exp
GEMINI_ARCHITECT_TEMPERATURE=0.1
GEMINI_ARCHITECT_MAX_TOKENS=8192

# Agent 3: DEVELOPER - FastAPI code generation
# Use best code generation model with higher token limit
GEMINI_DEVELOPER_MODEL=gemini-2.0-flash-exp
GEMINI_DEVELOPER_TEMPERATURE=0.1
GEMINI_DEVELOPER_MAX_TOKENS=32768
```

---

## COBOL Support

### Phase 1 (MVP) - ✅ Implemented
- ✅ WORKING-STORAGE SECTION (data definitions)
- ✅ PROCEDURE DIVISION (paragraphs, logic)
- ✅ PICTURE clauses (9, X, V, COMP, COMP-3, PACKED-DECIMAL)
- ✅ VALUE, OCCURS, REDEFINES
- ✅ 88-level condition names → Python Enums
- ✅ IF/ELSE/END-IF conditions
- ✅ PERFORM, MOVE, COMPUTE, ADD/SUBTRACT/MULTIPLY/DIVIDE
- ✅ DISPLAY, ACCEPT I/O
- ✅ FILE SECTION (FD/SD, SELECT/ASSIGN) - basic
- ✅ LINKAGE SECTION - basic

### Phase 2 (Batch & Dependencies) - ✅ Implemented
- ✅ **COPY statements** - Copybook resolution with nested includes
- ✅ **CALL statements** - Static CALL extraction with USING parameters
- ✅ **Shared file analysis** - FILE SECTION FD/SD, SELECT/ASSIGN mapping
- ✅ **Dependency graph** - Unified graph: programs, copybooks, files
- ✅ **Migration planner** - Grouped/Independent/Hybrid strategies
- ✅ **Shared Pydantic models** - Generated from shared copybooks
- ✅ **Service contracts** - OpenAPI specs + client stubs for CALL relationships

### Not Yet Supported
- ❌ COPY ... REPLACING
- ❌ Dynamic CALL (CALL variable-name)
- ❌ CICS/BMS screens
- ❌ Embedded SQL (EXEC SQL) - parser only, not executed
- ❌ Complex TABLE/SEARCH ALL
- ❌ Nested PROGRAM-ID (multiple programs per file)

---

## Project Structure

```
cobol/
├── src/
│   ├── pipeline/                    # Multi-agent pipeline
│   │   ├── __init__.py
│   │   ├── chain.py                 # LCEL chain composition (simple + batch)
│   │   ├── models.py                # Pydantic models (BusinessRules, FastAPIOutput, ServiceContract, SharedModel)
│   │   ├── prompts.py               # Prompt templates for each agent
│   │   ├── parsers.py               # Output parsers with validation
│   │   ├── runner.py                # CLI entry point (migrate, batch, graph, plan, test-gemini)
│   │   ├── system_graph.py          # Dependency graph builder (NEW)
│   │   ├── planner.py               # Migration planner (NEW)
│   │   └── batch_runner.py          # Batch orchestration (NEW)
│   ├── cobol/                       # COBOL parsing & analysis
│   │   ├── __init__.py
│   │   ├── extractor.py             # Section extraction (regex-based)
│   │   ├── parser.py                # Structured parsing (WORKING-STORAGE, PROCEDURE)
│   │   ├── discovery.py             # File discovery & inventory (NEW)
│   │   ├── copybook.py              # COPY statement resolution (NEW)
│   │   ├── callgraph.py             # CALL statement extraction (NEW)
│   │   └── dataflow.py              # File/shared data analysis (NEW)
│   └── fastapi/                     # FastAPI templates
│       ├── __init__.py
│       └── template.py              # Code templates
├── tests/
│   ├── test_cobol_parser.py
│   ├── test_pipeline.py
│   ├── test_callgraph.py            # NEW
│   ├── test_copybook_resolution.py  # NEW
│   ├── test_dataflow.py             # NEW
│   ├── test_equivalence.py          # NEW (semantic equivalence)
│   └── fixtures/
│       ├── phase2/                  # Test fixtures for Phase 2
│       └── phase2_coupled/          # Coupled programs with CALL/COPY
├── examples/
│   ├── sample.cbl                   # Simple sample
│   ├── inventory.cbl
│   └── payroll.cbl
├── migration-output/                # Generated batch output (gitignored)
├── pyproject.toml
├── .env.example
└── README.md
```

---

## Phase 2 Features Deep Dive

### 1. Copybook Resolution (`src/cobol/copybook.py`)
- Parses `COPY copybook-name` statements
- Resolves paths via search paths (COPYLIB, SYSLIB, custom dirs)
- Handles nested COPY statements
- Inlines copybook content into extracted sections

### 2. CALL Graph Extraction (`src/cobol/callgraph.py`)
- Extracts `CALL "PROGRAM-NAME" USING ...` statements
- Handles static calls (literal program names)
- Extracts USING parameters for contract generation
- Builds directed graph of program dependencies

### 3. Shared File Analysis (`src/cobol/dataflow.py`)
- Parses FILE SECTION FD/SD definitions
- Maps SELECT ... ASSIGN TO clauses to physical datasets
- Identifies programs sharing the same file
- Tracks access modes (INPUT, OUTPUT, I-O, EXTEND)

### 4. System Dependency Graph (`src/pipeline/system_graph.py`)
Unified graph with:
- **Nodes**: Programs, Copybooks, Files
- **Edges**: CALL, COPY, SHARED_FILE
- **Evidence tracking**: Source file, line numbers, context
- **Export**: JSON, Neo4j Cypher, Mermaid diagrams

```bash
# Generate graph visualization
python -m src.pipeline.runner graph tests/fixtures/phase2_coupled \
  -o ./graph.json --format mermaid

# Output includes:
# - graph.json (machine-readable)
# - graph.mmd (Mermaid diagram)
# - graph.cypher (Neo4j import)
```

### 5. Migration Planner (`src/pipeline/planner.py`)
Analyzes coupling and recommends groups:

```python
# Strategies:
# - INDEPENDENT: One service per program (max isolation)
# - GROUPED: Coupled programs together (shared data + calls)
# - HYBRID: Business capability groups
```

Output: `migration-plan.json` with:
- Program groups with rationale
- Shared copybooks per group
- Shared files per group
- Internal CALL relationships
- API contracts between services
- Unresolved dependencies (flagged for review)

### 6. Batch Pipeline Orchestrator (`src/pipeline/batch_runner.py`)
- Executes Phase 1 pipeline per migration group
- Generates shared models from shared copybooks
- Creates service contracts (OpenAPI + client stubs)
- Per-group isolation with hash-based resume
- Syntax validation of all generated code

### 7. Service Contracts (NEW)
For each CALL relationship, generates:
- **OpenAPI 3.0 spec** - Machine-readable API contract
- **Python client stub** - Async + sync httpx clients
- **Markdown documentation** - Human-readable contract

```
contracts/
├── SUMMARY.md                    # Overview of all contracts
├── combined_openapi.json         # Unified OpenAPI for all services
├── CUSTOMER-MAIN_to_VALIDATE-CUST.md
├── CUSTOMER-MAIN_to_VALIDATE-CUST_openapi.json
├── CUSTOMER-MAIN_to_VALIDATE-CUST_client.py
└── ...
```

---

## CLI Commands Reference

```bash
# Phase 1: Single file
cobol2fastapi migrate input.cbl -o ./output
cobol2fastapi preview input.cbl
cobol2fastapi test-gemini -m gemini-2.0-flash-exp -p "Hello"

# Phase 2: Batch processing
cobol2fastapi graph ./cobol-src -o ./graph.json --format json
cobol2fastapi graph ./cobol-src -o ./graph.mmd --format mermaid
cobol2fastapi graph ./cobol-src -o ./graph.cypher --format cypher

cobol2fastapi plan ./cobol-src -o ./plan.json --strategy grouped
cobol2fastapi plan ./cobol-src -o ./plan.json --strategy independent
cobol2fastapi plan ./cobol-src -o ./plan.json --strategy hybrid

cobol2fastapi batch ./cobol-src -o ./output \
  --copybook-dirs ./copybooks \
  --strategy grouped \
  --max-group-size 5 \
  --fresh              # Force fresh run (ignore intermediates)
```

### Model Overrides (per-agent)
```bash
cobol2fastapi migrate input.cbl -o ./output \
  --analyst-model gemini-2.0-flash-exp \
  --architect-model gemini-2.0-flash-exp \
  --developer-model gemini-2.0-flash-exp \
  --analyst-temp 0.1 \
  --architect-temp 0.1 \
  --developer-temp 0.1
```

---

## Generated Output Structure

### Phase 1 (Single Program)
```
output/
├── main.py              # FastAPI app entry point
├── models.py            # Pydantic models
├── services.py          # Business logic layer
├── routes.py            # API routes
├── requirements.txt     # Dependencies
├── README.md            # API documentation
└── intermediates/       # Debug: agent outputs
    ├── 01_extracted_sections.json
    ├── 02_business_rules.json
    ├── 03_pydantic_schema.json
    └── 04_fastapi_output.json
```

### Phase 2 (Batch Migration)
```
migration-output/
├── migration-plan.json           # Migration plan with groups
├── migration_report.json         # Execution report
├── contracts/                    # Service contracts
│   ├── SUMMARY.md
│   ├── combined_openapi.json
│   └── *_to_*.md / _openapi.json / _client.py
├── shared/                       # Shared models (from shared copybooks)
│   ├── __init__.py
│   └── customer_rec.py
├── group-0/                      # Service group 1
│   ├── main.py
│   ├── models.py
│   ├── services.py
│   ├── routes.py
│   ├── requirements.txt
│   ├── README.md
│   └── intermediates/            # Per-program intermediates
│       ├── CUSTOMER-MAIN/
│       ├── LOOKUP-CUST/
│       └── VALIDATE-CUST/
└── group-1/                      # Service group 2 (independent)
    └── ...
```

---

## Complete Batch Migration Flow (Phase 2) — Low-Level Step-by-Step

### Command
```bash
python -m src.pipeline.runner batch ./cobol-src \
  --copybook-dirs ./copybooks \
  --strategy grouped \
  -o ./migration-output
```

---

### Step 1: Discover Programs (`src/cobol/discovery.py`)
- Scans source directory for `.cbl`, `.cob`, `.cobol` files
- Extracts `PROGRAM-ID` from each file using regex
- Returns inventory: `[{program_id, path, size, mtime}, ...]`

---

### Step 2: Read All Source Code
```python
program_sources = {}
for prog in programs:
    program_sources[prog.program_id] = Path(prog.path).read_text()
```
Result: `{program_name: source_text, ...}`

---

### Step 3: Build Dependency Graph (`build_system_graph()` in `system_graph.py`)

**For EACH program, extract 7 types of dependencies:**

| Dependency | Source Section | Extractor Function |
|------------|----------------|-------------------|
| **Sections** | Full source | `extract_cobol_sections_with_copybooks()` (inlines COPY) |
| **CALLs** | PROCEDURE DIVISION | `extract_calls()` → target, using_params, is_dynamic, paragraph, line |
| **COPYs** | Original source | `extract_copy_statements()` → copy_name, replacing, line |
| **Files** | FILE SECTION + ENV | `extract_file_definitions()` + `extract_select_assign_from_env()` |
| **File Ops** | PROCEDURE DIVISION | `extract_file_operations()` → OPEN/READ/WRITE/REWRITE/DELETE/START/CLOSE/UNLOCK |
| **SQL** | Full source | `extract_sql_tables()` → table_name, operation (SELECT/INSERT/UPDATE/DELETE) |
| **CICS** | Full source | `extract_cics_calls()` → LINK/XCTL/SEND/RECEIVE targets |

**Graph Nodes Created:**
| Node Type | Fields |
|-----------|--------|
| `ProgramNode` | name, program_id, calls[], copies[], files[], unresolved_dynamic_calls[] |
| `CopybookNode` | name, used_by[] |
| `FileNode` | assign_name, fd_names[], used_by[], organization, access_mode, record_key |

**Graph Edges Created (18 types):**
| Edge Type | Source → Target | Trigger |
|-----------|-----------------|---------|
| `CALL` | Program → Program | Static `CALL "PROG"` |
| `DYNAMIC_CALL` | Program → Program | `CALL variable` |
| `COPY` | Program → Copybook | `COPY copybook` |
| `SHARED_FILE` | Program → File | File used by >1 program |
| `USES_FILE` | Program → File | File used by 1 program |
| `SQL_TABLE` | Program → Table | `EXEC SQL` |
| `CICS_LINK` | Program → Program | `EXEC CICS LINK` |
| `CICS_XCTL` | Program → Program | `EXEC CICS XCTL` |
| `CICS_SEND` | Program → Map | `EXEC CICS SEND MAP` |
| `CICS_RECEIVE` | Program → Map | `EXEC CICS RECEIVE MAP` |
| `FILE_OPEN/READ/WRITE/REWRITE/DELETE/START/CLOSE/UNLOCK` | Program → File | COBOL file verbs |

**Metadata Computed:**
- Entry points (programs not called by anyone)
- Leaf programs (programs that call no one)
- Circular CALL dependencies (DFS cycle detection)

**Exports:** `graph.json`, `graph.mmd` (Mermaid), `graph.cypher` (Neo4j)

---

### Step 4: Create Migration Plan (`create_migration_plan()` in `planner.py`)

**Coupling Analysis (per program):**
```python
call_score    = (calls + called_by) * 2.0
copy_score    = shared_copybooks * 1.5
file_score    = shared_files * 2.0
total_score   = call_score + copy_score + file_score
```

**Grouping by Strategy:**

| Strategy | Algorithm |
|----------|-----------|
| `INDEPENDENT` | 1 group per program |
| `GROUPED` | Connected components via `CALL` + `SHARED_FILE` edges (DFS) |
| `HYBRID` | Connected components; if internal_coupling > 10 AND size ≤ max_group_size → keep together, else split |

**Per Group Computed:**
- `shared_copybooks` (copybook.used_by > 1)
- `shared_files` (file.used_by > 1)
- `internal_calls` (CALL within group)
- `external_calls` (CALL crossing group boundary)
- `external_file_access` (file used outside group)

**Generated Artifacts:**
- `SharedModel` — Copybooks used by >1 group
- `ServiceContract` — CALL edges crossing group boundary (POST endpoint, request/response models)
- `unresolved` — Dynamic CALLs, missing copybooks, circular dependencies

**Output:** `migration-plan.json`

---

### Step 5: Batch Migration (`run_batch_migration_with_resume()` in `batch_runner.py`)

**For EACH group:**
```
group_dir = output/group-N/
```
- Filters `service_contracts` relevant to this group's programs
- **For EACH program in group:**
  1. Computes SHA256 hash of COBOL source (16 chars)
  2. Checks `intermediates/agent_<hash>.json` — **resumes** if exists
  3. Runs **3-agent pipeline** (Analyst → Architect → Developer) with `service_contracts` in config
  4. Saves output to `group_dir/`
  5. Validates syntax (`python -m py_compile`)

---

### Step 6: Generate Shared Models (`generate_shared_models_code()`)

**For each shared copybook (used by >1 group):**
1. Combines copybook source text
2. Runs mini-Architect pipeline on it
3. Saves Pydantic model to `output/shared/<model>.py`
4. Creates `shared/__init__.py` with exports

---

### Step 7: Generate Service Contracts (`generate_service_contracts_code()`)

**For each ServiceContract (cross-group CALL):**
| File | Purpose |
|------|---------|
| `contracts/SOURCE_to_TARGET.md` | Human-readable Markdown docs |
| `contracts/SOURCE_to_TARGET_openapi.json` | OpenAPI 3.0 spec |
| `contracts/SOURCE_to_TARGET_client.py` | Async + Sync httpx client stubs |
| `contracts/combined_openapi.json` | Unified spec for all services |
| `contracts/SUMMARY.md` | Index of all contracts |

---

### Step 8: Final Validation & Report
- Runs `py_compile` on all generated `.py` files
- Saves `migration_report.json` with per-program status
- Prints summary table

---

### Complete Data Flow Diagram

```
┌─────────────┐
│  .cbl files │
└──────┬──────┘
       │
       ▼
┌─────────────────────┐
│  Discover Programs  │  →  program_sources = {name: text}
└────────┬────────────┘
         │
         ▼
┌─────────────────────┐
│  Build Dependency   │  →  DependencyGraph
│  Graph              │     (ProgramNode, CopybookNode, FileNode,
│  (18 edge types)    │      CALL/COPY/SHARED_FILE/SQL/CICS/FILE_* edges)
└────────┬────────────┘
         │
         ▼
┌─────────────────────┐
│  Create Migration   │  →  MigrationPlan
│  Plan               │     (groups[], shared_models[], service_contracts[],
│  (3 strategies)     │      unresolved[])
└────────┬────────────┘
         │
         ▼
┌─────────────────────┐
│  Batch Migration    │  →  Per-group FastAPI services
│  (3-agent pipeline │     group-0/, group-1/, ...
│   per program)      │
│  + resume via hash  │
└────────┬────────────┘
         │
         ▼
┌─────────────────────┐
│  Generate Shared    │  →  shared/*.py (from shared copybooks)
│  Models             │
└────────┬────────────┘
         │
         ▼
┌─────────────────────┐
│  Generate Contracts │  →  contracts/*.md, *_openapi.json, *_client.py
│  (cross-group CALL) │
└────────┬────────────┘
         │
         ▼
┌─────────────────────┐
│  Validate & Report  │  →  migration_report.json
└─────────────────────┘
```

---

### Example: phase2_coupled Migration

The test fixture `tests/fixtures/phase2_coupled/` contains:

| Program | Description | Dependencies |
|---------|-------------|--------------|
| `CUSTOMER-MAIN.cbl` | Main entry point | CALLs LOOKUP-CUST, VALIDATE-CUST; COPY CUSTOMER-REC; FILE CUSTMAST |
| `LOOKUP-CUST.cbl` | Customer lookup | COPY CUSTOMER-REC; FILE CUSTMAST |
| `VALIDATE-CUST.cbl` | Customer validation | COPY CUSTOMER-REC |
| `REPORT-MAIN.cbl` | Report generation | Independent (no shared deps) |
| `CUSTOMER-REC.cpy` | Shared record layout | Used by 3 programs |
| `TRANSACTION-REC.cpy` | Transaction record | Used by REPORT-MAIN |

**Migration Plan Output (grouped strategy):**
- **group-0**: CUSTOMER-MAIN + LOOKUP-CUST + VALIDATE-CUST (shared CUSTOMER-REC, CUSTMAST)
- **group-1**: REPORT-MAIN (independent)

**Generated APIs:**
- `group-0`: Customer Management API (validation, CRUD, lookup)
- `group-1`: Report Generation API (summary, detail, working storage)

---

## Testing

```bash
# All tests
pytest

# Phase 1 tests
pytest tests/test_cobol_parser.py tests/test_pipeline.py -v

# Phase 2 tests
pytest tests/test_callgraph.py tests/test_copybook_resolution.py tests/test_dataflow.py -v

# With coverage
pytest --cov=src

# Run semantic equivalence tests (requires COBOL simulator)
pytest tests/test_equivalence.py -v
```

### Code Quality
```bash
# Lint
ruff check src/

# Format
ruff format src/

# Type check
mypy src/
```

---

## Pipeline Implementation Details

### Agent 1: Analyst Prompt
Extracts:
- All data fields with full metadata (level, picture, usage, value, occurs, redefines, parent, children)
- 88-level condition names with value mappings
- Business rules from each paragraph (type, conditions, actions, variables)
- I/O operations (DISPLAY, ACCEPT, READ, WRITE, OPEN, CLOSE)
- Paragraph inventory

### Agent 2: Architect Prompt
Generates:
- Pydantic models preserving COBOL hierarchy (01-level → class)
- Enums for 88-level conditions
- Proper type mapping (PIC 9→int, PIC 9V99→Decimal, PIC X→str, COMP→int, COMP-3→Decimal)
- List[T] for OCCURS
- Union/validation for REDEFINES
- Field descriptions from COBOL context

### Agent 3: Developer Prompt
Generates:
- `main.py` - FastAPI app with lifespan, CORS, health check, exception handling
- `models.py` - Pydantic models (copied from Architect + request/response wrappers)
- `services.py` - Service layer with DI, CRUD, business methods (paragraph→method)
- `routes.py` - RESTful endpoints with validation, pagination, proper HTTP codes
- `requirements.txt` - Pinned dependencies
- `README.md` - API documentation with examples

### Hash-Based Resume
Each program's COBOL source is hashed (SHA256, 16 chars). Intermediate outputs keyed by hash:
```
intermediates/
├── analyst_<hash>.json      # Business rules
├── architect_<hash>.json    # Pydantic schema
└── developer_<hash>.json    # FastAPI output
```
Re-running with same source skips completed stages automatically.

---

## Extending the Pipeline

### Add New COBOL Constructs
1. Update `src/cobol/extractor.py` to extract new sections
2. Update `src/cobol/parser.py` to parse new constructs
3. Update `src/pipeline/prompts.py` Analyst prompt to recognize new patterns
4. Update Architect prompt to generate appropriate Pydantic code

### Customize FastAPI Output
Modify templates in `src/fastapi/template.py` or update the Developer prompt.

### Add New LLM Provider
The pipeline uses LangChain's `ChatGoogleGenerativeAI`. To use another provider:

```python
# In chain.py get_llm()
from langchain_openai import ChatOpenAI
# or
from langchain_anthropic import ChatAnthropic
# or
from langchain_groq import ChatGroq
```

---

## Dependencies

```toml
[project]
dependencies = [
    "langchain>=0.3.0",
    "langchain-google-genai>=2.0",     # Gemini support
    "pydantic>=2.0",
    "python-dotenv",
    "typer",
    "rich",
    "networkx>=3.0",                    # Dependency graphs
    "pyyaml>=6.0",                      # Migration plans
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0",
    "pytest-asyncio>=0.23",
    "ruff>=0.5",
    "mypy>=1.10",
    "httpx>=0.27",                      # Client stubs
]
```

---

## Example Generated API

### Group-0: Customer Service (from phase2_coupled)

**POST /api/v1/customers/validate**
```json
{
  "cust_id": 1001,
  "cust_name": "John Doe",
  "cust_balance": "1500.50",
  "cust_status": "A"
}
```
Response:
```json
{
  "is_valid": true,
  "error_msg": "",
  "error_code": 0
}
```

**POST /api/v1/customers/** - Create customer (runs validation first)
**GET /api/v1/customers/** - List with pagination
**GET /api/v1/customers/{id}** - Get by ID
**PUT /api/v1/customers/{id}** - Update with re-validation
**DELETE /api/v1/customers/{id}** - Delete

### Group-1: Report Service

**POST /reports/run-main** - Execute MAIN-PARA workflow
**GET /reports** - List generated reports
**GET /working-storage** - Current WS-RPT-STATUS, WS-REPORT-COUNTER

---

## License

MIT

---

## Roadmap

### Phase 3 (Future)
- [ ] Semantic equivalence testing (COBOL simulator ↔ FastAPI)
- [ ] CICS/BMS screen mapping to React/Vue frontends
- [ ] Embedded SQL → SQLAlchemy models
- [ ] Dynamic CALL resolution
- [ ] COPY REPLACING support
- [ ] Performance optimization (parallel batch execution)
- [ ] Web UI for migration management

### Parser Upgrade Path (Post-MVP)
Current implementation uses **regex-based parsing** which handles ~80% of typical COBOL. For production use, consider:
- **ANTLR4 COBOL grammar** - Full AST, handles all edge cases
- **Tree-sitter COBOL** - Incremental parsing, IDE integration
- **Custom parser combinators** - Tailored to your COBOL dialect

The regex approach is sufficient for migration planning and initial code generation. Parser upgrades can be swapped in `src/cobol/extractor.py` without changing the agent pipeline.