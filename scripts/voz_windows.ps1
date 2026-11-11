# Texto a voz con una voz sintética de Windows (OneCore), sin internet ni modelos que descargar.
# Uso: powershell -File voz_windows.ps1 -Texto "Hola" -Salida salida.wav [-Voz "Pablo"] [-Velocidad "+0%"]
param(
    [Parameter(Mandatory = $true)][string]$Texto,
    [Parameter(Mandatory = $true)][string]$Salida,
    [string]$Voz = "Pablo",
    [string]$Velocidad = "+0%"
)
$ErrorActionPreference = "Stop"
Add-Type -AssemblyName System.Runtime.WindowsRuntime
$asTask = ([System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object {
    $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1' })[0]
function Esperar($op, [Type]$tipo) {
    $t = $asTask.MakeGenericMethod($tipo).Invoke($null, @($op))
    $t.Wait(-1) | Out-Null
    $t.Result
}
[Windows.Media.SpeechSynthesis.SpeechSynthesizer, Windows.Media.SpeechSynthesis, ContentType = WindowsRuntime] | Out-Null
[Windows.Storage.Streams.DataReader, Windows.Storage.Streams, ContentType = WindowsRuntime] | Out-Null

$sintetizador = New-Object Windows.Media.SpeechSynthesis.SpeechSynthesizer
$info = [Windows.Media.SpeechSynthesis.SpeechSynthesizer]::AllVoices | Where-Object { $_.DisplayName -like "*$Voz*" } | Select-Object -First 1
if (-not $info) { throw "No se encontró la voz '$Voz'" }
$sintetizador.Voice = $info
$escapado = [System.Security.SecurityElement]::Escape($Texto)
$ssml = "<speak version='1.0' xmlns='http://www.w3.org/2001/10/synthesis' xml:lang='$($info.Language)'><prosody rate='$Velocidad'>$escapado</prosody></speak>"
$flujo = Esperar ($sintetizador.SynthesizeSsmlToStreamAsync($ssml)) ([Windows.Media.SpeechSynthesis.SpeechSynthesisStream])
$lector = New-Object Windows.Storage.Streams.DataReader($flujo.GetInputStreamAt(0))
$n = [uint32]$flujo.Size
Esperar ($lector.LoadAsync($n)) ([uint32]) | Out-Null
$bytes = New-Object byte[] $n
$lector.ReadBytes($bytes)
[System.IO.File]::WriteAllBytes($Salida, $bytes)
Write-Output "$($info.DisplayName) -> $Salida ($n bytes)"
