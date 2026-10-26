param(
  [Parameter(Mandatory = $true)][int]$StartPort,
  [Parameter(Mandatory = $true)][int]$EndPort
)

for ($port = $StartPort; $port -le $EndPort; $port++) {
  $occupied = Get-NetTCPConnection -State Listen -LocalPort $port -ErrorAction SilentlyContinue
  if ($occupied) {
    continue
  }

  $listener = [System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Loopback, $port)
  try {
    $listener.Server.ExclusiveAddressUse = $true
    $listener.Start()
    $listener.Stop()
    Write-Output $port
    exit 0
  } catch {
    $listener.Stop()
  }
}

Write-Error "No free TCP port found in range $StartPort-$EndPort."
exit 1
