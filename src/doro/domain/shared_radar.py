"""Revision comparisons only. Synchronization receipts remain owned by Obsidian."""
from collections.abc import Mapping

from doro.domain.models import DoroError


def changed_revisions(remote: Mapping[str, int], received: Mapping[str, int],
                      pending: Mapping[str, str]) -> tuple[str, ...]:
    if set(remote) != set(received):
        raise DoroError("Radar Page scope and received baselines differ; do not reset them")
    changes = ["outbox:" + key + ":" + sha for key, sha in sorted(pending.items())]
    for page, sequence in sorted(remote.items()):
        if sequence < received[page]:
            raise DoroError("Radar observed an older Page version; no automatic rollback")
        if sequence > received[page]:
            changes.append("page:" + page + ":" + str(sequence))
    return tuple(changes)
