$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
py -3.13 -m jobsearcher.server
