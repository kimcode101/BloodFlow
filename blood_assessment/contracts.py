from __future__ import annotations
from datetime import datetime, date
from typing import Literal, Any
from pydantic import BaseModel, ConfigDict, Field, AwareDatetime

GROUPS = ('O+', 'O-', 'A+', 'A-', 'B+', 'B-', 'AB+', 'AB-')
Blood = Literal['O+', 'O-', 'A+', 'A-', 'B+', 'B-', 'AB+', 'AB-']
Schema = Literal['public', 'kim']

class Contract(BaseModel):
    model_config = ConfigDict(extra='forbid')

class Snapshot(Contract):
    snapshot_id: str
    dataset_schema: Schema
    as_of: AwareDatetime
    source: str
    tables: dict[str, list[dict[str, Any]]]
    data_hash: str
    version: str = '1'

class GraphPolicy(Contract):
    version: str = 'dated-cp-sat-v1'
    max_seconds_per_stage: float = Field(default=10, gt=0, le=60, allow_inf_nan=False)
    allow_unmet_demand: bool = True
    traffic: Literal['normal', 'rush'] = 'rush'

class Policy(Contract):
    version: str = 'floor-fefo-v1'
    window: int = Field(default=7, ge=1, le=365)
    alpha: float = Field(default=.4, gt=0, le=1)
    planning: Literal['floor', 'additive_stress'] = 'floor'
    target_days: int = Field(default=2, ge=1, le=14)
    buffer: float = Field(default=.25, ge=0, le=3)
    exposure_elapsed: float | None = Field(default=None, gt=0, lt=1)
    reserves: dict[str, int] = Field(default_factory=dict)
    min_ml_days: int = Field(default=14, ge=4)
    graph: GraphPolicy = Field(default_factory=GraphPolicy)

class Forecast(Contract):
    site_id: str
    blood_type: Blood
    forecast_interval: tuple[AwareDatetime, AwareDatetime]
    expected_consumption: float = Field(ge=0)
    uncertainty_range: tuple[float, float]
    uncertainty_method: str
    selected_method: str
    training_window: tuple[date, date]
    complete_days_used: int
    backtest_metrics: dict[str, Any]
    known_scheduled_units: int
    planning_policy: str
    proposed_requirement: float
    assumptions: list[str]
    source_refs: list[str]

class Requirement(Contract):
    site_id: str
    blood_type: Blood
    target: int = Field(ge=0)
    components: dict[str, Any]
    evidence_ref: str

class AssessmentRun(Contract):
    assessment_id: str
    snapshot_id: str
    dataset_schema: Schema
    as_of: AwareDatetime
    forecast_run_ids: list[str]
    model_version: str
    policy_version: str
    findings: list[dict[str, Any]]
    proposed_requirement_updates: list[Requirement]
    proposed_priority_updates: list[dict[str, Any]]
    unresolved_data_issues: list[str]
    requires_review: bool = True
    evidence_refs: list[str]
    explanation: str

class Claim(Contract):
    evidence_ref: str
    field: Literal['stock', 'daily_rate', 'target', 'unmet_demand', 'expiry_3_days']
    value: float

class AgentReview(Contract):
    claims: list[Claim]
    finding_refs: list[str]
    next_action: Literal['request_review', 'investigate_data']
