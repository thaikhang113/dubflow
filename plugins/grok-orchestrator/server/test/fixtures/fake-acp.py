#!/usr/bin/python3
import json
import sys

if "--malformed" in sys.argv:
    print("not-json", flush=True)

prompt_id = None

def send(value):
    print(json.dumps(value), flush=True)

def update(value):
    send({"jsonrpc": "2.0", "method": "session/update", "params": {"sessionId": "fake-acp-session", "update": value}})

for line in sys.stdin:
    message = json.loads(line)
    method = message.get("method")
    if method == "initialize":
        send({"jsonrpc": "2.0", "id": message["id"], "result": {"protocolVersion": 1}})
    elif method == "session/new":
        send({"jsonrpc": "2.0", "id": message["id"], "result": {"sessionId": "fake-acp-session"}})
    elif method == "session/prompt":
        prompt_id = message["id"]
        update({"sessionUpdate": "agent_thought_chunk", "content": {"type": "text", "text": "private thought"}})
        update({"sessionUpdate": "agent_message_chunk", "content": {"type": "text", "text": "Working"}})
        update({"sessionUpdate": "tool_call", "toolCallId": "tool-1", "title": "Edit file", "kind": "edit"})
        send({"jsonrpc": "2.0", "id": 900, "method": "session/request_permission", "params": {
            "sessionId": "fake-acp-session",
            "toolCall": {"toolCallId": "tool-1", "title": "Edit file", "kind": "edit"},
            "options": [{"optionId": "yes", "kind": "allow_once", "name": "Allow"}, {"optionId": "no", "kind": "reject_once", "name": "Reject"}],
        }})
    elif method is None and message.get("id") == 900 and prompt_id is not None:
        update({"sessionUpdate": "tool_call_update", "toolCallId": "tool-1", "status": "completed", "content": [{"type": "diff", "path": "src/a.ts", "oldText": "a", "newText": "b"}]})
        update({"sessionUpdate": "tool_call", "toolCallId": "tool-2", "title": "Run npm test", "kind": "execute"})
        update({"sessionUpdate": "tool_call_update", "toolCallId": "tool-2", "status": "completed", "kind": "execute", "content": []})
        send({"jsonrpc": "2.0", "id": prompt_id, "result": {"stopReason": "end_turn"}})
        prompt_id = None
