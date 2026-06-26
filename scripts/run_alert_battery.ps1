param(
    [switch]$KeepStackUp
)

$ErrorActionPreference = "Stop"

function Write-Step {
    param([string]$Message)
    Write-Host "[NEXUS-ALERT-BATTERY] $Message"
}

function Wait-HttpOk {
    param(
        [string]$Url,
        [int]$Retries = 30,
        [int]$SleepSeconds = 2
    )

    for ($i = 0; $i -lt $Retries; $i++) {
        try {
            $response = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 5
            if ($response.StatusCode -ge 200 -and $response.StatusCode -lt 500) {
                return
            }
        } catch {
        }
        Start-Sleep -Seconds $SleepSeconds
    }

    throw "Timeout esperando a $Url"
}

function Assert-True {
    param(
        [bool]$Condition,
        [string]$Message
    )

    if (-not $Condition) {
        throw $Message
    }
}

function Invoke-Json {
    param(
        [string]$Method,
        [string]$Url,
        [object]$Body = $null
    )

    if ($null -eq $Body) {
        return Invoke-RestMethod -Method $Method -Uri $Url -ContentType "application/json"
    }

    return Invoke-RestMethod -Method $Method -Uri $Url -ContentType "application/json" -Body ($Body | ConvertTo-Json -Depth 8)
}

try {
    Write-Step "Levantando stack base con Docker Compose"
    docker compose up -d mongodb redis web alertmanager prometheus | Out-Null

    Write-Step "Esperando salud de Nexus, Alertmanager y Prometheus"
    Wait-HttpOk "http://localhost:5010/api/nexus/health"
    Wait-HttpOk "http://localhost:9093/-/healthy"
    Wait-HttpOk "http://localhost:9090/-/healthy"

    Write-Step "Simulando webhook directo de Alertmanager hacia Nexus"
    $firingPayload = @{
        receiver = "nexus-admins"
        status = "firing"
        alerts = @(
            @{
                status = "firing"
                fingerprint = "battery-fp-001"
                labels = @{
                    alertname = "DiskFull"
                    severity = "critical"
                    instance = "srv-app-01"
                }
                annotations = @{
                    summary = "Disk full on srv-app-01"
                    description = "Filesystem over threshold"
                }
            }
        )
    }
    $created = Invoke-Json -Method POST -Url "http://localhost:5010/api/nexus/monitoring/webhook" -Body $firingPayload
    Assert-True ($created.incidents_created -eq 1) "Nexus no creo el incidente esperado"

    Write-Step "Verificando incidente creado"
    $incident = Invoke-Json -Method GET -Url "http://localhost:5010/api/nexus/incidents/battery-fp-001"
    Assert-True ($incident.incident.status -eq "open") "El incidente no quedo en estado open"

    Write-Step "Simulando resolucion desde webhook"
    $resolvedPayload = @{
        receiver = "nexus-admins"
        status = "resolved"
        alerts = @(
            @{
                status = "resolved"
                fingerprint = "battery-fp-001"
                labels = @{
                    alertname = "DiskFull"
                    severity = "critical"
                    instance = "srv-app-01"
                }
            }
        )
    }
    $resolved = Invoke-Json -Method POST -Url "http://localhost:5010/api/nexus/monitoring/webhook" -Body $resolvedPayload
    Assert-True ($resolved.incidents_resolved -eq 1) "Nexus no marco el incidente como resuelto"

    Write-Step "Creando silencio en Alertmanager a traves de Nexus"
    $silence = Invoke-Json -Method POST -Url "http://localhost:5010/api/nexus/monitoring/silence" -Body @{
        alert_name = "DiskFull"
        created_by = "battery-runner"
        duration_seconds = 900
        comment = "Battery test silence"
    }
    Assert-True (-not [string]::IsNullOrWhiteSpace($silence.silence_id)) "No se creo el silencio esperado"

    Write-Step "Inyectando alerta en Alertmanager para probar consulta de superficie"
    $amAlert = @(
        @{
            labels = @{
                alertname = "HighCPU"
                severity = "warning"
                instance = "srv-app-02"
            }
            annotations = @{
                summary = "CPU high on srv-app-02"
                description = "Synthetic battery alert"
            }
            startsAt = (Get-Date).ToUniversalTime().ToString("o")
            endsAt = (Get-Date).ToUniversalTime().AddMinutes(15).ToString("o")
            generatorURL = "battery://synthetic"
        }
    )
    Invoke-Json -Method POST -Url "http://localhost:9093/api/v2/alerts" -Body $amAlert | Out-Null
    Start-Sleep -Seconds 2

    Write-Step "Leyendo alertas enriquecidas desde Nexus"
    $alerts = Invoke-Json -Method GET -Url "http://localhost:5010/api/nexus/monitoring/alerts"
    Assert-True ($alerts.total -ge 1) "Nexus no devolvio alertas desde Alertmanager"

    Write-Step "Revisando auditoria"
    $audit = Invoke-Json -Method GET -Url "http://localhost:5010/api/nexus/audit"
    Assert-True ($audit.total -ge 3) "La auditoria no registro suficientes eventos"

    Write-Step "Bateria completada correctamente"
    exit 0
}
catch {
    Write-Error $_
    exit 1
}
finally {
    if (-not $KeepStackUp) {
        try {
            Write-Step "Apagando stack de prueba"
            docker compose down | Out-Null
        } catch {
        }
    }
}
