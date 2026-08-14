# OpenClaw local tool

Run the DubFlow worker:

```powershell
py scripts/run_remote_worker.py --queue remote_queue
```

Send JSON to the local OpenClaw adapter:

```powershell
'{"action":"prepare","text":"https://example.com/video"}' |
  py -m autodub.openclaw_tool --queue remote_queue
```

Actions:

- `prepare`: extract links and return missing questions.
- `submit`: create one queue job per link and return `batch_id`.
- `status`: return aggregate and per-video progress.
- `cancel`: cancel non-terminal jobs in a batch.
- `retry_failed`: replace failed jobs with fresh queue jobs.

Submit example:

```json
{
  "action": "submit",
  "links": ["https://example.com/video"],
  "options": {
    "voice": "Truc Ly",
    "translate_style": "social",
    "subtitle_mode": "burn"
  }
}
```

OpenClaw must keep adapter output from stdout as JSON. DubFlow secrets remain
in local `.env` and are never part of the job payload.
