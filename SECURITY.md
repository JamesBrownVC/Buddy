# Security and privacy

Buddy handles unusually sensitive data: voice transcripts, personal memory,
tasks, browser sessions, and credentials for external services. Treat every
deployment as a private personal system, not as a public web application.

## Secure defaults

- The hub binds to `127.0.0.1` and public tunnelling is disabled by default.
- Launchers generate a 256-bit `HUB_SECRET` in the gitignored `.env`.
- Memory, task state, agent documentation, mutations, and routing require that
  secret. The local dashboard receives it only in a URL fragment and keeps it
  in `sessionStorage`.
- Call-answer links are HMAC-signed and expire after 10 minutes.
- ElevenLabs browser sessions use temporary signed URLs. Agent authentication
  is enabled, audio storage is disabled, and hosted conversation retention is
  set to zero by the provisioning script.
- Post-call webhooks require an ElevenLabs HMAC signature. Raw local transcript
  storage is disabled unless `STORE_CALL_TRANSCRIPTS=1` is explicitly set.
- Runtime state and generated PRDs are ignored by Git.

## Before enabling remote access

1. Keep `ENABLE_PUBLIC_TUNNEL=0` unless remote voice/webhook access is needed.
2. Put the hub behind an identity-aware proxy such as Cloudflare Access. The
   proxy is an extra layer; do not disable Buddy's own authentication.
3. Use a stable hostname and HTTPS. Avoid sharing a raw quick-tunnel URL.
4. Configure ElevenLabs tool authentication and the post-call webhook HMAC
   secret (`ELEVENLABS_WEBHOOK_SECRET`).
5. Re-run `setup_elevenlabs.py` so signed-agent auth and zero-retention privacy
   settings are applied.
6. Never expose the stealth-browser or noVNC ports (`8080`, `5900`) publicly.

## Repository hygiene

- Never commit `.env`, `state/`, browser profiles, transcripts, logs, sessions,
  generated PRDs, or Hermes profiles.
- GitHub secret scanning and push protection should stay enabled.
- If a credential is ever committed, revoke/rotate it first. Removing the file
  from the latest commit is not enough because Git retains history.

## Reporting a vulnerability

Do not open a public issue containing exploit details or personal data. Contact
the repository owner privately through their GitHub profile.
