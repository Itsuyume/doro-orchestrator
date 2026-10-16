"""External-process fixtures, not replacements for internal radar logic."""
import json
from pathlib import Path
import sys
from uuid import uuid4

from doro.infrastructure.radar_settings import RadarSettings

PAGES = ("page_" + "a" * 32, "page_" + "b" * 32)

FAKE_OBSIDIAN = r'''
import pathlib,json
r=pathlib.Path(__file__).parent
d=json.loads((r/'probe.json').read_text())
c=json.loads((r/'vault/AI/config/connection.json').read_text())
state=json.loads((r/'vault/.obsidian/plugins/doro-study-sync/shared-state.json').read_text())
pages=[c['libraryPageId'],c['handoffPageId']]
d.update({'vault':str(r/'vault'),'pages':pages,'received':{p:state['pages'][p]['sequence'] for p in pages}})
print('=> '+json.dumps(d))
'''


FAKE_CODEX = r'''
import json,sys,subprocess
from pathlib import Path
r=Path(__file__).parent
if len(sys.argv)>1 and sys.argv[1]=='app-server' and (r/'spawn-child').exists():
 child=subprocess.Popen([sys.executable,'-c','import time;time.sleep(60)'])
 (r/'child.pid').write_text(str(child.pid))
def log(value):
 with (r/'calls.jsonl').open('a') as f: f.write(json.dumps(value)+'\n')
if sys.argv[1]=='queue':
 log({'command':'queue','args':sys.argv[2:]})
 owner=sys.argv[sys.argv.index('--thread')+1]
 receipt='bad-receipt' if (r/'bad-queue').exists() else '11111111-1111-4111-8111-111111111111'
 print('Queued message '+receipt+' for thread '+owner+'.')
 sys.exit(0)
for line in sys.stdin:
 x=json.loads(line); method=x['method']; log({'method':method,'params':x['params']})
 if 'id' not in x: continue
 if method=='initialize': result={}
 elif method=='thread/start': result={'thread':{'id':'temporary-context'}}
 elif method=='mcpServer/tool/call':
  page=x['params']['arguments']['page_id']
  data=json.loads((r/'remote.json').read_text())
  result={'isError':(r/'rpc-error').exists(),'structuredContent':{'content':None,'metadata':{'page_id':page,'current_sequence':data[page]}}}
 else: raise RuntimeError('Unexpected or model-generating method: '+method)
 print(json.dumps({'id':x['id'],'result':result}),flush=True)
'''


def fixture(root: Path) -> RadarSettings:
    codex, obsidian = root / "codex", root / "obsidian"
    codex.write_text("#!" + sys.executable + "\n" + FAKE_CODEX)
    obsidian.write_text("#!" + sys.executable + "\n" + FAKE_OBSIDIAN)
    codex.chmod(0o700)
    obsidian.chmod(0o700)
    vault = root / "vault"
    plugin = vault / ".obsidian/plugins/doro-study-sync"
    plugin.mkdir(parents=True)
    pages = PAGES
    (plugin / "shared-state.json").write_text(json.dumps({"pages": {p: {"sequence": 1} for p in pages}}))
    (root / "remote.json").write_text(json.dumps({p: 1 for p in pages}))
    (root / "probe.json").write_text(json.dumps({"enabled": True, "pending": []}))
    connection = vault / "AI/config/connection.json"
    connection.parent.mkdir(parents=True)
    connection.write_text(json.dumps({"enabled": True, "libraryPageId": pages[0], "handoffPageId": pages[1]}))
    owner = str(uuid4())
    automation = root / "automation.toml"
    automation.write_text('id="space"\ntarget_thread_id="' + owner + '"\n')
    settings = RadarSettings(True, connection, automation, root / "journal", codex, obsidian,
                             owner, vault, 1800)
    settings.state_root.mkdir()
    return settings


def calls(root: Path) -> list[dict[str, object]]:
    path = root / "calls.jsonl"
    return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []
