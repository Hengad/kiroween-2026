# TDD guard: remind the agent to write a failing test first, but only for production code.
# Reads the PreToolUse JSON from stdin. Prints a reminder for non-exempt paths; stays silent otherwise.

$raw = [Console]::In.ReadToEnd()
try { $data = $raw | ConvertFrom-Json } catch { exit 0 }

$path = $data.tool_input.path
if (-not $path) { exit 0 }
$p = ($path -replace '\\', '/')

# Exempt: docs, steering/hooks/specs, config and data files, and test files themselves.
$exempt = @(
    '\.md$', '/\.kiro/', '\.json$', '\.ya?ml$', '\.toml$', '\.ini$', '\.cfg$', '\.txt$', '\.env(\..*)?$',
    '(^|/)\.gitignore$', '(^|/)LICENSE$',
    '/tests?/', '(^|/)test_[^/]*\.py$', '(^|/)conftest\.py$', '\.(test|spec)\.(ts|js)$', '/e2e/'
)
foreach ($pattern in $exempt) {
    if ($p -match $pattern) { exit 0 }
}

Write-Output "TDD check: this write changes production code ($p). Confirm that a failing test requiring this behavior already exists and was run and seen failing. If not, write and run that test first instead."
exit 0
