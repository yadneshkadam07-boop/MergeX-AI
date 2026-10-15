<#
.SYNOPSIS
    MergeX AI task runner for Windows (the equivalent of the Makefile).

.DESCRIPTION
    Wraps the common development commands so Windows contributors do not need
    `make`. Run from the repository root.

.EXAMPLE
    .\scripts\dev.ps1 setup
    .\scripts\dev.ps1 check
    .\scripts\dev.ps1 api
#>
[CmdletBinding()]
param(
    [Parameter(Position = 0)]
    [ValidateSet(
        'help', 'setup', 'setup-backend', 'setup-frontend', 'hooks',
        'up', 'down', 'clean-volumes', 'api', 'web',
        'migrate', 'migrate-down', 'migration', 'db-current',
        'check', 'lint', 'format', 'typecheck', 'test', 'build'
    )]
    [string]$Task = 'help',

    # Revision message. Used only by the `migration` task.
    [Parameter(Position = 1, ValueFromRemainingArguments = $true)]
    [string]$RevisionMessage
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$RepoRoot = Split-Path -Parent $PSScriptRoot
$BackendDir = Join-Path $RepoRoot 'backend'
$FrontendDir = Join-Path $RepoRoot 'frontend'
$VenvPython = Join-Path $BackendDir '.venv\Scripts\python.exe'

function Write-Step([string]$Message) {
    Write-Host "==> $Message" -ForegroundColor Cyan
}

# Runs a native command and converts a non-zero exit code into a terminating
# error, so a failing step stops the task instead of being silently ignored.
function Invoke-Checked {
    param(
        [Parameter(Mandatory)][string]$Exe,
        [string[]]$Arguments = @(),
        [string]$WorkingDirectory = $RepoRoot
    )
    Push-Location $WorkingDirectory
    try {
        & $Exe @Arguments
        if ($LASTEXITCODE -ne 0) {
            throw "`"$Exe $($Arguments -join ' ')`" failed with exit code $LASTEXITCODE"
        }
    }
    finally {
        Pop-Location
    }
}

function Get-InterpreterPath {
    foreach ($candidate in @('py', 'python3', 'python')) {
        $command = Get-Command $candidate -ErrorAction SilentlyContinue
        if ($null -eq $command) { continue }
        # Skip the Microsoft Store stub, which is not a usable interpreter.
        if ($command.Source -like '*WindowsApps*') { continue }
        return $command.Source
    }
    throw 'No Python interpreter found. Install Python 3.11 (winget install Python.Python.3.11).'
}

function Assert-Venv {
    if (-not (Test-Path $VenvPython)) {
        throw "Backend virtualenv missing. Run: .\scripts\dev.ps1 setup-backend"
    }
}

function Invoke-Py([string[]]$Arguments) {
    Assert-Venv
    Invoke-Checked -Exe $VenvPython -Arguments $Arguments -WorkingDirectory $BackendDir
}

function Invoke-Npm([string[]]$Arguments) {
    Invoke-Checked -Exe 'npm' -Arguments $Arguments -WorkingDirectory $FrontendDir
}

switch ($Task) {
    'help' {
        Write-Host ''
        Write-Host 'MergeX AI tasks' -ForegroundColor White
        Write-Host ''
        @(
            @{ n = 'setup';          d = 'Install backend venv + frontend node_modules' },
            @{ n = 'setup-backend';  d = 'Create backend/.venv and install dev dependencies' },
            @{ n = 'setup-frontend'; d = 'Install frontend dependencies' },
            @{ n = 'hooks';          d = 'Install git pre-commit hooks' },
            @{ n = 'up';             d = 'Start the full stack in Docker' },
            @{ n = 'down';           d = 'Stop the Docker stack' },
            @{ n = 'clean-volumes';  d = 'Stop the stack and delete the database volume' },
            @{ n = 'migrate';        d = 'Apply all database migrations' },
            @{ n = 'migrate-down';   d = 'Roll back the most recent migration' },
            @{ n = 'migration';      d = 'Autogenerate a revision (pass a message)' },
            @{ n = 'db-current';     d = 'Show the applied revision' },
            @{ n = 'api';            d = 'Run the backend locally with reload' },
            @{ n = 'web';            d = 'Run the frontend dev server' },
            @{ n = 'check';          d = 'lint + typecheck + test (what CI runs)' },
            @{ n = 'lint';           d = 'Lint backend and frontend' },
            @{ n = 'format';         d = 'Auto-format backend and frontend' },
            @{ n = 'typecheck';      d = 'mypy + tsc' },
            @{ n = 'test';           d = 'Backend tests with coverage' },
            @{ n = 'build';          d = 'Production build of the frontend' }
        ) | ForEach-Object {
            Write-Host ('  {0,-16} {1}' -f $_.n, $_.d)
        }
        Write-Host ''
    }

    'setup' {
        & $PSCommandPath 'setup-backend'
        & $PSCommandPath 'setup-frontend'
    }

    'setup-backend' {
        $interpreter = Get-InterpreterPath
        Write-Step "Creating virtualenv with $interpreter"
        Invoke-Checked -Exe $interpreter -Arguments @('-m', 'venv', '.venv') -WorkingDirectory $BackendDir
        Write-Step 'Upgrading pip'
        Invoke-Py @('-m', 'pip', 'install', '--upgrade', 'pip', 'setuptools', 'wheel')
        Write-Step 'Installing backend (editable) + dev dependencies'
        Invoke-Py @('-m', 'pip', 'install', '-e', '.[dev]')
    }

    'setup-frontend' {
        Write-Step 'Installing frontend dependencies'
        Invoke-Npm @('install')
    }

    'hooks' {
        Write-Step 'Installing pre-commit hooks'
        Invoke-Py @('-m', 'pre_commit', 'install')
    }

    'up' { Invoke-Checked -Exe 'docker' -Arguments @('compose', 'up', '--build') }
    'down' { Invoke-Checked -Exe 'docker' -Arguments @('compose', 'down') }
    'clean-volumes' { Invoke-Checked -Exe 'docker' -Arguments @('compose', 'down', '--volumes') }

    'migrate' {
        Write-Step 'alembic upgrade head'
        Invoke-Py @('-m', 'alembic', 'upgrade', 'head')
    }

    'migrate-down' {
        Write-Step 'alembic downgrade -1'
        Invoke-Py @('-m', 'alembic', 'downgrade', '-1')
    }

    'migration' {
        if ([string]::IsNullOrWhiteSpace($RevisionMessage)) {
            throw 'A message is required, e.g.: .\scripts\dev.ps1 migration "add issue table"'
        }
        Write-Step "alembic revision --autogenerate -m '$RevisionMessage'"
        Invoke-Py @('-m', 'alembic', 'revision', '--autogenerate', '-m', $RevisionMessage)
    }

    'db-current' {
        Invoke-Py @('-m', 'alembic', 'current')
    }

    'api' {
        Write-Step 'Backend on http://localhost:8000 (docs at /docs)'
        Invoke-Py @('-m', 'uvicorn', 'app.main:app', '--reload', '--port', '8000')
    }

    'web' {
        Write-Step 'Frontend on http://localhost:5173'
        Invoke-Npm @('run', 'dev')
    }

    'check' {
        & $PSCommandPath 'lint'
        & $PSCommandPath 'typecheck'
        & $PSCommandPath 'test'
        Write-Host 'All checks passed.' -ForegroundColor Green
    }

    'lint' {
        Write-Step 'ruff'
        Invoke-Py @('-m', 'ruff', 'check', '.')
        Write-Step 'black --check'
        Invoke-Py @('-m', 'black', '--check', '.')
        Write-Step 'eslint'
        Invoke-Npm @('run', 'lint')
        Write-Step 'prettier --check'
        Invoke-Npm @('run', 'format:check')
    }

    'format' {
        Write-Step 'ruff --fix'
        Invoke-Py @('-m', 'ruff', 'check', '--fix', '.')
        Write-Step 'black'
        Invoke-Py @('-m', 'black', '.')
        Write-Step 'prettier --write'
        Invoke-Npm @('run', 'format')
    }

    'typecheck' {
        Write-Step 'mypy'
        Invoke-Py @('-m', 'mypy')
        Write-Step 'tsc'
        Invoke-Npm @('run', 'typecheck')
    }

    'test' {
        Write-Step 'pytest'
        Invoke-Py @('-m', 'pytest', '--cov=app', '--cov-report=term-missing')
    }

    'build' {
        Write-Step 'vite build'
        Invoke-Npm @('run', 'build')
    }
}
