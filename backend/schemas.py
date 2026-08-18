from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


# ── Topology data types (mirrors frontend TypeScript) ──────────────


ContainerType = Literal[
    "web-server",
    "file-server",
    "plc",
    "firewall",
    "switch",
    "router",
    "workstation",
    "hmi",
]


class Container(BaseModel):
    id: str
    name: str
    type: str  # validated as ContainerType on the frontend; kept loose here to survive LLM-generated values
    ip: str
    kind: str | None = None
    image: str | None = None
    status: str | None = None  # "running" | "stopped" | "paused" at runtime; loose for stored data
    metadata: dict | None = None
    persistencePaths: list[str] | None = None
    config: dict | None = None


class Connection(BaseModel):
    from_: str = Field(alias="from")
    to: str
    label: str | None = None
    fromInterface: str | None = None
    toInterface: str | None = None
    fromContainer: str | None = None
    toContainer: str | None = None

    model_config = {"populate_by_name": True}


class Subnet(BaseModel):
    id: str
    name: str
    cidr: str
    gateway: str | None = None
    containers: list[Container] = Field(default_factory=list)
    connections: list[Connection] = Field(default_factory=list)


class Position(BaseModel):
    x: float
    y: float


class Site(BaseModel):
    id: str
    name: str
    location: str = ""
    position: Position = Field(default_factory=lambda: Position(x=100, y=100))
    subnets: list[Subnet] = Field(default_factory=list)
    subnetConnections: list[Connection] = Field(default_factory=list)


class ScriptExecution(BaseModel):
    containerId: str
    script: str
    args: list[str] | None = None


class AttackPhase(BaseModel):
    id: str
    name: str
    description: str | None = None
    executions: list[ScriptExecution] = Field(default_factory=list)


class Scenario(BaseModel):
    id: str
    name: str
    description: str | None = None
    phases: list[AttackPhase] = Field(default_factory=list)


class TopologyData(BaseModel):
    name: str | None = None
    sites: list[Site] = Field(default_factory=list)
    siteConnections: list[Connection] = Field(default_factory=list)
    scenarios: list[Scenario] | None = None


# ── API request/response models ────────────────────────────────────


class TopologyCreate(BaseModel):
    name: str
    data: TopologyData


class TopologyUpdate(BaseModel):
    name: str | None = None
    data: TopologyData | None = None


class TopologyRecord(BaseModel):
    id: str
    name: str
    data: TopologyData
    clab_yaml: str | None = None
    status: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class TopologySummary(BaseModel):
    id: str
    name: str
    status: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class FirewallRule(BaseModel):
    source: str
    destination: str
    protocol: Literal["any", "tcp", "udp", "icmp"]
    port: str
    action: Literal["accept", "drop"]


class FirewallRulesUpdate(BaseModel):
    rules: list[FirewallRule]


class FirewallRulesResponse(BaseModel):
    rules: list[FirewallRule]


# ── Auth / Classroom ──────────────────────────────────────────────


class StudentLoginRequest(BaseModel):
    join_code: str


class TokenResponse(BaseModel):
    role: Literal["instructor", "student"]
    token: str
    topology_id: str | None = None


class ClassSessionCreate(BaseModel):
    name: str
    template_id: str


class ClassSessionRecord(BaseModel):
    id: str
    name: str
    template_id: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class StudentSlotRecord(BaseModel):
    id: str
    session_id: str
    topology_id: str
    join_code: str
    label: str | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class InstantiateRequest(BaseModel):
    count: int = Field(ge=1, le=200)
    label_prefix: str = "Student"
