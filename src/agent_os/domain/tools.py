"""Domain models for agent tool definitions, schemas, and execution results."""

from pydantic import BaseModel, Field

from agent_os.domain.policy import ActionTier


class ToolParameterSchema(BaseModel):
    """Schema describing an individual tool parameter."""

    name: str
    type_name: str
    description: str
    required: bool = True
    default: str | int | float | bool | None = None


class ToolDefinition(BaseModel):
    """Declarative specification for an agent capability tool."""

    name: str
    description: str
    action_tier: ActionTier
    parameters: list[ToolParameterSchema] = Field(default_factory=list)


class ToolExecutionResult(BaseModel):
    """Standard execution result returned by all capability tools."""

    tool_name: str
    success: bool
    output: str
    error: str | None = None
