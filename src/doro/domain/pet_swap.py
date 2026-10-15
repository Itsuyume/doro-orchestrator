from dataclasses import replace
import re

from doro.domain.models import DoroError, PetSwap


def prepare_swap(state: PetSwap | None, session_id: str, observed: str) -> PetSwap:
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", observed):
        raise DoroError("A stable pet ID from the actual official selection is required")
    if state is None or state.stage in {"restored", "superseded"}:
        if observed == "default":
            raise DoroError("No original official pet is known; do not guess a restore target")
        return PetSwap(observed, (session_id,), "prepared")
    expected = "default" if state.stage == "active" else state.original_pet_id
    if observed != expected or state.stage not in {"active", "prepared"}:
        raise DoroError("Official pet selection changed or restoration is pending; do not overwrite it")
    sessions = tuple(dict.fromkeys((*state.sessions, session_id)))
    return replace(state, sessions=sessions)


def activate_swap(state: PetSwap, session_id: str, observed: str) -> PetSwap:
    if state.stage not in {"prepared", "active"} or session_id not in state.sessions or observed != "default":
        raise DoroError("Verify the official companion is off before activating the dedicated pet")
    return replace(state, stage="active")


def release_swap(state: PetSwap, session_id: str) -> PetSwap:
    if state.stage not in {"prepared", "active"} or session_id not in state.sessions:
        raise DoroError("No display lease belongs to this session")
    remaining = tuple(value for value in state.sessions if value != session_id)
    return replace(state, sessions=remaining, stage=state.stage if remaining else "restoring")


def finish_restore(state: PetSwap, observed: str) -> PetSwap:
    if state.stage != "restoring" or state.sessions or observed == "default":
        raise DoroError("Restoration is not confirmed, or another display lease remains")
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", observed):
        raise DoroError("A stable observed pet ID is required")
    return replace(state, stage="restored" if observed == state.original_pet_id else "superseded")
