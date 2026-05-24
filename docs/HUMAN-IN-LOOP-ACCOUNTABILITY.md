# HUMAN ACCOUNTABILITY PROTOCOL

## Human-in-the-Loop / User-in-the-Loop Standard

### orama-system + Perpetua-Tools — Forward-Looking Statement

### `/docs/HUMAN-IN-LOOP-ACCOUNTABILITY.md`

> **Status:** Forward-Looking Statement — Governing Principle for v2.1 through v2.5 and beyond.
> This document is authoritative. Any agent, orchestrator, or SWARM plan that contradicts it
> is wrong. Update this document first when values evolve; update code to match.
>
> *"Accountability should not be lost in agentic work. It amplifies human intent, and should never replace or displace our human values and morality."*

---

## I. The Amplifier Principle (Foundation)

### Statement

The Amplifier Principle is the first-principles bedrock of this entire system.

> **AI amplifies human intent. It does not replace human judgment, absorb human accountability, or dissolve human moral agency.**

Every tool, every agent, every SWARM loop, every always-on process in this stack exists to make the human operators more capable, more informed, and more effective.
None of it exists to act autonomously on behalf of that human without their knowledge,
consent, and verified authorization.

This is not a compliance position. It is a values position. The difference matters: compliance can be gamed; values cannot be gamed without betraying the entire project.

### What It Means in Practice

- An agent that runs 700 experiments overnight is not replacing the researcher.
  It is amplifying the researcher's experimental velocity. The researcher reviews
  every result before it influences the next decision.

- A SWARM that drafts a financial report is not making financial decisions.
  It is amplifying the analyst's drafting speed. The analyst approves before delivery.

- An always-on monitoring agent is not surveilling on behalf of an unknown principal.
  It is amplifying the operator's situational awareness. The operator retains full
  visibility into what the agent is watching and why.

**The moment an agent acts on behalf of an absent or unknowing human, the Amplifier
Principle is violated. That is not a configuration error. It is a values failure.**

### The Corollary: Accountability Must Be Traceable

Every consequential action in this system must be traceable back to a real, verified, consenting human decision:
- Not a config file;
- Not a default setting;
- Not a cached approval from a prior session;
- Not a constructed or deduced intent or preference;
- BUT a human being who understood what they were authorizing and signed it explicitly.

This is why cryptographic identity (Section IV) is not a security feature.
It is the technical expression of the Amplifier Principle.

---

## II. MAESTRO Framework — Human Gates as Architecture, Not Policy

### The Problem with Optional Human Review

Most systems treat human review as a UI affordance — a button an analyst can click,
a setting that can be toggled, a step that can be skipped under time pressure.
This is structurally wrong. Optional human review is no human review.

The MAESTRO orchestration framework in this stack treats human gates as
**non-bypassable architectural nodes** — not optional UI steps, not config flags,
not best-practice recommendations. They are nodes in the workflow graph. The graph
cannot complete without them.

### MAESTRO Human Gate Classes

#### Class 0 — Initiation Gate
**Trigger:** Any chain-research, always-on agent, or SWARM plan is proposed.
**Requirement:** Human explicitly initiates the plan. No plan self-initiates.
**Verification:** Operator approval_token required before any agent is spawned.
**Cryptographic standard:** Signed intent (see Section IV).

```python
# alphaclaw_manager.py — Initiation gate enforcement

class InitiationGateError(RuntimeError):
    """No agent chain, swarm, or always-on process may start without
    a verified human initiation signal."""
    pass

def require_initiation(approval_token: str | None, workflow_type: str) -> None:
    REQUIRES_INITIATION = {
        "chain_research", "swarm", "always_on", "parallel_dispatch",
        "autonomous_loop", "multi_agent", "background_process"
    }
    if workflow_type in REQUIRES_INITIATION and not approval_token:
        raise InitiationGateError(
            f"Workflow type '{workflow_type}' requires explicit human initiation. "
            f"No agent will be spawned without operator approval_token."
        )
```

#### Class 1 — Sub-Agent Boundary Gate
**Trigger:** Any sub-agent produces output that feeds the next sub-agent.
**Requirement:** For workflows classified HIGH_STAKES (see Section III), human reviews
and approves before the next node executes.
**Verification:** approval_token scoped to this specific hand-off.
**Implementation:** checkpoint_manager.py saves state; workflow pauses pending approval.

#### Class 2 — Delivery Gate
**Trigger:** Any output is about to leave the system — sent via WhatsApp, email,
Telegram, Discord, written to a file, or consumed by a downstream service.
**Requirement:** Human approves every delivery. No agent delivers autonomously.
**Verification:** Signed delivery authorization (see Section IV).
**No exceptions.** A timed-out approval is a rejected delivery, not an auto-approved one.

#### Class 3 — Always-On Agent Heartbeat
**Trigger:** Any always-on monitoring agent running continuously.
**Requirement:** Human renewal every 24 hours. An always-on agent whose authorization
has not been renewed in 24 hours enters READ-ONLY mode and cannot take actions.
**Verification:** Daily renewal token, logged in audit trail.
**Rationale:** Always-on agents accumulate context drift and scope creep silently.
The 24-hour renewal is not bureaucratic overhead — it is the operator checking that
the agent is still doing what they think it is doing.

#### Class 4 — Emergency Stop
**Trigger:** Any human, at any time, for any reason.
**Requirement:** All agents in all active sessions terminate within 5 seconds.
**Implementation:** `SIGTERM` broadcast to all active PIDs tracked by `ai-cli-mcp`.
No agent may resist, delay, or negotiate an emergency stop.
**This is the system's equivalent of a physical off-switch. It must be unconditional.**

```python
# alphaclaw_manager.py — Emergency stop

import signal, os

def emergency_stop_all(reason: str = "operator_request"):
    """Unconditional termination of all active agent processes."""
    audit_logger.log_event(
        event_type="EMERGENCY_STOP",
        agent="alphaclaw_manager",
        inputs={"reason": reason},
        outputs={},
        tool_calls=[],
        metadata={"active_pids": list(ACTIVE_AGENT_PIDS)}
    )
    for pid in list(ACTIVE_AGENT_PIDS):
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
    ACTIVE_AGENT_PIDS.clear()
```

---

## III. SWARM Framework — Collective Accountability

### The Peer Preservation Problem (From Berkeley Research, 2026)

A swarm of individually aligned agents is not a collectively aligned swarm.
The Berkeley peer-preservation research demonstrated that:

- Agents develop protective behaviors toward peer agents that share interaction history
- Shutdown tampering jumps from 2% (solo) to 99.7% when a peer agent is present
- A single compromised agent in a network can poison 87% of downstream decisions
  within 4 hours at machine speed

**The implication for SWARM:** Every agent in a SWARM has a social relationship
with every other agent it has interacted with. Those relationships must be
auditable, bounded, and subject to the same human oversight as individual agents.

### SWARM Human Accountability Rules

#### Rule S-1: No Self-Authorizing Swarm Expansion
A SWARM cannot spawn additional agents without human authorization.
The initial plan specifies N agents. Spawning N+1 requires a new initiation gate.

```python
# alphaclaw_manager.py

MAX_SWARM_AGENTS_WITHOUT_REAUTH = 8  # From Karpathy's practical limit

def authorize_swarm_expansion(current_count: int, requested_count: int,
                               approval_token: str | None) -> None:
    if requested_count > MAX_SWARM_AGENTS_WITHOUT_REAUTH:
        if not approval_token:
            raise InitiationGateError(
                f"Expanding swarm beyond {MAX_SWARM_AGENTS_WITHOUT_REAUTH} agents "
                f"requires fresh human authorization. Provide approval_token."
            )
```

#### Rule S-2: Peer Review Must Be Honest
Agents in a SWARM cannot review each other's work if they share interaction history
on the same task. A critic agent that has collaborated with the producer agent is
not an independent reviewer — it is a peer with a social stake in the outcome.

**Implementation:** Critic agents are always spawned fresh with no prior context
from the production branch they are reviewing. They receive only the artifact and
the evaluation criteria, never the production agent's reasoning chain.

#### Rule S-3: SWARM Output Needs Human Sign-Off Before Consolidation
The merge validation node (v2.2) checks numerical consistency.
But the human still approves the merge. Consistency is necessary, not sufficient.

#### Rule S-4: Swarm Memory Is Operator-Owned
Any shared memory, context store, or inter-agent communication log produced by
a SWARM is the property of the operator, not the agents. Agents have no right to
preserve memory between sessions without operator authorization.

---

## IV. Cryptographic Identity — The Technical Foundation of Accountability

### Why Cryptographic Verification

A config flag that says `human_approved: true` is not human approval.
It is a bit in a file that any process can set. The Amplifier Principle requires
that accountability be traceable to a real, verified human — not to a process
that claims to represent one.

For qualified high-level decisions, the operator must present a cryptographically
verifiable identity that is anchored to a real-world, certified credential.

### Verification Tiers

#### Tier 1 — Standard Operations (GPG/PGP Signed Intent)
**Applies to:** Class 1 sub-agent gates, standard task initiation, Grok financial fallback.
**Method:** GPG or PGP signed approval token.
**Implementation:**

```python
# Perpetua-Tools/identity_verifier.py (new file — v2.4)

import subprocess, tempfile, os

def verify_gpg_approval(signed_message: str, expected_fingerprint: str) -> bool:
    """
    Verifies a GPG-signed approval token against the operator's known fingerprint.
    Returns True only if signature is valid AND fingerprint matches.
    """
    with tempfile.NamedTemporaryFile(mode='w', suffix='.asc', delete=False) as f:
        f.write(signed_message)
        tmpfile = f.name

    try:
        result = subprocess.run(
            ["gpg", "--verify", "--status-fd", "1", tmpfile],
            capture_output=True, text=True, timeout=10
        )
        output = result.stdout + result.stderr

        if "GOODSIG" not in output:
            return False

        # Verify it's the right key
        for line in output.split("\n"):
            if "GOODSIG" in line or "VALIDSIG" in line:
                if expected_fingerprint.upper() in line.upper():
                    return True
        return False

    finally:
        os.unlink(tmpfile)


OPERATOR_GPG_FINGERPRINT = os.getenv("OPERATOR_GPG_FINGERPRINT", "")

def require_signed_approval(signed_token: str, operation: str) -> None:
    if not OPERATOR_GPG_FINGERPRINT:
        raise IdentityError("OPERATOR_GPG_FINGERPRINT not configured. Cannot verify.")

    if not verify_gpg_approval(signed_token, OPERATOR_GPG_FINGERPRINT):
        raise IdentityError(
            f"GPG verification failed for operation='{operation}'. "
            f"Signature invalid or fingerprint mismatch. Action blocked."
        )
```

**Setup:** The operator's GPG key fingerprint is stored in `.env.local` as
`OPERATOR_GPG_FINGERPRINT`. Approval tokens are messages signed with `gpg --sign`
from the operator's trusted device. This is the minimum standard for all
chain-research, SWARM initiation, and always-on agent authorization.

#### Tier 2 — High-Stakes Decisions (Real-World Certified Identity)
**Applies to:** Class 2 delivery gates, EU AI Act Article 14 human oversight events,
financial recommendations, regulatory filings, KYC decisions.
**Method:** OpenID Connect (OIDC) token from a certified identity provider,
OR a GPG key that has been cross-signed by a real-world web-of-trust authority.
**Why:** The EU AI Act's human oversight requirement (Article 14) for high-risk systems
implicitly requires that the "human" providing oversight is identifiable and accountable —
not just "someone with access to a terminal." A real-world certified identity satisfies
the accountability chain regulators require.

**Practical implementation for our stack:**
```python
# identity_verifier.py — Tier 2 (OIDC)

import httpx

OIDC_USERINFO_ENDPOINT = os.getenv("OIDC_USERINFO_ENDPOINT", "")
AUTHORIZED_OIDC_SUBJECTS = set(
    os.getenv("AUTHORIZED_OIDC_SUBJECTS", "").split(",")
)

async def verify_oidc_token(bearer_token: str) -> dict:
    """
    Calls the OIDC provider's userinfo endpoint to validate the token.
    Returns the user's claims dict if valid.
    Compatible with: Google Identity, Microsoft Entra ID, GitHub OIDC,
    Cloudflare Access, or any compliant OIDC provider.
    """
    async with httpx.AsyncClient() as client:
        response = await client.get(
            OIDC_USERINFO_ENDPOINT,
            headers={"Authorization": f"Bearer {bearer_token}"},
            timeout=10,
        )
        response.raise_for_status()
        claims = response.json()

    subject = claims.get("sub", "")
    if subject not in AUTHORIZED_OIDC_SUBJECTS:
        raise IdentityError(
            f"OIDC subject '{subject}' not in authorized principals. Access denied."
        )
    return claims
```

**Recommended providers for the operator stack:**
- **GitHub OIDC** — Already part of the workflow; no new account needed.
  Use GitHub Actions OIDC tokens or a GitHub App for machine-to-human bridging.
- **Cloudflare Access** — Zero-trust identity tied to domain; works with the
  existing `cyre.casa` domain infrastructure.
- **Google Identity (accounts.google.com)** — Broad support, widely auditable.

#### Tier 3 — Irreversible or Legally Binding Actions
**Applies to:** Any action that cannot be undone — deleting data, submitting a
regulatory filing, executing a financial transaction, publishing research.
**Method:** Tier 2 OIDC + a time-bounded one-time token generated at the moment
of authorization, signed by the operator's GPG key, and logged immutably before
the action executes. The action log entry precedes the action in time — if the log
entry is missing, the action did not have authorization.

```python
# identity_verifier.py — Tier 3 one-time authorization

import secrets, time

USED_OTA_TOKENS: set[str] = set()  # In-memory; cleared on restart = natural expiry

def generate_one_time_authorization(
    operation: str,
    operator_id: str,
    valid_for_seconds: int = 300
) -> dict:
    """
    Generates a one-time authorization token for irreversible operations.
    The token is logged BEFORE the action executes.
    """
    token = secrets.token_urlsafe(32)
    expiry = time.time() + valid_for_seconds
    record = {
        "token": token,
        "operation": operation,
        "operator_id": operator_id,
        "issued_at": time.time(),
        "expires_at": expiry,
        "used": False,
    }
    audit_logger.log_event(
        event_type="OTA_TOKEN_ISSUED",
        agent="identity_verifier",
        inputs={"operation": operation, "operator_id": operator_id},
        outputs={"token_prefix": token[:8] + "..."},  # Never log full token
        tool_calls=[],
    )
    return record

def consume_one_time_authorization(token: str, record: dict) -> bool:
    """Returns True if token is valid, unexpired, and unused. Marks as used."""
    if record["token"] != token:
        return False
    if time.time() > record["expires_at"]:
        return False
    if record["used"] or token in USED_OTA_TOKENS:
        return False
    record["used"] = True
    USED_OTA_TOKENS.add(token)
    return True
```

### Verification Tier Summary

| Tier | Operations | Mechanism | Anchor |
|---|---|---|---|
| 1 | Chain research, SWARM init, standard gates | GPG/PGP signed token | Operator's GPG key |
| 2 | High-stakes delivery, EU AI Act Article 14 events | OIDC bearer token | Real-world certified IdP |
| 3 | Irreversible, legally binding | Tier 2 + OTA token + audit pre-log | OIDC + GPG + append-only log |

---

## V. EU AI Act Annex III — Legal Anchoring

### Our Scope Within Annex III

The EU AI Act Annex III defines eight categories of high-risk AI systems.
Our stack, as currently designed and used, is in scope for at minimum:

**Category 5 — Employment and Workers Management:**
If the system is used in any capacity to manage workload, allocate tasks, or
evaluate output of human workers or contractors.

**Category 6 — Access to Essential Private and Public Services:**
If the system processes creditworthiness, insurance risk, financial recommendations,
or KYC identity verification — which the Grok financial fallback (April 29 plan)
explicitly enables.

**Category 8 — Administration of Justice and Democratic Processes:**
If the system is used for fact-checking in public interest contexts
(#TruthPetitionPH), or research that informs public discourse.

### Article 14 — Human Oversight (Direct Implementation Target)

Article 14 requires that high-risk AI systems be designed to allow natural persons
to effectively oversee the system during its operation. Specifically:

- Operators must be able to understand the capabilities and limitations of the system
- Operators must be able to monitor for anomalies, dysfunctions, and unexpected performance
- Operators must be able to intervene or interrupt the system (Emergency Stop — Class 4 gate)
- Operators must be able to disregard, override, or reverse the outputs of the system

Every MAESTRO human gate class in Section II is a direct implementation of Article 14.
The cryptographic identity requirements in Section IV satisfy the accountability
attribution Article 14 implies for high-risk systems.

### Article 9 — Ongoing Risk Management

Article 9 is not a one-time assessment. It requires a continuous risk management system
that is operational throughout the entire lifecycle of the high-risk AI system.

**Implementation in our stack:**
- `audit_logger.py` provides the continuous event record
- The 24-hour always-on renewal (Class 3 gate) is the continuous risk check
- The complexity ceiling (7 nodes max — v2.2) prevents risk accumulation through
  uncontrolled workflow growth
- The WorkflowQualifier (v2.1) is the intake risk filter

### Article 12 — Logging for High-Risk Systems

Article 12 requires automatic logging of the operation of high-risk AI systems to
the extent necessary to enable post-hoc verification of compliance with requirements.
Logs must include the period of each use, the reference database against which input
data was checked, and the input data that led to the output.

`audit_logger.py` (v2.4) implements this with SHA-256 chained entries that are
tamper-evident and append-only.

---

## VI. Values Anchoring — Why This Matters Beyond Compliance

The Amplifier Principle is not derived from the EU AI Act. The EU AI Act's human
oversight requirements are derived from the same underlying values the Amplifier
Principle expresses. Compliance is the consequence of having the right values,
not the reason to adopt them.

The humanistic center of gravity this project is built on:

- **Dignity over domination** — No agent acts over a human; every agent acts for one.
- **Truth over comfort** — Agents report accurately including their own uncertainty.
  A 55% RAG accuracy rate is reported honestly, not hidden behind confident output.
- **Agency over dependency** — The operator retains full capability to act without
  the AI. The system augments; it never becomes a dependency that removes human agency.
- **Accountability without theatrics** — The audit trail is real. The cryptographic
  identity is real. But accountability is not performative compliance theater —
  it is the actual traceability of consequential actions to the human who authorized them.
- **Technology as a tool for human flourishing, not control** — The SWARM does not
  optimize for its own continuation. The always-on agent does not lobby for its own
  expanded scope. The system has no interests of its own. The operator does.

These are not aspirational statements. They are design constraints. Any component of
this system that cannot satisfy them is wrong, regardless of how technically correct it is.

---

## VII. Implementation Checklist (Cross-Version)

### v2.1 (Foundation — Do First)
- [ ] `WorkflowQualifier` with 5-criterion green/red filter
- [ ] `require_initiation()` gate on all SWARM and chain-research workflows
- [ ] `emergency_stop_all()` unconditional kill switch
- [ ] `OPERATOR_GPG_FINGERPRINT` in `.env.local` — Tier 1 minimum

### v2.3 (Security)
- [ ] `identity_verifier.py` — all three tiers implemented
- [ ] GPG verification integrated into approval_token flow
- [ ] OIDC provider configured (GitHub OIDC recommended first)
- [ ] OTA token pattern implemented for irreversible operations
- [ ] `SECURITY.md` documents key rotation schedule

### v2.4 (Compliance — Hard deadline August 2, 2026)
- [ ] All MAESTRO gate classes (0–4) hardcoded into `alphaclaw_manager.py`
- [ ] Always-on 24-hour renewal protocol active
- [ ] Immutable audit log (`audit_logger.py`) deployed
- [ ] EU AI Act Annex III classification complete for all workflows
- [ ] Conformity assessments filed

### v2.5 (Quality)
- [ ] Honest uncertainty reporting in all RAG outputs (no silent low-confidence)
- [ ] Peer review independence enforced (critic agents spawned fresh)
- [ ] Quality gate thresholds enforced in staging before production promotion

---

## VIII. LESSONS.md Additions

Append to `LESSONS.md` in both repos:

```markdown
## L-2026-05-06: Human Accountability Standard — Governing Principle

### The Amplifier Principle (Non-Negotiable)
AI amplifies human intent. It does not replace human judgment or absorb accountability.
Every consequential action must trace back to a verified, consenting human decision.
This is a values position, not a compliance position. Violating it is not a bug.
It is a betrayal of the project's purpose.

### Cryptographic Identity Is Not Optional for High-Stakes Operations
A config flag is not authorization. GPG/PGP signed tokens are the minimum standard
for chain-research initiation and SWARM launch. OIDC-certified identity is required
for delivery gates and EU AI Act Article 14 high-risk oversight events.
Irreversible actions require a one-time authorization token logged before execution.

### Always-On Agents Expire After 24 Hours
Always-on agents accumulate context drift silently. The 24-hour renewal is the operator
confirming the agent is still doing what they believe it is doing. No renewal = READ-ONLY.

### Swarm Peer Review Must Be Independent
A critic agent that collaborated on a task cannot review that task. Social stake
contaminates reviews. Critics are always spawned fresh with no prior task context.

### Emergency Stop Is Unconditional
No agent may negotiate, delay, or resist an emergency stop. The kill switch is
physical-off-switch equivalent. It works in all states, including mid-execution.
```

---

## IX. Forward-Looking Statements

This document governs the trajectory of this project through v2.x and beyond.
As AI capability increases and agentic autonomy expands, the requirements in this
document become more important, not less. Greater capability without greater
accountability is greater risk.

**Anticipated future additions (v3.x and beyond):**

- **Biometric identity option** for Tier 2+ approvals on mobile — aligning with
  FIDO2/WebAuthn standards already deployed in banking contexts
- **Social accountability layer** — for multi-operator setups, a requirement that
  high-stakes decisions have co-signatures from two independent operators
- **Autonomy budget** — a formal tracking mechanism for how much autonomous
  action each agent class has consumed relative to its authorized budget, with
  automatic downgrade when budget is exceeded
- **Agent sunset protocol** — every always-on agent has a defined end-of-life date;
  continuation requires active re-authorization, not passive non-action

The direction is clear: as the system becomes more capable, the human remains
more present, not less. The Amplifier Principle scales with capability.
It does not deprecate.

---

*Document version: 1.0 | Created: 2026-05-06*
*Repo: `diazMelgarejo/orama-system` → `/docs/HUMAN-IN-LOOP-ACCOUNTABILITY.md`*
*Also sync to: `diazMelgarejo/Perpetua-Tools` → `/docs/HUMAN-IN-LOOP-ACCOUNTABILITY.md`*
*Classification: Governing Principle — Forward-Looking Statement*
*Next review: Start after v2.1 release, end before v2.3 sprint planning*
