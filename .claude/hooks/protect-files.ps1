$ErrorActionPreference = "Stop"

$inputJson = [Console]::In.ReadToEnd()

try {
    $event = $inputJson | ConvertFrom-Json
} catch {
    exit 0
}

$filePath = $event.tool_input.file_path

if (-not $filePath) {
    exit 0
}

$fileName = [System.IO.Path]::GetFileName($filePath)

$protectedFiles = @(
    ".env",
    ".env.local",
    ".env.production",
    ".env.development",
    "secrets.json",
    "credentials.json"
)

if ($protectedFiles -contains $fileName -or $fileName -match "\.pem$|\.key$") {
    Write-Error "BLOCKED: $filePath is a sensitive/protected file."
    exit 2
}

exit 0