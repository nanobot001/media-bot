# Setup Guide: Prowlarr & Network Integration

This document outlines how to configure the Dockerized Prowlarr service and link it to the native PM2-managed `media-bot` on Windows.

---

## 1. Prowlarr Host Connectivity

Although Prowlarr runs in Docker for Windows, the container maps port `9696` to the host network interface. 

* **Host-to-Docker URL**: The native PM2 script running on your Windows machine connects to Prowlarr at:
  ```text
  http://127.0.0.1:9696
  ```
* **Setting the API Key**:
  1. Open your browser and navigate to `http://localhost:9696`.
  2. Go to **Settings** -> **General**.
  3. Under the **Security** section, copy the **API Key**.
  4. Paste this value into your local `media-bot` `.env` file:
     ```env
     PROWLARR_API_KEY=your_prowlarr_api_key_here
     PROWLARR_URL=http://127.0.0.1:9696
     ```

---

## 2. Configuring Trackers/Indexers in Prowlarr

To ensure the bot receives high-quality search results:

1. In the Prowlarr web UI, navigate to **Indexers**.
2. Click **Add New** and choose your preferred public or private torrent indexers.
3. **Category Matching**: Ensure the configured indexers support the **Movies** category (`2000`). The bot queries Prowlarr using:
   ```text
   /api/v1/search?categories=2000
   ```
4. Perform a test search inside the Prowlarr UI to confirm the indexers successfully fetch results.

---

## 3. Verifying Bot-to-Prowlarr Communication

Once the `.env` settings are saved, test the connection via the CLI:

```powershell
# Set PYTHONPATH
$env:PYTHONPATH="src"

# Run search query test
py -3.8 -m moviebot.cli.tool_cli search --query "Inception"
```
If Prowlarr is connected correctly, the command returns a JSON envelope containing the matched torrent results (with redacted/safe tracker hashes).

---

## 4. Tautulli Webhook Integration

The bot runs a FastAPI webhook listener concurrently on port `8000` to process playback activity events from Tautulli.

### 4.1. Security Configuration
Define a shared secret in your `.env` file to authorize incoming webhook payloads:
```env
TAUTULLI_WEBHOOK_SECRET=your_configured_webhook_secret
```
The webhook listener verifies this secret using either:
*   An HTTP Header: `Authorization: Bearer your_configured_webhook_secret`
*   A URL Query Parameter: `?token=your_configured_webhook_secret`

### 4.2. Tautulli Notification Agent Setup
To configure Tautulli to push events:
1. Navigate to Tautulli **Settings** -> **Notification Agents**.
2. Click **Add a new notification agent** and select **Webhook**.
3. Set the **Webhook URL**:
   ```text
   http://127.0.0.1:8000/webhook/tautulli?token=your_configured_webhook_secret
   ```
4. Set the **Method** to `POST`.
5. Go to the **Triggers** tab and select the events you wish to forward (e.g., `Playback Start`, `Playback Stop`, `Watched`).
6. Go to the **Data** tab. For the triggers selected, specify a JSON payload containing the following fields:
   ```json
   {
     "event": "{event}",
     "rating_key": "{rating_key}",
     "imdb_id": "{imdb_id}",
     "title": "{title}",
     "user": "{user}",
     "player": "{player}"
   }
   ```
7. Click **Save**.

### 4.3. Manual Local Validation
You can verify the webhook listener is functional by running the following `curl` command in PowerShell:
```powershell
Invoke-RestMethod -Uri "http://127.0.0.1:8000/webhook/tautulli?token=default_secret" `
  -Method Post `
  -ContentType "application/json" `
  -Body '{"event": "play", "title": "Inception", "user": "alice"}'
```
If authorized and successful, the server logs the event to the SQLite `events` table and returns:
```json
{"status": "success", "event_logged": "play"}
```

---

## 5. FlareSolverr Integration

FlareSolverr is a proxy server designed to bypass Cloudflare protection, allowing indexers in Prowlarr to successfully fetch results from protected sites.

### 5.1. How it is Deployed
FlareSolverr runs inside the Docker Compose network on port `8191` (mapped to `http://localhost:8191` on the host).

### 5.2. Integration with Prowlarr
To configure Prowlarr to use FlareSolverr:
1. Open the Prowlarr web UI at `http://localhost:9696`.
2. Navigate to **Settings** -> **Indexers**.
3. Under the **Proxies** section, click the **+** (Add) button.
4. Select **FlareSolverr**.
5. Set the following fields:
   * **Name**: `FlareSolverr`
   * **Tags**: (Leave empty, or add tags to restrict FlareSolverr to specific indexers if desired)
   * **Host**: `http://flaresolverr:8191` (since both Prowlarr and FlareSolverr are running in the same Docker network).
6. Click **Test** to verify connection, then click **Save**.
