"use strict";
/** @typedef {{speaker:string,phase:string,text:string}} Turn */
/** @typedef {{id:string,kind:string,summary:string,decision:string}} Checkpoint */
/** @typedef {{speaker:string,phase:string,input:string,output:string,status:string,error:string}} Exchange */
/** @typedef {{session_id:string,mode:string,status:string,speaker:string,phase:string,task:string,context:string,calls:Record<string,number>,claude_call_limit:number,cost_usd_reported:number,agy_enabled:boolean,error:string,turns:Turn[],checkpoints:Checkpoint[],exchanges:Exchange[],pending_input:string,pending_input_error:string}} State */
const names = {work:"GPT Work · 도로",claude:"Claude Code",codex:"GPT · Codex CLI"};
const phases = {draft:"초안",review:"검토",rebuttal:"반론·보완",recheck:"재검토",final:"최종 판단",decision:"검토 결과 반영",completed:"완료"};
const gates = {start:"시작 범위",branch:"중요 분기",apply:"파일 반영"};
const decisions = {pending:"승인 대기",approve:"승인",reject:"보류·수정 요청"};
const token = location.hash.slice(1) || sessionStorage.getItem("doro-view-token") || "";
if(token)sessionStorage.setItem("doro-view-token",token);
history.replaceState(null,"",location.pathname);
let previous = "", historyKey = "", auditKey = "";

/** @param {string} id @param {string} text */
function setText(id,text) {
  const node=document.getElementById(id);
  if(node && node.textContent!==text)node.textContent=text;
}
/** @param {string} id @param {boolean} value */
function show(id,value) {const node=document.getElementById(id);if(node)node.hidden=!value;}

/** @param {string} title @param {string} text @param {boolean} open */
function detail(title,text,open=false) {
  const row=document.createElement("details"),summary=document.createElement("summary"),body=document.createElement("pre");
  row.open=open;summary.textContent=title;body.textContent=text;row.append(summary,body);return row;
}

/** @param {State} state */
function renderApproval(state) {
  const gate=state.checkpoints.at(-1);
  show("approval-section",!!gate);
  if(!gate)return;
  const waiting=state.status==="awaiting_approval",declined=state.status==="awaiting_direction";
  setText("approval-state",`${gates[gate.kind]||gate.kind} · ${decisions[gate.decision]||gate.decision}`);
  setText("approval-summary",gate.summary);
  setText("approval-help",waiting?"이 대화에 뜬 승인 요청에 답해줘. 답하기 전에는 다음 단계로 넘어가지 않아.":declined?"네가 방향을 정하거나 수정안을 승인할 때까지 기다려.":"승인한 범위에서 이어가. 중요한 분기와 파일 반영은 다시 확인해.");
  setText("approval-log",state.checkpoints.map((g,i)=>`${i+1}. ${gates[g.kind]||g.kind} · ${decisions[g.decision]||g.decision}\n${g.summary}`).join("\n\n"));
}

/** @param {State} state */
function renderExchange(state) {
  show("pending-section",!!state.pending_input || !!state.pending_input_error);
  setText("pending-input",state.pending_input);setText("pending-error",state.pending_input_error);
  show("pending-error",!!state.pending_input_error);
  const latest=state.exchanges.at(-1);show("exchange-section",!!latest);
  if(!latest)return;
  const labels={running:"응답 생성 중",completed:"응답 수신 완료",failed:"실패 · 부분 응답 보존",interrupted:"중단 · 부분 응답 보존"};
  setText("exchange-state",`${names[latest.speaker]||latest.speaker} · ${phases[latest.phase]||latest.phase} · ${labels[latest.status]||latest.status}`);
  setText("exchange-input",latest.input);setText("exchange-output",latest.output||"첫 응답을 기다리는 중이야.");
  setText("response-label",latest.status==="completed"?"CLI가 완료한 최종 응답이야. 도로가 내용을 검토해.":"생성 중인 공개 응답이야. 완료 전에는 다음 참가자에게 전달하지 않아.");
  setText("exchange-error",latest.error);show("exchange-error",!!latest.error);
  const previousExchanges=state.exchanges.slice(0,-1),key=JSON.stringify(previousExchanges);
  if(key===auditKey)return;
  auditKey=key;const host=document.getElementById("past-exchanges");
  if(host)host.replaceChildren(...previousExchanges.map((x,i)=>detail(`${i+1}. 이전 입력·응답 · ${names[x.speaker]||x.speaker}`,
    `상태: ${labels[x.status]||x.status}\n\n[보낸 입력]\n${x.input}\n\n[응답]\n${x.output}\n\n${x.error}`)));
}

/** @param {State} state */
function renderHistory(state) {
  const key=JSON.stringify(state.turns);if(key===historyKey)return;
  historyKey=key;const host=document.getElementById("history");
  if(!host)return;
  const old=Array.from(host.children).map(row=>row instanceof HTMLDetailsElement && row.open);
  host.replaceChildren(...state.turns.map((turn,i)=>detail(`${i+1}. ${names[turn.speaker]||turn.speaker} · ${phases[turn.phase]||turn.phase}`,
    turn.text,i<old.length?old[i]:i>=state.turns.length-2)));
}

/** @param {State} state */
function render(state) {
  const main=state.mode==="work"?"GPT Work":"Codex CLI";
  setText("owner",`네가 요청할 때 시작하고, ${main}가 최종 판단을 맡아.`);
  const statuses={awaiting_approval:"네 승인을 기다리는 중",awaiting_direction:"네 방향 결정을 기다리는 중",failed:"협업이 멈췄어 · 오류 확인이 필요해",interrupted:"협업이 중단됐어",completed:"도로의 최종 판단까지 완료"};
  setText("current",statuses[state.status]||`${names[state.speaker]||state.speaker} · ${phases[state.phase]||state.phase}`);
  setText("task",state.task);setText("calls",`${state.calls.claude||0} / ${state.claude_call_limit}회`);
  setText("cost",`$${state.cost_usd_reported.toFixed(4)}`);setText("agy",state.agy_enabled?"활성":"꺼짐");
  setText("turns",`${state.turns.length}개 발언`);
  const final=state.turns.find(turn=>turn.phase==="final");
  show("decision-section",!!final);
  if(final){setText("decision-summary",final.text.split(/\n\s*\n/)[0]);setText("decision-full",final.text);}
  const flow=document.getElementById("flow"),done=new Set(state.turns.map(turn=>turn.phase));
  if(flow)Array.from(flow.children).forEach((node,index)=>{
    const phase=node.getAttribute("data-phase")||"",speaker=index%2===0?main:"Claude";
    node.textContent=`${speaker} ${phases[phase]||phase}`;
    node.className=done.has(phase)?"done":state.status!=="completed" && index===state.turns.length?"active":"";
  });
  renderApproval(state);renderExchange(state);renderHistory(state);
  show("error",!!state.error);setText("error",state.error);
}

async function poll() {
  try {
    const response=await fetch("/api/status",{headers:{Authorization:`Bearer ${token}`},cache:"no-store"});
    if(response.status===401){setText("freshness","도로에게 진행 상황판을 다시 열어달라고 말해줘");return;}
    if(!response.ok)throw new Error(`상태를 읽지 못했어 (${response.status})`);
    /** @type {State} */ const state=await response.json();
    const key=JSON.stringify(state);if(key!==previous){render(state);previous=key;}
    setText("freshness",`마지막 확인 ${new Date().toLocaleTimeString("ko-KR")}`);
    if(state.status==="completed")return;
  } catch(error) {setText("freshness",error instanceof Error?error.message:"연결 확인이 필요해");}
  setTimeout(poll,1000);
}
poll();
