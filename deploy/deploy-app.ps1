param(
    [string]$ConfigPath = "deploy/deploy.config.toml"
)

$ErrorActionPreference = "Stop"
$PSNativeCommandUseErrorActionPreference = $false

function Write-Step { param([string]$Message) Write-Host "[deploy-app] $Message" }

function Get-Config {
    param([string]$Path)
    if (-not (Test-Path $Path)) { throw "Config file not found: $Path" }
    $json = python -c "import json, pathlib, tomllib; p=pathlib.Path(r'$Path'); print(json.dumps(tomllib.loads(p.read_text(encoding='utf-8'))))"
    if ($LASTEXITCODE -ne 0) { throw "Failed to parse config file: $Path" }
    return $json | ConvertFrom-Json
}

function Select-Value {
    param([string]$Configured, [string]$Default)
    if ([string]::IsNullOrWhiteSpace($Configured)) { return $Default }
    return $Configured
}

function Normalize-StorageAccountName {
    param([string]$Value)
    $normalized = ($Value.ToLower() -replace "[^a-z0-9]", "")
    if ($normalized.Length -lt 3) { $normalized = $normalized + "123" }
    if ($normalized.Length -gt 22) { $normalized = $normalized.Substring(0, 22) }
    return "st$normalized"
}

function Upload-BlobFromFile {
    param(
        [string]$AccountName,
        [string]$Container,
        [string]$BlobName,
        [string]$FilePath
    )
    if (-not (Test-Path $FilePath)) { throw "Source file not found: $FilePath" }
    az storage blob upload `
      --account-name $AccountName --container-name $Container `
      --name $BlobName --file $FilePath `
      --auth-mode login --overwrite true | Out-Null
    Write-Step "  Uploaded $BlobName -> $Container"
}

# ---------------------------------------------------------------------------
# Load config
# ---------------------------------------------------------------------------
$config = Get-Config -Path $ConfigPath

$subscriptionId = $config.azure.subscription_id
if ([string]::IsNullOrWhiteSpace($subscriptionId)) { $subscriptionId = az account show --query id -o tsv }
az account set --subscription $subscriptionId

$prefix      = $config.naming.prefix.ToLower()
$rg          = Select-Value $config.azure.resource_group_name "rg-$prefix"
$webAppName  = Select-Value $config.naming.web_app_name "app-$prefix"
$storageAcct = Select-Value $config.naming.storage_account_name (Normalize-StorageAccountName -Value $prefix)
$searchSvc   = Select-Value $config.naming.search_service_name "srch-$($prefix.ToLower() -replace '[^a-z0-9-]', '')"
$usersContainer = $config.storage.users_container

# ---------------------------------------------------------------------------
# 1. ZIP-deploy web app
# ---------------------------------------------------------------------------
Write-Step "Packaging application for deployment."
$zipPath = Join-Path $env:TEMP "teams-meetings-agent-deploy.zip"
if (Test-Path $zipPath) { Remove-Item $zipPath }

$sourceDir = Join-Path (Get-Location) "src"
if (-not (Test-Path $sourceDir)) { throw "src/ directory not found." }

$stagingDir = Join-Path $env:TEMP "teams-meetings-agent-staging"
if (Test-Path $stagingDir) { Remove-Item $stagingDir -Recurse -Force }
New-Item -ItemType Directory -Path $stagingDir | Out-Null

Copy-Item -Path "src/*" -Destination $stagingDir -Recurse
Copy-Item -Path "requirements.txt" -Destination $stagingDir
if (Test-Path "host.json") { Copy-Item -Path "host.json" -Destination $stagingDir }

Compress-Archive -Path "$stagingDir/*" -DestinationPath $zipPath -Force
Remove-Item $stagingDir -Recurse -Force

Write-Step "Deploying to '$webAppName'."
az webapp deploy --resource-group $rg --name $webAppName --src-path $zipPath --type zip | Out-Null
Remove-Item $zipPath

# ---------------------------------------------------------------------------
# 2. Seed monitored users blob
# ---------------------------------------------------------------------------
$usersFile = "deploy/assets/users/monitored_users.json"
if (Test-Path $usersFile) {
    Write-Step "Seeding monitored users blob."
    Upload-BlobFromFile -AccountName $storageAcct -Container $usersContainer -BlobName "monitored_users.json" -FilePath $usersFile
} else {
    Write-Step "No monitored_users.json found at $usersFile -- skipping seed."
}

# ---------------------------------------------------------------------------
# 3. Create / update AI Search index
# ---------------------------------------------------------------------------
Write-Step "Ensuring AI Search index '$($config.search.index_name)'."
$searchEndpoint = "https://$searchSvc.search.windows.net"
$searchAdminKey = az search admin-key show --resource-group $rg --service-name $searchSvc --query primaryKey -o tsv

$useVector = [bool]$config.search.use_vector
$embeddingDims = $config.search.embedding_dimensions

$fields = @(
    @{ name="id"; type="Edm.String"; key=$true; filterable=$true },
    @{ name="meeting_id"; type="Edm.String"; filterable=$true; searchable=$false },
    @{ name="transcript_id"; type="Edm.String"; filterable=$true; searchable=$false },
    @{ name="meeting_subject"; type="Edm.String"; searchable=$true; filterable=$true },
    @{ name="meeting_organizer"; type="Edm.String"; searchable=$true; filterable=$true },
    @{ name="meeting_date"; type="Edm.DateTimeOffset"; filterable=$true; sortable=$true },
    @{ name="attendees"; type="Collection(Edm.String)"; filterable=$true; searchable=$true },
    @{ name="chunk_index"; type="Edm.Int32"; filterable=$false; sortable=$true },
    @{ name="chunk_text"; type="Edm.String"; searchable=$true },
    @{ name="action_items"; type="Edm.String"; searchable=$true },
    @{ name="summary"; type="Edm.String"; searchable=$true }
)

if ($useVector) {
    $fields += @{
        name="content_vector"
        type="Collection(Edm.Single)"
        searchable=$true
        dimensions=$embeddingDims
        vectorSearchProfile="default-profile"
    }
}

$indexBody = @{
    name = $config.search.index_name
    fields = $fields
}

if ($useVector) {
    $indexBody["vectorSearch"] = @{
        algorithms = @(
            @{ name="default-algo"; kind="hnsw"; hnswParameters=@{ m=4; efConstruction=400; efSearch=500; metric="cosine" } }
        )
        profiles = @(
            @{ name="default-profile"; algorithmConfigurationName="default-algo" }
        )
    }
}

$indexJson = $indexBody | ConvertTo-Json -Depth 10

$indexExists = $false
try {
    $resp = Invoke-RestMethod -Method Get -Uri "$searchEndpoint/indexes/$($config.search.index_name)?api-version=2024-07-01" `
      -Headers @{ "api-key" = $searchAdminKey; "Content-Type" = "application/json" } -ErrorAction SilentlyContinue
    $indexExists = $true
} catch {}

if ($indexExists) {
    Write-Step "  Index exists -- updating."
    Invoke-RestMethod -Method Put -Uri "$searchEndpoint/indexes/$($config.search.index_name)?api-version=2024-07-01" `
      -Headers @{ "api-key" = $searchAdminKey; "Content-Type" = "application/json" } `
      -Body $indexJson | Out-Null
} else {
    Write-Step "  Creating index."
    Invoke-RestMethod -Method Post -Uri "$searchEndpoint/indexes?api-version=2024-07-01" `
      -Headers @{ "api-key" = $searchAdminKey; "Content-Type" = "application/json" } `
      -Body $indexJson | Out-Null
}

# ---------------------------------------------------------------------------
# 4. Build Teams manifest ZIP
# ---------------------------------------------------------------------------
$manifestDir = "manifest"
if (Test-Path $manifestDir) {
    Write-Step "Building Teams manifest ZIP."

    $manifestJson = Get-Content "$manifestDir/manifest.json" -Raw
    $appId = (az webapp config appsettings list --resource-group $rg --name $webAppName --query "[?name=='MICROSOFT_APP_ID'].value | [0]" -o tsv)
    if (-not [string]::IsNullOrWhiteSpace($appId)) {
        $manifestJson = $manifestJson -replace "\{\{BOT_ID\}\}", $appId
        $manifestJson = $manifestJson -replace "\{\{APP_DOMAIN\}\}", "$webAppName.azurewebsites.net"
    }

    $manifestOutputDir = Join-Path $env:TEMP "teams-manifest-staging"
    if (Test-Path $manifestOutputDir) { Remove-Item $manifestOutputDir -Recurse -Force }
    New-Item -ItemType Directory -Path $manifestOutputDir | Out-Null

    $manifestJson | Set-Content "$manifestOutputDir/manifest.json" -Encoding UTF8
    if (Test-Path "$manifestDir/color.png") { Copy-Item "$manifestDir/color.png" $manifestOutputDir }
    if (Test-Path "$manifestDir/outline.png") { Copy-Item "$manifestDir/outline.png" $manifestOutputDir }

    $manifestZip = "deploy/teams-manifest.zip"
    if (Test-Path $manifestZip) { Remove-Item $manifestZip }
    Compress-Archive -Path "$manifestOutputDir/*" -DestinationPath $manifestZip -Force
    Remove-Item $manifestOutputDir -Recurse -Force

    Write-Step "  Manifest ZIP written to $manifestZip"
    Write-Step "  Upload via Teams Admin Center or sideload for testing."
}

Write-Step "Application deployment complete."
