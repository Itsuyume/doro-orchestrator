"use strict";
/** @typedef {{speaker:string,phase:string,text:string}} Turn */
/** @typedef {{session_id:string,mode:string,status:string,speaker:string,phase:string,task:string,calls:Record<string,number>,claude_call_limit:number,cost_usd_reported:number,agy_enabled:boolean,error:string,turns:Turn[]}} State */
const names = {work:"GPT Work · 도로",claude:"Claude Code",codex:"GPT · Codex CLI"};
const phases = {draft:"초안",review:"검토",rebuttal:"반론·보완",recheck:"재검토",final:"최종 판단",decision:"검토 결과 반영",completed:"완료"};
const token = location.hash.slice(1) || sessionStorage.getItem("doro-view-token") || "";
if(token)sessionStorage.setItem("doro-view-token",token);
history.replaceState(null,"",location.pathname);
let previous = "";
/** @param {string} id @param {string} text */
function setText(id,text) {const node=document.getElementById(id);if(node && node.textContent!==text)node.textContent=text;}
/** @param {State} state */
function render(state) {
  const main=state.mode==="work"?"GPT Work":"Codex CLI";
  setText("owner",`네가 요청할 때 시작하고, ${main}가 최종 판단을 맡아.`);
  const waiting=state.status==="awaiting_work"?" · 도로가 검토 결과를 반영할 차례":"";
  const label=state.status==="completed"?"도로의 최종 판단까지 완료":`${names[state.speaker]||state.speaker} · ${phases[state.phase]||state.phase}${waiting}`;
  setText("current",label);setText("task",state.task);
  setText("calls",`${state.calls.claude||0} / ${state.claude_call_limit}회`);
  setText("cost",`$${state.cost_usd_reported.toFixed(4)}`);setText("agy",state.agy_enabled?"활성":"꺼짐");
  setText("turns",`${state.turns.length}개 발언`);
  const flow=document.getElementById("flow");
  const done=new Set(state.turns.map(turn=>turn.phase));
  if(flow)Array.from(flow.children).forEach((node,index)=>{const phase=node.getAttribute("data-phase")||"";const speaker=index%2===0?main:"Claude";node.textContent=`${speaker} ${phases[phase]||phase}`;node.className=done.has(phase)?"done":state.status!=="completed" && index===state.turns.length?"active":"";});
  const host=document.getElementById("history");
  if(host){host.replaceChildren();state.turns.forEach((turn,index)=>{const row=document.createElement("details"),title=document.createElement("summary"),body=document.createElement("pre");row.open=index>=state.turns.length-2;title.textContent=`${index+1}. ${names[turn.speaker]||turn.speaker} · ${phases[turn.phase]||turn.phase}`;body.textContent=turn.text;row.append(title,body);host.append(row);});}
  const error=document.getElementById("error");if(error){error.hidden=!state.error;error.textContent=state.error;}
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
  setTimeout(poll,2000);
}
poll();
