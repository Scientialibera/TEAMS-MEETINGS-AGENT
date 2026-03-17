param(
    [string]$ConfigPath = "deploy/deploy.config.toml"
)

$ErrorActionPreference = "Stop"
$PSNativeCommandUseErrorActionPreference = $false

function Write-Step { param([string]$Message) Write-Host "[deploy-infra] $Message" }

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
    if ([string]::IsNullOrWhiteSpace($normalized)) { throw "Invalid naming prefix for storage account." }
    if ($normalized.Length -lt 3) { $normalized = $normalized + "123" }
    if ($normalized.Length -gt 22) { $normalized = $normalized.Substring(0, 22) }
    return "st$normalized"
}

function Normalize-SearchName {
    param([string]$Value)
    $normalized = ($Value.ToLower() -replace "[^a-z0-9-]", "")
    if ([string]::IsNullOrWhiteSpace($normalized)) { throw "Invalid naming prefix for search service." }
    if ($normalized.Length -gt 53) { $normalized = $normalized.Substring(0, 53) }
    return "srch-$normalized"
}

function Normalize-CogName {
    param([string]$Prefix, [string]$Value)
    $normalized = ($Value.ToLower() -replace "[^a-z0-9-]", "")
    if ([string]::IsNullOrWhiteSpace($normalized)) { throw "Invalid naming prefix for cognitive account." }
    if ($normalized.Length -gt 18) { $normalized = $normalized.Substring(0, 18) }
    return "$Prefix-$normalized"
}

function Normalize-RedisName {
    param([string]$Value)
    $normalized = ($Value.ToLower() -replace "[^a-z0-9]", "")
    if ([string]::IsNullOrWhiteSpace($normalized)) { throw "Invalid naming prefix for redis cache." }
    if ($normalized.Length -lt 3) { $normalized = $normalized + "123" }
    if ($normalized.Length -gt 58) { $normalized = $normalized.Substring(0, 58) }
    return "redis$normalized"
}

function Ensure-RoleAssignment {
    param(
        [string]$PrincipalId,
        [string]$Scope,
        [string]$Role,
        [string]$PrincipalType = "ServicePrincipal"
    )
    $count = az role assignment list `
      --assignee-object-id $PrincipalId `
      --scope $Scope `
      --query "[?roleDefinitionName=='$Role'] | length(@)" `
      -o tsv
    if ($LASTEXITCODE -ne 0) { throw "Failed to query role assignments for '$Role'." }
    if ($count -eq "0") {
        Write-Step "  Assigning role '$Role'."
        az role assignment create `
          --assignee-object-id $PrincipalId `
          --assignee-principal-type $PrincipalType `
          --role $Role `
          --scope $Scope | Out-Null
    }
}

# ---------------------------------------------------------------------------
# Load config
# ---------------------------------------------------------------------------
$config = Get-Config -Path $ConfigPath

$subscriptionId = $config.azure.subscription_id
if ([string]::IsNullOrWhiteSpace($subscriptionId)) { $subscriptionId = az account show --query id -o tsv }
if ([string]::IsNullOrWhiteSpace($subscriptionId)) { throw "No Azure subscription. Set azure.subscription_id or run az login." }

$prefix       = $config.naming.prefix.ToLower()
$location     = Select-Value $config.azure.location "eastus"
$rg           = Select-Value $config.azure.resource_group_name "rg-$prefix"
$webAppName   = Select-Value $config.naming.web_app_name "app-$prefix"
$aspName      = Select-Value $config.naming.app_service_plan_name "plan-$prefix"
$storageAcct  = Select-Value $config.naming.storage_account_name (Normalize-StorageAccountName -Value $prefix)
$searchSvc    = Select-Value $config.naming.search_service_name (Normalize-SearchName -Value $prefix)
$openAiAcct   = Select-Value $config.naming.openai_account_name (Normalize-CogName -Prefix "aoai" -Value $prefix)
$redisCache   = Select-Value $config.naming.redis_cache_name (Normalize-RedisName -Value $prefix)
$botName      = Select-Value $config.naming.bot_name "bot-$prefix"

$usersContainer = $config.storage.users_container
$stateContainer = $config.storage.state_container

$deployOpenAI  = [bool]$config.openai.deploy_openai
$deploySearch  = [bool]$config.search.deploy_search
$searchSku     = $config.search.sku
$redisSku      = Select-Value $config.redis.sku "Basic"
$redisCapacity = Select-Value $config.redis.capacity "C0"
$webAppSku     = Select-Value $config.app_settings.webapp_sku "B1"
$pythonVersion = Select-Value $config.app_settings.python_version "3.11"
$botSku        = Select-Value $config.bot.bot_sku "F0"

Write-Step "Subscription: $subscriptionId"
az account set --subscription $subscriptionId

$executorObjectId = az ad signed-in-user show --query id -o tsv
if ([string]::IsNullOrWhiteSpace($executorObjectId)) { throw "Could not resolve signed-in user object id." }

# ---------------------------------------------------------------------------
# 1. Resource Group
# ---------------------------------------------------------------------------
Write-Step "Ensuring resource group '$rg'."
$rgExists = az group exists --name $rg -o tsv
if ($rgExists -ne "true") { az group create --name $rg --location $location | Out-Null }
$rgScope = az group show --name $rg --query id -o tsv

# ---------------------------------------------------------------------------
# 2. Storage Account + containers
# ---------------------------------------------------------------------------
Write-Step "Ensuring storage account '$storageAcct'."
$storageExists = az storage account list --resource-group $rg --query "[?name=='$storageAcct'] | length(@)" -o tsv
if ($storageExists -eq "0") {
    az storage account create `
      --resource-group $rg --name $storageAcct --location $location `
      --sku Standard_LRS --kind StorageV2 `
      --min-tls-version TLS1_2 --allow-blob-public-access false | Out-Null
}
$storageScope = az storage account show --resource-group $rg --name $storageAcct --query id -o tsv
Ensure-RoleAssignment -PrincipalId $executorObjectId -PrincipalType User -Scope $storageScope -Role "Storage Blob Data Owner"

foreach ($container in @($usersContainer, $stateContainer)) {
    $exists = az storage container exists --account-name $storageAcct --name $container --auth-mode login --query exists -o tsv
    if ($exists -ne "true") {
        az storage container create --account-name $storageAcct --name $container --auth-mode login | Out-Null
    }
}

# ---------------------------------------------------------------------------
# 3. App Service Plan + Web App
# ---------------------------------------------------------------------------
Write-Step "Ensuring App Service Plan '$aspName'."
$aspExists = az appservice plan list --resource-group $rg --query "[?name=='$aspName'] | length(@)" -o tsv
if ($aspExists -eq "0") {
    az appservice plan create `
      --resource-group $rg --name $aspName --location $location `
      --sku $webAppSku --is-linux | Out-Null
}

Write-Step "Ensuring Web App '$webAppName'."
$appExists = az webapp list --resource-group $rg --query "[?name=='$webAppName'] | length(@)" -o tsv
if ($appExists -eq "0") {
    az webapp create `
      --resource-group $rg --name $webAppName --plan $aspName `
      --runtime "PYTHON:$pythonVersion" | Out-Null
}

az webapp config set --resource-group $rg --name $webAppName --always-on true | Out-Null
az webapp config set --resource-group $rg --name $webAppName --startup-file "python -m gunicorn src.app:init_app --bind 0.0.0.0:8000 --worker-class aiohttp.GunicornWebWorker --timeout 600" | Out-Null

# ---------------------------------------------------------------------------
# 4. Azure OpenAI
# ---------------------------------------------------------------------------
if ($deployOpenAI) {
    Write-Step "Ensuring Azure OpenAI account '$openAiAcct'."
    $aoaiExists = az cognitiveservices account list --resource-group $rg --query "[?name=='$openAiAcct'] | length(@)" -o tsv
    if ($aoaiExists -eq "0") {
        az cognitiveservices account create `
          --name $openAiAcct --resource-group $rg --kind OpenAI `
          --sku $config.openai.sku_name --location $location `
          --custom-domain $openAiAcct | Out-Null
    }

    foreach ($dep in @(
        @{ name=$config.openai.chat_deployment; model=$config.openai.chat_model; version=$config.openai.chat_model_version },
        @{ name=$config.openai.embedding_deployment; model=$config.openai.embedding_model; version=$config.openai.embedding_model_version }
    )) {
        $depExists = az cognitiveservices account deployment list --name $openAiAcct --resource-group $rg --query "[?name=='$($dep.name)'] | length(@)" -o tsv
        if ($depExists -eq "0") {
            az cognitiveservices account deployment create `
              --name $openAiAcct --resource-group $rg `
              --deployment-name $dep.name `
              --model-format OpenAI --model-name $dep.model --model-version $dep.version `
              --sku-name $config.openai.deployment_sku_name `
              --sku-capacity $config.openai.capacity | Out-Null
        }
    }
}

# ---------------------------------------------------------------------------
# 5. Azure AI Search
# ---------------------------------------------------------------------------
if ($deploySearch) {
    Write-Step "Ensuring AI Search service '$searchSvc'."
    $searchExists = az search service list --resource-group $rg --query "[?name=='$searchSvc'] | length(@)" -o tsv
    if ($searchExists -eq "0") {
        az search service create --resource-group $rg --name $searchSvc --sku $searchSku --partition-count 1 --replica-count 1 | Out-Null
    }
} else {
    $searchExists = az search service list --resource-group $rg --query "[?name=='$searchSvc'] | length(@)" -o tsv
    if ($searchExists -eq "0") { throw "Search service '$searchSvc' not found and deploy_search=false." }
}

# ---------------------------------------------------------------------------
# 6. Entra App Registration
# ---------------------------------------------------------------------------
$entraAppName = Select-Value $config.entra.app_display_name "Teams Meetings Agent"
$configuredAppId = $config.entra.app_id

if ([string]::IsNullOrWhiteSpace($configuredAppId)) {
    Write-Step "Creating Entra app registration '$entraAppName'."
    $existingApp = az ad app list --display-name $entraAppName --query "[0].appId" -o tsv
    if ([string]::IsNullOrWhiteSpace($existingApp)) {
        $appId = az ad app create `
          --display-name $entraAppName `
          --sign-in-audience AzureADMyOrg `
          --query appId -o tsv
    } else {
        $appId = $existingApp
        Write-Step "  Reusing existing app registration $appId."
    }

    $spExists = az ad sp list --filter "appId eq '$appId'" --query "length(@)" -o tsv
    if ($spExists -eq "0") { az ad sp create --id $appId | Out-Null }

    $secret = az ad app credential reset --id $appId --display-name "deploy-generated" --query password -o tsv
    Write-Step "  App ID: $appId"
    Write-Step "  Secret generated (store securely)."
} else {
    $appId = $configuredAppId
    $secret = $config.entra.app_secret
    Write-Step "Using configured Entra app: $appId"
}

# ---------------------------------------------------------------------------
# 7. Azure Cache for Redis
# ---------------------------------------------------------------------------
Write-Step "Ensuring Redis cache '$redisCache'."
$redisExists = az redis list --resource-group $rg --query "[?name=='$redisCache'] | length(@)" -o tsv
if ($redisExists -eq "0") {
    az redis create `
      --resource-group $rg --name $redisCache --location $location `
      --sku $redisSku --vm-size $redisCapacity `
      --enable-non-ssl-port false `
      --minimum-tls-version "1.2" | Out-Null
}

# ---------------------------------------------------------------------------
# 8. Azure Bot Service
# ---------------------------------------------------------------------------
Write-Step "Ensuring Azure Bot '$botName'."
$botExists = az bot show --resource-group $rg --name $botName 2>$null
if ([string]::IsNullOrWhiteSpace($botExists)) {
    az bot create `
      --resource-group $rg --name $botName `
      --kind registration `
      --app-type SingleTenant `
      --appid $appId `
      --tenant-id (az account show --query tenantId -o tsv) `
      --endpoint "https://$webAppName.azurewebsites.net/api/messages" `
      --sku $botSku | Out-Null
}

# ---------------------------------------------------------------------------
# 9. Teams Channel
# ---------------------------------------------------------------------------
Write-Step "Ensuring Teams channel on bot."
$teamsChannelExists = az bot msteams show --resource-group $rg --name $botName 2>$null
if ([string]::IsNullOrWhiteSpace($teamsChannelExists)) {
    az bot msteams create --resource-group $rg --name $botName | Out-Null
}

# ---------------------------------------------------------------------------
# 10. Web App Managed Identity + RBAC
# ---------------------------------------------------------------------------
Write-Step "Assigning system-managed identity to Web App."
az webapp identity assign --resource-group $rg --name $webAppName --identities [system] | Out-Null
$webAppPrincipalId = az webapp identity show --resource-group $rg --name $webAppName --query principalId -o tsv
if ([string]::IsNullOrWhiteSpace($webAppPrincipalId)) { throw "Could not resolve Web App managed identity." }

Ensure-RoleAssignment -PrincipalId $webAppPrincipalId -Scope $storageScope -Role "Storage Blob Data Contributor"

$openAiEndpoint = az cognitiveservices account show --resource-group $rg --name $openAiAcct --query properties.endpoint -o tsv
if (-not [string]::IsNullOrWhiteSpace($openAiEndpoint)) {
    $openAiScope = az cognitiveservices account show --resource-group $rg --name $openAiAcct --query id -o tsv
    Ensure-RoleAssignment -PrincipalId $webAppPrincipalId -Scope $openAiScope -Role "Cognitive Services OpenAI User"
}

$searchScope = az search service show --resource-group $rg --name $searchSvc --query id -o tsv
Ensure-RoleAssignment -PrincipalId $webAppPrincipalId -Scope $searchScope -Role "Search Index Data Contributor"
$redisScope = az redis show --resource-group $rg --name $redisCache --query id -o tsv
Ensure-RoleAssignment -PrincipalId $webAppPrincipalId -Scope $redisScope -Role "Reader"

# ---------------------------------------------------------------------------
# 11. Web App Settings
# ---------------------------------------------------------------------------
Write-Step "Setting Web App application settings."
$blobUrl = (az storage account show --resource-group $rg --name $storageAcct --query "primaryEndpoints.blob" -o tsv).TrimEnd("/")
$searchEndpoint = "https://$searchSvc.search.windows.net"
$redisHost = az redis show --resource-group $rg --name $redisCache --query hostName -o tsv
$redisPassword = az redis list-keys --resource-group $rg --name $redisCache --query primaryKey -o tsv
$tenantId = az account show --query tenantId -o tsv

$settings = @(
    "MICROSOFT_APP_ID=$appId",
    "MICROSOFT_APP_PASSWORD=$secret",
    "MICROSOFT_APP_TENANT_ID=$tenantId",
    "MICROSOFT_APP_TYPE=SingleTenant",
    "BLOB_ACCOUNT_URL=$blobUrl",
    "BLOB_USERS_CONTAINER=$usersContainer",
    "BLOB_STATE_CONTAINER=$stateContainer",
    "AOAI_ENDPOINT=$openAiEndpoint",
    "AOAI_API_VERSION=$($config.openai.api_version)",
    "AOAI_CHAT_DEPLOYMENT=$($config.openai.chat_deployment)",
    "AOAI_EMBEDDING_DEPLOYMENT=$($config.openai.embedding_deployment)",
    "SEARCH_ENDPOINT=$searchEndpoint",
    "SEARCH_INDEX=$($config.search.index_name)",
    "SEARCH_USE_VECTOR=$($config.search.use_vector.ToString().ToLower())",
    "SEARCH_EMBEDDING_DIMENSIONS=$($config.search.embedding_dimensions)",
    "GRAPH_API_VERSION=$($config.graph.api_version)",
    "REMINDER_WINDOW_MINUTES=$($config.graph.reminder_window_minutes)",
    "SCHEDULER_INTERVAL_MINUTES=$($config.graph.scheduler_interval_minutes)",
    "SUBSCRIPTION_RENEWAL_MINUTES=$($config.graph.subscription_renewal_minutes)",
    "WEBHOOK_URL=https://$webAppName.azurewebsites.net/api/notifications",
    "REDIS_HOST=$redisHost",
    "REDIS_PORT=6380",
    "REDIS_PASSWORD=$redisPassword",
    "REDIS_SSL=true",
    "REDIS_REMINDER_TTL_SECONDS=$($config.redis.reminder_ttl_seconds)"
)
az webapp config appsettings set --resource-group $rg --name $webAppName --settings $settings | Out-Null

# ---------------------------------------------------------------------------
# 12. Application Access Policy (manual step guidance)
# ---------------------------------------------------------------------------
Write-Step "---"
Write-Step "MANUAL STEP: Application Access Policy for Graph Online Meeting APIs."
Write-Step "Run these commands in Teams PowerShell (Connect-MicrosoftTeams):"
Write-Step ""
Write-Step "  New-CsApplicationAccessPolicy ``"
Write-Step "    -Identity 'MeetingsAgent-Policy' ``"
Write-Step "    -AppIds '$appId' ``"
Write-Step "    -Description 'Allow meetings agent transcript and AI insights access'"
Write-Step ""
Write-Step "  Grant-CsApplicationAccessPolicy ``"
Write-Step "    -PolicyName 'MeetingsAgent-Policy' -Global"
Write-Step ""
Write-Step "Changes may take up to 30 minutes to propagate."
Write-Step "---"

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
Write-Step "Infrastructure deployment complete."
Write-Output ""
Write-Output "Resource group:    $rg"
Write-Output "Storage account:   $storageAcct"
Write-Output "Web App:           $webAppName (https://$webAppName.azurewebsites.net)"
Write-Output "App Service Plan:  $aspName"
Write-Output "Azure OpenAI:      $openAiAcct"
Write-Output "AI Search:         $searchSvc"
Write-Output "Redis Cache:       $redisCache"
Write-Output "Bot:               $botName"
Write-Output "Entra App ID:      $appId"
Write-Output ""
Write-Output "IMPORTANT: Save the app secret securely. It will not be displayed again."
