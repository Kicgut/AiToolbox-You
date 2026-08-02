import json
import sys
import time

mode = sys.argv[1]
if mode == "claude":
    args = sys.argv[2:]
    assert "-p" in args and "hello" not in args
    assert sys.stdin.read()
    print("fixture stderr", file=sys.stderr, flush=True)
    records = [
        {"type": "init", "session_id": "claude-session"},
        {"type": "partial", "delta": "hel"},
        {"type": "assistant", "text": "hello"},
        {"type": "tool_use", "name": "echo", "input": {}},
        {"type": "tool_result", "output": "ok"},
        {"type": "hook", "name": "pre_tool"},
        {"type": "result", "usage": {"input_tokens": 1}},
    ]
    if "malformed" in args:
        print("not-json", flush=True)
        records.append({"type": "new_future_record", "raw_value": 1})
    if "error-record" in args:
        records.append({"type": "error", "message": "fixture error"})
    for item in records:
        print(json.dumps(item), flush=True)
    raise SystemExit
if mode == "timeout":
    time.sleep(10)
    raise SystemExit
if mode in {"unsupported", "version", "business"}:
    for line in sys.stdin:
        msg = json.loads(line)
        if msg.get("method") == "initialize":
            if mode == "unsupported": response = {"id": msg["id"], "error": {"code": "unsupported_capability"}}
            elif mode == "version": response = {"id": msg["id"], "result": {"protocolVersion": "999"}}
            else: response = {"id": msg["id"], "error": {"code": "prompt_rejected"}}
            print(json.dumps(response), flush=True)
            break
    raise SystemExit

if mode == "exec":
    sys.stdin.read()
    records = ({"type":"session_started","session_id":"fixture-thread"},{"type":"user_message","text":"hello"},{"type":"assistant_delta","delta":"world"},{"type":"tool_call","name":"echo"},{"type":"tool_result","output":"ok"},{"type":"usage","input_tokens":1},{"type":"turn_completed"},{"type":"file_changed","path":"x"},{"type":"command_output","output":"done"})
    for item in records: print(json.dumps(item), flush=True)
    print("not-json", flush=True); print("fixture stderr", file=sys.stderr, flush=True)
    raise SystemExit

for line in sys.stdin:
    msg = json.loads(line)
    if mode in {"app", "app_noise", "app_interrupt", "late", "app_approval", "app_unknown", "turn_business", "app_resume", "app_fork"}:
        if msg.get("method") == "initialize":
            assert msg["params"]["clientInfo"]["name"] == "ai-coding-workbench"
            assert msg["params"]["clientInfo"]["title"] == "AI Coding Workbench"
            assert msg["params"]["clientInfo"]["version"] == "0.1.0"
            assert msg["params"]["capabilities"]["experimentalApi"] is False
            if mode == "app_noise":
                print("not-json-before-response", flush=True)
                print("fixture stderr before response", file=sys.stderr, flush=True)
            print(json.dumps({"id": msg["id"], "result": {"protocolVersion": "1"}}), flush=True)
        elif msg.get("method") == "thread/start":
            assert "prompt" not in msg["params"]
            print(json.dumps({"id": msg["id"], "result": {"thread": {"id": "fixture-thread"}}}), flush=True)
        elif msg.get("method") == "thread/resume":
            assert mode == "app_resume" and msg["params"]["threadId"] == "source-thread"
            print(json.dumps({"id": msg["id"], "result": {"thread": {"id": "source-thread"}}}), flush=True)
        elif msg.get("method") == "thread/fork":
            assert mode == "app_fork" and msg["params"]["threadId"] == "source-thread"
            print(json.dumps({"id": msg["id"], "result": {"thread": {"id": "forked-thread"}}}), flush=True)
        elif msg.get("method") == "turn/start":
            if mode != "app_approval":
                assert msg["params"]["input"][0] == {"type": "text", "text": "hello", "text_elements": []}
            if mode == "late": time.sleep(10); raise SystemExit
            if mode == "turn_business":
                print(json.dumps({"id": msg["id"], "error": {"code": "prompt_rejected"}}), flush=True)
                break
            print(json.dumps({"id": msg["id"], "result": {"turn": {"id": "fixture-turn", "items": [], "status": "inProgress"}}}), flush=True)
            if mode == "app_interrupt":
                continue
            if mode == "app_approval":
                print(json.dumps({"id": 99, "method": "item/commandExecution/requestApproval", "params": {"command": "git status --short", "cwd": ".", "reason": "fixture approval"}}), flush=True)
                continue
            if mode == "app_unknown":
                print(json.dumps({"id": 88, "method": "future/request", "params": {"value": "unknown"}}), flush=True)
                continue
            records = ({"type":"user_message","text":"hello"},{"type":"assistant_delta","delta":"world"},{"type":"tool_call","name":"echo"},{"type":"tool_result","output":"ok"},{"type":"usage","input_tokens":1},{"type":"turn_completed"},{"type":"file_changed","path":"x"},{"type":"command_output","output":"done"})
            for item in records: print(json.dumps(item), flush=True)
            print("not-json", flush=True); print("fixture stderr", file=sys.stderr, flush=True); break
        elif mode == "app_approval" and msg.get("id") == 99:
            assert msg["result"]["decision"] == "accept"
            print(json.dumps({"method": "turn/completed", "params": {"threadId": "fixture-thread"}}), flush=True)
            break
        elif mode == "app_unknown" and msg.get("id") == 88:
            assert msg["error"]["code"] == "unsupported_method"
            print(json.dumps({"method": "turn/completed", "params": {"threadId": "fixture-thread"}}), flush=True)
            break
        elif mode == "app_interrupt" and msg.get("method") == "turn/interrupt":
            assert msg["params"] == {"threadId": "fixture-thread", "turnId": "fixture-turn"}
            print(json.dumps({"id": msg["id"], "result": {}}), flush=True)
            print(json.dumps({"method": "turn/completed", "params": {"threadId": "fixture-thread", "turnId": "fixture-turn"}}), flush=True)
            break
    else:
        records = ({"type":"session_started","session_id":"fixture-thread"},{"type":"user_message","text":"hello"},{"type":"assistant_delta","delta":"world"},{"type":"tool_call","name":"echo"},{"type":"tool_result","output":"ok"},{"type":"usage","input_tokens":1},{"type":"turn_completed"},{"type":"file_changed","path":"x"},{"type":"command_output","output":"done"})
        for item in records: print(json.dumps(item), flush=True)
        print("not-json", flush=True); print("fixture stderr", file=sys.stderr, flush=True); break
