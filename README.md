# dmm-radar-discord

Polls [dmmradar.com/map](https://dmmradar.com/map) for verified death pins and posts new ones to a Discord webhook.

Every 45s it hits the SvelteKit `/map/__data.json` route, expands the devalue dedup payload, and posts any pin it hasn't seen yet with `status == "verified"`. Each kill gets one embed plus a follow-up message per clip URL so Discord renders the inline player. Twitch clips win when they exist, kick is the fallback. Seen pin IDs persist to `/app/data/seen.json` so restarts don't repost.

## env

- `DISCORD_WEBHOOK_URL` (required)
- `POLL_INTERVAL` seconds, default `45`
- `STATE_FILE` path, default `/app/data/seen.json`

## run

```
python3 dmm.py dump                              # print parsed pins
DISCORD_WEBHOOK_URL=... python3 dmm.py preview 3 # post 3 recent to webhook
DISCORD_WEBHOOK_URL=... python3 dmm.py loop      # polling daemon
```

## deploy

Dokku worker. See `Procfile`, `Dockerfile`, and `.github/workflows/deploy.yml`.

## notes

`__data.json` isn't a documented API, it's a SvelteKit implementation detail. If dmmradar restructures the route the parser breaks and needs a quick update. Only running this for the duration of the current DMM event.
