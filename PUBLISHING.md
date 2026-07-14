# Publishing Changes to the Live Dashboard

Once your dashboard is on GitHub Pages, you have **3 ways** to update it.

## Option 1: Push from GitHub Desktop (recommended for code changes)

The simplest workflow. Whenever you change any file in the project:

1. **Open GitHub Desktop**
2. The current repo should be `India-Macro` (top dropdown)
3. If changes are detected, you'll see them in the **Changes** tab
4. **Bottom-left**: type a commit message (e.g. `Update curation rules`)
5. Click **Commit to main** (blue button at bottom)
6. Click **Push origin** (top-right blue button)

**Result:** The GitHub Actions workflow will trigger automatically (because I updated it to listen for all `main` branch pushes) and deploy the new build to your live URL within ~2-3 minutes.

**To watch the deploy:**
- Go to https://github.com/interestandprinciples/India-Macro/actions
- You'll see a "Daily Refresh" run with a yellow 🟡 in-progress circle
- When it turns green ✅, your changes are live
- Refresh your dashboard URL to see the update

## Option 2: Manual trigger from the Actions tab (for force-refresh)

If you want to trigger a build without changing any files:

1. Go to https://github.com/interestandprinciples/India-Macro/actions
2. Click **Daily Refresh** in the left sidebar
3. Right side: click **Run workflow** dropdown → green **Run workflow** button
4. Wait 2-3 minutes for the green ✅

**Result:** The workflow re-fetches ALL data sources (DBIE, RBI Ref, PPAC, MoSPI, live tickers) and rebuilds the dashboard with the latest data.

## Option 3: Fast deploy (skip data refetch)

If you only changed UI files (HTML, CSS, curate.html) and don't need fresh data:

1. Go to https://github.com/interestandprinciples/India-Macro/actions
2. Click **Deploy** in the left sidebar (I created this workflow)
3. Right side: click **Run workflow** → **Run workflow**
4. Wait ~1 minute for green ✅

**Result:** Just deploys the current `dashboard/index.html` without re-fetching data. Useful for testing UI changes quickly.

## Typical workflow by change type

| I changed...                | Use                   | Time to live  |
| --------------------------- | --------------------- | ------------- |
| Dashboard files (HTML, CSS) | GitHub Desktop push   | ~2-3 min      |
| Curation rules               | GitHub Desktop push   | ~2-3 min      |
| Scripts (Python)             | GitHub Desktop push   | ~2-3 min      |
| Workflow file (`.yml`)       | GitHub Desktop push   | ~2-3 min      |
| Just want fresh data         | Actions → Daily Refresh → Run workflow | ~2-3 min |
| Only want to deploy current (no data refresh) | Actions → Deploy → Run workflow | ~1 min |

## Daily 3:45 PM IST auto-refresh

The workflow has a cron schedule: `15 10 * * 1-5` (UTC) = 3:45 PM IST, Mon–Fri.

It automatically:
1. Fetches latest DBIE
2. Fetches latest RBI Ref Rates
3. Fetches latest PPAC crude
4. Fetches latest MoSPI / World Bank
5. Fetches latest live market tickers
6. Rebuilds the dashboard with all fresh data
7. Deploys to GitHub Pages

You don't have to do anything — the dashboard updates itself every weekday at 3:45 PM IST.

## Verifying a deploy worked

After pushing or triggering, check:
1. **Actions tab** in GitHub repo — should show a green ✅ run
2. **Live URL** — hard-refresh in browser (Cmd+Shift+R) to see the latest
3. **Last-modified timestamp** — should be very recent if you view the page source

## Rolling back a bad change

If you push something broken:

1. In GitHub Desktop, click **History** tab
2. Find the last good commit (before the broken one)
3. Right-click it → **Revert changes in commit**
4. Commit the revert and push

The bad version will be replaced with the previous working state on the live site within 2-3 minutes.

## Direct file editing (advanced)

If you want to edit a single file directly in GitHub's web UI:

1. Go to the file on github.com (e.g., https://github.com/interestandprinciples/India-Macro/blob/main/dashboard/index.html)
2. Click the pencil icon (Edit this file)
3. Make your changes
4. Click **Commit changes** at the bottom
5. Add a message, click **Commit directly to the main branch**

**Result:** The workflow will auto-trigger and deploy within 2-3 minutes. But for big edits, use a local editor + GitHub Desktop instead.
