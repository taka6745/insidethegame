param([object]$WebhookData, [string]$Mode = 'last-resort')
# stream-start / stream-stop: Stream Analytics follows play (Event Hubs alerts). last-resort: stop what
# doesn't serve the viewer. hard-stop: stop every container app and database in our groups.
# Starts and stops only; never deletes. `./dev azure up` restores everything.
$ErrorActionPreference = 'Continue'
Connect-AzAccount -Identity | Out-Null
$groups = @(${groups})
$apps = @(${apps})

function Invoke-Action($resource, $path, $body) {
  $result = Invoke-AzRestMethod -Method POST -Path "$($resource.ResourceId)/$path" -Payload $body
  Write-Output "$($resource.Name): $path -> $($result.StatusCode)"
  return $result
}

$jobs = Get-AzResource -ResourceGroupName '${etl_group}' -ResourceType 'Microsoft.StreamAnalytics/streamingjobs' -ErrorAction SilentlyContinue
foreach ($job in $jobs) {
  $state = (Invoke-AzRestMethod -Path "$($job.ResourceId)?api-version=2020-03-01").Content | ConvertFrom-Json
  $running = $state.properties.jobState -in @('Running', 'Starting', 'Restarting', 'Scaling')
  if ($Mode -eq 'stream-start' -and -not $running) {
    # Resume after the last output, so events buffered in Event Hubs while stopped are not lost.
    $result = Invoke-Action $job 'start?api-version=2020-03-01' '{"outputStartMode":"LastOutputEventTime"}'
    if ($result.StatusCode -ge 400) {  # never produced output yet
      $since = (Get-Date).ToUniversalTime().AddMinutes(-30).ToString('o')
      Invoke-Action $job 'start?api-version=2020-03-01' "{`"outputStartMode`":`"CustomTime`",`"outputStartTime`":`"$since`"}" | Out-Null
    }
  } elseif ($Mode -ne 'stream-start' -and $running) {
    Invoke-Action $job 'stop?api-version=2020-03-01' $null | Out-Null
  }
}

$everything = $Mode -eq 'hard-stop'
if ($Mode -eq 'last-resort' -or $everything) {
  foreach ($group in $groups) {
    foreach ($app in (Get-AzResource -ResourceGroupName $group -ResourceType 'Microsoft.App/containerApps' -ErrorAction SilentlyContinue)) {
      if ($everything -or ($apps | Where-Object { $app.Name -like "*$_" })) { Invoke-Action $app 'stop?api-version=2024-03-01' $null | Out-Null }
    }
    $serverGroups = if ($everything) { $groups } else { @('${servers}') }
    if ($group -notin $serverGroups) { continue }
    foreach ($server in (Get-AzResource -ResourceGroupName $group -ResourceType 'Microsoft.DBforPostgreSQL/flexibleServers' -ErrorAction SilentlyContinue)) {
      Invoke-Action $server 'stop?api-version=2022-12-01' $null | Out-Null
    }
  }
}
