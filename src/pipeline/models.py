"""Pydantic models for inter-agent data exchange in the migration pipeline."""

from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from enum import Enum


class PicType(str, Enum):
    """COBOL PICTURE clause types mapped to Python types."""
    ALPHANUMERIC = "str"
    NUMERIC = "int"
    DECIMAL = "Decimal"
    ALPHABETIC = "str"
    COMPUTATIONAL = "int"
    COMP_3 = "Decimal"


class DataField(BaseModel):
    """Represents a COBOL data field definition."""
    name: str = Field(..., description="Field name")
    level: int = Field(..., description="Level number (01, 05, 10, etc.)")
    picture: Optional[str] = Field(None, description="PICTURE clause")
    usage: Optional[str] = Field(None, description="USAGE clause (COMP, COMP-3, etc.)")
    value: Optional[str] = Field(None, description="VALUE clause")
    occurs: Optional[int] = Field(None, description="OCCURS count")
    redefines: Optional[str] = Field(None, description="REDEFINES field name")
    parent: Optional[str] = Field(None, description="Parent field name")
    children: List['DataField'] = Field(default_factory=list, description="Child fields")
    condition_names: List[Dict[str, str]] = Field(
        default_factory=list,
        description="88-level condition names with values"
    )

    @property
    def is_group(self) -> bool:
        return self.picture is None and len(self.children) > 0

    @property
    def is_elementary(self) -> bool:
        return self.picture is not None

    def python_type(self) -> str:
        """Map COBOL picture to Python type."""
        if not self.picture:
            return "Any"

        pic = self.picture.upper()

        if self.usage and 'COMP' in self.usage.upper():
            if 'COMP-3' in self.usage.upper() or 'PACKED' in self.usage.upper():
                return "Decimal"
            return "int"

        if '9' in pic:
            if 'V' in pic or '.' in pic:
                return "Decimal"
            return "int"

        if 'X' in pic or 'A' in pic:
            return "str"

        return "str"


DataField.model_rebuild()


class BusinessRule(BaseModel):
    """Represents a business rule extracted from PROCEDURE DIVISION."""
    name: str = Field(..., description="Paragraph/rule name")
    rule_type: str = Field(
        ...,
        description="Type: validation, calculation, lookup, conditional, workflow, data_transfer, io"
    )
    description: str = Field(..., description="Human-readable description")
    source_paragraph: str = Field(..., description="Source paragraph name")
    conditions: List[Dict[str, str]] = Field(
        default_factory=list,
        description="IF conditions with then/else branches"
    )
    actions: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="Actions: MOVE, COMPUTE, PERFORM, etc."
    )
    variables_used: List[str] = Field(
        default_factory=list,
        description="Variable names referenced in this rule"
    )


class IOOperation(BaseModel):
    """Represents an I/O operation in COBOL."""
    operation: str = Field(..., description="Operation: READ, WRITE, DISPLAY, ACCEPT, OPEN, CLOSE")
    target: str = Field(..., description="Target file/field")
    paragraph: str = Field(..., description="Source paragraph")
    details: str = Field(default="", description="Additional context")


class BusinessRules(BaseModel):
    """Complete business rules extracted by Agent 1 (Analyst)."""
    program_name: str = Field(..., description="COBOL PROGRAM-ID")
    data_definitions: List[DataField] = Field(
        default_factory=list,
        description="All data fields from WORKING-STORAGE"
    )
    business_logic: List[BusinessRule] = Field(
        default_factory=list,
        description="Business rules from PROCEDURE DIVISION"
    )
    io_operations: List[IOOperation] = Field(
        default_factory=list,
        description="I/O operations found"
    )
    condition_names: Dict[str, Dict[str, str]] = Field(
        default_factory=dict,
        description="88-level condition name mappings"
    )
    paragraphs: List[str] = Field(
        default_factory=list,
        description="All paragraph names"
    )


class ModelDefinition(BaseModel):
    """Pydantic model definition for Agent 2 (Architect) output."""
    name: str = Field(..., description="Model class name")
    fields: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="Field definitions: name, type, description, default"
    )
    config: Dict[str, Any] = Field(
        default_factory=dict,
        description="Pydantic model config (orm_mode, etc.)"
    )
    docstring: str = Field(default="", description="Model docstring")


class EnumDefinition(BaseModel):
    """Enum definition for 88-level conditions."""
    name: str = Field(..., description="Enum class name")
    values: Dict[str, str] = Field(
        default_factory=dict,
        description="Enum members: name -> value"
    )
    docstring: str = Field(default="", description="Enum docstring")


class PydanticSchema(BaseModel):
    """Complete Pydantic schema output by Agent 2 (Architect)."""
    models: List[ModelDefinition] = Field(
        default_factory=list,
        description="Pydantic model definitions"
    )
    enums: List[EnumDefinition] = Field(
        default_factory=list,
        description="Enum definitions for condition names"
    )
    imports: List[str] = Field(
        default_factory=lambda: ["from pydantic import BaseModel, Field", "from decimal import Decimal", "from typing import Optional, List", "from enum import Enum"],
        description="Required imports"
    )


class FastAPIOutput(BaseModel):
    """Complete FastAPI application output by Agent 3 (Developer)."""
    main_py: str = Field(..., description="main.py - FastAPI app entry point")
    models_py: str = Field(..., description="models.py - Pydantic models")
    services_py: str = Field(..., description="services.py - Business logic layer")
    routes_py: str = Field(..., description="routes.py - API route definitions")
    requirements_txt: str = Field(
        default="fastapi>=0.100\nuvicorn>=0.23\npydantic>=2.0\npython-dotenv>=1.0",
        description="requirements.txt content"
    )
    readme_md: str = Field(default="", description="README.md with API documentation")