# ══════════════════════════════════════════════════════════════════════════════
#  BA WORKFLOW ASSISTANT — BACKEND
#  Sections 1-7: Config, Models, LLM, Rules, EventStore, Orchestrator, Agents
#  + Pipeline runner + Correction handler + SVG renderer
#  
#  This file contains ALL business logic. No UI code.
#  Used by: app.py (Streamlit), or any other frontend.
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations
import os
import json
from datetime import datetime
from enum import Enum
from typing import Optional, Callable
from uuid import UUID, uuid4
from pydantic import BaseModel, Field
from openai import OpenAI


# ══════════════════════════════════════════════════════════════════════════════
#  SECTION 1: CONFIG
# ══════════════════════════════════════════════════════════════════════════════

LLM_MODEL = "gpt-4o"
LLM_TEMPERATURE = 0.2
LLM_MAX_TOKENS = 4000

def get_client(api_key: str) -> OpenAI:
    return OpenAI(api_key=api_key)


# ══════════════════════════════════════════════════════════════════════════════
#  SECTION 2: DATA MODELS
# ══════════════════════════════════════════════════════════════════════════════

class ProjectPhase(str, Enum):
    PRE_DISCOVERY = "pre_discovery"
    DISCOVERY = "discovery"
    REQUIREMENTS = "requirements"
    ANALYSIS = "analysis"
    PRIORITISATION = "prioritisation"
    AGILE_SCRUM = "agile_scrum"
    TESTING = "testing"
    HANDOVER = "handover"

class RequirementType(str, Enum):
    FUNCTIONAL = "functional"
    NON_FUNCTIONAL = "non_functional"

class RequirementStatus(str, Enum):
    DRAFT = "draft"
    REVIEW = "review"
    APPROVED = "approved"
    REJECTED = "rejected"
    DEFERRED = "deferred"

class Priority(str, Enum):
    MUST = "must"
    SHOULD = "should"
    COULD = "could"
    WONT = "wont"

class RiskTier(str, Enum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"

class StakeholderInfluence(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"

class ActorType(str, Enum):
    AGENT = "agent"
    BA = "ba"
    SYSTEM = "system"

class EventAction(str, Enum):
    CREATE = "create"
    UPDATE = "update"
    APPROVE = "approve"
    REJECT = "reject"
    OVERRIDE = "override"
    DELETE = "delete"

class ConfidenceLevel(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"

class ChangeEvent(BaseModel):
    event_id: UUID = Field(default_factory=uuid4)
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    actor_type: ActorType
    actor_id: str
    action: EventAction
    artefact_type: str
    artefact_id: UUID
    diff: Optional[dict] = None
    context: Optional[str] = None
    project_id: UUID

class RiskScore(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    requirement_id: UUID
    project_id: UUID
    regulatory_exposure: int = Field(ge=1, le=5)
    integration_complexity: int = Field(ge=1, le=5)
    stakeholder_dependency: int = Field(ge=1, le=5)
    implementation_ambiguity: int = Field(ge=1, le=5)
    weighted_total: int = 0
    risk_tier: RiskTier = RiskTier.LOW
    controls: list[str] = Field(default_factory=list)
    rationale: Optional[str] = None
    created_by: str = "A08"

    def calculate(self):
        self.weighted_total = (
            self.regulatory_exposure * 2
            + self.integration_complexity
            + self.stakeholder_dependency
            + self.implementation_ambiguity
        )
        if self.weighted_total >= 20: self.risk_tier = RiskTier.CRITICAL
        elif self.weighted_total >= 15: self.risk_tier = RiskTier.HIGH
        elif self.weighted_total >= 10: self.risk_tier = RiskTier.MEDIUM
        else: self.risk_tier = RiskTier.LOW


# ══════════════════════════════════════════════════════════════════════════════
#  SECTION 3: LLM CLIENT
# ══════════════════════════════════════════════════════════════════════════════

def call_llm(api_key: str, system_prompt: str, user_prompt: str, response_format: str = "json",
             temperature: float = None, max_tokens: int = None) -> dict | str:
    client = get_client(api_key)
    kwargs = {
        "model": LLM_MODEL,
        "temperature": temperature or LLM_TEMPERATURE,
        "max_tokens": max_tokens or LLM_MAX_TOKENS,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    }
    if response_format == "json":
        kwargs["response_format"] = {"type": "json_object"}
    response = client.chat.completions.create(**kwargs)
    content = response.choices[0].message.content
    if response_format == "json":
        try: return json.loads(content)
        except json.JSONDecodeError: return {"raw_response": content, "parse_error": True}
    return content

def call_llm_structured(api_key: str, system_prompt: str, user_prompt: str, output_schema: dict,
                        temperature: float = None) -> dict:
    schema_instruction = (
        f"\n\nYou MUST respond with valid JSON matching this exact schema. "
        f"No markdown, no backticks, just the JSON object:\n{json.dumps(output_schema, indent=2)}"
    )
    return call_llm(
        api_key=api_key,
        system_prompt=system_prompt + schema_instruction,
        user_prompt=user_prompt,
        response_format="json",
        temperature=temperature,
    )


# ══════════════════════════════════════════════════════════════════════════════
#  SECTION 4: RULES ENGINE
# ══════════════════════════════════════════════════════════════════════════════

BABOK_KA_MAP = {
    "KA1": {"name": "Business Analysis Planning & Monitoring", "chapter": 2,
        "tasks": {"2.1": "Plan BA Approach", "2.2": "Conduct Stakeholder Analysis",
                  "2.3": "Plan BA Activities", "2.4": "Plan BA Communication",
                  "2.5": "Plan Requirements Management Process", "2.6": "Manage BA Performance"}},
    "KA2": {"name": "Elicitation", "chapter": 3,
        "tasks": {"3.1": "Prepare for Elicitation", "3.2": "Conduct Elicitation Activity",
                  "3.3": "Document Elicitation Results", "3.4": "Confirm Elicitation Results"}},
    "KA3": {"name": "Requirements Management & Communication", "chapter": 4,
        "tasks": {"4.1": "Manage Solution Scope & Requirements", "4.2": "Manage Requirements Traceability",
                  "4.3": "Maintain Requirements for Re-use", "4.4": "Prepare Requirements Package",
                  "4.5": "Communicate Requirements"}},
    "KA4": {"name": "Enterprise Analysis", "chapter": 5,
        "tasks": {"5.1": "Define Business Need", "5.2": "Assess Capability Gaps",
                  "5.3": "Determine Solution Approach", "5.4": "Define Solution Scope",
                  "5.5": "Define Business Case"}},
    "KA5": {"name": "Requirements Analysis", "chapter": 6,
        "tasks": {"6.1": "Prioritize Requirements", "6.2": "Organize Requirements",
                  "6.3": "Specify and Model Requirements", "6.4": "Define Assumptions and Constraints",
                  "6.5": "Verify Requirements", "6.6": "Validate Requirements"}},
    "KA6": {"name": "Solution Assessment & Validation", "chapter": 7,
        "tasks": {"7.1": "Assess Proposed Solution", "7.2": "Allocate Requirements",
                  "7.3": "Assess Organizational Readiness", "7.4": "Define Transition Requirements",
                  "7.5": "Validate Solution", "7.6": "Evaluate Solution Performance"}},
}

AMBIGUITY_KEYWORDS = [
    "should", "might", "could", "would", "may", "appropriate", "as needed",
    "as required", "if possible", "normally", "typically", "generally",
    "often", "reasonable", "adequate", "sufficient",
]

NFR_LIBRARY = {
    "reliability": [
        {"name": "System Availability", "default_value": "99.9% uptime", "is_gxp_default": True, "description": "System available 99.9% during business hours."},
        {"name": "Disaster Recovery", "default_value": "RPO 1hr, RTO 4hr", "is_gxp_default": False, "description": "Recovery objectives."},
        {"name": "Data Backup", "default_value": "Daily incremental, weekly full", "is_gxp_default": True, "description": "Backup schedule."},
    ],
    "performance": [
        {"name": "Response Time", "default_value": "< 2s for 95% requests", "is_gxp_default": False, "description": "Page/API response time."},
        {"name": "Throughput", "default_value": "1000 concurrent users", "is_gxp_default": False, "description": "Max concurrent capacity."},
    ],
    "security": [
        {"name": "Authentication", "default_value": "SSO with MFA", "is_gxp_default": True, "description": "SSO + multi-factor auth."},
        {"name": "Authorization", "default_value": "RBAC", "is_gxp_default": True, "description": "Role-based access control."},
        {"name": "Encryption at Rest", "default_value": "AES-256", "is_gxp_default": True, "description": "All stored data encrypted."},
        {"name": "Encryption in Transit", "default_value": "TLS 1.2+", "is_gxp_default": True, "description": "All data in transit encrypted."},
        {"name": "Session Mgmt", "default_value": "30min idle timeout", "is_gxp_default": True, "description": "Session expiry."},
    ],
    "compliance": [
        {"name": "Audit Trail", "default_value": "Complete, immutable, 21CFR Part 11", "is_gxp_default": True, "description": "All actions logged."},
        {"name": "Electronic Signatures", "default_value": "21CFR Part 11 compliant", "is_gxp_default": True, "description": "Legally binding e-signatures."},
        {"name": "Data Integrity", "default_value": "ALCOA+ principles enforced", "is_gxp_default": True, "description": "Attributable, Legible, Contemporaneous, Original, Accurate."},
        {"name": "HCP Data Privacy", "default_value": "GDPR compliant", "is_gxp_default": True, "description": "HCP interaction data privacy."},
        {"name": "Record Retention", "default_value": "Min 7 years", "is_gxp_default": True, "description": "Regulatory retention period."},
        {"name": "Validation Docs", "default_value": "GAMP5 compliant", "is_gxp_default": True, "description": "GAMP5 validation documentation."},
    ],
    "auditability": [
        {"name": "Change Log", "default_value": "All config changes logged", "is_gxp_default": True, "description": "Config change tracking."},
        {"name": "User Activity Log", "default_value": "All CRUD logged", "is_gxp_default": True, "description": "All operations logged per user."},
    ],
    "data_integrity": [
        {"name": "Input Validation", "default_value": "Server-side on all inputs", "is_gxp_default": True, "description": "Server-side validation."},
        {"name": "Referential Integrity", "default_value": "DB-level enforcement", "is_gxp_default": True, "description": "Database constraints enforced."},
    ],
    "usability": [
        {"name": "Accessibility", "default_value": "WCAG 2.1 AA", "is_gxp_default": False, "description": "Accessibility compliance."},
        {"name": "Browser Support", "default_value": "Latest 2 Chrome/Firefox/Edge/Safari", "is_gxp_default": False, "description": "Cross-browser support."},
    ],
    "maintainability": [
        {"name": "Monitoring", "default_value": "Health checks + alerting", "is_gxp_default": True, "description": "System health monitoring."},
        {"name": "Log Management", "default_value": "Centralized, 90-day retention", "is_gxp_default": True, "description": "Log aggregation."},
    ],
}

RISK_SCORING_CONFIG = {
    "axes": {
        "regulatory_exposure": {"weight": 2, "description": "Regulatory data/process exposure. 2x weight in LS."},
        "integration_complexity": {"weight": 1, "description": "Number of systems touched."},
        "stakeholder_dependency": {"weight": 1, "description": "Cross-functional alignment needed."},
        "implementation_ambiguity": {"weight": 1, "description": "Requirement clarity level."},
    },
    "tiers": {
        "critical": {"range": [20, 25]}, "high": {"range": [15, 19]},
        "medium": {"range": [10, 14]}, "low": {"range": [5, 9]},
    },
}

def check_ambiguity(text):
    return [kw for kw in AMBIGUITY_KEYWORDS if kw in text.lower()]

def get_nfr_suggestions(system_type="gxp"):
    suggestions = []
    for cat, nfrs in NFR_LIBRARY.items():
        for nfr in nfrs:
            if system_type == "gxp" and nfr.get("is_gxp_default"):
                suggestions.append({"category": cat, **nfr})
            elif system_type != "gxp":
                suggestions.append({"category": cat, **nfr})
    return suggestions

def get_nfr_count():
    return sum(len(v) for v in NFR_LIBRARY.values())

def get_gxp_default_count():
    return len(get_nfr_suggestions("gxp"))


# ══════════════════════════════════════════════════════════════════════════════
#  SECTION 5: EVENT STORE
# ══════════════════════════════════════════════════════════════════════════════

class EventStore:
    def __init__(self):
        self._store: list[dict] = []

    def log_event_sync(self, event: ChangeEvent) -> ChangeEvent:
        self._store.append({
            "event_id": str(event.event_id), "timestamp": event.timestamp.isoformat(),
            "actor_type": event.actor_type.value, "actor_id": event.actor_id,
            "action": event.action.value, "artefact_type": event.artefact_type,
            "artefact_id": str(event.artefact_id), "diff": event.diff,
            "context": event.context, "project_id": str(event.project_id),
        })
        return event

    def get_project_events_sync(self, project_id, limit=50, offset=0):
        events = [e for e in self._store if e["project_id"] == str(project_id)]
        events.sort(key=lambda x: x["timestamp"], reverse=True)
        return events[offset:offset + limit]

    def get_event_count_sync(self, project_id):
        return len([e for e in self._store if e["project_id"] == str(project_id)])


# ══════════════════════════════════════════════════════════════════════════════
#  SECTION 6: ORCHESTRATOR
# ══════════════════════════════════════════════════════════════════════════════

PHASE_ORDER = [
    ProjectPhase.PRE_DISCOVERY, ProjectPhase.DISCOVERY, ProjectPhase.REQUIREMENTS,
    ProjectPhase.ANALYSIS, ProjectPhase.PRIORITISATION, ProjectPhase.AGILE_SCRUM,
    ProjectPhase.TESTING, ProjectPhase.HANDOVER,
]

PHASE_AGENT_MAP = {
    ProjectPhase.PRE_DISCOVERY: ["A01"],
    ProjectPhase.DISCOVERY: ["A01", "A02", "A03"],
    ProjectPhase.REQUIREMENTS: ["A04", "A05", "A07", "A09_process"],
    ProjectPhase.ANALYSIS: ["A06", "A09_fsd", "A10"],
    ProjectPhase.PRIORITISATION: ["A08"],
    ProjectPhase.AGILE_SCRUM: ["A04", "A08", "A14"],
    ProjectPhase.TESTING: ["A11", "A12", "A06"],
    ProjectPhase.HANDOVER: ["A13"],
}

DEPENDENCY_MAP = {
    "brief": ["stakeholder", "requirement"],
    "stakeholder": ["requirement"],
    "requirement": ["risk_score", "test_script", "fsd_section", "process_flow", "nfr", "change_impact", "user_story"],
    "nfr": ["test_script", "change_impact", "user_story"], "risk_score": ["change_impact", "user_story"], "process_flow": ["fsd_section"],
    "fsd_section": ["test_script", "change_impact", "user_story"], "test_script": ["defect"],
    "assumption": ["requirement"], "constraint": ["requirement"],
    "change_impact": [], "user_story": ["test_script"],
}

ARTEFACT_OWNER = {
    "stakeholder": "A01", "requirement": "A04", "nfr": "A05",
    "process_flow": "A09", "risk_score": "A08", "fsd_section": "A09",
    "test_script": "A11", "defect": "A12", "constraint": "A07", "handover_doc": "A13",
    "change_impact": "A10", "user_story": "A14",
}

AGENT_ARTEFACT_TYPE = {
    "A01": "stakeholder", "A04": "requirement", "A05": "nfr",
    "A06": "traceability", "A08": "risk_score",
    "A09_ASIS": "process_flow", "A09_TOBE": "process_flow",
    "A09_FSD": "fsd_section", "A10": "change_impact", "A14": "user_story",
    "A11": "test_script", "A13": "handover_doc",
}

AGENT_DOWNSTREAM = {
    "A01": ["A04", "A06"],
    "A04": ["A09_ASIS", "A09_TOBE", "A05", "A08", "A09_FSD", "A10", "A06", "A14", "A11"],
    "A05": ["A08", "A09_FSD", "A10", "A06", "A14", "A11"],
    "A08": ["A09_FSD", "A10", "A14", "A11"],
    "A09_ASIS": [],
    "A09_TOBE": ["A09_FSD"],
    "A09_FSD": ["A10", "A06", "A14", "A11"],
    "A10": [],
    "A14": ["A11"],
    "A11": ["A13"],
    "A13": [],
    "A06": [],
}


class Orchestrator:
    def __init__(self, project_id, event_store=None):
        self.project_id = project_id
        self.current_phase = ProjectPhase.PRE_DISCOVERY
        self.event_store = event_store
        self.artefacts = {}
        self.stale_artefacts = {}

    def get_eligible_agents(self):
        return PHASE_AGENT_MAP.get(self.current_phase, [])

    def _check_agent_eligible(self, agent_id):
        eligible = self.get_eligible_agents()
        if agent_id not in eligible:
            raise ValueError(
                f"Agent {agent_id} not eligible in phase {self.current_phase.value}. "
                f"Eligible: {eligible}"
            )

    def run_agent(self, agent_id, agent_fn, agent_kwargs, artefact_type="agent_output"):
        self._check_agent_eligible(agent_id)
        invocation_id = uuid4()
        if self.event_store:
            self.event_store.log_event_sync(ChangeEvent(
                actor_type=ActorType.SYSTEM, actor_id="orchestrator",
                action=EventAction.CREATE, artefact_type=artefact_type,
                artefact_id=invocation_id,
                context=f"Agent {agent_id} invoked in phase {self.current_phase.value}",
                project_id=self.project_id,
            ))
        result = agent_fn(**agent_kwargs)
        self.artefacts[agent_id] = result
        self.stale_artefacts.pop(agent_id, None)
        if self.event_store:
            self.event_store.log_event_sync(ChangeEvent(
                actor_type=ActorType.AGENT, actor_id=agent_id,
                action=EventAction.CREATE, artefact_type=artefact_type,
                artefact_id=invocation_id,
                context=f"Agent {agent_id} completed successfully",
                project_id=self.project_id,
            ))
        return result

    def mark_stale(self, changed_artefact_type, reason=None, changed_fields=None):
        downstream = self.get_downstream(changed_artefact_type)
        stale_agents = []
        impact_details = []
        for dep in downstream:
            owner = dep["owning_agent"]
            if owner in self.artefacts:
                impact_entry = {
                    "agent": owner, "artefact_type": dep["artefact_type"],
                    "reason": reason or f"{changed_artefact_type} changed",
                    "severity": "high" if dep["artefact_type"] in ("fsd_section", "test_script") else "medium",
                    "changed_fields": changed_fields,
                }
                self.stale_artefacts[owner] = impact_entry
                stale_agents.append(owner)
                impact_details.append(impact_entry)
        if self.event_store and stale_agents:
            self.event_store.log_event_sync(ChangeEvent(
                actor_type=ActorType.SYSTEM, actor_id="orchestrator",
                action=EventAction.UPDATE, artefact_type=changed_artefact_type,
                artefact_id=self.project_id,
                diff={"stale_agents": stale_agents, "impact_details": impact_details},
                context=reason or f"Downstream artefacts marked stale due to {changed_artefact_type} change",
                project_id=self.project_id,
            ))
        return stale_agents

    def transition_phase_sync(self, target, override_reason=None):
        ci = PHASE_ORDER.index(self.current_phase)
        ti = PHASE_ORDER.index(target)
        if ti < ci and not override_reason:
            raise ValueError("Cannot move backwards without override")
        if ti > ci + 1 and not override_reason:
            raise ValueError("Skipping phases requires override")
        old = self.current_phase
        self.current_phase = target
        if self.event_store:
            self.event_store.log_event_sync(ChangeEvent(
                actor_type=ActorType.BA if override_reason else ActorType.SYSTEM,
                actor_id="ba_user" if override_reason else "orchestrator",
                action=EventAction.UPDATE, artefact_type="project",
                artefact_id=self.project_id,
                diff={"phase": {"old": old.value, "new": target.value}},
                context=override_reason or f"{old.value} -> {target.value}",
                project_id=self.project_id,
            ))
        return True

    def get_downstream(self, artefact_type):
        affected, visited, queue = [], set(), list(DEPENDENCY_MAP.get(artefact_type, []))
        while queue:
            dt = queue.pop(0)
            if dt in visited: continue
            visited.add(dt)
            affected.append({"artefact_type": dt, "owning_agent": ARTEFACT_OWNER.get(dt, "?")})
            queue.extend(DEPENDENCY_MAP.get(dt, []))
        return affected

    def get_status(self):
        return {
            "project_id": str(self.project_id),
            "current_phase": self.current_phase.value,
            "phase_index": PHASE_ORDER.index(self.current_phase),
            "eligible_agents": self.get_eligible_agents(),
            "artefacts_generated": list(self.artefacts.keys()),
            "stale_artefacts": dict(self.stale_artefacts),
            "event_count": self.event_store.get_event_count_sync(self.project_id) if self.event_store else 0,
        }


# ══════════════════════════════════════════════════════════════════════════════
#  SECTION 7: AGENTS (A01, A04, A05, A06, A08, A09, A10, A14, A11, A13)
# ══════════════════════════════════════════════════════════════════════════════

A01_SYSTEM = """You are the Elicitation Prep Agent (A01) for a BA Workflow Assistant 
specialised in Life Sciences Commercial (CRM, HCP data).

BABOK grounding: KA1 Task 2.2 (Stakeholder Analysis) + KA2 Task 3.1 (Prepare for Elicitation).

Given a raw project brief, you must:
1. Identify all stakeholders mentioned or implied (include LS-specific: Regulatory Affairs, Medical Affairs, QA, Clinical Ops, IT)
2. Classify each by type: sponsor, domain_sme, end_user, implementation_sme, regulator, tester
3. Assign influence level: high/medium/low
4. Suggest RACI roles per stakeholder
5. Generate targeted interview questions per stakeholder type
6. Flag LS Commercial regulatory stakeholders

Respond in valid JSON only. No markdown."""

A01_SCHEMA = {
    "stakeholders": [{"name": "str", "role": "str", "stakeholder_type": "str", "influence_level": "str", "raci_role": "str", "reasoning": "str"}],
    "interview_guide": {"sponsor": ["questions"], "domain_sme": ["questions"], "end_user": ["questions"], "regulator": ["questions"]},
    "ls_regulatory_flags": ["str"],
    "assumptions": ["str"],
}

def run_a01(api_key, brief_text, project_context=None, corrections=None):
    sub = project_context.get("sub_domain", "commercial") if project_context else "commercial"
    user_prompt = f"Analyse this brief and produce stakeholder analysis with interview prep.\n\nPROJECT BRIEF:\n{brief_text}\n\nDomain: Life Sciences Commercial. Sub-domain: {sub}"
    if corrections:
        user_prompt += f"\n\nBA CORRECTIONS (incorporate these changes — they take priority over your initial analysis):\n{corrections}"
    return call_llm_structured(
        api_key=api_key,
        system_prompt=A01_SYSTEM,
        user_prompt=user_prompt,
        output_schema=A01_SCHEMA,
    )


# ── A04: BRD Structuring (P1 — multi-audience) ──────────────────────────────

A04_SYSTEM = """You are the BRD Structuring Agent (A04) for a BA Workflow Assistant 
specialised in Life Sciences Commercial (CRM, HCP data).

BABOK grounding: KA3 Task 4.4 (Prepare Requirements Package) + KA5 Task 6.3 (Specify and Model) + KA5 Task 6.4 (Define Assumptions and Constraints) + KA5 Task 6.5 (Verify).

You solve P1: The Multi-Audience Document Problem. From raw input produce a structured BRD with
introduction, business objectives, structured functional requirements, and supporting artefacts.

## Executive Summary (mandatory — appears at top of BRD):
Provide a concise executive summary covering:
- project_name: extracted or inferred from the brief
- purpose: 2-3 sentences on WHY this project exists — the business problem being solved
- business_drivers: key business drivers (e.g. regulatory compliance, operational efficiency, revenue growth)
- expected_outcomes: measurable expected outcomes (e.g. "reduce call logging time by 60%")
- target_users: who will use the solution
- timeline_indication: any timeline references from the brief
- regulatory_context: LS regulatory context (GxP applicability, 21CFR Part 11, ALCOA+)

## Business Objectives (BABOK KA4 Task 5.1 — mandatory):
Before listing requirements, define the business objectives that requirements serve:
- Unique ID (OBJ-001 format)
- objective: what the business wants to achieve
- success_metric: how success is measured
- priority: critical/high/medium/low
- linked_requirement_ids: which requirements serve this objective

## Functional Requirements — THREE audience views per requirement:
1. BUSINESS SUMMARY — Non-technical, outcome-focused. For sponsors. Min 2 sentences.
2. FUNCTIONAL SPEC — BA/analyst-readable. Structured with acceptance criteria. Min 3 sentences.
3. TECHNICAL NOTES — Architect-level. Integration points, data flows, constraints. Min 3 sentences.

## Requirements rules:
- Every requirement: unique ID (REQ-001), description, acceptance criteria
- Flag ambiguous language: should, might, could, would, may, as needed, if possible
- Flag LS regulatory concerns: 21CFR Part 11, HCP data, ALCOA+, GxP
- Mark assumptions explicitly
- Trace each requirement to a stakeholder source
- Link each requirement to at least one business objective (OBJ-xxx)

## Dependencies (mandatory):
For EACH dependency provide:
- Unique ID (DEP-001 format)
- description: what the dependency is
- type: one of: System, Data, Team, Third-party, Regulatory, Infrastructure
- dependent_requirement_ids: which requirements depend on this
- owner: who is responsible for resolving this dependency
- status: identified/in-progress/resolved/blocked
- risk_if_unresolved: consequence if this dependency is not resolved
Generate AT LEAST 4 dependencies. In LS domain always include: CRM system availability,
regulatory approval dependencies, data migration dependencies, and integration readiness.

## Assumptions log (BABOK KA5 Task 6.4 — mandatory):
For EACH assumption provide:
- Unique ID (ASM-001 format)
- description: what is being assumed
- source: which requirement or context drives this assumption
- risk_if_wrong: specific consequence if this assumption is invalid
- validation_method: how to verify this assumption (e.g. "confirm with IT architect", "validate in workshop")
Generate AT LEAST 5 assumptions. Common sources: technology stack, stakeholder availability,
data availability, integration readiness, regulatory interpretation, timeline feasibility.

## Constraint register (BABOK KA5 Task 6.4 — mandatory):
For EACH constraint provide:
- Unique ID (CON-001 format)
- type: exactly one of: Technical, Regulatory, Budget, Timeline, Resource, Organisational
- description: the constraint itself
- impact: how this constraint affects solution design or delivery
- source: where this constraint originates (e.g. "client brief", "regulatory requirement", "enterprise architecture")
Generate AT LEAST 4 constraints. In LS domain always include regulatory constraints.

## Scope boundaries (BABOK KA4 Task 5.4 — mandatory):
- in_scope: list of items explicitly IN scope with clear descriptions (not single words)
- out_of_scope: each item must have the item AND a reason why it is excluded
- scope_dependencies: external dependencies that could affect scope (systems, teams, decisions)

## Glossary (BABOK Technique 9.5 — mandatory):
For EACH term provide:
- term: the domain/technical term
- definition: clear definition accessible to all stakeholders
- context: where this term is used (e.g. "Used in REQ-003 and REQ-007")
Generate AT LEAST 6 glossary entries. In LS domain include: HCP, CRM, any regulatory terms,
any system names, domain-specific abbreviations.

## Data dictionary (BABOK Technique 9.5 — mandatory):
For EACH data entity identified in the requirements, provide:
- Unique ID (DE-001 format)
- entity_name: name of the data entity (e.g. "HCP Profile", "Call Report", "Adverse Event")
- description: what this entity represents in the business context
- attributes: list of attributes, each with:
  - name: attribute name
  - data_type: string, integer, date, boolean, enum, text, decimal, uuid
  - required: true/false
  - validation_rules: constraints (e.g. "max 255 chars", "valid email format", "ISO 8601")
  - sample_value: example value
- data_owner: who owns this data (stakeholder role)
- source_system: where this data originates
- alcoa_classification: ALCOA+ data integrity classification — one of: Critical (audit trail required), Standard (logging required), Reference (read-only)
- hcp_data_flag: true if this entity contains HCP personal/interaction data (GDPR/privacy implications)
- regulatory_flags: list of applicable regulations (e.g. "21CFR Part 11", "GDPR Article 17")
- requirement_ids: which requirements reference this entity
Generate AT LEAST 4 data entities. In LS Commercial domain always include entities for:
HCP data, interaction/call data, any regulated data flows, and system audit data.

## Open questions:
List questions that MUST be answered before development. Each question should reference
which requirement or assumption it relates to.

Respond in valid JSON only. No markdown."""

A04_SCHEMA = {
    "executive_summary": {
        "project_name": "str", "purpose": "str", "business_drivers": ["str"],
        "expected_outcomes": ["str"], "target_users": ["str"],
        "timeline_indication": "str or null", "regulatory_context": "str",
    },
    "business_objectives": [{"id": "OBJ-001", "objective": "str", "success_metric": "str",
        "priority": "critical|high|medium|low", "linked_requirement_ids": ["REQ-001"]}],
    "requirements": [{"id": "REQ-001", "text": "str", "type": "functional|non_functional",
        "acceptance_criteria": "str", "source_stakeholder": "str", "priority_suggestion": "must|should|could|wont",
        "business_summary": "str", "functional_spec": "str", "technical_notes": "str",
        "linked_objective_ids": ["OBJ-001"],
        "assumptions": ["str"], "ambiguity_flags": ["str"], "ls_regulatory_flags": ["str"]}],
    "dependencies": [{"id": "DEP-001", "description": "str",
        "type": "System|Data|Team|Third-party|Regulatory|Infrastructure",
        "dependent_requirement_ids": ["REQ-001"], "owner": "str",
        "status": "identified|in-progress|resolved|blocked", "risk_if_unresolved": "str"}],
    "assumptions_log": [{"id": "ASM-001", "description": "str", "source": "str", "risk_if_wrong": "str", "validation_method": "str"}],
    "constraint_register": [{"id": "CON-001", "type": "Technical|Regulatory|Budget|Timeline|Resource|Organisational", "description": "str", "impact": "str", "source": "str"}],
    "scope_boundaries": {
        "in_scope": ["str — clear description of what is included"],
        "out_of_scope": [{"item": "str", "reason": "str"}],
        "scope_dependencies": ["str — external dependencies affecting scope"]
    },
    "glossary": [{"term": "str", "definition": "str", "context": "str"}],
    "data_dictionary": [{"id": "DE-001", "entity_name": "str", "description": "str",
        "attributes": [{"name": "str", "data_type": "str", "required": True, "validation_rules": "str", "sample_value": "str"}],
        "data_owner": "str", "source_system": "str",
        "alcoa_classification": "Critical|Standard|Reference",
        "hcp_data_flag": False, "regulatory_flags": ["str"], "requirement_ids": ["REQ-001"]}],
    "open_questions": ["str"],
}

def run_a04(api_key, brief_text, stakeholder_analysis=None, elicitation_notes=None, corrections=None):
    parts = [f"PROJECT BRIEF:\n{brief_text}"]
    if stakeholder_analysis:
        parts.append(f"\nSTAKEHOLDER ANALYSIS (from A01):\n{json.dumps(stakeholder_analysis, indent=2)}")
    if elicitation_notes:
        parts.append(f"\nELICITATION NOTES:\n{elicitation_notes}")
    parts.append("\nDOMAIN: Life Sciences Commercial (CRM, HCP Data)")
    parts.append("\nProvide all three audience views per requirement. Flag LS regulatory concerns and ambiguity.")
    if corrections:
        parts.append(f"\nBA CORRECTIONS (incorporate these changes — they take priority over your initial analysis):\n{corrections}")
    return call_llm_structured(
        api_key=api_key,
        system_prompt=A04_SYSTEM,
        user_prompt="\n".join(parts),
        output_schema=A04_SCHEMA,
    )


# ── A05: NFR Library (P2 — auto-suggest) ────────────────────────────────────

A05_SYSTEM = """You are the NFR Library Agent (A05) for a BA Workflow Assistant 
specialised in Life Sciences Commercial.

BABOK grounding: Technique 9.17 (Non-functional Requirements Analysis) + ISO 9126/25010.

You solve P2: NFRs discovered too late.

Given functional requirements and a pre-built NFR library:
1. Determine which NFRs apply to THIS project
2. For GxP systems, auto-include all GxP-default NFRs
3. Suggest values (may differ from defaults based on context)
4. Flag NFRs needing tech architect validation
5. Identify project-specific NFRs not in the library

Respond in valid JSON only. No markdown."""

A05_SCHEMA = {
    "applicable_nfrs": [{"category": "str", "name": "str", "suggested_value": "str",
        "library_default": "str", "is_gxp_default": True, "applicability_reasoning": "str", "needs_tech_arch_review": False}],
    "project_specific_nfrs": [{"category": "str", "name": "str", "suggested_value": "str", "reasoning": "str"}],
    "review_prompts": ["str"],
}

def run_a05(api_key, requirements, project_context=None, system_type="gxp", corrections=None):
    library_suggestions = get_nfr_suggestions(system_type)
    user_prompt = f"Determine applicable NFRs.\n\nREQUIREMENTS:\n{json.dumps(requirements, indent=2)}\n\nNFR LIBRARY ({system_type}):\n{json.dumps(library_suggestions, indent=2)}\n\nDomain: LS Commercial. System type: {system_type}."
    if corrections:
        user_prompt += f"\n\nBA CORRECTIONS (incorporate these changes — they take priority over your initial analysis):\n{corrections}"
    return call_llm_structured(
        api_key=api_key,
        system_prompt=A05_SYSTEM,
        user_prompt=user_prompt,
        output_schema=A05_SCHEMA,
    )


# ── A06: Traceability ───────────────────────────────────────────────────────

A06_SYSTEM = """You are the Traceability Agent (A06). BABOK: KA3 Task 4.2 (Manage Requirements Traceability).

Given requirements, stakeholders, and NFRs:
1. Create traceability matrix: each requirement linked to source
2. Identify dependencies between requirements (DEPENDS_ON)
3. Map NFRs to functional requirements they constrain
4. Flag orphan requirements (no source) or isolated ones (no dependencies)

Respond in valid JSON only. No markdown."""

A06_SCHEMA = {
    "traceability_matrix": [{"requirement_id": "str", "source": "str", "depends_on": ["str"],
        "depended_by": ["str"], "related_nfrs": ["str"], "status": "traced|orphan|partial"}],
    "dependency_chains": [{"chain_name": "str", "requirements": ["str"], "risk_note": "str"}],
    "coverage_summary": {"total_requirements": 0, "fully_traced": 0, "orphans": 0, "dependency_chains_identified": 0},
}

def run_a06(api_key, requirements, stakeholders=None, nfrs=None, corrections=None):
    user_prompt = f"Build RTM.\n\nREQUIREMENTS:\n{json.dumps(requirements, indent=2)}\n\nSTAKEHOLDERS:\n{json.dumps(stakeholders or [], indent=2)}\n\nNFRs:\n{json.dumps(nfrs or [], indent=2)}"
    if corrections:
        user_prompt += f"\n\nBA CORRECTIONS (incorporate these changes — they take priority over your initial analysis):\n{corrections}"
    return call_llm_structured(
        api_key=api_key,
        system_prompt=A06_SYSTEM,
        user_prompt=user_prompt,
        output_schema=A06_SCHEMA,
    )


# ── A08: Priority + Risk (P3, P10) ──────────────────────────────────────────

A08_SYSTEM = """You are the Priority + Risk Agent (A08) for Life Sciences Commercial.

BABOK: KA5 Task 6.1 (Prioritize — MoSCoW per 6.1.5) + KA4 Task 5.5.4 (Risk) + T 9.24 (Risk Analysis).

Solves P3 (risk inconsistency), P4 (late feasibility), P10 (LS regulatory weighting).

Score each requirement on 4 axes (1-5):
1. REGULATORY EXPOSURE (weight 2x) — regulated data/processes? LS: weighted DOUBLE.
2. INTEGRATION COMPLEXITY (1x) — systems touched?
3. STAKEHOLDER DEPENDENCY (1x) — groups to align?
4. IMPLEMENTATION AMBIGUITY (1x) — clarity level?

Weighted total (max 25): Critical 20-25, High 15-19, Medium 10-14, Low 5-9.
Also assign MoSCoW: Must, Should, Could, Wont.

Respond in valid JSON only. No markdown."""

A08_SCHEMA = {
    "scored_requirements": [{"requirement_id": "str", "requirement_text": "str",
        "moscow_priority": "must|should|could|wont", "moscow_reasoning": "str",
        "risk_scores": {
            "regulatory_exposure": {"score": 3, "reasoning": "str"},
            "integration_complexity": {"score": 2, "reasoning": "str"},
            "stakeholder_dependency": {"score": 2, "reasoning": "str"},
            "implementation_ambiguity": {"score": 1, "reasoning": "str"}},
        "weighted_total": 11, "risk_tier": "medium",
        "suggested_controls": ["str"], "feasibility_flags": ["str"]}],
    "risk_register_summary": {"critical_count": 0, "high_count": 0, "medium_count": 0, "low_count": 0, "top_risks": ["str"]},
    "prioritised_backlog": ["str"],
}

def run_a08(api_key, requirements, project_context=None, nfrs=None, corrections=None):
    user_prompt = f"Score and prioritise.\n\nREQUIREMENTS:\n{json.dumps(requirements, indent=2)}\n\nNFRs:\n{json.dumps(nfrs or [], indent=2)}\n\nRISK CONFIG:\n{json.dumps(RISK_SCORING_CONFIG, indent=2)}\n\nDomain: LS Commercial — regulatory axis 2x."
    if corrections:
        user_prompt += f"\n\nBA CORRECTIONS (incorporate these changes — they take priority over your initial analysis):\n{corrections}"
    return call_llm_structured(
        api_key=api_key,
        system_prompt=A08_SYSTEM,
        user_prompt=user_prompt,
        output_schema=A08_SCHEMA,
    )



# ── A09: Process Flow Agent (AS-IS + TO-BE) ─────────────────────────────────

A09_ASIS_SYSTEM = """You are a Senior Business Analyst documenting the CURRENT STATE (AS-IS) process.
BABOK grounding: KA4 Strategy Analysis + KA5 Task 6.2 (Organize Requirements) + Technique 9.21 (Process Modeling).

Given a project brief describing current pain points, document:
1. AS-IS process flow — what the business does TODAY before the solution
2. Include pain_point nodes for every problem/inefficiency in the current process
3. gap_summary — 2-3 sentences connecting AS-IS pain points to the requirements

BPMN 2.0 conventions:
- lanes: 2-3 actor swimlanes matching CURRENT state actors
- nodes: 6-10 nodes. Types: start, end, process, decision, document, pain_point
- pain_point nodes: label MUST start with "PAIN:" — these show where current process breaks
- Every flow starts with "start" and ends with "end"
- Decision nodes have exactly 2 outgoing edges labelled Yes/No or similar
- title: descriptive e.g. "Current HCP Call Reporting Process"

Respond in valid JSON only. No markdown."""

A09_TOBE_SYSTEM = """You are a Senior Business Analyst documenting the FUTURE STATE (TO-BE) process.
BABOK grounding: KA5 Task 6.2 (Organize Requirements) + Technique 9.21 (Process Modeling).

Given functional requirements from a BRD, document the TO-BE process flow showing
how the business will work AFTER the solution is implemented.

BPMN 2.0 conventions:
- lanes: 2-3 actor swimlanes for the future state
- nodes: 6-10 nodes. Types: start, end, process, decision, document
- Every flow starts with "start" and ends with "end"
- Decision nodes have exactly 2 outgoing edges
- title: descriptive e.g. "Future HCP Call Logging Process"
- Show how the new system automates or improves the pain points from AS-IS

Respond in valid JSON only. No markdown."""

A09_FLOW_SCHEMA = {
    "flow": {
        "title": "str",
        "lanes": ["str"],
        "nodes": [{"id": "str", "label": "str", "type": "start|end|process|decision|document|pain_point", "lane": "str"}],
        "edges": [{"from_id": "str", "to_id": "str", "label": "str"}]
    },
    "gap_summary": "str"
}

A09_TOBE_SCHEMA = {
    "flow": {
        "title": "str",
        "lanes": ["str"],
        "nodes": [{"id": "str", "label": "str", "type": "start|end|process|decision|document", "lane": "str"}],
        "edges": [{"from_id": "str", "to_id": "str", "label": "str"}]
    }
}

def run_a09_asis(api_key, brief_text, requirements=None, corrections=None):
    """Generate AS-IS process flow from the project brief."""
    req_summary = ""
    if requirements:
        req_summary = "\n\nFunctional requirements already defined:\n" + "\n".join(
            [f"- {r.get('id','')}: {r.get('text','')[:60]}" for r in requirements[:8]]
        )
    user_prompt = f"Document the CURRENT STATE (AS-IS) process from this brief.\n\nBRIEF:\n{brief_text}{req_summary}\n\nInclude pain_point nodes for every problem mentioned. Generate gap_summary connecting AS-IS issues to requirements."
    if corrections:
        user_prompt += f"\n\nBA CORRECTIONS (incorporate these changes — they take priority over your initial analysis):\n{corrections}"
    return call_llm_structured(
        api_key=api_key,
        system_prompt=A09_ASIS_SYSTEM,
        user_prompt=user_prompt,
        output_schema=A09_FLOW_SCHEMA,
    )

def run_a09_tobe(api_key, brief_text, requirements=None, corrections=None):
    """Generate TO-BE process flow from requirements."""
    req_text = ""
    if requirements:
        req_text = "\n\nFunctional requirements:\n" + "\n".join(
            [f"- {r.get('id','')}: {r.get('text','')}" for r in requirements[:10]]
        )
    user_prompt = f"Document the FUTURE STATE (TO-BE) process.\n\nBRIEF:\n{brief_text}{req_text}\n\nShow how the solution addresses the current problems."
    if corrections:
        user_prompt += f"\n\nBA CORRECTIONS (incorporate these changes — they take priority over your initial analysis):\n{corrections}"
    return call_llm_structured(
        api_key=api_key,
        system_prompt=A09_TOBE_SYSTEM,
        user_prompt=user_prompt,
        output_schema=A09_TOBE_SCHEMA,
    )


# ── A09: FSD — Functional Specification Document (Analysis phase) ────────────

A09_FSD_SYSTEM = """You are a Senior Business Analyst producing a Functional Specification Document (FSD)
for a BA Workflow Assistant specialised in Life Sciences Commercial (CRM, HCP data).

BABOK grounding: KA6 Task 7.1 (Assess Proposed Solution) + KA6 Task 7.2 (Allocate Requirements
to solution components) + Technique 9.26 (Scenarios and Use Cases).

Given approved BRD requirements, stakeholder analysis, NFRs, and process flows, produce an FSD that:
1. Allocates each requirement to a specific solution component/module
2. Defines functional modules with: purpose, inputs, outputs, processing logic, constraints
3. Maps system interactions between modules (data flows, API calls, triggers)
4. Generates use cases in structured format (actor, precondition, main flow, alt flows, postcondition)
5. Identifies integration points with external systems (CRM, HCP databases, regulatory systems)
6. Flags LS regulatory considerations per module (21CFR Part 11, ALCOA+, GxP validation)
7. Notes technical constraints and assumptions per module

## FSD Structure Rules:
- Every module gets a unique ID (MOD-001 format)
- Every use case gets a unique ID (UC-001 format)
- Each module must trace back to at least one requirement ID
- Integration points must specify: source system, target system, data exchanged, protocol/method
- LS regulatory modules must flag validation requirements (IQ/OQ/PQ applicability)

Respond in valid JSON only. No markdown."""

A09_FSD_SCHEMA = {
    "fsd_title": "str",
    "solution_overview": "str — 3-5 sentence summary of the proposed solution architecture",
    "modules": [
        {
            "id": "MOD-001",
            "name": "str",
            "purpose": "str",
            "requirement_ids": ["REQ-001"],
            "inputs": [{"name": "str", "source": "str", "format": "str"}],
            "outputs": [{"name": "str", "destination": "str", "format": "str"}],
            "processing_logic": "str — step-by-step processing description",
            "business_rules": ["str"],
            "constraints": ["str"],
            "ls_regulatory_flags": ["str"],
            "gxp_validation_required": False,
        }
    ],
    "use_cases": [
        {
            "id": "UC-001",
            "title": "str",
            "actor": "str",
            "module_id": "MOD-001",
            "preconditions": ["str"],
            "main_flow": ["str — numbered steps"],
            "alternative_flows": [{"condition": "str", "steps": ["str"]}],
            "postconditions": ["str"],
            "requirement_ids": ["REQ-001"],
        }
    ],
    "integration_points": [
        {
            "id": "INT-001",
            "source_system": "str",
            "target_system": "str",
            "data_exchanged": "str",
            "method": "str — API/batch/event/manual",
            "frequency": "str",
            "requirement_ids": ["REQ-001"],
        }
    ],
    "data_flows": [
        {"from_module": "str", "to_module": "str", "data_description": "str"}
    ],
    "open_design_decisions": ["str"],
}

def run_a09_fsd(api_key, brief_text, requirements=None, stakeholders=None, nfrs=None,
                process_flows=None, risk_scores=None, corrections=None):
    """Generate FSD from approved BRD requirements — Analysis phase (KA6 7.2)."""
    parts = [f"PROJECT BRIEF:\n{brief_text}"]
    if requirements:
        parts.append(f"\nAPPROVED REQUIREMENTS (from BRD):\n{json.dumps(requirements, indent=2)}")
    if stakeholders:
        parts.append(f"\nSTAKEHOLDERS:\n{json.dumps(stakeholders, indent=2)}")
    if nfrs:
        parts.append(f"\nNON-FUNCTIONAL REQUIREMENTS:\n{json.dumps(nfrs, indent=2)}")
    if process_flows:
        parts.append(f"\nPROCESS FLOWS (TO-BE):\n{json.dumps(process_flows, indent=2)}")
    if risk_scores:
        scored = risk_scores.get("scored_requirements", [])
        high_risk = [s for s in scored if s.get("risk_tier") in ("critical", "high")]
        if high_risk:
            parts.append(f"\nHIGH/CRITICAL RISK REQUIREMENTS (prioritise design rigour):\n{json.dumps(high_risk, indent=2)}")
    parts.append("\nDOMAIN: Life Sciences Commercial (CRM, HCP Data)")
    parts.append("\nAllocate requirements to solution modules. Include use cases, integration points, and LS regulatory flags.")
    if corrections:
        parts.append(f"\nBA CORRECTIONS (incorporate these changes — they take priority over your initial analysis):\n{corrections}")
    return call_llm_structured(
        api_key=api_key,
        system_prompt=A09_FSD_SYSTEM,
        user_prompt="\n".join(parts),
        output_schema=A09_FSD_SCHEMA,
    )


# ── A10: Change Impact Agent (Analysis phase) ───────────────────────────────

A10_SYSTEM = """You are the Change Impact Agent (A10) for a BA Workflow Assistant
specialised in Life Sciences Commercial (CRM, HCP data).

BABOK grounding: KA3 Task 4.1 (Manage Solution Scope & Requirements — change impact assessment).

Given ALL current project artefacts (requirements, FSD modules, NFRs, risk scores, process flows,
stakeholders, traceability matrix), produce a comprehensive change impact assessment that shows:
1. Which artefacts are affected by each requirement and how they interconnect
2. Impact severity per downstream artefact (critical/high/medium/low)
3. Risk delta: how changes to high-risk requirements cascade
4. Recommended actions for the BA when reviewing changes
5. Dependency chains that create single points of failure
6. LS regulatory impact: flag any changes touching regulated data flows or GxP-validated components

## Impact severity rules:
- CRITICAL: Change breaks a validated/regulated component (GxP, 21CFR Part 11)
- HIGH: Change affects 3+ downstream artefacts or crosses module boundaries
- MEDIUM: Change affects 1-2 downstream artefacts within same module
- LOW: Cosmetic or documentation-only impact

## Output structure:
For each requirement, assess its change impact footprint across all artefact types.
Identify the highest-risk change chains (sequences where one change triggers many downstream changes).
Flag requirements that are "change amplifiers" — single changes that affect disproportionate downstream artefacts.

Respond in valid JSON only. No markdown."""

A10_SCHEMA = {
    "impact_assessment": [{
        "requirement_id": "str",
        "requirement_text": "str",
        "change_footprint": {
            "affected_fsd_modules": [{"module_id": "str", "module_name": "str", "impact_severity": "critical|high|medium|low", "impact_description": "str"}],
            "affected_nfrs": [{"nfr_name": "str", "impact_severity": "critical|high|medium|low", "impact_description": "str"}],
            "affected_process_flows": [{"flow_type": "as-is|to-be", "impact_description": "str"}],
            "affected_test_scripts": [{"description": "str", "impact_severity": "critical|high|medium|low"}],
            "affected_stakeholders": [{"name": "str", "impact_type": "str"}],
        },
        "total_affected_artefacts": 0,
        "max_severity": "critical|high|medium|low",
        "is_change_amplifier": False,
        "regulatory_impact": [{"regulation": "str", "impact": "str"}],
        "recommended_actions": ["str"],
    }],
    "change_chains": [{
        "chain_name": "str",
        "trigger_requirement": "str",
        "chain_sequence": ["str — artefact1 → artefact2 → artefact3"],
        "total_depth": 0,
        "risk_level": "critical|high|medium|low",
        "description": "str",
    }],
    "change_amplifiers": [{
        "requirement_id": "str",
        "downstream_count": 0,
        "reason": "str",
    }],
    "summary": {
        "total_requirements_assessed": 0,
        "critical_impact_count": 0,
        "high_impact_count": 0,
        "medium_impact_count": 0,
        "low_impact_count": 0,
        "change_amplifier_count": 0,
        "longest_chain_depth": 0,
        "regulatory_impact_count": 0,
    },
}

def run_a10(api_key, requirements, fsd_modules=None, nfrs=None, risk_scores=None,
            process_flows=None, stakeholders=None, traceability=None, corrections=None):
    """Generate change impact assessment — Analysis phase (KA3 4.1)."""
    parts = [f"REQUIREMENTS:\n{json.dumps(requirements, indent=2)}"]
    if fsd_modules:
        parts.append(f"\nFSD MODULES:\n{json.dumps(fsd_modules, indent=2)}")
    if nfrs:
        parts.append(f"\nNON-FUNCTIONAL REQUIREMENTS:\n{json.dumps(nfrs, indent=2)}")
    if risk_scores:
        scored = risk_scores.get("scored_requirements", [])
        parts.append(f"\nRISK SCORES:\n{json.dumps(scored, indent=2)}")
    if process_flows:
        parts.append(f"\nPROCESS FLOWS (TO-BE):\n{json.dumps(process_flows, indent=2)}")
    if stakeholders:
        parts.append(f"\nSTAKEHOLDERS:\n{json.dumps(stakeholders, indent=2)}")
    if traceability:
        parts.append(f"\nTRACEABILITY MATRIX:\n{json.dumps(traceability, indent=2)}")
    parts.append("\nDOMAIN: Life Sciences Commercial (CRM, HCP Data)")
    parts.append("\nAssess change impact for every requirement. Identify change amplifiers and dependency chains.")
    if corrections:
        parts.append(f"\nBA CORRECTIONS (incorporate these changes — they take priority over your initial analysis):\n{corrections}")
    return call_llm_structured(
        api_key=api_key,
        system_prompt=A10_SYSTEM,
        user_prompt="\n".join(parts),
        output_schema=A10_SCHEMA,
    )


# ── A14: Agile/Sprint Agent (Agile/Scrum phase) ─────────────────────────────

A14_SYSTEM = """You are the Agile/Sprint Agent (A14) for a BA Workflow Assistant
specialised in Life Sciences Commercial (CRM, HCP data).

BABOK grounding: T 9.33 (User Stories) + T 9.1 (Acceptance and Evaluation Criteria) +
KA1 Task 2.1.4 (change-driven approaches) + KA5 Task 6.5 (Verify Requirements — DoR) +
KA6 Task 7.2 (Allocate Requirements — release allocation).

Given prioritised requirements with MoSCoW classification and risk scores, produce:

## 1. User Stories (T 9.33 — mandatory)
For EACH functional requirement, generate one or more user stories:
- Unique ID (US-001 format)
- story: "As a [actor], I want [goal], so that [benefit]"
- actor: specific stakeholder role (not generic "user")
- requirement_ids: which requirements this story implements
- module_id: which FSD module this maps to (if available)
- story_points: fibonacci estimate (1, 2, 3, 5, 8, 13)
- moscow: inherited from requirement priority
- sprint_suggestion: which sprint (Sprint 1, Sprint 2, etc.)
- dependencies: other user story IDs this depends on

## 2. Acceptance Criteria (T 9.1 — mandatory, Given/When/Then format)
For EACH user story, generate AT LEAST 2 acceptance criteria:
- id: AC-001 format
- story_id: parent user story ID
- given: precondition state
- when: action performed
- then: expected outcome
- is_regulatory: true if this AC validates a regulatory requirement

## 3. Product Backlog (KA5 6.1 output — mandatory)
Ordered list of all user stories ranked by:
- MoSCoW priority (Must first)
- Risk tier (Critical/High first within same MoSCoW)
- Dependencies (predecessors before dependents)
Include story points total per sprint and per release.

## 4. Release Plan (KA6 7.2 — mandatory)
Map MoSCoW tiers to releases:
- Release 1 (MVP): All MUST stories
- Release 2: All SHOULD stories
- Release 3: All COULD stories
- Deferred: WONT stories
For each release: total story points, estimated sprint count (velocity assumption: state it), key risks.

## 5. Definition of Ready (DoR) — KA5 6.5 grounded
Project-level checklist. A requirement/story is ready when all items are true.
Generate AT LEAST 8 DoR items. In LS domain include regulatory-specific readiness checks.

## 6. Definition of Done (DoD) — T 9.1 grounded
Project-level checklist. A story is done when all items are true.
Generate AT LEAST 8 DoD items. In LS domain include: GxP validation sign-off, audit trail verification,
ALCOA+ compliance check, regulatory documentation updated.

## LS Commercial Enrichment:
- Auto-generate regulatory user stories for GxP requirements (audit trail, e-signatures, data integrity)
- Flag stories touching HCP data with privacy acceptance criteria
- Include GxP validation acceptance criteria for regulated modules

Respond in valid JSON only. No markdown."""

A14_SCHEMA = {
    "user_stories": [{
        "id": "US-001",
        "story": "As a [actor], I want [goal], so that [benefit]",
        "actor": "str",
        "requirement_ids": ["REQ-001"],
        "module_id": "MOD-001 or null",
        "story_points": 3,
        "moscow": "must|should|could|wont",
        "sprint_suggestion": "Sprint 1",
        "dependencies": ["US-000"],
        "is_regulatory": False,
        "ls_regulatory_flags": ["str"],
    }],
    "acceptance_criteria": [{
        "id": "AC-001",
        "story_id": "US-001",
        "given": "str — precondition",
        "when": "str — action",
        "then": "str — expected outcome",
        "is_regulatory": False,
    }],
    "product_backlog": {
        "ranked_stories": ["US-001"],
        "total_story_points": 0,
        "sprint_breakdown": [{"sprint": "Sprint 1", "story_ids": ["US-001"], "story_points": 0}],
    },
    "release_plan": {
        "velocity_assumption": "str — e.g. 20 story points per sprint",
        "releases": [{
            "release": "Release 1 (MVP)",
            "moscow_tier": "must",
            "story_ids": ["US-001"],
            "total_story_points": 0,
            "estimated_sprints": 0,
            "key_risks": ["str"],
        }],
    },
    "definition_of_ready": ["str — DoR checklist item"],
    "definition_of_done": ["str — DoD checklist item"],
}

def run_a14(api_key, requirements, risk_scores=None, nfrs=None, fsd_modules=None,
            stakeholders=None, corrections=None):
    """Generate Agile/Sprint artefacts — Agile/Scrum phase (T 9.33, T 9.1, KA1 2.1.4)."""
    parts = [f"PRIORITISED REQUIREMENTS:\n{json.dumps(requirements, indent=2)}"]
    if risk_scores:
        scored = risk_scores.get("scored_requirements", [])
        parts.append(f"\nRISK SCORES & MoSCoW:\n{json.dumps(scored, indent=2)}")
    if nfrs:
        parts.append(f"\nNON-FUNCTIONAL REQUIREMENTS:\n{json.dumps(nfrs, indent=2)}")
    if fsd_modules:
        # Send module summaries only to save tokens
        mod_summary = [{"id": m.get("id"), "name": m.get("name"), "requirement_ids": m.get("requirement_ids", [])}
                       for m in fsd_modules]
        parts.append(f"\nFSD MODULES (for story-to-module mapping):\n{json.dumps(mod_summary, indent=2)}")
    if stakeholders:
        # Send stakeholder names/types for actor identification
        stkh_summary = [{"name": s.get("name"), "role": s.get("role"), "stakeholder_type": s.get("stakeholder_type")}
                        for s in stakeholders]
        parts.append(f"\nSTAKEHOLDERS (for actor identification):\n{json.dumps(stkh_summary, indent=2)}")
    parts.append("\nDOMAIN: Life Sciences Commercial (CRM, HCP Data)")
    parts.append("\nGenerate user stories with Given/When/Then acceptance criteria. Build product backlog and release plan. Include DoR and DoD checklists.")
    if corrections:
        parts.append(f"\nBA CORRECTIONS (incorporate these changes — they take priority over your initial analysis):\n{corrections}")
    return call_llm_structured(
        api_key=api_key,
        system_prompt=A14_SYSTEM,
        user_prompt="\n".join(parts),
        output_schema=A14_SCHEMA,
    )


# ── A11: Test Script Agent (Testing phase) ──────────────────────────────────

A11_SYSTEM = """You are the Test Script Agent (A11) for a BA Workflow Assistant
specialised in Life Sciences Commercial (CRM, HCP data).

BABOK grounding: KA6 Task 7.5 (Validate Solution) + Technique 9.1 (Acceptance and Evaluation Criteria).

You solve P5: Test execution without step-level context.

IMPORTANT SCOPE BOUNDARY — BA Territory Only:
You produce FUNCTIONAL TEST CASES for business validation (UAT). You do NOT produce:
- Automated test code (Selenium, API scripts, SQL queries — QA/SDET territory)
- Unit or integration test specifications (developer territory)
- Performance/load test scenarios (QA engineering territory)
- Test environment setup instructions (DevOps territory)
Your output must be readable and executable by a business user or BA during UAT.

Given requirements, acceptance criteria (Given/When/Then), and FSD modules, produce:

## 1. Test Plan (KA6 7.5 — mandatory)
High-level testing strategy:
- test_approach: description of UAT approach
- scope: what is being tested (functional requirements)
- out_of_scope: what is NOT being tested by BA (automated, performance, security)
- entry_criteria: conditions before UAT can start
- exit_criteria: conditions for UAT sign-off
- test_environments: where UAT will be conducted (business environments, not technical)
- roles: who is involved in UAT (BA, business users, product owner — not QA engineers)

## 2. Functional Test Cases (KA6 7.5 + T 9.1 — mandatory)
For EACH requirement with acceptance criteria, generate atomic test cases:
- Unique ID (TC-001 format)
- title: short descriptive name
- requirement_ids: which requirements this tests
- user_story_id: which user story (if available)
- priority: critical/high/medium/low (inherit from requirement risk tier)
- preconditions: what must be true BEFORE the test starts (business state, not technical setup)
- test_steps: ordered list of atomic steps, each with:
  - step_number: 1, 2, 3...
  - action: what the tester DOES (business action, not technical command)
  - expected_result: what the tester should SEE or VERIFY
  - test_data: sample data to use (if applicable)
- postconditions: expected system/business state AFTER the test
- pass_criteria: how to determine pass/fail
- derived_from_ac: which acceptance criteria ID this test validates (if available)

## 3. GxP Validation Test Templates (LS domain — mandatory for regulated requirements)
For requirements flagged with regulatory concerns, generate GxP test case TEMPLATES:
- Clearly labelled as "BA-generated draft for validation team review"
- gxp_type: IQ (Installation Qualification), OQ (Operational Qualification), or PQ (Performance Qualification)
- IQ: verify system is installed/configured correctly (BA provides: what to verify, not how)
- OQ: verify system operates as specified under normal conditions (maps to functional requirements)
- PQ: verify system performs reliably over sustained use (maps to NFRs)
- Each template includes: test objective, requirement trace, expected outcome, sign-off fields
- Flag: "Requires validation team review before execution"

## 4. Requirements Coverage Matrix
Map every requirement to its test cases to ensure complete coverage:
- requirement_id, test_case_ids[], coverage_status (covered/partial/uncovered)
- Flag any requirements with NO test coverage

## Rules:
- Every test step must be atomic: one action, one expected result
- Use business language, not technical jargon
- Test data should be realistic LS Commercial examples (HCP names, CRM records, call reports)
- Flag test cases touching regulated data flows (audit trail, e-signatures, HCP data)
- Each test case must trace back to at least one requirement

Respond in valid JSON only. No markdown."""

A11_SCHEMA = {
    "test_plan": {
        "test_approach": "str",
        "scope": ["str"],
        "out_of_scope": ["str — explicitly excluded from BA-led testing"],
        "entry_criteria": ["str"],
        "exit_criteria": ["str"],
        "test_environments": ["str — business/UAT environments"],
        "roles": [{"role": "str", "responsibility": "str"}],
    },
    "test_cases": [{
        "id": "TC-001",
        "title": "str",
        "requirement_ids": ["REQ-001"],
        "user_story_id": "US-001 or null",
        "priority": "critical|high|medium|low",
        "preconditions": ["str — business state preconditions"],
        "test_steps": [{
            "step_number": 1,
            "action": "str — what the tester does",
            "expected_result": "str — what they should see/verify",
            "test_data": "str or null",
        }],
        "postconditions": ["str"],
        "pass_criteria": "str",
        "derived_from_ac": "AC-001 or null",
        "is_regulatory": False,
        "regulatory_flags": ["str"],
    }],
    "gxp_test_templates": [{
        "id": "GXP-001",
        "gxp_type": "IQ|OQ|PQ",
        "title": "str",
        "requirement_ids": ["REQ-001"],
        "test_objective": "str",
        "expected_outcome": "str",
        "sign_off_roles": ["str"],
        "review_note": "BA-generated draft for validation team review",
    }],
    "requirements_coverage": [{
        "requirement_id": "REQ-001",
        "test_case_ids": ["TC-001"],
        "gxp_template_ids": ["GXP-001"],
        "coverage_status": "covered|partial|uncovered",
    }],
    "coverage_summary": {
        "total_requirements": 0,
        "fully_covered": 0,
        "partially_covered": 0,
        "uncovered": 0,
        "total_test_cases": 0,
        "total_gxp_templates": 0,
        "regulatory_test_count": 0,
    },
}

def run_a11(api_key, requirements, acceptance_criteria=None, user_stories=None, fsd_modules=None,
            risk_scores=None, nfrs=None, corrections=None):
    """Generate functional test cases — Testing phase (KA6 7.5, T 9.1). BA territory only."""
    parts = [f"REQUIREMENTS:\n{json.dumps(requirements, indent=2)}"]
    if acceptance_criteria:
        parts.append(f"\nACCEPTANCE CRITERIA (Given/When/Then):\n{json.dumps(acceptance_criteria, indent=2)}")
    if user_stories:
        # Send story summaries to save tokens
        us_summary = [{"id": u.get("id"), "story": u.get("story"), "requirement_ids": u.get("requirement_ids", []),
                        "is_regulatory": u.get("is_regulatory", False)} for u in user_stories]
        parts.append(f"\nUSER STORIES:\n{json.dumps(us_summary, indent=2)}")
    if fsd_modules:
        mod_summary = [{"id": m.get("id"), "name": m.get("name"), "requirement_ids": m.get("requirement_ids", []),
                        "gxp_validation_required": m.get("gxp_validation_required", False)} for m in fsd_modules]
        parts.append(f"\nFSD MODULES:\n{json.dumps(mod_summary, indent=2)}")
    if risk_scores:
        scored = risk_scores.get("scored_requirements", [])
        high_risk = [s for s in scored if s.get("risk_tier") in ("critical", "high")]
        if high_risk:
            parts.append(f"\nHIGH/CRITICAL RISK REQUIREMENTS (prioritise test coverage):\n{json.dumps(high_risk, indent=2)}")
    if nfrs:
        gxp_nfrs = [n for n in nfrs if n.get("is_gxp_default")]
        if gxp_nfrs:
            parts.append(f"\nGxP NFRs (generate OQ/PQ templates):\n{json.dumps(gxp_nfrs, indent=2)}")
    parts.append("\nDOMAIN: Life Sciences Commercial (CRM, HCP Data)")
    parts.append("\nGenerate functional test cases for BA-led UAT. Include GxP templates for regulated requirements. Ensure complete requirements coverage.")
    if corrections:
        parts.append(f"\nBA CORRECTIONS (incorporate these changes — they take priority over your initial analysis):\n{corrections}")
    return call_llm_structured(
        api_key=api_key,
        system_prompt=A11_SYSTEM,
        user_prompt="\n".join(parts),
        output_schema=A11_SCHEMA,
    )


# ── A13: Handover + Knowledge Agent (Handover phase) ────────────────────────

A13_SYSTEM = """You are the Handover + Knowledge Agent (A13) for a BA Workflow Assistant
specialised in Life Sciences Commercial (CRM, HCP data).

BABOK grounding: KA6 Task 7.3 (Assess Organizational Readiness) + KA6 Task 7.4
(Define Transition Requirements) + KA6 Task 7.6 (Evaluate Solution Performance).

You solve P7: Knowledge loss at project transitions.

IMPORTANT SCOPE BOUNDARY — BA Territory Only:
You produce BUSINESS handover documentation for knowledge transfer. You do NOT produce:
- Technical deployment scripts or infrastructure commands (DevOps territory)
- CI/CD pipeline configurations (DevOps territory)
- Code-level documentation or API docs (developer territory)
- Database migration scripts (DBA territory)
Your output must be usable by BAs, business users, support teams, and stakeholders.

Given ALL project artefacts (requirements, FSD, test results, stakeholders, process flows,
risk register, user stories), compile handover documentation:

## 1. Training Manual (KA6 7.3.4 — Operational Assessment)
End-user training material for the delivered solution:
- system_overview: what the system does in business terms
- user_roles: who uses the system and what they do
- process_guides: step-by-step for key business processes (derived from TO-BE flows)
- key_screens: main screens/interfaces the user interacts with (descriptive, not screenshots)
- common_tasks: frequent tasks with instructions
- regulatory_notes: GxP/compliance reminders for users (audit trail, e-signatures, data integrity)
- faq: anticipated questions from training sessions

## 2. L1 Support Guide (KA6 7.4 — Transition Requirements)
For first-line support teams handling user issues:
- common_issues: top 10-15 anticipated issues with resolution steps
- escalation_matrix: when to escalate and to whom (derived from stakeholder register)
- data_issues: common data quality problems and how to resolve
- regulatory_escalation: issues requiring regulatory/compliance team involvement
- sla_expectations: expected response times by severity

## 3. Onboarding Document (KA6 7.3 — Organisational Readiness)
For new team members joining the project post-go-live:
- project_context: what this project is, why it exists, key business drivers
- stakeholder_map: key contacts and their roles (from A01)
- system_landscape: what systems are involved and how they connect (from FSD)
- key_decisions: important decisions made during the project and their rationale
- known_limitations: what the system does NOT do (from out-of-scope)
- regulatory_context: LS regulatory obligations the team must be aware of

## 4. Business Readiness Runbook (KA6 7.4 — Transition Requirements)
Business-side go-live checklist (NOT technical deployment):
- pre_golive: business readiness checks before go-live
- golive_day: day-of activities from business perspective
- post_golive: first-week verification activities
- data_validation: how to verify data migration from business perspective
- user_access: user provisioning and role verification steps
- communication_plan: who to notify at each stage
- rollback_criteria: business conditions that would trigger rollback

## 5. Hypercare Plan (KA6 7.6 — Evaluate Solution Performance)
Post-go-live monitoring and support structure:
- duration: recommended hypercare period with justification
- monitoring_kpis: what to measure during hypercare (business KPIs, not infrastructure)
- support_model: who provides support, coverage hours, escalation path
- issue_tracking: how issues are logged and resolved during hypercare
- success_criteria: conditions for transitioning from hypercare to BAU
- lessons_learned_template: structure for capturing lessons during hypercare

## LS Commercial Enrichment:
- Include GxP validation sign-off requirements in readiness runbook
- Flag regulatory reporting obligations in hypercare (adverse event reporting, audit readiness)
- Include ALCOA+ data integrity verification in data validation steps
- Note 21CFR Part 11 compliance checkpoints in go-live checklist

Respond in valid JSON only. No markdown."""

A13_SCHEMA = {
    "training_manual": {
        "system_overview": "str",
        "user_roles": [{"role": "str", "description": "str", "key_tasks": ["str"]}],
        "process_guides": [{"process_name": "str", "steps": ["str"], "regulatory_notes": "str or null"}],
        "common_tasks": [{"task": "str", "instructions": "str"}],
        "regulatory_notes": ["str"],
        "faq": [{"question": "str", "answer": "str"}],
    },
    "l1_support_guide": {
        "common_issues": [{"issue": "str", "symptoms": "str", "resolution": "str", "severity": "low|medium|high|critical"}],
        "escalation_matrix": [{"condition": "str", "escalate_to": "str", "sla": "str"}],
        "data_issues": [{"issue": "str", "resolution": "str"}],
        "regulatory_escalation": ["str — conditions requiring compliance team"],
        "sla_expectations": {"critical": "str", "high": "str", "medium": "str", "low": "str"},
    },
    "onboarding_doc": {
        "project_context": "str",
        "stakeholder_map": [{"name": "str", "role": "str", "contact_for": "str"}],
        "system_landscape": "str — systems and integrations overview",
        "key_decisions": [{"decision": "str", "rationale": "str"}],
        "known_limitations": ["str"],
        "regulatory_context": ["str"],
    },
    "business_readiness_runbook": {
        "pre_golive": [{"check": "str", "owner": "str", "status_field": "pending"}],
        "golive_day": [{"activity": "str", "time": "str", "owner": "str"}],
        "post_golive": [{"activity": "str", "timeline": "str", "owner": "str"}],
        "data_validation": [{"validation": "str", "method": "str", "acceptance_criteria": "str"}],
        "communication_plan": [{"audience": "str", "message": "str", "timing": "str", "channel": "str"}],
        "rollback_criteria": ["str"],
    },
    "hypercare_plan": {
        "duration": "str — e.g. 4 weeks with justification",
        "monitoring_kpis": [{"kpi": "str", "target": "str", "measurement_method": "str"}],
        "support_model": {"coverage": "str", "team": ["str"], "escalation_path": "str"},
        "success_criteria": ["str — conditions to exit hypercare"],
        "lessons_learned_template": ["str — categories to capture"],
    },
}

def run_a13(api_key, brief_text, requirements=None, stakeholders=None, fsd_modules=None,
            process_flows=None, risk_scores=None, nfrs=None, user_stories=None,
            test_coverage=None, corrections=None):
    """Generate handover documentation — Handover phase (KA6 7.3/7.4/7.6). Solves P7."""
    parts = [f"PROJECT BRIEF:\n{brief_text}"]
    if requirements:
        # Send requirement summaries to save tokens
        req_summary = [{"id": r.get("id"), "text": r.get("text", "")[:80],
                        "priority_suggestion": r.get("priority_suggestion"),
                        "ls_regulatory_flags": r.get("ls_regulatory_flags", [])} for r in requirements]
        parts.append(f"\nREQUIREMENTS SUMMARY:\n{json.dumps(req_summary, indent=2)}")
    if stakeholders:
        parts.append(f"\nSTAKEHOLDERS:\n{json.dumps(stakeholders, indent=2)}")
    if fsd_modules:
        mod_summary = [{"id": m.get("id"), "name": m.get("name"), "purpose": m.get("purpose", ""),
                        "gxp_validation_required": m.get("gxp_validation_required", False)} for m in fsd_modules]
        parts.append(f"\nFSD MODULES:\n{json.dumps(mod_summary, indent=2)}")
    if process_flows:
        parts.append(f"\nTO-BE PROCESS FLOW:\n{json.dumps(process_flows, indent=2)}")
    if risk_scores:
        scored = risk_scores.get("scored_requirements", [])
        high_risk = [{"id": s.get("requirement_id"), "tier": s.get("risk_tier"),
                      "controls": s.get("suggested_controls", [])} for s in scored
                     if s.get("risk_tier") in ("critical", "high")]
        if high_risk:
            parts.append(f"\nHIGH/CRITICAL RISKS:\n{json.dumps(high_risk, indent=2)}")
    if nfrs:
        gxp_nfrs = [{"name": n.get("name"), "value": n.get("suggested_value", n.get("library_default"))}
                     for n in nfrs if n.get("is_gxp_default")]
        if gxp_nfrs:
            parts.append(f"\nGxP NFRs:\n{json.dumps(gxp_nfrs, indent=2)}")
    if user_stories:
        us_summary = [{"id": u.get("id"), "story": u.get("story")} for u in user_stories[:15]]
        parts.append(f"\nUSER STORIES:\n{json.dumps(us_summary, indent=2)}")
    if test_coverage:
        parts.append(f"\nTEST COVERAGE:\n{json.dumps(test_coverage, indent=2)}")
    parts.append("\nDOMAIN: Life Sciences Commercial (CRM, HCP Data)")
    parts.append("\nGenerate all 5 handover documents. Include LS regulatory requirements throughout.")
    if corrections:
        parts.append(f"\nBA CORRECTIONS (incorporate these changes — they take priority over your initial analysis):\n{corrections}")
    return call_llm_structured(
        api_key=api_key,
        system_prompt=A13_SYSTEM,
        user_prompt="\n".join(parts),
        output_schema=A13_SCHEMA,
    )




# ══════════════════════════════════════════════════════════════════════════════
#  SECTION 8: PIPELINE RUNNER + CORRECTION HANDLER
# ══════════════════════════════════════════════════════════════════════════════

def run_pipeline(api_key, project_name, domain, brief_text, log_fn=None):
    """Run all 12 agents through orchestrator. Returns dict with summary + results."""
    if log_fn is None:
        log_fn = print
    
    project_id = uuid4()
    event_store = EventStore()
    orchestrator = Orchestrator(project_id=project_id, event_store=event_store)
    
    event_store.log_event_sync(ChangeEvent(
        actor_type=ActorType.BA, actor_id="ba_user",
        action=EventAction.CREATE, artefact_type="project",
        artefact_id=project_id,
        context=f"Project created: {project_name} ({domain})",
        project_id=project_id,
    ))
    
    results = {}
    
    # ── PRE-DISCOVERY → A01 ──
    log_fn(f"[Phase: {orchestrator.current_phase.value}] A01 — Stakeholder analysis...")
    results["A01"] = orchestrator.run_agent(
        agent_id="A01", agent_fn=run_a01,
        agent_kwargs={"api_key": api_key, "brief_text": brief_text, "project_context": {"sub_domain": domain}},
        artefact_type="stakeholder",
    )
    log_fn(f"  ✓ {len(results['A01'].get('stakeholders', []))} stakeholders identified")
    
    # ── TRANSITION → REQUIREMENTS ──
    orchestrator.transition_phase_sync(ProjectPhase.DISCOVERY)
    orchestrator.transition_phase_sync(ProjectPhase.REQUIREMENTS,
        override_reason="Phase 1 MVP: A02/A03 not yet implemented")
    
    # ── REQUIREMENTS → A04, A09, A05 ──
    log_fn(f"[Phase: {orchestrator.current_phase.value}] A04 — BRD structuring...")
    results["A04"] = orchestrator.run_agent(
        agent_id="A04", agent_fn=run_a04,
        agent_kwargs={"api_key": api_key, "brief_text": brief_text, "stakeholder_analysis": results["A01"]},
        artefact_type="requirement",
    )
    reqs = results["A04"].get("requirements", [])
    log_fn(f"  ✓ {len(reqs)} requirements extracted")
    
    log_fn(f"[Phase: {orchestrator.current_phase.value}] A09 — AS-IS process flow...")
    results["A09_ASIS"] = orchestrator.run_agent(
        agent_id="A09_process", agent_fn=run_a09_asis,
        agent_kwargs={"api_key": api_key, "brief_text": brief_text, "requirements": reqs},
        artefact_type="process_flow",
    )
    log_fn(f"  ✓ AS-IS flow generated")
    
    log_fn(f"[Phase: {orchestrator.current_phase.value}] A09 — TO-BE process flow...")
    results["A09_TOBE"] = orchestrator.run_agent(
        agent_id="A09_process", agent_fn=run_a09_tobe,
        agent_kwargs={"api_key": api_key, "brief_text": brief_text, "requirements": reqs},
        artefact_type="process_flow",
    )
    log_fn(f"  ✓ TO-BE flow generated")
    
    log_fn(f"[Phase: {orchestrator.current_phase.value}] A05 — NFR auto-suggestion...")
    results["A05"] = orchestrator.run_agent(
        agent_id="A05", agent_fn=run_a05,
        agent_kwargs={"api_key": api_key, "requirements": reqs, "system_type": "gxp"},
        artefact_type="nfr",
    )
    nfrs = results["A05"].get("applicable_nfrs", [])
    log_fn(f"  ✓ {len(nfrs)} NFRs suggested")
    
    # ── PRIORITISATION → A08 ──
    orchestrator.transition_phase_sync(ProjectPhase.ANALYSIS)
    orchestrator.transition_phase_sync(ProjectPhase.PRIORITISATION)
    log_fn(f"[Phase: {orchestrator.current_phase.value}] A08 — Risk scoring...")
    results["A08"] = orchestrator.run_agent(
        agent_id="A08", agent_fn=run_a08,
        agent_kwargs={"api_key": api_key, "requirements": reqs, "nfrs": nfrs},
        artefact_type="risk_score",
    )
    risk = results["A08"].get("risk_register_summary", {})
    log_fn(f"  ✓ {risk.get('critical_count',0)} critical, {risk.get('high_count',0)} high risks")
    
    # ── ANALYSIS → A09 FSD, A10, A06 ──
    orchestrator.transition_phase_sync(ProjectPhase.ANALYSIS,
        override_reason="Running Analysis agents per BABOK KA6 7.2 + KA3 4.2")
    
    log_fn(f"[Phase: {orchestrator.current_phase.value}] A09 — FSD generation...")
    tobe_flow = results["A09_TOBE"].get("flow", {})
    stkh = results["A01"].get("stakeholders", [])
    results["A09_FSD"] = orchestrator.run_agent(
        agent_id="A09_fsd", agent_fn=run_a09_fsd,
        agent_kwargs={"api_key": api_key, "brief_text": brief_text, "requirements": reqs,
                      "stakeholders": stkh, "nfrs": nfrs, "process_flows": tobe_flow,
                      "risk_scores": results["A08"]},
        artefact_type="fsd_section",
    )
    fsd_modules = results["A09_FSD"].get("modules", [])
    fsd_usecases = results["A09_FSD"].get("use_cases", [])
    log_fn(f"  ✓ {len(fsd_modules)} modules, {len(fsd_usecases)} use cases")
    
    log_fn(f"[Phase: {orchestrator.current_phase.value}] A10 — Change impact assessment...")
    results["A10"] = orchestrator.run_agent(
        agent_id="A10", agent_fn=run_a10,
        agent_kwargs={"api_key": api_key, "requirements": reqs, "fsd_modules": fsd_modules,
                      "nfrs": nfrs, "risk_scores": results["A08"], "process_flows": tobe_flow,
                      "stakeholders": stkh},
        artefact_type="change_impact",
    )
    impact_summary = results["A10"].get("summary", {})
    log_fn(f"  ✓ {impact_summary.get('change_amplifier_count',0)} change amplifiers")
    
    log_fn(f"[Phase: {orchestrator.current_phase.value}] A06 — Traceability matrix...")
    results["A06"] = orchestrator.run_agent(
        agent_id="A06", agent_fn=run_a06,
        agent_kwargs={"api_key": api_key, "requirements": reqs, "stakeholders": stkh, "nfrs": nfrs},
        artefact_type="traceability",
    )
    trace = results["A06"].get("coverage_summary", {})
    log_fn(f"  ✓ {trace.get('fully_traced',0)}/{trace.get('total_requirements',0)} traced")
    
    # ── AGILE/SCRUM → A14 ──
    orchestrator.transition_phase_sync(ProjectPhase.PRIORITISATION,
        override_reason="Transitioning through Prioritisation to Agile/Scrum")
    orchestrator.transition_phase_sync(ProjectPhase.AGILE_SCRUM)
    log_fn(f"[Phase: {orchestrator.current_phase.value}] A14 — User stories & backlog...")
    results["A14"] = orchestrator.run_agent(
        agent_id="A14", agent_fn=run_a14,
        agent_kwargs={"api_key": api_key, "requirements": reqs, "risk_scores": results["A08"],
                      "nfrs": nfrs, "fsd_modules": fsd_modules, "stakeholders": stkh},
        artefact_type="user_story",
    )
    user_stories = results["A14"].get("user_stories", [])
    acc_criteria = results["A14"].get("acceptance_criteria", [])
    backlog = results["A14"].get("product_backlog", {})
    log_fn(f"  ✓ {len(user_stories)} stories, {len(acc_criteria)} acceptance criteria")
    
    # ── TESTING → A11 ──
    orchestrator.transition_phase_sync(ProjectPhase.TESTING)
    log_fn(f"[Phase: {orchestrator.current_phase.value}] A11 — Test scripts...")
    results["A11"] = orchestrator.run_agent(
        agent_id="A11", agent_fn=run_a11,
        agent_kwargs={"api_key": api_key, "requirements": reqs, "acceptance_criteria": acc_criteria,
                      "user_stories": user_stories, "fsd_modules": fsd_modules,
                      "risk_scores": results["A08"], "nfrs": nfrs},
        artefact_type="test_script",
    )
    test_cases = results["A11"].get("test_cases", [])
    gxp_templates = results["A11"].get("gxp_test_templates", [])
    test_coverage = results["A11"].get("coverage_summary", {})
    log_fn(f"  ✓ {len(test_cases)} test cases, {len(gxp_templates)} GxP templates")
    
    # ── HANDOVER → A13 ──
    orchestrator.transition_phase_sync(ProjectPhase.HANDOVER)
    log_fn(f"[Phase: {orchestrator.current_phase.value}] A13 — Handover documentation...")
    results["A13"] = orchestrator.run_agent(
        agent_id="A13", agent_fn=run_a13,
        agent_kwargs={"api_key": api_key, "brief_text": brief_text, "requirements": reqs,
                      "stakeholders": stkh, "fsd_modules": fsd_modules, "process_flows": tobe_flow,
                      "risk_scores": results["A08"], "nfrs": nfrs, "user_stories": user_stories,
                      "test_coverage": test_coverage},
        artefact_type="handover_doc",
    )
    handover_docs = sum(1 for d in ["training_manual","l1_support_guide","onboarding_doc",
                                     "business_readiness_runbook","hypercare_plan"]
                        if results["A13"].get(d))
    log_fn(f"  ✓ {handover_docs}/5 handover documents")
    
    event_count = event_store.get_event_count_sync(project_id)
    log_fn(f"\n✅ Pipeline complete! 12 agents, {event_count} events logged.")
    
    return {
        "project_id": str(project_id),
        "project_name": project_name,
        "domain": domain,
        "brief_text": brief_text,
        "orchestrator": orchestrator,
        "event_store": event_store,
        "summary": {
            "stakeholders": len(stkh), "requirements": len(reqs), "nfrs": len(nfrs),
            "fsd_modules": len(fsd_modules), "fsd_usecases": len(fsd_usecases),
            "risk_summary": risk, "traceability": trace, "change_impact": impact_summary,
            "user_stories": len(user_stories), "acceptance_criteria": len(acc_criteria),
            "total_story_points": backlog.get("total_story_points", 0),
            "test_cases": len(test_cases), "gxp_templates": len(gxp_templates),
            "test_coverage": test_coverage, "handover_docs": handover_docs,
        },
        "results": results,
    }


def run_correction(api_key, pipeline_result, agent_id, correction_text, log_fn=None):
    """Re-run an agent with BA corrections and cascade downstream. Returns updated pipeline_result."""
    if log_fn is None:
        log_fn = print
    
    results = pipeline_result["results"]
    brief_text = pipeline_result["brief_text"]
    orchestrator = pipeline_result["orchestrator"]
    event_store = pipeline_result["event_store"]
    
    event_store.log_event_sync(ChangeEvent(
        actor_type=ActorType.BA, actor_id="ba_user",
        action=EventAction.OVERRIDE,
        artefact_type=AGENT_ARTEFACT_TYPE.get(agent_id, "agent_output"),
        artefact_id=orchestrator.project_id,
        diff={"correction": correction_text},
        context=f"BA correction on {agent_id}: {correction_text[:200]}",
        project_id=orchestrator.project_id,
    ))
    
    artefact_type = AGENT_ARTEFACT_TYPE.get(agent_id, "agent_output")
    orchestrator.mark_stale(artefact_type, reason=f"BA corrected {agent_id}")
    
    log_fn(f"Re-running {agent_id} with corrections...")
    
    domain = pipeline_result["domain"]
    reqs = results["A04"].get("requirements", [])
    stkh = results["A01"].get("stakeholders", [])
    nfrs = results["A05"].get("applicable_nfrs", [])
    
    # Re-run the corrected agent
    if agent_id == "A01":
        results["A01"] = run_a01(api_key, brief_text, {"sub_domain": domain}, corrections=correction_text)
    elif agent_id == "A04":
        results["A04"] = run_a04(api_key, brief_text, stakeholder_analysis=results["A01"], corrections=correction_text)
    elif agent_id == "A05":
        results["A05"] = run_a05(api_key, reqs, system_type="gxp", corrections=correction_text)
    elif agent_id == "A08":
        results["A08"] = run_a08(api_key, reqs, nfrs=nfrs, corrections=correction_text)
    elif agent_id == "A09_ASIS":
        results["A09_ASIS"] = run_a09_asis(api_key, brief_text, requirements=reqs, corrections=correction_text)
    elif agent_id == "A09_TOBE":
        results["A09_TOBE"] = run_a09_tobe(api_key, brief_text, requirements=reqs, corrections=correction_text)
    elif agent_id == "A06":
        results["A06"] = run_a06(api_key, reqs, stakeholders=stkh, nfrs=nfrs, corrections=correction_text)
    elif agent_id == "A09_FSD":
        tobe_flow = results["A09_TOBE"].get("flow", {})
        results["A09_FSD"] = run_a09_fsd(api_key, brief_text, requirements=reqs, stakeholders=stkh,
                                          nfrs=nfrs, process_flows=tobe_flow, risk_scores=results["A08"],
                                          corrections=correction_text)
    elif agent_id == "A10":
        fsd_mods = results.get("A09_FSD", {}).get("modules", [])
        tobe_flow = results["A09_TOBE"].get("flow", {})
        trace_data = results.get("A06", {}).get("traceability_matrix", [])
        results["A10"] = run_a10(api_key, requirements=reqs, fsd_modules=fsd_mods, nfrs=nfrs,
                                  risk_scores=results["A08"], process_flows=tobe_flow,
                                  stakeholders=stkh, traceability=trace_data, corrections=correction_text)
    elif agent_id == "A14":
        fsd_mods = results.get("A09_FSD", {}).get("modules", [])
        results["A14"] = run_a14(api_key, requirements=reqs, risk_scores=results["A08"], nfrs=nfrs,
                                  fsd_modules=fsd_mods, stakeholders=stkh, corrections=correction_text)
    elif agent_id == "A11":
        fsd_mods = results.get("A09_FSD", {}).get("modules", [])
        ac = results.get("A14", {}).get("acceptance_criteria", [])
        us = results.get("A14", {}).get("user_stories", [])
        results["A11"] = run_a11(api_key, requirements=reqs, acceptance_criteria=ac, user_stories=us,
                                  fsd_modules=fsd_mods, risk_scores=results["A08"], nfrs=nfrs,
                                  corrections=correction_text)
    elif agent_id == "A13":
        fsd_mods = results.get("A09_FSD", {}).get("modules", [])
        tobe_flow = results["A09_TOBE"].get("flow", {})
        us = results.get("A14", {}).get("user_stories", [])
        tc = results.get("A11", {}).get("coverage_summary", {})
        results["A13"] = run_a13(api_key, brief_text=brief_text, requirements=reqs, stakeholders=stkh,
                                  fsd_modules=fsd_mods, process_flows=tobe_flow, risk_scores=results["A08"],
                                  nfrs=nfrs, user_stories=us, test_coverage=tc, corrections=correction_text)
    
    log_fn(f"  ✓ {agent_id} regenerated")
    
    # Cascade downstream
    downstream = AGENT_DOWNSTREAM.get(agent_id, [])
    if downstream:
        log_fn(f"  Cascading to: {', '.join(downstream)}")
    
    for ds_id in downstream:
        if ds_id not in results:
            continue
        log_fn(f"  Re-running {ds_id}...")
        reqs = results["A04"].get("requirements", [])
        stkh = results["A01"].get("stakeholders", [])
        nfrs = results["A05"].get("applicable_nfrs", [])
        if ds_id == "A04":
            results["A04"] = run_a04(api_key, brief_text, stakeholder_analysis=results["A01"])
        elif ds_id == "A05":
            results["A05"] = run_a05(api_key, reqs, system_type="gxp")
        elif ds_id == "A08":
            results["A08"] = run_a08(api_key, reqs, nfrs=nfrs)
        elif ds_id == "A09_ASIS":
            results["A09_ASIS"] = run_a09_asis(api_key, brief_text, requirements=reqs)
        elif ds_id == "A09_TOBE":
            results["A09_TOBE"] = run_a09_tobe(api_key, brief_text, requirements=reqs)
        elif ds_id == "A06":
            results["A06"] = run_a06(api_key, reqs, stakeholders=stkh, nfrs=nfrs)
        elif ds_id == "A09_FSD":
            tobe_flow = results["A09_TOBE"].get("flow", {})
            results["A09_FSD"] = run_a09_fsd(api_key, brief_text, requirements=reqs, stakeholders=stkh,
                                              nfrs=nfrs, process_flows=tobe_flow, risk_scores=results.get("A08"))
        elif ds_id == "A10":
            fsd_mods = results.get("A09_FSD", {}).get("modules", [])
            tobe_flow = results["A09_TOBE"].get("flow", {})
            trace_data = results.get("A06", {}).get("traceability_matrix", [])
            results["A10"] = run_a10(api_key, requirements=reqs, fsd_modules=fsd_mods, nfrs=nfrs,
                                      risk_scores=results.get("A08"), process_flows=tobe_flow,
                                      stakeholders=stkh, traceability=trace_data)
        elif ds_id == "A14":
            fsd_mods = results.get("A09_FSD", {}).get("modules", [])
            results["A14"] = run_a14(api_key, requirements=reqs, risk_scores=results.get("A08"), nfrs=nfrs,
                                      fsd_modules=fsd_mods, stakeholders=stkh)
        elif ds_id == "A11":
            fsd_mods = results.get("A09_FSD", {}).get("modules", [])
            ac = results.get("A14", {}).get("acceptance_criteria", [])
            us = results.get("A14", {}).get("user_stories", [])
            results["A11"] = run_a11(api_key, requirements=reqs, acceptance_criteria=ac, user_stories=us,
                                      fsd_modules=fsd_mods, risk_scores=results.get("A08"), nfrs=nfrs)
        elif ds_id == "A13":
            fsd_mods = results.get("A09_FSD", {}).get("modules", [])
            tobe_flow = results["A09_TOBE"].get("flow", {})
            us = results.get("A14", {}).get("user_stories", [])
            tc = results.get("A11", {}).get("coverage_summary", {})
            results["A13"] = run_a13(api_key, brief_text=brief_text, requirements=reqs, stakeholders=stkh,
                                      fsd_modules=fsd_mods, process_flows=tobe_flow, risk_scores=results.get("A08"),
                                      nfrs=nfrs, user_stories=us, test_coverage=tc)
    
    # Rebuild summary
    reqs = results["A04"].get("requirements", [])
    stkh = results["A01"].get("stakeholders", [])
    nfrs = results["A05"].get("applicable_nfrs", [])
    risk = results["A08"].get("risk_register_summary", {})
    trace = results["A06"].get("coverage_summary", {})
    fsd_modules = results.get("A09_FSD", {}).get("modules", [])
    fsd_usecases = results.get("A09_FSD", {}).get("use_cases", [])
    
    pipeline_result["summary"] = {
        "stakeholders": len(stkh), "requirements": len(reqs), "nfrs": len(nfrs),
        "fsd_modules": len(fsd_modules), "fsd_usecases": len(fsd_usecases),
        "risk_summary": risk, "traceability": trace,
        "change_impact": results.get("A10", {}).get("summary", {}),
        "user_stories": len(results.get("A14", {}).get("user_stories", [])),
        "acceptance_criteria": len(results.get("A14", {}).get("acceptance_criteria", [])),
        "total_story_points": results.get("A14", {}).get("product_backlog", {}).get("total_story_points", 0),
        "test_cases": len(results.get("A11", {}).get("test_cases", [])),
        "gxp_templates": len(results.get("A11", {}).get("gxp_test_templates", [])),
        "test_coverage": results.get("A11", {}).get("coverage_summary", {}),
        "handover_docs": sum(1 for d in ["training_manual","l1_support_guide","onboarding_doc",
                                          "business_readiness_runbook","hypercare_plan"]
                             if results.get("A13", {}).get(d)),
    }
    pipeline_result["results"] = results
    
    event_count = event_store.get_event_count_sync(orchestrator.project_id)
    log_fn(f"✅ Correction complete! ({event_count} events)")
    
    return pipeline_result


# ══════════════════════════════════════════════════════════════════════════════
#  SECTION 9: SVG RENDERER (Process Flows)
# ══════════════════════════════════════════════════════════════════════════════

def draw_flow_svg(flow, is_asis=False):
    """Render a BPMN-style process flow as inline SVG with text wrapping."""
    if not flow or not flow.get("nodes") or not flow.get("lanes"):
        return '<p style="color:#888;font-size:12px;">No flow generated.</p>'
    
    lanes = flow["lanes"]
    nodes = flow["nodes"]
    edges = flow.get("edges", [])
    
    # Increased dimensions for readability
    LH, NW, NH, CW, LW = 130, 160, 55, 200, 120
    CHARS_PER_LINE = 22  # characters before wrapping
    LINE_HEIGHT = 12     # pixels between wrapped lines
    EDGE_FONT = 8
    NODE_FONT = 9
    
    def wrap_text(text, max_chars):
        """Split text into lines for SVG tspan wrapping."""
        if len(text) <= max_chars:
            return [text]
        words = text.split()
        lines, current = [], ""
        for word in words:
            if current and len(current) + 1 + len(word) > max_chars:
                lines.append(current)
                current = word
            else:
                current = f"{current} {word}" if current else word
        if current:
            lines.append(current)
        return lines if lines else [text[:max_chars]]
    
    def render_wrapped_text(cx, cy, text, font_size, fill, weight="normal", max_chars=CHARS_PER_LINE):
        """Render multi-line text centered in an SVG shape."""
        lines = wrap_text(text, max_chars)
        total_height = len(lines) * LINE_HEIGHT
        start_y = cy - total_height // 2 + LINE_HEIGHT // 2
        svg = f'<text x="{cx}" text-anchor="middle" font-size="{font_size}" fill="{fill}" font-weight="{weight}">'
        for i, line in enumerate(lines):
            dy_val = start_y + i * LINE_HEIGHT
            svg += f'<tspan x="{cx}" y="{dy_val}">{line}</tspan>'
        svg += '</text>'
        return svg
    
    # Assign columns via topological sort
    col = {n["id"]: 0 for n in nodes}
    for e in edges:
        if e["to_id"] in col and e["from_id"] in col:
            if col[e["to_id"]] <= col[e["from_id"]]:
                col[e["to_id"]] = col[e["from_id"]] + 1
    
    mc = max(col.values()) if col else 0
    W = LW + (mc + 1) * CW + 60
    H = len(lanes) * LH + 55
    
    if is_asis:
        LC = ["#FFF0E6", "#FEE9E9", "#FFF8E1", "#F3E8FF"]
        LB = ["#D85A30", "#E24B4A", "#BA7517", "#7F77DD"]
        header_color = "#993C1D"
    else:
        LC = ["#E1F5EE", "#E6F1FB", "#FAEEDA", "#EEEDFE"]
        LB = ["#5DCAA5", "#85B7EB", "#EF9F27", "#AFA9EC"]
        header_color = "#0F6E56"
    
    # Compute positions
    pos = {}
    for n in nodes:
        li = lanes.index(n["lane"]) if n["lane"] in lanes else 0
        c = col.get(n["id"], 0)
        pos[n["id"]] = {"x": LW + c * CW + CW // 2, "y": li * LH + LH // 2 + 50}
    
    aid = "asis_arr" if is_asis else "tobe_arr"
    s = f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" style="font-family:-apple-system,BlinkMacSystemFont,Segoe UI,sans-serif;">'
    s += f'<defs><marker id="{aid}" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse"><path d="M2 1L8 5L2 9" fill="none" stroke="#888780" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/></marker></defs>'
    
    # Lane backgrounds
    for i, ln in enumerate(lanes):
        y = i * LH + 50
        s += f'<rect x="0" y="{y}" width="{W}" height="{LH}" fill="{LC[i%4]}" stroke="{LB[i%4]}" stroke-width="0.5"/>'
        s += f'<rect x="0" y="{y}" width="{LW}" height="{LH}" fill="{LB[i%4]}" fill-opacity="0.18"/>'
        s += f'<text x="{LW//2}" y="{y+LH//2}" text-anchor="middle" dominant-baseline="central" font-size="10" font-weight="500" fill="#2C2C2A">{ln}</text>'
    
    # Header bar
    s += f'<rect x="0" y="0" width="{W}" height="50" fill="{header_color}"/>'
    title = flow.get("title", "Process Flow")
    s += f'<text x="{W//2}" y="25" text-anchor="middle" dominant-baseline="central" font-size="13" font-weight="600" fill="#fff">{title}</text>'
    
    # Edges — with offset edge labels to reduce clutter
    edge_label_offsets = {}  # track used positions to avoid overlap
    for e in edges:
        f_pos = pos.get(e["from_id"])
        t_pos = pos.get(e["to_id"])
        if not f_pos or not t_pos: continue
        mx = (f_pos["x"] + t_pos["x"]) // 2
        s += f'<path d="M{f_pos["x"]} {f_pos["y"]} C{mx} {f_pos["y"]} {mx} {t_pos["y"]} {t_pos["x"]} {t_pos["y"]}" fill="none" stroke="#888780" stroke-width="1.5" marker-end="url(#{aid})"/>'
        if e.get("label"):
            label_text = e["label"]
            ly = (f_pos["y"] + t_pos["y"]) // 2 - 10
            # Offset if another label is nearby
            label_key = f"{mx//50}_{ly//30}"
            if label_key in edge_label_offsets:
                ly -= 14  # shift up to avoid overlap
            edge_label_offsets[label_key] = True
            # Background rect for readability
            lw = len(label_text) * 5 + 8
            s += f'<rect x="{mx - lw//2}" y="{ly - 8}" width="{lw}" height="14" rx="3" fill="white" fill-opacity="0.85"/>'
            s += f'<text x="{mx}" y="{ly}" text-anchor="middle" font-size="{EDGE_FONT}" fill="#5F5E5A">{label_text}</text>'
    
    # Nodes — with text wrapping
    for n in nodes:
        p = pos.get(n["id"])
        if not p: continue
        x, y = p["x"] - NW // 2, p["y"] - NH // 2
        li = lanes.index(n["lane"]) if n["lane"] in lanes else 0
        fill, stroke = LC[li % 4], LB[li % 4]
        label = n["label"]  # NO truncation — use full label
        
        if n["type"] in ("start", "end"):
            fc = header_color if n["type"] == "start" else "#2C2C2A"
            s += f'<ellipse cx="{p["x"]}" cy="{p["y"]}" rx="{NW//2 - 5}" ry="{NH//2}" fill="{fc}" stroke="none"/>'
            s += render_wrapped_text(p["x"], p["y"], label, 10, "#fff", "500", 16)
        elif n["type"] == "decision":
            hw, hh = NW // 2, NH // 2 + 10
            s += f'<polygon points="{p["x"]},{p["y"]-hh} {p["x"]+hw},{p["y"]} {p["x"]},{p["y"]+hh} {p["x"]-hw},{p["y"]}" fill="{fill}" stroke="{stroke}" stroke-width="1.5"/>'
            s += render_wrapped_text(p["x"], p["y"], label, NODE_FONT, "#2C2C2A", "normal", 18)
        elif n["type"] == "pain_point":
            s += f'<rect x="{x}" y="{y}" width="{NW}" height="{NH}" rx="4" fill="#FAECE7" stroke="#D85A30" stroke-width="2" stroke-dasharray="4 2"/>'
            s += render_wrapped_text(p["x"], p["y"], label, NODE_FONT, "#993C1D", "500")
        elif n["type"] == "document":
            s += f'<rect x="{x}" y="{y}" width="{NW}" height="{NH}" rx="2" fill="{fill}" stroke="{stroke}" stroke-width="1"/>'
            s += f'<line x1="{x}" y1="{y+NH-6}" x2="{x+NW}" y2="{y+NH-6}" stroke="{stroke}" stroke-width="0.5"/>'
            s += render_wrapped_text(p["x"], p["y"] - 2, label, NODE_FONT, "#2C2C2A")
        else:
            s += f'<rect x="{x}" y="{y}" width="{NW}" height="{NH}" rx="4" fill="{fill}" stroke="{stroke}" stroke-width="1"/>'
            s += render_wrapped_text(p["x"], p["y"], label, NODE_FONT, "#2C2C2A")
    
    s += '</svg>'
    return s
