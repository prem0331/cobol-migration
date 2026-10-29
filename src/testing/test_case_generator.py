"""
Test Case Generator for Semantic Equivalence Testing

Automatically generates test cases from BusinessRules JSON:
- Normal flow (default VALUES)
- Boundary conditions (88-level transitions)
- Error conditions (validation rules)
- Edge cases (min/max/empty values)
"""

import json
from decimal import Decimal
from typing import Dict, List, Any, Optional, Set, Union
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class TestCase:
    """A single test case for equivalence testing."""
    name: str
    description: str
    inputs: Dict[str, Any]                    # Input values to set
    expected_outputs: Dict[str, Any]          # Expected output fields
    program_id: str
    paragraph: str = "MAIN-PARA"
    category: str = "functional"              # functional, boundary, error, edge


def generate_test_cases(business_rules: Dict[str, Any]) -> List[TestCase]:
    """
    Generate comprehensive test cases from BusinessRules.

    Returns test cases covering:
    1. Normal flow with default VALUES
    2. Each 88-level condition (ACTIVE/INACTIVE etc.)
    3. Each validation rule's error condition
    4. Boundary values for numeric fields
    4. Empty/null conditions for alphanumeric fields
    """
    test_cases = []
    program_id = business_rules.get("program_name", "UNKNOWN")

    # Extract field info
    fields = {f["name"]: f for f in business_rules.get("data_definitions", [])}
    rules = business_rules.get("business_logic", [])
    condition_names = business_rules.get("condition_names", {})

    # Identify input vs output fields
    input_fields = _identify_input_fields(fields, rules)
    output_fields = [f for f in fields if f not in input_fields]

    # ============================================================
    # 1. NORMAL FLOW - Default VALUES from WORKING-STORAGE
    # ============================================================
    normal_inputs = {}
    for name, field in fields.items():
        if field.get("value") is not None:
            normal_inputs[name] = _parse_cobol_value(field["value"], field.get("picture"))

    # Simulate to get expected outputs
    from .cobol_simulator import CobolSimulator
    sim = CobolSimulator(business_rules)
    sim.set_inputs(normal_inputs)
    outputs = sim.run_all()

    expected_outputs = {name: outputs.get(name) for name in output_fields}

    test_cases.append(TestCase(
        name="normal_flow",
        description="Normal execution with WORKING-STORAGE default VALUES",
        inputs=normal_inputs,
        expected_outputs=expected_outputs,
        program_id=program_id,
        category="functional"
    ))

    # ============================================================
    # 2. 88-LEVEL CONDITION TESTS
    # Each 88-level creates a test with that condition value
    # ============================================================
    for field_name, cond_info in condition_names.items():
        field_obj = fields.get(cond_info.get("field", ""))
        if not field_obj:
            continue

        cond_value = cond_info.get("value", "")
        test_inputs = normal_inputs.copy()
        test_inputs[field_obj["name"]] = _parse_cobol_value(cond_value, field_obj.get("picture"))

        sim2 = CobolSimulator(business_rules)
        sim2.set_inputs(test_inputs)
        outputs2 = sim2.run_all()
        expected2 = {name: outputs2.get(name) for name in output_fields}

        test_cases.append(TestCase(
            name=f"condition_{field_name.lower()}",
            description=f"Test 88-level {field_name} = {cond_value}",
            inputs=test_inputs,
            expected_outputs=expected2,
            program_id=program_id,
            category="boundary"
        ))

    # ============================================================
    # 3. VALIDATION ERROR CONDITIONS
    # Each validation rule's failure case
    # ============================================================
    for rule in rules:
        if rule.get("rule_type") == "validation":
            # Find the condition that triggers error
            for cond in rule.get("conditions", []):
                condition_expr = cond.get("condition", "")
                if condition_expr:
                    # Create input that triggers this condition
                    error_inputs = _create_error_input(condition_expr, fields, normal_inputs)

                    if error_inputs:
                        sim3 = CobolSimulator(business_rules)
                        sim3.set_inputs(error_inputs)
                        outputs3 = sim3.run_all()
                        expected3 = {name: outputs3.get(name) for name in output_fields}

                        test_cases.append(TestCase(
                            name=f"error_{rule['name'].lower()}",
                            description=f"Validation error: {rule.get('description', rule['name'])}",
                            inputs=error_inputs,
                            expected_outputs=expected3,
                            program_id=program_id,
                            category="error"
                        ))

    # ============================================================
    # 4. BOUNDARY VALUE TESTS FOR NUMERIC FIELDS
    # ============================================================
    for name, field in fields.items():
        picture = field.get("picture", "")
        if _is_numeric_picture(picture):
            boundary_inputs = _generate_boundary_inputs(name, picture, fields, normal_inputs)

            for idx, b_input in enumerate(boundary_inputs):
                sim_b = CobolSimulator(business_rules)
                sim_b.set_inputs(b_input)
                outputs_b = sim_b.run_all()
                expected_b = {n: outputs_b.get(n) for n in output_fields}

                test_cases.append(TestCase(
                    name=f"boundary_{name.lower()}_{idx}",
                    description=f"Boundary test for {name} ({picture})",
                    inputs=b_input,
                    expected_outputs=expected_b,
                    program_id=program_id,
                    category="edge"
                ))

    # ============================================================
    # 5. EMPTY/NULL TESTS FOR ALPHANUMERIC FIELDS
    # ============================================================
    for name, field in fields.items():
        picture = field.get("picture", "")
        if _is_alphanumeric_picture(picture):
            empty_inputs = normal_inputs.copy()
            empty_inputs[name] = ""

            sim_e = CobolSimulator(business_rules)
            sim_e.set_inputs(empty_inputs)
            outputs_e = sim_e.run_all()
            expected_e = {n: outputs_e.get(n) for n in output_fields}

            test_cases.append(TestCase(
                name=f"empty_{name.lower()}",
                description=f"Empty value for {name} ({picture})",
                inputs=empty_inputs,
                expected_outputs=expected_e,
                program_id=program_id,
                category="edge"
            ))

    return test_cases


def _identify_input_fields(fields: Dict, rules: List[Dict]) -> Set[str]:
    """Identify fields that are inputs (referenced in conditions but not set by rules)."""
    # Fields used in conditions
    condition_fields = set()
    for rule in rules:
        for cond in rule.get("conditions", []):
            condition_fields.update(_extract_field_names(cond.get("condition", "")))

    # Fields set by rules (outputs)
    output_fields = set()
    for rule in rules:
        for action in rule.get("actions", []):
            if action.get("type", "").upper() in ("MOVE", "COMPUTE"):
                if action.get("to"):
                    output_fields.add(action["to"])
                if action.get("target"):
                    output_fields.add(action["target"])

    # Inputs = used in conditions but not set by rules
    return condition_fields - output_fields


def _extract_field_names(condition: str) -> Set[str]:
    """Extract field names from a condition expression."""
    # Simple extraction - words that look like COBOL field names
    import re
    # COBOL field names: alphanumeric with hyphens, not keywords
    keywords = {"IF", "THEN", "ELSE", "END-IF", "NOT", "AND", "OR",
                "GREATER", "THAN", "LESS", "EQUAL", "TO"}
    words = re.findall(r'\b[A-Z][A-Z0-9-]*\b', condition.upper())
    return {w for w in words if w not in keywords and not w.isdigit()}


def _create_error_input(condition: str, fields: Dict, base_inputs: Dict) -> Optional[Dict]:
    """Create input that triggers a validation error condition."""
    # Simple approach: if condition is "FIELD = 0", set FIELD = 0
    # This is heuristic - real implementation would parse condition properly
    import re

    test_inputs = base_inputs.copy()

    # Try to extract field and value from simple conditions
    # "CUST-ID = 0" -> set CUST-ID = 0
    match = re.search(r'(\w+)\s*[=<>!]+\s*([\d\w\.\'\"]+)', condition)
    if match:
        field_name = match.group(1)
        value_str = match.group(2).strip("'\"")
        if field_name in fields:
            test_inputs[field_name] = _parse_cobol_value(value_str, fields[field_name].get("picture"))
            return test_inputs

    return None


def _is_numeric_picture(picture: str) -> bool:
    """Check if picture is numeric."""
    if not picture:
        return False
    pic = picture.upper()
    return '9' in pic and 'X' not in pic and 'A' not in pic


def _is_alphanumeric_picture(picture: str) -> bool:
    """Check if picture is alphanumeric."""
    if not picture:
        return False
    pic = picture.upper()
    return 'X' in pic or 'A' in pic


def _generate_boundary_inputs(
    field_name: str,
    picture: str,
    all_fields: Dict,
    base_inputs: Dict
) -> List[Dict]:
    """Generate boundary value inputs for a numeric field."""
    boundaries = []

    # Extract length from PIC 9(n) or 9(n)V99
    import re
    digits_match = re.search(r'9\((\d+)\)', picture)
    decimal_match = re.search(r'V9\((\d+)\)|V99', picture)

    total_digits = int(digits_match.group(1)) if digits_match else 5
    decimal_digits = int(decimal_match.group(1)) if decimal_match and decimal_match.group(1) else (2 if 'V99' in picture else 0)

    max_val = 10 ** (total_digits - decimal_digits) - 1
    if decimal_digits > 0:
        max_val = max_val / (10 ** decimal_digits)

    min_val = 0
    if 'S' in picture:
        min_val = -max_val

    test_values = [
        min_val,
        min_val + 1,
        0,
        1,
        max_val - 1,
        max_val,
        max_val + 1  # overflow
    ]

    for val in test_values:
        test_input = base_inputs.copy()
        if decimal_digits > 0:
            test_input[field_name] = Decimal(str(val))
        else:
            test_input[field_name] = int(val) if val == int(val) else Decimal(str(val))
        boundaries.append(test_input)

    return boundaries


def _parse_cobol_value(value: str, picture: Optional[str] = None) -> Any:
    """Parse COBOL VALUE clause to Python value."""
    value = value.strip()
    if value.startswith('"') and value.endswith('"'):
        return value[1:-1]
    if value.startswith("'") and value.endswith("'"):
        return value[1:-1]

    try:
        if picture and ('V' in picture.upper() or '.' in picture.upper()):
            return Decimal(value)
        return int(value)
    except:
        return value


def save_test_cases(test_cases: List[TestCase], filepath: Union[str, Path]):
    """Save test cases to JSON file."""
    data = {
        "test_cases": [
            {
                "name": tc.name,
                "description": tc.description,
                "inputs": tc.inputs,
                "expected_outputs": tc.expected_outputs,
                "program_id": tc.program_id,
                "paragraph": tc.paragraph,
                "category": tc.category
            }
            for tc in test_cases
        ]
    }
    with open(filepath, 'w') as f:
        json.dump(data, f, indent=2, default=str)


def load_test_cases(filepath: Union[str, Path]) -> List[TestCase]:
    """Load test cases from JSON file."""
    with open(filepath, 'r') as f:
        data = json.load(f)
    return [TestCase(**tc) for tc in data.get("test_cases", [])]


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        with open(sys.argv[1], 'r') as f:
            rules = json.load(f)
        cases = generate_test_cases(rules)
        print(json.dumps([{
            "name": c.name,
            "description": c.description,
            "inputs": c.inputs,
            "expected_outputs": c.expected_outputs,
            "category": c.category
        } for c in cases], indent=2, default=str))