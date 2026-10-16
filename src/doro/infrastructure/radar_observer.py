import json
import re
import unicodedata

from doro.domain.models import DoroError
from doro.domain.validation import boolean, integer, mapping, string
from doro.infrastructure.process import execute
from doro.infrastructure.radar_settings import RadarSettings


PROBE = """(async () => {
 const p = app.plugins.plugins['doro-study-sync'];
 if (!p?.shared) throw new Error('Shared-library plugin is unavailable');
 const c = await p.shared.settings();
 const enabled = Boolean(c?.enabled && p.shared.active());
 const pending = enabled ? (await p.shared.pending()).map(x => ({id:x.id,sha:x.sha})) : [];
 const pages = enabled ? [c.libraryPageId,c.handoffPageId] : [];
 const state = enabled ? JSON.parse(require('fs').readFileSync(require('path').join(p.shared.folder,'shared-state.json'),'utf8')) : null;
 const received = Object.fromEntries(pages.map(id => [id,state.pages[id]?.sequence]));
 return JSON.stringify({enabled,pending,pages,received,vault:p.shared.notes.root});
})()"""


def pending_versions(settings: RadarSettings) -> tuple[bool, dict[str, str], dict[str, int]]:
    result = execute([str(settings.obsidian), "vault=" + settings.vault.name, "eval", "code=" + PROBE],
                     "", settings.state_root, 20, 256_000)
    lines = [line[3:] for line in result.stdout.splitlines() if line.startswith("=> ")]
    if result.returncode or len(lines) != 1:
        raise DoroError("Obsidian radar probe failed; no Work fallback or automatic restart")
    data = mapping(json.loads(lines[0]), "Obsidian radar probe")
    enabled = boolean(data.get("enabled"), "Obsidian enabled")
    if unicodedata.normalize("NFC", string(data.get("vault"), "Vault root")) != unicodedata.normalize("NFC", str(settings.vault)):
        raise DoroError("Obsidian connected to a different Vault")
    if not enabled:
        return False, {}, {}
    raw_pages = data.get("pages")
    if not isinstance(raw_pages, list) or len(raw_pages) != 2:
        raise DoroError("Radar requires two explicit Page IDs from the existing connection")
    pages = tuple(string(p, "Page ID") for p in raw_pages)
    if len(set(pages)) != 2 or any(not re.fullmatch(r"page_[0-9a-f]{32}", p) for p in pages):
        raise DoroError("Radar Page scope is invalid")
    raw_received = mapping(data.get("received"), "received versions")
    if set(raw_received) != set(pages):
        raise DoroError("Received Page baseline is missing; do not reset it")
    received = {p: integer(raw_received[p], "received sequence", low=0, high=2**63 - 1) for p in pages}
    return enabled, outbox_versions(data.get("pending")), received


def outbox_versions(value: object) -> dict[str, str]:
    if not isinstance(value, list):
        raise DoroError("Obsidian returned an invalid pending list")
    versions: dict[str, str] = {}
    for raw in value:
        item = mapping(raw, "outbox version")
        key, sha = string(item.get("id"), "outbox id"), string(item.get("sha"), "outbox sha")
        if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,63}", key) or not re.fullmatch(r"[a-f0-9]{64}", sha):
            raise DoroError("Invalid outbox revision; nothing was sent")
        if key in versions:
            raise DoroError("Duplicate outbox ID; nothing was sent")
        versions[key] = sha
    return versions
