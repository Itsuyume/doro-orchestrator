from dataclasses import asdict
import hashlib
import json

from doro.domain.models import Config, DoroError, Session, Task, WorkRecovery
from doro.domain.policy import ensure_public
from doro.domain.work import validate_work, validate_work_scope, work_text


def session_digest(session: Session) -> str:
    """Bind an explicit recovery to the complete observed state, including pending decisions."""
    raw = json.dumps(asdict(session), sort_keys=True, ensure_ascii=False, allow_nan=False)
    return hashlib.sha256(raw.encode()).hexdigest()


def recover_work(config: Config, session: Session, checkpoint_id: str, expected_state: str,
                 expected_config: str, task: Task, draft: str, reason: str) -> None:
    validate_work_scope(session)
    if session_digest(session) != expected_state or config.fingerprint != expected_config:
        raise DoroError("Session or configuration changed after inspection; recovery was not applied")
    if config.fingerprint == session.config_fingerprint:
        raise DoroError("Configuration already matches; no duplicate recovery was applied")
    if session.rounds != config.limits.debate_rounds:
        raise DoroError("Changed review rounds require a separately reviewed scope")
    if session.status != "awaiting_approval" or session.turns[-1].provider != "work":
        raise DoroError("Recovery requires the existing unanswered scope and a Work draft")
    gate = session.checkpoints[-1]
    if gate.id != checkpoint_id or gate.kind != "start" or gate.decision != "pending":
        raise DoroError("Recovery checkpoint is stale or is not the initial scope")
    if task.classification != "public" or task.allowed_providers != session.task.allowed_providers:
        raise DoroError("Recovery cannot add an advisor or change the public-input boundary")
    if "agy" in task.allowed_providers and not config.providers["agy"].enabled:
        raise DoroError("AGY is disabled; recovery cannot enable it")
    ensure_public(task.message + "\n" + task.context)
    if not reason.strip() or len(reason) > 1000:
        raise DoroError("Recovery needs a meaningful reason within 1000 characters")
    ensure_public(reason)
    revision = work_text(config, draft, "revision")
    recovery = WorkRecovery(session.config_fingerprint, config.fingerprint, session.task,
                            checkpoint_id, reason, len(session.turns))
    session.recoveries.append(recovery)
    session.turns.append(revision)
    session.task, session.config_fingerprint = task, config.fingerprint
    validate_work(config, session)
