"""Custom output parsers for the migration pipeline."""

import json
import re
from typing import Any, Dict, Optional
from langchain_core.output_parsers import BaseOutputParser
from langchain_core.exceptions import OutputParserException

from .models import BusinessRules, PydanticSchema, FastAPIOutput


class RobustJsonOutputParser(BaseOutputParser[Dict[str, Any]]):
    """JSON parser that handles common LLM output issues."""

    def parse(self, text: str) -> Dict[str, Any]:
        # Try direct JSON parse first
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

        # Try to extract JSON from markdown code blocks
        json_block_match = re.search(
            r'```(?:json)?\s*(\{.*?\})\s*```',
            text,
            re.DOTALL
        )
        if json_block_match:
            try:
                return json.loads(json_block_match.group(1))
            except json.JSONDecodeError:
                pass

        # Try to find JSON object in text
        json_match = re.search(r'(\{.*\})', text, re.DOTALL)
        if json_match:
            try:
                return json.loads(json_match.group(1))
            except json.JSONDecodeError:
                pass

        raise OutputParserException(f"Could not parse JSON from output: {text[:500]}")


class BusinessRulesParser(RobustJsonOutputParser):
    """Parser for Agent 1 (Analyst) output."""

    def parse(self, text: str) -> BusinessRules:
        data = super().parse(text)
        return BusinessRules(**data)


class PydanticSchemaParser(RobustJsonOutputParser):
    """Parser for Agent 2 (Architect) output."""

    def parse(self, text: str) -> PydanticSchema:
        data = super().parse(text)
        return PydanticSchema(**data)


class FastAPIOutputParser(RobustJsonOutputParser):
    """Parser for Agent 3 (Developer) output."""

    def parse(self, text: str) -> FastAPIOutput:
        data = super().parse(text)
        return FastAPIOutput(**data)


# =============================================================================
# Python Code Parsers (for Architect/Developer raw code output)
# =============================================================================

def parse_pydantic_schema(text: str) -> PydanticSchema:
    """
    Parse Architect output which may be raw Python code instead of JSON.
    Extracts model definitions from Python source.
    """
    # Try JSON first
    try:
        parser = PydanticSchemaParser()
        return parser.parse(text)
    except OutputParserException:
        pass

    # Fallback: parse raw Python code
    models = []
    enums = []
    imports = [
        "from pydantic import BaseModel, Field",
        "from decimal import Decimal",
        "from typing import Optional, List",
        "from enum import Enum",
    ]

    # Extract class definitions
    class_pattern = r'class\s+(\w+)\s*\(([^)]+)\):'
    for match in re.finditer(class_pattern, text):
        class_name = match.group(1)
        base_classes = match.group(2).strip()

        # Get class body
        start = match.end()
        # Find next class or end of file
        next_class = re.search(r'\nclass\s+\w+', text[start:])
        end = start + next_class.start() if next_class else len(text)
        class_body = text[start:end]

        if 'Enum' in base_classes:
            # Parse enum
            values = {}
            for line in class_body.split('\n'):
                line = line.strip()
                if '=' in line and not line.startswith('#'):
                    parts = line.split('=', 1)
                    if len(parts) == 2:
                        values[parts[0].strip()] = parts[1].strip().strip('\'"')

            enums.append({
                "name": class_name,
                "values": values,
                "docstring": extract_docstring(class_body)
            })
        elif 'BaseModel' in base_classes:
            # Parse Pydantic model
            fields = []
            for line in class_body.split('\n'):
                line = line.strip()
                if ':' in line and not line.startswith('#') and not line.startswith('def '):
                    # Field definition: name: type = Field(...)
                    parts = line.split(':', 1)
                    if len(parts) == 2:
                        field_name = parts[0].strip()
                        rest = parts[1].strip()

                        # Extract type and default
                        field_type = "Any"
                        field_default = None

                        if '=' in rest:
                            type_part, default_part = rest.split('=', 1)
                            field_type = type_part.strip()
                            field_default = default_part.strip()
                        else:
                            field_type = rest

                        fields.append({
                            "name": field_name,
                            "type": field_type,
                            "default": field_default,
                            "description": ""
                        })

            models.append({
                "name": class_name,
                "fields": fields,
                "config": {},
                "docstring": extract_docstring(class_body)
            })

    return PydanticSchema(models=models, enums=enums, imports=imports)


def parse_fastapi_output(text: str) -> FastAPIOutput:
    """
    Parse Developer output which may be raw Python code files.
    """
    # Try JSON first
    try:
        parser = FastAPIOutputParser()
        return parser.parse(text)
    except OutputParserException:
        pass

    # Fallback: try to extract files from markdown code blocks
    files = {
        "main_py": "",
        "models_py": "",
        "services_py": "",
        "routes_py": "",
        "requirements_txt": "fastapi>=0.100\nuvicorn>=0.23\npydantic>=2.0\npython-dotenv>=1.0",
        "readme_md": ""
    }

    # Pattern for markdown code blocks with file names
    pattern = r'```(?:python)?\s*(?:#\s*(\S+\.py))?\n(.*?)\n```'
    for match in re.finditer(pattern, text, re.DOTALL):
        filename = match.group(1)
        content = match.group(2)

        if filename:
            fname = filename.lower()
            if 'main' in fname:
                files["main_py"] = content
            elif 'model' in fname:
                files["models_py"] = content
            elif 'service' in fname:
                files["services_py"] = content
            elif 'route' in fname or 'api' in fname:
                files["routes_py"] = content
            elif 'requirements' in fname:
                files["requirements_txt"] = content
            elif 'readme' in fname:
                files["readme_md"] = content

    # If no files found, put everything in main_py
    if not any(files.values()):
        files["main_py"] = text

    return FastAPIOutput(**files)


def extract_docstring(text: str) -> str:
    """Extract docstring from class body."""
    match = re.search(r'"""(.*?)"""', text, re.DOTALL)
    if match:
        return match.group(1).strip()
    match = re.search(r"'''(.*?)'''", text, re.DOTALL)
    if match:
        return match.group(1).strip()
    return ""


# =============================================================================
# Utility functions
# =============================================================================

def parse_business_rules(text: str) -> BusinessRules:
    """Parse Analyst output to BusinessRules."""
    parser = BusinessRulesParser()
    return parser.parse(text)


def save_intermediate_output(output_dir: str, stage: str, content: str) -> None:
    """Save intermediate output for debugging."""
    import os
    from datetime import datetime

    os.makedirs(output_dir, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"{stage}_{timestamp}.json"

    # Try to pretty-print JSON
    try:
        parsed = json.loads(content)
        content = json.dumps(parsed, indent=2)
    except json.JSONDecodeError:
        pass

    filepath = os.path.join(output_dir, filename)
    with open(filepath, 'w') as f:
        f.write(content)