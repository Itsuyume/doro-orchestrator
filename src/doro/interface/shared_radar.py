"""Model-free checks; only actual new revisions may enqueue the existing Work."""
import argparse
import json
from pathlib import Path
import sqlite3
import time

from doro.domain.models import DoroError
from doro.domain.shared_radar import changed_revisions
from doro.domain.work_delivery import QueueFailure
from doro.infrastructure.metadata_rpc import page_versions
from doro.infrastructure.radar_observer import pending_versions
from doro.infrastructure.radar_settings import RadarSettings, load_settings
from doro.infrastructure.radar_store import RadarJournal, journal, save_report
from doro.infrastructure.work_queue import CodexQueue


def observe(settings: RadarSettings, store: RadarJournal) -> tuple[str, ...] | None:
    active, pending, received = pending_versions(settings)
    if not active:
        return None
    checked, remote = store.cached()
    now = time.time()
    stale = set(remote) != set(received) or any(remote.get(p, -1) < version for p, version in received.items())
    if stale or not 0 <= now - checked < settings.remote_seconds:
        remote = page_versions(settings.codex, settings.state_root, tuple(received))
        store.cache(now, remote)
    return changed_revisions(remote, received, pending)


def delivery_message(settings: RadarSettings, event: str, revisions: tuple[str, ...]) -> str:
    envelope = {"version": 1, "event_id": event, "owner_thread_id": settings.owner,
                "revisions": list(revisions)}
    return ("공용 자료함 감시기가 보낸 자동 변경 알림이도로. 사람의 새 발언이나 승인이 아니도로.\n"
            "DORO_SHARED_CHANGE " + json.dumps(envelope, ensure_ascii=False) + "\n"
            "사용자가 승인한 공용 자료함↔Space 연결만 기존 이 Work에서 이어서 처리하도로. "
            "실제 현재 버전과 미전송 항목을 다시 대조하고 이미 처리한 변경은 반복하지 마도로. "
            "현재 연결 정본은 " + str(settings.connection) + " 이도로. "
            "기존 작업 절차는 " + str(settings.automation) + " 의 prompt를 읽어 따르도로. "
            "이 예약의 PAUSED는 변경 없는 정기 Work 호출을 막기 위한 상태이도로. "
            "Obsidian 자체의 중지·공용 연결 비활성·충돌·Private 경계는 그대로 지키도로. "
            "원문·다른 노트·다른 대화를 자동 전송하거나 Claude·AGY를 호출하지 마도로.")


def inspect_once(settings: RadarSettings, store: RadarJournal, dry_run: bool = False) -> dict[str, object]:
    if not settings.enabled:
        return {"state": "disabled", "work_queued": False}
    changes = observe(settings, store)
    if changes is None:
        return {"state": "obsidian_paused", "work_queued": False}
    if dry_run:
        return {"state": "preview", "changes": list(changes), "work_queued": False}
    claimed = store.claim(changes)
    if claimed is None:
        return {"state": "unchanged", "work_queued": False}
    event, revisions = claimed
    try:
        receipt = CodexQueue(settings.state_root, settings.codex).enqueue(
            settings.owner, delivery_message(settings, event, revisions))
    except QueueFailure as error:
        state = "unknown" if error.uncertain else "failed"
        store.complete(event, state, error=str(error))
        raise
    store.complete(event, "queued", receipt)
    return {"state": "queued", "event_id": event, "queue_id": receipt, "changes": list(revisions),
            "work_queued": True}


def main() -> int:
    parser = argparse.ArgumentParser(description="Check shared-library revisions without model generation")
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--status", action="store_true")
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    try:
        if args.report is not None:
            emit({"state": "reading_configuration", "work_queued": False}, args.report)
        settings = load_settings(args.config)
        with journal(settings.state_root, settings.owner) as store:
            result = store.status() if args.status else inspect_once(settings, store, args.dry_run)
        emit(result, args.report)
        return 0
    except QueueFailure as error:
        emit({"state": "unknown" if error.uncertain else "failed", "error": str(error),
              "work_queued": None if error.uncertain else False}, args.report)
        return 1
    except (DoroError, OSError, ValueError, sqlite3.Error) as error:
        emit({"state": "error", "error": str(error), "work_queued": None}, args.report)
        return 1


def emit(result: dict[str, object], report: Path | None) -> None:
    result["checked_at"] = time.time()
    if report is not None:
        save_report(report, result)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    raise SystemExit(main())
