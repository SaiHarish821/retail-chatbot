Get-Content -Path ".env" | ForEach-Object {
    $line = $_.Trim()
    if ($line -and -not $line.StartsWith("#") -and $line.Contains("=")) {
        $key, $value = $line.Split("=", 2)
        $key = $key.Trim()
        $value = $value.Trim()
        
        # Remove surrounding quotes if they exist
        if (($value.StartsWith('"') -and $value.EndsWith('"')) -or ($value.StartsWith("'") -and $value.EndsWith("'"))) {
            $value = $value.Substring(1, $value.Length - 2)
        }
        
        Write-Host "Syncing $key..."
        foreach ($env in "production", "preview", "development") {
            Write-Host "  Adding to $env..."
            Start-Process -FilePath "cmd.exe" -ArgumentList "/c", "vercel", "env", "add", $key, $env, "--value", $value, "--yes", "--force" -Wait -NoNewWindow
        }
    }
}
Write-Host "All environment variables synced successfully!"
