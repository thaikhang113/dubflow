import json
import sys
import urllib.request
from pathlib import Path

def _get_api_config():
    config_path = Path("D:/dubflow/openclaw.json")
    if not config_path.exists():
        # Fallback to local
        config_path = Path("D:/dubflow/data/openclaw.json") # Just a fallback
    if config_path.exists():
        try:
            return json.loads(config_path.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}

def call_openclaw(action: str, payload: dict):
    config = _get_api_config()
    token = config.get("token", "")
    port = config.get("port", 38643)
    host = config.get("bind_host", "127.0.0.1")
    if host == "0.0.0.0":
        host = "127.0.0.1"

    url = f"http://{host}:{port}/v1/tools/call"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }
    req_data = payload.copy()
    req_data["action"] = action

    req = urllib.request.Request(url, data=json.dumps(req_data).encode("utf-8"), headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req) as response:
            return json.loads(response.read().decode("utf-8"))
    except Exception as e:
        return {"ok": False, "error": str(e)}

def main():
    while True:
        line = sys.stdin.readline()
        if not line:
            break
        try:
            req = json.loads(line)
        except json.JSONDecodeError:
            continue

        if "id" not in req:
            continue

        req_id = req["id"]
        method = req.get("method")

        if method == "initialize":
            sys.stdout.write(json.dumps({
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "serverInfo": {"name": "DubFlow MCP", "version": "1.0"}
                }
            }) + "\n")
            sys.stdout.flush()

        elif method == "tools/list":
            sys.stdout.write(json.dumps({
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "tools": [
                        {
                            "name": "get_system_status",
                            "description": "Get DubFlow system status (RAM, CPU)",
                            "inputSchema": {"type": "object", "properties": {}}
                        },
                        {
                            "name": "list_voices",
                            "description": "List all available voices for dubbing",
                            "inputSchema": {"type": "object", "properties": {}}
                        },
                        {
                            "name": "get_settings",
                            "description": "Get the current DubFlow settings",
                            "inputSchema": {"type": "object", "properties": {}}
                        },
                        {
                            "name": "update_settings",
                            "description": "Update DubFlow settings",
                            "inputSchema": {
                                "type": "object",
                                "properties": {
                                    "updates": {
                                        "type": "object",
                                        "description": "Key-value pairs to update (e.g. translate_enabled: true)"
                                    }
                                },
                                "required": ["updates"]
                            }
                        },
                        {
                            "name": "update_vieneu",
                            "description": "Upgrade VieNeu TTS package to latest version and refresh voices",
                            "inputSchema": {"type": "object", "properties": {}}
                        },
                        {
                            "name": "get_vsr_status",
                            "description": "Get Video Subtitle Remover (VSR) installation and configuration status",
                            "inputSchema": {"type": "object", "properties": {}}
                        },
                        {
                            "name": "apply_blur_boxes",
                            "description": "Apply blur boxes (Gaussian blur/delogo) over specified coordinates on a video",
                            "inputSchema": {
                                "type": "object",
                                "properties": {
                                    "video_path": {
                                        "type": "string",
                                        "description": "Path to input video file"
                                    },
                                    "regions": {
                                        "type": "array",
                                        "items": {
                                            "type": "object",
                                            "properties": {
                                                "x": {"type": "number", "description": "Left coordinate (0.0 - 1.0)"},
                                                "y": {"type": "number", "description": "Top coordinate (0.0 - 1.0)"},
                                                "w": {"type": "number", "description": "Width (0.0 - 1.0)"},
                                                "h": {"type": "number", "description": "Height (0.0 - 1.0)"},
                                                "t_start": {"type": "number", "description": "Optional start time in seconds"},
                                                "t_end": {"type": "number", "description": "Optional end time in seconds"}
                                            },
                                            "required": ["x", "y", "w", "h"]
                                        },
                                        "description": "List of normalized bounding boxes to blur"
                                    },
                                    "output_path": {
                                        "type": "string",
                                        "description": "Optional output path for blurred video"
                                    }
                                },
                                "required": ["video_path", "regions"]
                            }
                        },
                        {
                            "name": "remove_video_subtitles",
                            "description": "Remove hardcoded subtitles or watermarks from a video using AI (VSR inpainting) or blur fallback",
                            "inputSchema": {
                                "type": "object",
                                "properties": {
                                    "video_path": {
                                        "type": "string",
                                        "description": "Path to input video file"
                                    },
                                    "output_path": {
                                        "type": "string",
                                        "description": "Optional output path for cleaned video"
                                    },
                                    "regions": {
                                        "type": "array",
                                        "items": {"type": "object"},
                                        "description": "Optional list of subtitle/watermark regions to remove. Defaults to bottom caption area"
                                    },
                                    "mode": {
                                        "type": "string",
                                        "description": "VSR inpainting mode: 'sttn-det', 'sttn', or 'propainter'"
                                    },
                                    "fallback_to_blur": {
                                        "type": "boolean",
                                        "description": "Whether to fallback to blur if VSR is not installed/fails (default true)"
                                    }
                                },
                                "required": ["video_path"]
                            }
                        },
                        {
                            "name": "setup_vsr",
                            "description": "Download and install/repair Video Subtitle Remover (VSR) backend in background",
                            "inputSchema": {"type": "object", "properties": {}}
                        }
                    ]
                }
            }) + "\n")
            sys.stdout.flush()

        elif method == "tools/call":
            params = req.get("params", {})
            name = params.get("name")
            args = params.get("arguments", {})
            
            result = call_openclaw("tools_call", {"name": name, "arguments": args})
            
            sys.stdout.write(json.dumps({
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False)}]
                }
            }) + "\n")
            sys.stdout.flush()
        else:
            sys.stdout.write(json.dumps({
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {"code": -32601, "message": "Method not found"}
            }) + "\n")
            sys.stdout.flush()

if __name__ == "__main__":
    main()
