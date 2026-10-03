param([ValidateSet('SessionStart', 'UserPromptSubmit')][string]$Event = 'SessionStart')
$frameworkRoot = Split-Path -Parent $PSScriptRoot
$hookScript = Join-Path $frameworkRoot 'scripts/context_hook.py'
if (Get-Command py -ErrorAction SilentlyContinue) {
    & py -3 $hookScript --event $Event
} else {
    & python $hookScript --event $Event
}
exit $LASTEXITCODE
