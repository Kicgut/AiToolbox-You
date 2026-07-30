import json
import sys
import time

mode = sys.argv[1]
if mode == "claude":
    args = sys.argv[2:]
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
    if mode in {"app", "late"}:
        if msg.get("method") == "initialize":
            assert msg["params"]["clientInfo"]["name"] == "ai-coding-workbench"
            assert msg["params"]["capabilities"]["experimentalApi"] is False
            print(json.dumps({"id": msg["id"], "result": {"protocolVersion": "1"}}), flush=True)
        elif msg.get("method") == "thread/start":
            assert "prompt" not in msg["params"]
            print(json.dumps({"id": msg["id"], "result": {"thread": {"id": "fixture-thread"}}}), flush=True)
        elif msg.get("method") == "turn/start":
            assert msg["params"]["input"][0] == {"type": "text", "text": "hello", "text_elements": []}
            if mode == "late": time.sleep(10); raise SystemExit
            print(json.dumps({"id": msg["id"], "result": {}}), flush=True)
            records = ({"type":"user_message","text":"hello"},{"type":"assistant_delta","delta":"world"},{"type":"tool_call","name":"echo"},{"type":"tool_result","output":"ok"},{"type":"usage","input_tokens":1},{"type":"turn_completed"},{"type":"file_changed","path":"x"},{"type":"command_output","output":"done"})
            for item in records: print(json.dumps(item), flush=True)
            print("not-json", flush=True); print("fixture stderr", file=sys.stderr, flush=True); break
    else:
        records = ({"type":"session_started","session_id":"fixture-thread"},{"type":"user_message","text":"hello"},{"type":"assistant_delta","delta":"world"},{"type":"tool_call","name":"echo"},{"type":"tool_result","output":"ok"},{"type":"usage","input_tokens":1},{"type":"turn_completed"},{"type":"file_changed","path":"x"},{"type":"command_output","output":"done"})
        for item in records: print(json.dumps(item), flush=True)
        print("not-json", flush=True); print("fixture stderr", file=sys.stderr, flush=True); break
