"""Chronological OpenAI Decisions API replay. Python standard library only.

No expected labels are read until replay finishes. Credentials stay in memory.
"""
import argparse
from collections import Counter, defaultdict
from copy import deepcopy
from datetime import datetime, timezone
import getpass
import hashlib
import json
import math
import os
from pathlib import Path
import random
import re
import statistics
import sys
import time
import urllib.error
import urllib.request

ENDPOINT = "https://api.openai.com/v1/decisions"
ACTIONS = ["IGNORE", "MONITOR", "REVIEW", "URGENT_REVIEW"]
STATUSES = ["planned", "normal", "active", "unverified", "partially_supported", "disputed", "resolution_reported", "recovery"]
TAG_QUERIES = {
    "UNVERIFIED": "Does an important claim in this report remain unverified by the supplied evidence? An authenticated account does not prove every claim.",
    "DUPLICATE": "Does this report simply repeat an earlier report's claim without adding substantive information?",
    "CONFLICTING": "Does this report conflict with an earlier claim, or repeat a claim already disputed in the prior event evidence?",
    "LOCATION_UNCLEAR": "Is the reported incident's location unknown? A named non-Paris city is not an unknown location.",
    "TIME_UNCLEAR": "Is the reported incident's time unknown? An explicitly old incident has known past timing.",
    "RESOLUTION_REPORTED": "Does this report claim that the specific local interruption or incident has ended? This is a reported resolution, not a verified citywide all-clear."
}

def read_jsonl(path):
    return [json.loads(s) for s in path.read_text(encoding="utf-8").splitlines() if s.strip()]

def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temp.replace(path)

def append_jsonl(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(value, ensure_ascii=False) + "\n")

def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()

def choice(name, instructions, values):
    return {"name":name,"type":"choice","instructions":instructions,
            "choices":[{"value":v,"description":d} for v,d in values.items()]}

def assessment_questions(rubric):
    output=[]
    for q in rubric["questions"]:
        if q["kind"]=="score":
            output.append({"name":q["name"],"type":"score","instructions":q["question"],
                "levels":[{"label":str(i),"description":desc} for i,desc in enumerate(q["levels"])]})
        else:
            options=q["options"]
            if isinstance(options,list):
                options={v:v.replace("_"," ") for v in options}
            if q["name"]=="zone":
                options=dict(options)
                options["paris_west"]="Demo central/west corridor including Opera, Concorde and Etoile; not a hospital catchment."
                options["paris_centre_east"]="Republique and Bastille, within Paris."
                options["paris_northeast"]="La Chapelle and explicitly northern/northeastern Paris."
            output.append(choice(q["name"],q["question"],options))
    return output

def decode_answers(response, questions):
    raw=response.get("answers")
    if not isinstance(raw,list) or len(raw)!=len(questions):
        raise ValueError("Incomplete answers array")
    result={}
    for q,a in zip(questions,raw):
        if a.get("name")!=q["name"]:
            raise ValueError("Answer name mismatch")
        if a.get("type")=="refusal":
            raise RuntimeError("MODEL_REFUSAL: "+q["name"])
        if a.get("type")!=q["type"]:
            raise ValueError("Answer type mismatch")
        if q["type"]=="choice":
            val=a.get("choice")
            if val not in {c["value"] for c in q["choices"]}:
                raise ValueError("Unknown choice")
            result[q["name"]]=val
        elif q["type"]=="predicate":
            val=a.get("probability")
            if not isinstance(val,(float,int)) or not math.isfinite(val) or not 0<=val<=1:
                raise ValueError("Invalid predicate probability")
            result[q["name"]]=val
        else:
            score=a.get("score")
            probs=a.get("probabilities")
            if not isinstance(score,(float,int)) or not math.isfinite(score) or not 0<=score<len(q["levels"]):
                raise ValueError("Invalid score")
            if not isinstance(probs,list) or not probs:
                raise ValueError("Missing score probabilities")
            mode=max(probs,key=lambda p:p["probability"])
            index=int(mode["value"])
            if not 0<=index<len(q["levels"]):
                raise ValueError("Invalid score level index")
            result[q["name"]]=score
            result[q["name"]+"_mode"]=index
    return result

class Client:
    def __init__(self,key,model,folder,timeout=30):
        self.key=key
        self.model=model
        self.folder=folder
        self.timeout=timeout
        self.calls=[]

    def redact(self,text):
        return re.sub(r"sk-[A-Za-z0-9_-]+","[REDACTED]",str(text).replace(self.key,"[REDACTED]"))

    def ask(self,rid,stage,evidence,questions):
        payload={"model":self.model,"input":json.dumps(evidence,ensure_ascii=False),"questions":questions}
        fingerprint=digest(payload)
        cache=self.folder/"calls"/(rid+"_"+stage+".json")
        if cache.exists():
            receipt=json.loads(cache.read_text(encoding="utf-8"))
            if receipt["request_sha256"]!=fingerprint:
                raise ValueError("Cached request changed; use a new run directory")
            self.calls.append(receipt)
            return decode_answers(receipt["response"],questions)
        data=json.dumps(payload,ensure_ascii=False).encode("utf-8")
        headers={"Authorization":"Bearer "+self.key,"Content-Type":"application/json"}
        for attempt in range(1,3):
            started=time.perf_counter()
            try:
                req=urllib.request.Request(ENDPOINT,data=data,headers=headers,method="POST")
                with urllib.request.urlopen(req,timeout=self.timeout) as resp:
                    body=resp.read().decode("utf-8")
                    request_id=resp.headers.get("x-request-id")
                elapsed=time.perf_counter()-started
                response=json.loads(body)
                if response.get("model")!=self.model:
                    raise ValueError("Served-model mismatch: "+str(response.get("model")))
                usage=response.get("usage")
                if not isinstance(usage,dict) or not isinstance(usage.get("input_tokens"),int) or usage["input_tokens"]<=0:
                    raise ValueError("Missing nonzero API token usage")
                receipt={"report_id":rid,"stage":stage,"endpoint":ENDPOINT,
                    "request_sha256":fingerprint,"request":payload,"response":response,
                    "request_id":request_id,"attempt":attempt,"request_latency_s":elapsed,
                    "received_at":datetime.now(timezone.utc).isoformat(),"requested_model":self.model}
                # Record native output before decoding, including any refusal.
                write_json(cache,receipt)
                self.calls.append(receipt)
                return decode_answers(response,questions)
            except urllib.error.HTTPError as e:
                body=self.redact(e.read().decode("utf-8",errors="replace"))
                error={"report_id":rid,"stage":stage,"failure_class":"http_error",
                    "http_status":e.code,"attempt":attempt,"message":body,"request_sha256":fingerprint}
                append_jsonl(self.folder/"errors.jsonl",error)
                if e.code in {429,500,502,503,504} and attempt<2:
                    time.sleep(1+random.random())
                    continue
                raise RuntimeError(f"HTTP {e.code}: {body}") from None
            except (urllib.error.URLError,TimeoutError,OSError) as e:
                append_jsonl(self.folder/"errors.jsonl",{"report_id":rid,"stage":stage,
                    "failure_class":"network_or_timeout","message":self.redact(e),"attempt":attempt})
                raise RuntimeError("Network/timeout error: "+self.redact(e)) from None

def flags_questions(rubric):
    policy="\n".join(rubric["paris_action_policy_in_order"])
    qs=[choice("contribution","Classify this report's contribution to the selected event. If no event was selected use unrelated; if a new event is being created use new_event. "+" ".join(rubric["comparison_stage"]["rules"]),
               {x:x.replace("_"," ") for x in rubric["comparison_stage"]["contribution_options"]}),
        choice("paris_action","Choose the new-report action for the Paris queue. Follow this ordered policy, using report content and selected prior evidence. IGNORE retains the record. Prior severity remains visible at event level.\n"+policy,
               {x:x.replace("_"," ") for x in ACTIONS}),
        choice("event_action","What review priority should the selected/new event now retain, for its own geographical route? Do not apply the Paris exclusion to a Lyon event. Preserve unresolved earlier serious claims through duplicates and historical material; an incomplete weaker account does not clear them. Corrections or resolution reports require REVIEW. No event means IGNORE.",
               {x:x.replace("_"," ") for x in ACTIONS}),
        choice("event_status","What is the evidence/lifecycle state of the selected/new event after this report? A single resolution report supports resolution_reported, not automatic closure. No event: use normal.",
               {x:x.replace("_"," ") for x in STATUSES})]
    for tag,instructions in TAG_QUERIES.items():
        qs.append({"name":"tag_"+tag,"type":"predicate","instructions":instructions})
    return qs

def replay(client,reports,rubric,folder):
    history=[]
    events={}
    predictions=[]
    policy=rubric["model_input_policy"]
    qa=assessment_questions(rubric)
    qf=flags_questions(rubric)
    for report in reports:
        rid=report["report_id"]
        # History consists only of raw previous posts, never authored labels.
        common={"task":"Synthetic social-report triage, not clinical demand estimation.",
                "rules":policy,"simulated_now":report["available_at"],"current_report":report}
        assessment=client.ask(rid,"assess",dict(common,prior_reports=history),qa)
        candidates=list(events.values())
        choices={"NEW_EVENT":"A relevant new incident, planned gathering, national/regional context, recovery, or an unlocated claim not linked to an existing event.",
                 "NO_EVENT":"Unrelated ordinary social content or explicitly historical content with no useful existing event link."}
        choices.update({e["event_id"]:"Existing event; judge its supplied reports, time, place and claims." for e in candidates})
        matchq=choice("event_match","Choose the event this report concerns. Shared protest vocabulary, one city, or proximity alone does not identify the same event. Explicit reposts should retain their existing event. Unknown time/location must not be guessed. Use only earlier candidate evidence.",choices)
        matched=client.ask(rid,"match",dict(common,assessment=assessment,candidate_events=candidates),[matchq])["event_match"]
        prior=deepcopy(events.get(matched))
        selection="existing" if prior else ("new" if matched=="NEW_EVENT" else "none")
        flags=client.ask(rid,"flags",dict(common,assessment=assessment,selected_event=prior,
                        event_selection=selection,quoted_previous_reports=[p for p in history if p["report_id"]==report.get("quoted_report_id")]),qf)
        event_id=None
        if matched!="NO_EVENT":
            event_id=matched if prior else f"MODEL-EV-{len(events)+1:03d}"
            if prior:
                state=deepcopy(prior)
            else:
                state={"event_id":event_id,"reports":[],"zone":assessment["zone"]}
            state["reports"].append(report)
            state["as_of"]=report["available_at"]
            state["event_action"]=flags["event_action"]
            state["status"]=flags["event_status"]
            state["latest_assessment"]=assessment
            state["latest_report_id"]=rid
            if assessment["zone"] not in {"unknown","france_unspecified","paris_unspecified"}:
                state["zone"]=assessment["zone"]
            state["action_route"]="paris" if state["zone"].startswith("paris_") else state["zone"]
            events[event_id]=state
        pred={"report_id":rid,"available_at":report["available_at"],"assessment":assessment,
              "event_match_choice":matched,"event_id":event_id,"decisions":flags,
              "tags":[tag for tag in TAG_QUERIES if flags["tag_"+tag]>=0.5],
              "predicate_threshold":0.5,"event_after":deepcopy(events.get(event_id))}
        predictions.append(pred)
        history.append(report)
        write_json(folder/"predictions.json",predictions)
        write_json(folder/"event_states.json",list(events.values()))
        print(f"{rid} {report['available_at'][8:10]} Oct {report['available_at'][11:16]} -> {flags['paris_action']} | {event_id or 'no event'} | {flags['contribution']} | event {flags['event_action']}",flush=True)
    return predictions

def evaluate(predictions,expected,reports,client,run):
    by_expected={t["report_id"]:t for t in expected}
    by_report={r["report_id"]:r for r in reports}
    confusion={a:{b:0 for b in ACTIONS} for a in ACTIONS}
    grades=defaultdict(list)
    compared=[]
    baseline=run/"baseline"
    (baseline/"traces").mkdir(parents=True,exist_ok=True)
    result_rows=[]
    for p in predictions:
        rid=p["report_id"]
        target=by_expected[rid]
        expected_action=target["paris_action"]
        actual=p["decisions"]["paris_action"]
        confusion[expected_action][actual]+=1
        g={"flag_agreement":int(actual==expected_action)}
        diffs={}
        for name,reference in target["decisions"].items():
            predicted=p["assessment"][name+"_mode" if name=="reported_impact_level" else name]
            g[name+"_agreement"]=int(predicted==reference)
            if predicted!=reference:
                diffs[name]={"expected":reference,"actual":predicted}
        g["contribution_agreement"]=int(p["decisions"]["contribution"]==target["comparison"]["contribution"])
        if target["comparison"]["expected_event_id"] is not None:
            g["event_priority_agreement"]=int(p["decisions"]["event_action"]==target["expected_event_action_after"])
            g["event_status_agreement"]=int(p["decisions"]["event_status"]==target["expected_event_status_after"])
        for tag in TAG_QUERIES:
            g["tag_"+tag+"_agreement"]=int((tag in p["tags"])==(tag in target["tags"]))
        for key,val in g.items():
            grades[key].append(val)
        calls=[c for c in client.calls if c["report_id"]==rid]
        tokens=sum(c["response"]["usage"]["input_tokens"] for c in calls)
        latency=sum(c["request_latency_s"] for c in calls)
        trace={"prompt_id":rid,"rep":1,"turns":[],"reference":target,"prediction":p}
        for c in calls:
            trace["turns"].extend([{"role":"user","content":c["request"]["input"]},
                                   {"role":"assistant","content":json.dumps(c["response"],ensure_ascii=False)}])
        write_json(baseline/"traces"/(rid+"_rep1.json"),trace)
        row={"prompt_id":rid,"rep":1,"model":client.model,"status":"ok","grade":g,
             "prompt":by_report[rid]["text"],"tags":[by_report[rid]["published_at"][:10]],
             "usage":{"input_tokens":tokens,"output_tokens":sum(c["response"]["usage"].get("output_tokens",0) for c in calls)},
             "latency_s":latency,"cost_usd_base_input_rate_estimate":tokens*0.10/1_000_000,
             "stop_reason":"typed_decisions_complete","trace_ref":f"baseline/traces/{rid}_rep1.json"}
        result_rows.append(row)
        compared.append({"report_id":rid,"expected_flag":expected_action,"actual_flag":actual,
            "flag_agrees":actual==expected_action,"expected_event_id":target["comparison"]["expected_event_id"],
            "actual_event_id":p["event_id"],"field_disagreements":diffs,
            "expected_contribution":target["comparison"]["contribution"],"actual_contribution":p["decisions"]["contribution"],
            "expected_event_action":target["expected_event_action_after"],"actual_event_action":p["decisions"]["event_action"],
            "expected_event_status":target["expected_event_status_after"],"actual_event_status":p["decisions"]["event_status"]})
    (baseline/"results.jsonl").write_text("".join(json.dumps(r,ensure_ascii=False)+"\n" for r in result_rows),encoding="utf-8")
    write_json(run/"comparison.json",compared)
    pair_tp=pair_fp=pair_fn=pair_tn=0
    for i,p in enumerate(predictions):
        for q in predictions[:i]:
            a=by_expected[p["report_id"]]["comparison"]["expected_event_id"]
            b=by_expected[q["report_id"]]["comparison"]["expected_event_id"]
            same_expected=a is not None and a==b
            same_actual=p["event_id"] is not None and p["event_id"]==q["event_id"]
            if same_actual and same_expected: pair_tp+=1
            elif same_actual: pair_fp+=1
            elif same_expected: pair_fn+=1
            else: pair_tn+=1
    counts=Counter(t["paris_action"] for t in expected)
    total_tokens=sum(c["response"]["usage"]["input_tokens"] for c in client.calls)
    per_class={}
    for a in ACTIONS:
        tp=confusion[a][a]
        predicted=sum(confusion[b][a] for b in ACTIONS)
        positive=sum(confusion[a].values())
        per_class[a]={"support":positive,"precision":tp/predicted if predicted else None,"recall":tp/positive if positive else None}
    summary={"interpretation":"Exploratory agreement with assistant-authored, unreviewed labels; not real-world or clinical accuracy.",
        "model":client.model,"reports_completed":len(predictions),"reports_expected":len(expected),
        "actual_api_requests":len(client.calls),"repetitions":1,
        "metric_agreement":{k:{"matched":sum(v),"n":len(v),"rate":statistics.mean(v)} for k,v in grades.items()},
        "confusion_matrix_expected_rows_actual_columns":confusion,"per_class":per_class,
        "majority_class_baseline":{"flag":counts.most_common(1)[0][0],"agreement":max(counts.values())/len(expected)},
        "event_pair_counts":{"true_positive":pair_tp,"false_positive":pair_fp,"false_negative":pair_fn,"true_negative":pair_tn},
        "event_pair_precision":pair_tp/(pair_tp+pair_fp) if pair_tp+pair_fp else None,
        "event_pair_recall":pair_tp/(pair_tp+pair_fn) if pair_tp+pair_fn else None,
        "input_tokens":total_tokens,"base_rate_estimated_cost_usd":total_tokens*0.10/1_000_000,
        "cost_note":"Input usage from native responses at the published $0.10/M base rate. Not a billing receipt; regional/long-context premiums are not known.",
        "sum_successful_request_latency_s":sum(c["request_latency_s"] for c in client.calls),
        "uncertainty_note":"Single chronological trajectory; correlated event reports and no repeated runs. No generalisation interval or stability claim.",
        "tag_threshold_note":"0.5 is a disclosed demonstration threshold, not calibrated on held-out data."}
    write_json(run/"summary.json",summary)
    write_json(baseline/"summary.json",{"label":"OpenAI Decisions chronological replay","model":client.model,
        "description":summary["interpretation"]})
    write_json(run/"_state.json",{"flow":"Paris social chronological replay","primary_metric":"flag_agreement","test_ids":[r["report_id"] for r in reports]})
    md="# OpenAI Decisions API: chronological replay\n\n"+summary["interpretation"]+"\n\n"
    rate=summary["metric_agreement"]["flag_agreement"]
    md+=f"**Report flags: {rate['matched']}/{rate['n']} agree ({rate['rate']:.1%}).** Majority-class baseline: {summary['majority_class_baseline']['agreement']:.1%}.\n\n"
    md+=f"Model: `{client.model}`. Calls: {len(client.calls)}. Input tokens: {total_tokens:,}. Published base-rate estimate: ${summary['base_rate_estimated_cost_usd']:.6f}. This is not a billing receipt.\n\n"
    md+="The API directly selected the report flag and event priority. Expected labels were read only after replay. Events were built from prior model outputs and raw prior posts. There was no oracle event routing. The six core tags use a 0.5 predicate threshold.\n\n"
    md+="| Expected / actual | IGNORE | MONITOR | REVIEW | URGENT_REVIEW |\n|---|---:|---:|---:|---:|\n"
    for a in ACTIONS: md+="| "+a+" | "+" | ".join(str(confusion[a][b]) for b in ACTIONS)+" |\n"
    md+="\n## Every incoming post\n\n| Time / ID | Expected flag | API flag | API event / contribution | Event priority / state |\n|---|---|---|---|---|\n"
    for p,t in zip(predictions,compared):
        f=p["decisions"]
        md+=f"| {p['available_at'][8:10]} Oct {p['available_at'][11:16]} / {p['report_id']} | {t['expected_flag']} | {t['actual_flag']}{' **DISAGREES**' if not t['flag_agrees'] else ''} | {p['event_id'] or 'none'} / {f['contribution']} | {f['event_action']} / {f['event_status']} |\n"
    md+="\n## Flag disagreements\n\n"
    for t in compared:
        if not t["flag_agrees"]:
            r=by_report[t["report_id"]]
            md+=f"### {t['report_id']}: expected {t['expected_flag']}, API {t['actual_flag']}\n\n{r['text']}\n\nReference rationale: {by_expected[t['report_id']]['rationale']}\n\nOther field disagreements: `{json.dumps(t['field_disagreements'],ensure_ascii=False)}`.\n\n"
    md+="## Limits\n\nThis small case set and its labels were generated by the assistant in the earlier conversation, not independently adjudicated. Label disagreements can reflect model errors, ambiguous criteria, or questionable references. Existing references remain unchanged. One run cannot measure repeatability. No patient, inventory, or verified transfusion outcome is part of the scoring.\n"
    (run/"COMPARISON.md").write_text(md,encoding="utf-8")
    print(json.dumps({"report_flags":rate,"requests":len(client.calls),"input_tokens":total_tokens,"base_rate_cost_estimate_usd":summary["base_rate_estimated_cost_usd"]},indent=2))
    return summary

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--dataset",type=Path,default=Path(__file__).parent/"paris-protest-social-simulation-v1")
    parser.add_argument("--run-dir",type=Path,default=Path(__file__).parent/"openai-decisions-replay-v1")
    parser.add_argument("--model",default="gpt-6-luna")
    parser.add_argument("--key-stdin",action="store_true")
    parser.add_argument("--self-test",action="store_true")
    args=parser.parse_args()
    if args.self_test:
        from tempfile import TemporaryDirectory
        q=choice("x","Choose",{"a":"a","b":"b"})
        assert decode_answers({"answers":[{"name":"x","type":"choice","choice":"a"}]},[q])=={"x":"a"}
        try: decode_answers({"answers":[{"name":"x","type":"choice","choice":"bad"}]},[q])
        except ValueError: pass
        else: raise AssertionError("Unknown value accepted")
        try: decode_answers({"answers":[{"name":"x","type":"refusal"}]},[q])
        except RuntimeError: pass
        else: raise AssertionError("Refusal treated as a label")
        reports=read_jsonl(args.dataset/"social_reports.jsonl")
        assert reports==sorted(reports,key=lambda r:r["available_at"])
        assert all("decisions" not in r and "expected_event_id" not in r for r in reports)
        print("PASS: decoding, refusal handling, chronology and input-label separation")
        return
    args.run_dir.mkdir(parents=True,exist_ok=True)
    reports=read_jsonl(args.dataset/"social_reports.jsonl")
    assert reports==sorted(reports,key=lambda r:r["available_at"])
    rubric=json.loads((args.dataset/"decision_rubric.json").read_text(encoding="utf-8"))
    identity={"dataset_sha256":digest(reports),"rubric_sha256":digest(rubric),
        "runner_sha256":hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),"model":args.model,
        "provider":"OpenAI direct Decisions API","endpoint":ENDPOINT,
        "authorization":"User requested this dataset replay and comparison in the current chat.",
        "labels":"Assistant-authored, not independently human-reviewed; scoring is provisional agreement."}
    manifest=args.run_dir/"run_manifest.json"
    if manifest.exists() and json.loads(manifest.read_text(encoding="utf-8"))!=identity:
        raise RuntimeError("Run configuration changed; use a fresh --run-dir")
    write_json(manifest,identity)
    key=os.environ.get("OPENAI_API_KEY","")
    if not key:
        print("Waiting for API credential on stdin; it will not be saved or echoed.",flush=True)
        key=sys.stdin.readline().strip() if args.key_stdin else getpass.getpass("OpenAI API key: ")
    if not key:
        raise RuntimeError("OPENAI_API_KEY is missing")
    client=Client(key,args.model,args.run_dir/"baseline")
    try:
        predictions=replay(client,reports,rubric,args.run_dir/"baseline")
        # The inference path is finished before reference labels are loaded.
        expected=read_jsonl(args.dataset/"expected_decisions.jsonl")
        evaluate(predictions,expected,reports,client,args.run_dir)
        write_json(args.run_dir/"run_status.json",{"status":"complete","reports":len(predictions),"live_api":True})
    except Exception as e:
        safe=client.redact(e)
        write_json(args.run_dir/"run_status.json",{"status":"incomplete","error":safe,"live_api_requests_completed":len(client.calls)})
        print(safe,file=sys.stderr)
        sys.exit(1)
    finally:
        client.key=""
        key=""

if __name__=="__main__":
    main()
