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
