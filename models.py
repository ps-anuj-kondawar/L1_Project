from pydantic import BaseModel, Field

class ExtractedChemical(BaseModel):
    name: str = Field(description="Name of the chemical")
    concentration: str = Field(description="Detected concentration, e.g., '12%' or '500 ppm'")

class ExtractedHardware(BaseModel):
    name: str = Field(description="Name of the container or equipment")
    target_temperature_celsius: float = Field(description="Target operating temperature in Celsius")

class ExtractionResult(BaseModel):
    chemicals: list[ExtractedChemical] = Field(description="List of chemicals extracted from the input")
    hardware: list[ExtractedHardware] = Field(description="List of hardware extracted from the input")

class ChemicalFlag(BaseModel):
    chemical_name: str = Field(
        description="The name of the chemical as found in the user input."
    )
    is_compliant: bool = Field(
        description="True if the detected concentration is within regulatory limits, False otherwise."
    )
    detected_concentration: str = Field(
        description="The concentration as stated in the user input (e.g., '6%' or '500 ppm')."
    )
    regulatory_limit: str = Field(
        description=(
            "The permissible exposure limit from the regulatory database (e.g., '1 ppm TWA'), "
            "or 'Unknown: No regulatory data found' if the chemical is not in the database."
        )
    )
    source_citation: str = Field(
        description=(
            "The exact text chunk retrieved from ChromaDB that supports this ruling."
        )
    )

class HardwareFlag(BaseModel):
    equipment_name: str = Field(
        description="The name of the container or equipment as mentioned in the user input."
    )
    target_temperature_celsius: float = Field(
        description="The target operating temperature in Celsius as stated in the user input."
    )
    max_safe_temperature_celsius: float = Field(
        description="The maximum safe operating temperature for this equipment, from the MCP server."
    )
    is_safe: bool = Field(
        description=(
            "True if target_temperature_celsius <= max_safe_temperature_celsius, False otherwise."
        )
    )

class ComplianceReport(BaseModel):
    chemical_flags: list[ChemicalFlag] = Field(
        description="One ChemicalFlag entry for each chemical identified in the user input."
    )
    hardware_flags: list[HardwareFlag] = Field(
        description="One HardwareFlag entry for each container or equipment mentioned in the user input."
    )
    overall_approval_status: str = Field(
        description=(
            "'APPROVED' if all checks pass and there are no systemic hazards. "
            "'REJECTED' if any check fails or there is a severe hazard. "
            "'PARTIAL' if mixed or if there are secondary environmental risks (e.g., boiling point exceeded)."
        )
    )
    summary: str = Field(
        description="A single sentence summarising the overall compliance finding, explicitly mentioning any boiling point or secondary hazards if present."
    )
