# Setup: Host on GitHub Pages + Custom Domain

This is a step-by-step guide to deploy the dashboard publicly at
`interestandprinciples.com/india-macro` (or any subdomain).

## Prerequisites

- A GitHub account (free)
- Admin access to your DNS provider (wherever `interestandprinciples.com` is registered)

## 1. Create a GitHub repository

1. Go to https://github.com/new
2. Repository name: `india-macroeconomic-dashboard` (or your preferred name)
3. **Private** or **Public** — your choice. Public is fine since the data is all public.
4. **Do NOT** initialize with README / .gitignore / license (we already have them)
5. Click **Create repository**

## 2. Push your local project to GitHub

Replace `<your-username>` and `<repo-name>` with your actual values.

### Option A — Using GitHub's Personal Access Token (easiest, no SSH setup)

```bash
cd /Users/niravshah/Desktop/RBI\ Macro\ Indicators

# Configure git (one-time, use your GitHub email and username)
git config --global user.email "your-email@example.com"
git config --global user.name "Your Name"

# Init the repo
git init
git add .
git commit -m "Initial commit: India Macroeconomic Dashboard"
git branch -M main
git remote add origin https://github.com/<your-username>/<repo-name>.git
git push -u origin main
```

When prompted for credentials, paste a **Personal Access Token** (not your password).
Create one at https://github.com/settings/tokens — choose "Fine-grained tokens" with
**Contents: Read and write** + **Pages: Read and write** + **Workflows: Read and write** scopes.

### Option B — Using SSH (no token needed, but requires key setup)

```bash
# 1. Generate SSH key (skip if you already have one)
ssh-keygen -t ed25519 -C "your-email@example.com"
# Press enter to accept defaults, optionally set a passphrase

# 2. Copy the public key
cat ~/.ssh/id_ed25519.pub
# Add it at https://github.com/settings/keys

# 3. Push
cd /Users/niravshah/Desktop/RBI\ Macro\ Indicators
git init
git add .
git commit -m "Initial commit: India Macroeconomic Dashboard"
git branch -M main
git remote add origin git@github.com:<your-username>/<repo-name>.git
git push -u origin main
```

## 3. Enable GitHub Pages

1. Go to your repo → **Settings** → **Pages**
2. Under **Source**, select **GitHub Actions**
3. (Optional) Under **Custom domain**, enter `india-macro.interestandprinciples.com`
4. (Optional) Check **Enforce HTTPS**

## 4. Trigger the first deployment

The workflow runs automatically every day at **10:15 UTC = 3:45 PM IST**,
but for the first time you need to trigger it manually:

1. Go to **Actions** tab in your repo
2. Click **Daily Refresh** on the left
3. Click **Run workflow** → **Run workflow** (green button)
4. Wait 2–3 minutes for the workflow to complete
5. Your site will be live at:
   - `https://<your-username>.github.io/<repo-name>/` (default)
   - `https://india-macro.interestandprinciples.com/` (after DNS + custom domain)

## 5. Configure your custom domain (interestandprinciples.com)

In your DNS provider (Cloudflare / GoDaddy / Namecheap / etc.):

| Type  | Name                       | Value                          | TTL  |
| ----- | -------------------------- | ------------------------------ | ---- |
| CNAME | `india-macro`              | `<your-username>.github.io.`  | 300  |

For apex domain (`interestandprinciples.com`), the dashboard will be at
`https://interestandprinciples.com/india-macro/`.

If you want it at the **root** instead of a subdomain:
- Use 4 A records pointing to GitHub's IPs:
  - 185.199.108.153
  - 185.199.109.153
  - 185.199.110.153
  - 185.199.111.153
- Or use ALIAS / ANAME if your DNS provider supports it

## 6. Verify the deployment

After ~5 minutes, check:

- ✅ `https://github.com/<your-username>/<repo-name>/actions` — workflow should show green ✓
- ✅ `https://<your-username>.github.io/<repo-name>/` — dashboard should load
- ✅ `https://india-macro.interestandprinciples.com/` (if you set it up) — should also load

## Schedule (post-deployment)

The `daily-refresh.yml` workflow runs at:
- **10:15 UTC = 3:45 PM IST** every Mon–Fri (Indian market days)

It will:
1. Pull latest DBIE (50 + Other Macroeconomic Indicators)
2. Pull latest RBI Reference Rates
3. Pull latest PPAC crude oil
4. Pull latest MoSPI / World Bank
5. Pull latest live market tickers
6. Rebuild the dashboard with all fresh data
7. Deploy to GitHub Pages (under 30 seconds)

You can also trigger a manual refresh anytime:
- Go to Actions → Daily Refresh → Run workflow

## Troubleshooting

- **Workflow fails at "Fetch + rebuild"**: open the failed run's log, check the
  error. Common causes: Python package not found (add to `requirements.txt`),
  network timeout, RBI/DBIE rate limit.
- **Custom domain not working**: wait 24–48h for DNS to propagate, check
  the repo's Pages settings show a green "DNS check successful" message.
- **404 on the dashboard URL**: make sure GitHub Pages is enabled with
  "GitHub Actions" as the source.
- **Data is stale**: trigger a manual workflow run.

## What gets deployed

Every time the workflow runs, GitHub Pages serves a fresh `index.html` at
your URL. The HTML is **self-contained** (~2.8 MB) with all ~50,000 data
points inlined — visitors don't need any backend or external API to view it.

The "live tickers" (USD/INR, NIFTY, etc.) embedded in the dashboard will
be **15 minutes to 24 hours stale** depending on when the workflow last
ran, since GitHub Pages hosts only static files. For truly real-time
tickers, you would need a different architecture (e.g., a paid
serverless function with WebSocket), but for daily macro snapshots
this is the right tradeoff.
