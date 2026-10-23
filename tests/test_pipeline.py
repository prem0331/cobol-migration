"""Integration tests for the migration pipeline."""

import pytest
import os
from pathlib import Path
from src.cobol.extractor import extract_cobol_sections
from src.cobol.parser import parse_cobol_file
from src.pipeline.models import BusinessRules, PydanticSchema, FastAPIOutput
from src.pipeline.parsers import parse_business_rules, parse_pydantic_schema, parse_fastapi_output


# Test data
SAMPLE_BUSINESS_RULES_JSON = """
{
    "program_name": "CUSTINQ",
    "data_definitions": [
        {
            "name": "CUSTOMER-RECORD",
            "level": 1,
            "picture": null,
            "usage": null,
            "value": null,
            "occurs": null,
            "redefines": null,
            "parent": null,
            "children": [
                {
                    "name": "CUST-ID",
                    "level": 5,
                    "picture": "9(6)",
                    "usage": null,
                    "value": null,
                    "occurs": null,
                    "redefines": null,
                    "parent": "CUSTOMER-RECORD",
                    "children": [],
                    "condition_names": []
                },
                {
                    "name": "CUST-NAME",
                    "level": 5,
                    "picture": "X(30)",
                    "usage": null,
                    "value": null,
                    "occurs": null,
                    "redefines": null,
                    "parent": "CUSTOMER-RECORD",
                    "children": [],
                    "condition_names": []
                },
                {
                    "name": "CUST-BALANCE",
                    "level": 5,
                    "picture": "9(7)V99",
                    "usage": null,
                    "value": null,
                    "occurs": null,
                    "redefines": null,
                    "parent": "CUSTOMER-RECORD",
                    "children": [],
                    "condition_names": []
                },
                {
                    "name": "CUST-STATUS",
                    "level": 5,
                    "picture": "X",
                    "usage": null,
                    "value": null,
                    "occurs": null,
                    "redefines": null,
                    "parent": "CUSTOMER-RECORD",
                    "children": [],
                    "condition_names": [
                        {"name": "ACTIVE", "value": "'A'"},
                        {"name": "INACTIVE", "value": "'I'"}
                    ]
                }
            ],
            "condition_names": []
        }
    ],
    "business_logic": [
        {
            "name": "MAIN-PARA",
            "rule_type": "conditional",
            "description": "Main program flow with validation and display",
            "source_paragraph": "MAIN-PARA",
            "conditions": [
                {
                    "condition": "ACTIVE",
                    "then": "DISPLAY customer info",
                    "else": "DISPLAY error message"
                }
            ],
            "actions": [
                {"type": "PERFORM", "paragraph": "VALIDATE-CUST-ID"},
                {"type": "PERFORM", "paragraph": "LOOKUP-CUSTOMER"},
                {"type": "DISPLAY", "target": "CUST-NAME"}
            ],
            "variables_used": ["CUST-ID", "CUST-NAME", "CUST-BALANCE", "CUST-STATUS"]
        }
    ],
    "io_operations": [
        {"operation": "DISPLAY", "target": "prompt", "paragraph": "MAIN-PARA", "details": "DISPLAY Enter Customer ID"},
        {"operation": "ACCEPT", "target": "CUST-ID", "paragraph": "MAIN-PARA", "details": "ACCEPT CUST-ID"}
    ],
    "condition_names": {
        "ACTIVE": {"field": "CUST-STATUS", "value": "'A'"},
        "INACTIVE": {"field": "CUST-STATUS", "value": "'I'"}
    },
    "paragraphs": ["MAIN-PARA", "VALIDATE-CUST-ID", "LOOKUP-CUSTOMER", "DISPLAY-CUSTOMER"]
}
"""


def test_business_rules_model():
    """Test BusinessRules model validation."""
    rules = BusinessRules.model_validate_json(SAMPLE_BUSINESS_RULES_JSON)
    assert rules.program_name == "CUSTINQ"
    assert len(rules.data_definitions) == 1
    assert rules.data_definitions[0].name == "CUSTOMER-RECORD"
    assert len(rules.data_definitions[0].children) == 4
    assert len(rules.business_logic) == 1
    assert len(rules.io_operations) == 2


def test_parse_business_rules_json():
    """Test parsing business rules from JSON string."""
    rules = parse_business_rules(SAMPLE_BUSINESS_RULES_JSON)
    assert isinstance(rules, BusinessRules)
    assert rules.program_name == "CUSTINQ"


def test_pydantic_schema_model():
    """Test PydanticSchema model."""
    schema_data = {
        "models": [
            {
                "name": "Customer",
                "fields": [
                    {"name": "cust_id", "type": "int", "default": None, "description": "Customer ID"},
                    {"name": "cust_name", "type": "str", "default": None, "description": "Customer name"},
                    {"name": "cust_balance", "type": "Decimal", "default": None, "description": "Account balance"},
                    {"name": "cust_status", "type": "CustomerStatus", "default": None, "description": "Account status"}
                ],
                "config": {},
                "docstring": "Customer record from COBOL CUSTOMER-RECORD"
            }
        ],
        "enums": [
            {
                "name": "CustomerStatus",
                "values": {"ACTIVE": "'A'", "INACTIVE": "'I'"},
                "docstring": "Customer status codes from 88-levels"
            }
        ],
        "imports": [
            "from pydantic import BaseModel, Field",
            "from decimal import Decimal",
            "from typing import Optional, List",
            "from enum import Enum"
        ]
    }
    schema = PydanticSchema(**schema_data)
    assert len(schema.models) == 1
    assert schema.models[0].name == "Customer"
    assert len(schema.enums) == 1


def test_fastapi_output_model():
    """Test FastAPIOutput model."""
    output_data = {
        "main_py": "from fastapi import FastAPI\napp = FastAPI()",
        "models_py": "from pydantic import BaseModel\nclass Customer(BaseModel): pass",
        "services_py": "class CustomerService: pass",
        "routes_py": "from fastapi import APIRouter\nrouter = APIRouter()",
        "requirements_txt": "fastapi\nuvicorn",
        "readme_md": "# API"
    }
    output = FastAPIOutput(**output_data)
    assert output.main_py.startswith("from fastapi")
    assert output.models_py.startswith("from pydantic")


def test_cobol_to_parsed_flow():
    """Test full COBOL -> extract -> parse flow."""
    sample_cobol = Path("tests/fixtures/sample.cbl").read_text()
    sections = extract_cobol_sections(sample_cobol)
    parsed = parse_cobol_file(sections)

    assert parsed.program_name == "CUSTINQ"
    assert len(parsed.data_fields) > 5
    assert len(parsed.business_logic) > 0
    assert len(parsed.paragraphs) > 0


def test_field_type_mapping():
    """Test COBOL picture to Python type mapping."""
    from src.cobol.parser import DataField

    test_cases = [
        ("9(6)", None, "int"),
        ("9(7)V99", None, "Decimal"),
        ("X(30)", None, "str"),
        ("X", None, "str"),
        ("9(5)", "COMP", "int"),
        ("9(5)", "COMP-3", "Decimal"),
        ("S9(7)V99", "COMP-3", "Decimal"),
    ]

    for picture, usage, expected_type in test_cases:
        field = DataField(name="TEST", level=5, picture=picture, usage=usage)
        assert field.python_type() == expected_type, f"Failed for {picture} {usage}: got {field.python_type()}, expected {expected_type}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])