# End-User Doctor Design

## Goal

Make Runtime Doctor understandable without IT knowledge.

## Interface

- Show three totals first: ready, needs setup, optional.
- Sort workflows by severity: needs setup, optional, ready.
- Replace technical status copy with plain Vietnamese.
- For each missing item, show one short next action.
- Add one action button per workflow that opens the relevant existing screen or setting.
- Keep technical names such as `AI33_API_KEY` only as secondary detail.

## Boundaries

- Reuse existing `/api/runtime/doctor` response.
- Do not expose keys, tokens, cookies, endpoints or filesystem paths.
- Do not add dependencies or backend routes.
- Keep automatic Doctor refresh when Settings opens.

## Verification

- Static UI test covers totals, plain-language guidance and action controls.
- Existing web tests remain green.
- Desktop and mobile layouts have no overflow.
