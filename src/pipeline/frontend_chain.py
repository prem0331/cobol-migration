"""Agent 4: Frontend Generator - OpenAPI Spec to HTML/CSS/JS Application."""

import os
import json
from typing import Dict, Any, Optional, List
from langchain_core.runnables import RunnableLambda
from langchain_google_genai import ChatGoogleGenerativeAI

from .models import FrontendOutput, ServiceContract
from .frontend_prompts import FRONTEND_PROMPT
from .parsers import save_intermediate_output, RobustJsonOutputParser


def get_llm_for_frontend(
    model: Optional[str] = None,
    temperature: Optional[float] = None,
    max_tokens: Optional[int] = None,
) -> ChatGoogleGenerativeAI:
    """Create Gemini LLM instance configured for Frontend Generator (Agent 4)."""
    return ChatGoogleGenerativeAI(
        model=model or os.getenv("GEMINI_FRONTEND_MODEL", "gemini-flash-lite-latest"),
        temperature=temperature or float(os.getenv("GEMINI_FRONTEND_TEMPERATURE", "0.1")),
        max_output_tokens=max_tokens or int(os.getenv("GEMINI_FRONTEND_MAX_TOKENS", "32768")),
        google_api_key=os.getenv("GEMINI_API_KEY"),
    )


def load_openapi_spec(service_dirs: List[str]) -> Dict[str, Any]:
    """Load and merge OpenAPI specs from multiple service directories."""
    merged_spec = {
        "openapi": "3.1.0",
        "info": {
            "title": "Migrated COBOL Services API",
            "version": "1.0.0"
        },
        "paths": {},
        "components": {
            "schemas": {}
        },
        "tags": []
    }

    seen_schemas = set()
    seen_tags = set()

    for i, service_dir in enumerate(service_dirs):
        main_loaded = False
        # Try to load from main.py by importing and calling app.openapi()
        main_py_path = os.path.join(service_dir, "main.py")
        if os.path.exists(main_py_path):
            try:
                import sys
                import importlib.util

                # Add service_dir to sys.path so imports work
                if service_dir not in sys.path:
                    sys.path.insert(0, service_dir)

                # Clear any previously cached modules that this service might import
                # This prevents cross-contamination between services
                modules_to_clear = ['routes', 'models', 'services']
                for mod in modules_to_clear:
                    if mod in sys.modules:
                        del sys.modules[mod]

                # Use unique module name to avoid caching conflicts between services
                module_name = f"main_service_{i}"
                spec = importlib.util.spec_from_file_location(module_name, main_py_path)
                module = importlib.util.module_from_spec(spec)
                sys.modules[module_name] = module
                spec.loader.exec_module(module)

                if hasattr(module, 'app'):
                    openapi = module.app.openapi()

                    # Merge paths
                    for path, methods in openapi.get("paths", {}).items():
                        # Don't overwrite if already exists (from another service)
                        if path not in merged_spec["paths"]:
                            merged_spec["paths"][path] = methods

                    # Merge schemas
                    for name, schema in openapi.get("components", {}).get("schemas", {}).items():
                        if name not in seen_schemas:
                            merged_spec["components"]["schemas"][name] = schema
                            seen_schemas.add(name)

                    # Merge tags
                    for tag in openapi.get("tags", []):
                        tag_name = tag.get("name", "")
                        if tag_name not in seen_tags:
                            merged_spec["tags"].append(tag)
                            seen_tags.add(tag_name)

                    main_loaded = True
            except Exception as e:
                print(f"Warning: Could not load OpenAPI from {service_dir}: {e}")

        # Fallback: parse routes.py directly to extract endpoints and tags ONLY if main.py failed
        if not main_loaded:
            routes_py_path = os.path.join(service_dir, "routes.py")
            if os.path.exists(routes_py_path):
                print(f"  Parsing routes.py from {service_dir} (fallback)")
                _parse_routes_py_for_openapi(routes_py_path, merged_spec, seen_schemas, seen_tags)

    # If no tags found, infer from path prefixes
    if not merged_spec["tags"]:
        _infer_tags_from_paths(merged_spec)

    return merged_spec


def _parse_routes_py_for_openapi(routes_py_path: str, merged_spec: Dict, seen_schemas: set, seen_tags: set):
    """Parse routes.py to extract endpoints, tags, and schemas."""
    import re

    try:
        content = open(routes_py_path).read()

        # Extract router tags
        router_tags_match = re.search(r'APIRouter\([^)]*tags=\[["\']([^"\']+)["\']', content)
        router_tag = router_tags_match.group(1) if router_tags_match else None

        # Extract prefix
        prefix_match = re.search(r'APIRouter\([^)]*prefix=["\']([^"\']+)["\']', content)
        prefix = prefix_match.group(1) if prefix_match else ""

        # Extract endpoints with metadata
        # Pattern: @router.method("/path", ..., summary="...", description="...")
        pattern = r'@router\.(get|post|put|delete|patch)\s*\(\s*["\']([^"\']+)["\']([^)]*?summary=["\']([^"\']*)["\'])?(?:[^)]*?description=["\']([^"\']*)["\'])?'
        matches = re.findall(pattern, content, re.DOTALL)

        # Add router tag if found
        if router_tag and router_tag not in seen_tags:
            merged_spec["tags"].append({"name": router_tag, "description": f"Endpoints for {router_tag}"})
            seen_tags.add(router_tag)

        for method, path, summary_raw, summary_val, description in matches:
            full_path = prefix + path
            summary_clean = summary_val if summary_val else ""
            description_clean = description if description else ""

            # Only add if path doesn't already exist (avoid duplicates from main.py)
            if full_path not in merged_spec["paths"]:
                merged_spec["paths"][full_path] = {}

            # Only add method if not already present
            if method.lower() not in merged_spec["paths"][full_path]:
                merged_spec["paths"][full_path][method.lower()] = {
                    "summary": summary_clean,
                    "description": description_clean,
                    "tags": [router_tag] if router_tag else [],
                    "responses": {
                        "200": {"description": "Successful response"}
                    }
                }

    except Exception as e:
        print(f"  Warning: Could not parse {routes_py_path}: {e}")


def _infer_tags_from_paths(merged_spec: Dict):
    """Infer tags from path prefixes when no explicit tags exist."""
    seen = set()
    for path in merged_spec["paths"]:
        # Extract first meaningful path segment
        parts = [p for p in path.split("/") if p and p not in ["api", "v1"]]
        if parts:
            tag = parts[0].replace("-", " ").title()
            if tag not in seen:
                merged_spec["tags"].append({"name": tag, "description": f"Endpoints for {tag}"})
                seen.add(tag)


def load_service_contracts(contracts_dir: str) -> List[ServiceContract]:
    """Load service contracts from migration output."""
    contracts = []
    contracts_file = os.path.join(contracts_dir, "service_contracts.json")
    if os.path.exists(contracts_file):
        try:
            with open(contracts_file, 'r') as f:
                data = json.load(f)
            for item in data:
                contracts.append(ServiceContract(**item))
        except Exception:
            pass
    return contracts


def load_migration_plan(plan_file: str) -> Dict[str, Any]:
    """Load migration plan for grouping context."""
    if os.path.exists(plan_file):
        try:
            with open(plan_file, 'r') as f:
                return json.load(f)
        except Exception:
            pass
    return {}


class FrontendOutputParser(RobustJsonOutputParser):
    """Parser for Agent 4 (Frontend Generator) output."""

    def parse(self, text: str) -> FrontendOutput:
        data = super().parse(text)

        # Handle both formats: flat structure (expected) or files array/object (what LLM sometimes produces)
        if "files" in data:
            files = data["files"]
            flat_data = {}

            # Handle files as array: [{"path": "...", "content": "..."}, ...]
            if isinstance(files, list):
                for file_entry in files:
                    if isinstance(file_entry, dict) and "path" in file_entry and "content" in file_entry:
                        path = file_entry["path"]
                        content = file_entry["content"]
                        field_name = self._path_to_field(path)
                        if field_name:
                            flat_data[field_name] = content

            # Handle files as object: {"index.html": "...", "style.css": "..."}
            elif isinstance(files, dict):
                for path, content in files.items():
                    field_name = self._path_to_field(path)
                    if field_name:
                        flat_data[field_name] = content

            if flat_data:
                return FrontendOutput(**flat_data)

        return FrontendOutput(**data)

    def _path_to_field(self, path: str) -> Optional[str]:
        """Map file path to FrontendOutput field name."""
        path = path.lower().replace("\\", "/")

        if path == "index.html":
            return "index_html"
        elif path == "style.css":
            return "style_css"
        elif path == "app.js":
            return "app_js"
        elif path == "api-client.js":
            return "api_client_js"
        elif path == "readme.md":
            return "readme_md"

        return None


def create_frontend_chain(
    output_dir: Optional[str] = None,
    model: Optional[str] = None,
    temperature: Optional[float] = None,
    max_tokens: Optional[int] = None,
):
    """Create Agent 4 chain: OpenAPI Spec + Contracts -> FrontendOutput."""
    llm = get_llm_for_frontend(model, temperature, max_tokens)

    parser = FrontendOutputParser()

    def prepare_frontend_input(inputs: Dict[str, Any]) -> Dict[str, Any]:
        """Prepare OpenAPI spec and contracts for frontend prompt."""
        service_dirs = inputs.get("service_dirs", [])
        contracts_dir = inputs.get("contracts_dir", "")
        plan_file = inputs.get("plan_file", "")

        # Load and merge OpenAPI specs
        openapi_spec = load_openapi_spec(service_dirs)

        # Load service contracts
        contracts = load_service_contracts(contracts_dir)
        contracts_json = json.dumps([c.model_dump() for c in contracts], indent=2)

        # Load migration plan
        migration_plan = load_migration_plan(plan_file)

        # Extract program names from schemas
        program_names = list(openapi_spec.get("components", {}).get("schemas", {}).keys())

        return {
            "openapi_spec_json": json.dumps(openapi_spec, indent=2),
            "service_contracts_json": contracts_json,
            "migration_plan_json": json.dumps(migration_plan, indent=2),
            "program_names": ", ".join(program_names),
        }

    def save_frontend_output(output: FrontendOutput) -> FrontendOutput:
        """Save intermediate frontend output."""
        if output_dir:
            save_intermediate_output(output_dir, "05_frontend_output", output.model_dump_json(indent=2))
        return output

    chain = (
        RunnableLambda(prepare_frontend_input)
        | FRONTEND_PROMPT
        | llm
        | parser
        | RunnableLambda(save_frontend_output)
    )

    return chain


def run_frontend_generation(
    service_dirs: List[str],
    output_dir: str,
    contracts_dir: Optional[str] = None,
    plan_file: Optional[str] = None,
    model: Optional[str] = None,
    temperature: Optional[float] = None,
    max_tokens: Optional[int] = None,
) -> FrontendOutput:
    """Run the frontend generation pipeline."""
    chain = create_frontend_chain(
        output_dir=output_dir,
        model=model,
        temperature=temperature,
        max_tokens=max_tokens,
    )

    inputs = {
        "service_dirs": service_dirs,
        "contracts_dir": contracts_dir or os.path.join(os.path.dirname(service_dirs[0]), "..", "contracts") if service_dirs else "",
        "plan_file": plan_file or os.path.join(os.path.dirname(service_dirs[0]), "..", "migration-plan.json") if service_dirs else "",
    }

    return chain.invoke(inputs)


def write_frontend_files(output_dir: str, frontend_output: FrontendOutput) -> None:
    """Write generated frontend files to output directory."""
    import os
    from pathlib import Path

    out_path = Path(output_dir)
    out_path.mkdir(parents=True, exist_ok=True)

    # Root files
    root_files = {
        "index.html": frontend_output.index_html,
        "style.css": frontend_output.style_css,
        "app.js": frontend_output.app_js,
        "api-client.js": frontend_output.api_client_js,
    }

    for filename, content in root_files.items():
        if content.strip():
            (out_path / filename).write_text(content, encoding="utf-8")

    # README
    if frontend_output.readme_md.strip():
        (out_path / "README.md").write_text(frontend_output.readme_md, encoding="utf-8")