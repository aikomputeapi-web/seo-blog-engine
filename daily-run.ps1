# Daily autonomous SEO blog run: research competitors + write + publish articles for every registered site.
# Created by jcode 2026-10-08. Runs at most once per day (state file guard);
# started at sign-in via Startup folder + re-checked hourly while jcode runs.

$logDir = "C:\Users\Administrator\coding\seo-blog-engine\logs"
if (-not (Test-Path $logDir)) { New-Item -ItemType Directory -Path $logDir | Out-Null }
$stamp = Get-Date -Format "yyyy-MM-dd"
$log = Join-Path $logDir "scheduled-$stamp.log"
$stateFile = "C:\Users\Administrator\coding\seo-blog-engine\data\state\last-scheduled-run.txt"

# once-per-day guard: skip if already ran today
if (Test-Path $stateFile) {
    $lastRun = (Get-Content $stateFile -Raw -ErrorAction SilentlyContinue).Trim()
    if ($lastRun -eq $stamp) { exit 0 }
}

"[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] scheduled run starting" | Add-Content $log

# 1. run the engine (research + write + publish + push for all registered sites)
Set-Location "C:\Users\Administrator\coding\seo-blog-engine"
python -m engine.cli run *>> $log

# 2. deploy every registered site that has a Pages deployment (wrangler pages deploy dist)
$sitesFile = "C:\Users\Administrator\coding\seo-blog-engine\data\sites.json"
if (Test-Path $sitesFile) {
    $sites = Get-Content $sitesFile -Raw | ConvertFrom-Json
    foreach ($site in $sites) {
        $repo = $site.repo
        $distDir = Join-Path $repo "dist"
        if (Test-Path $distDir) {
            "[$(Get-Date -Format 'HH:mm:ss')] building + deploying $($site.key)" | Add-Content $log
            try {
                Push-Location $repo
                $packageJson = Join-Path $repo "package.json"
                if (Test-Path $packageJson) {
                    npm run build *>> $log   # rebuild so new articles are in dist
                }
                $pagesCfg = Join-Path $repo ".pages-project"
                if (Test-Path $pagesCfg) {
                    $projectName = (Get-Content $pagesCfg -Raw).Trim()
                    npx wrangler pages deploy dist --project-name $projectName --branch main --commit-dirty=true *>> $log
                } else {
                    "[$(Get-Date -Format 'HH:mm:ss')] no .pages-project file, skipping deploy" | Add-Content $log
                }
            } catch {
                "[$(Get-Date -Format 'HH:mm:ss')] deploy failed: $_" | Add-Content $log
            } finally {
                Pop-Location
            }
        } else {
            # GitHub-push-driven sites (Cloudflare Pages git integration) need no local deploy
            "[$(Get-Date -Format 'HH:mm:ss')] $($site.key): no dist, relying on git push" | Add-Content $log
        }
    }
}

"[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] scheduled run finishing" | Add-Content $log
Set-Content -Path $stateFile -Value $stamp -NoNewline
