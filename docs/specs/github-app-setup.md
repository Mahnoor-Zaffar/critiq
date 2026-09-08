# Critiq — GitHub App Setup

> Document type: setup / operations guide
> Related: `api.md` (endpoints), `architecture.md`

---

## 1. Overview

Critiq runs as a **GitHub App** so it can act on behalf of many repositories and
orgs. This guide covers creating the App, granting permissions, and wiring up
webhooks for local development.

---

## 2. Create the GitHub App

1. Go to **Settings → Developer settings → GitHub Apps → New GitHub App**.
2. **App name:** `critiq` (or your chosen name).
3. **Homepage URL:** your repo or project URL (required).
4. **Callback URL:** `http://localhost:3000/callback` (not used heavily in V1;
   harmless to set).
5. **Webhook URL:** `https://<your-tunnel>/webhooks/github` (public URL for dev).
6. **Webhook secret:** generate a strong random string; this becomes
   `CRITIQ_GITHUB_WEBHOOK_SECRET`.
7. **Permissions:** grant the following **Read and write**:
   - **Pull requests** (read/write) — required to create reviews
   - **Contents** (read) — required to fetch files/trees
   - **Metadata** (read) — required (mandatory)
8. **Subscribe to events:** check **Pull request**.
9. Click **Create GitHub App**.
10. Note the **App ID** (`CRITIQ_GITHUB_APP_ID`).
11. Generate a **Private Key** (`CRITIQ_GITHUB_APP_PRIVATE_KEY`). For local dev
    you can paste the PEM contents into an env var or write to a file.

---

## 3. Permissions Summary (V1)

| Permission | Access | Why |
| ---------- | ------ | --- |
| Pull requests | read/write | create reviews + inline comments |
| Contents | read | fetch files, tree, blob contents |
| Metadata | read | required by GitHub |

---

## 4. Install the App

1. From the GitHub App page, choose **Install App**.
2. Select the account (user or org) and choose **All repositories** or selected
   repos.
3. Recording the **installation id** for the event (`installation.id` in the
   webhook payload) is the system's handle to that install.

---

## 5. Local Webhook Tunnel

For local development, expose the running FastAPI app so GitHub can deliver
webhooks.

Option A — **ngrok**:
```
ngrok http 8000
```
Copy the `https://...ngrok.io` URL and set the App's Webhook URL to
`https://<id>.ngrok.io/webhooks/github`.

Option B — **cloudflared**:
```
cloudflared tunnel --url http://localhost:8000
```

Each time the tunnel URL changes (free tier), update the GitHub App's Webhook
URL.

---

## 6. Auth Flow

1. **App JWT:** Sign a JWT (RS256) with the App's private key. Claims:
   ```json
   { "iat": <now>, "exp": <now+10min>, "iss": <APP_ID> }
   ```
2. **Installation token:** `POST /app/installations/{installation_id}/access_tokens`
   with `Authorization: Bearer <jwt>`.
3. **API requests:** use `Authorization: Bearer <installation_token>` for
   repository/PR scoped calls.
4. Cache the installation token and refresh before expiry.

---

## 7. Environment Variables

All credentials are supplied via environment (see `.env.example`):

- `CRITIQ_GITHUB_APP_ID`
- `CRITIQ_GITHUB_APP_PRIVATE_KEY`
- `CRITIQ_GITHUB_WEBHOOK_SECRET`
- `CRITIQ_GITHUB_CLIENT_ID` / `CRITIQ_GITHUB_CLIENT_SECRET`
- `CRITIQ_OPENROUTER_API_KEY`

---

## 8. Event Handling

Critiq handles the following `pull_request` actions:

- `opened`
- `synchronize`
- `reopened`

On each, the API verifies the signature and enqueues a review job. Duplicate
deliveries are debounced by keying on `(installation_id, repository_id, pr_number)`.
