# Local Ajaib browser capture

Run from your local repository on a computer with a desktop. The core screener
still uses only Python's standard library; browser capture is optional.

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-browser.txt
python -m playwright install chromium
python -m screenerx.ajaib_browser --output data/ajaib-session-1
```

On Windows, activate with `.venv\Scripts\Activate.ps1` in PowerShell.

The default opens Ajaib's informational Terminal page. Navigate to your actual
official web interface, or supply its URL with `--url https://YOUR-AJAIB-HOST/...`.
Log in manually in the opened browser, including any OTP, and open Broker Summary.
Select your tickers and dates. Successful JSON responses from the observed
`ht2.ajaib.co.id` broker-summary route are saved with timestamps and SHA-256 hashes.
Close the browser to finish. Use a new output directory each run.

This does not guess login endpoints, read username/password environment variables,
export tokens, or automate trades. It preserves normal TLS verification. It does
not solve Cloudflare challenges. If the feature is only available in the native
app, or the web request is blocked, this helper cannot capture it.

The browser profile contains session credentials: `.auth/` is ignored by Git.
Responses under `data/` are also ignored. Keep both private; delete `.auth/` to
remove the saved browser session. Don't commit HAR files or copied request headers.

Captured broker JSON still needs schema mapping and coverage checks before it can
populate the screener's broker CSV. It is not automatically treated as complete
20-session coverage or as zero flow for missing brokers.
