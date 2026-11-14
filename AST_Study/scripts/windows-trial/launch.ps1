param([switch]$CheckOnly)
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName PresentationFramework
$root = $PSScriptRoot
$data = Join-Path $env:LOCALAPPDATA 'SYNESIS-PDF-Trial'
$logs = Join-Path $data '.runtime'
$mutex = New-Object System.Threading.Mutex($false, 'Local\SYNESIS-PDF-Trial-v1')
$owned = $false
try {
    $owned = $mutex.WaitOne(0)
    if (-not $owned) {
        [System.Windows.MessageBox]::Show('SYNESIS 시험판이 이미 실행 중이에요.', 'SYNESIS') | Out-Null
        exit 0
    }
    New-Item -ItemType Directory -Force -Path $logs | Out-Null
    $log = Join-Path $logs ('launch-' + (Get-Date -Format 'yyyyMMdd-HHmmss') + '.log')
    $env:SYNESIS_APP_ROOT = $root
    $env:SYNESIS_DATA_DIR = $data
    $env:SYNESIS_CREDENTIALS_FILE = Join-Path $root 'config\credentials.env'
    $env:PYTHONUTF8 = '1'
    $env:PYTHONDONTWRITEBYTECODE = '1'
    $env:PYTHON_DOTENV_DISABLED = '1'
    $python = Join-Path $root '.venv-pdf\Scripts\python.exe'
    $java = Join-Path $root 'runtime\java\bin\java.exe'
    $env:SSL_CERT_FILE = Join-Path $root '.venv-pdf\Scripts\Lib\site-packages\certifi\cacert.pem'
    $env:REQUESTS_CA_BUNDLE = $env:SSL_CERT_FILE
    $env:PATH = (Join-Path $root 'runtime\java\bin') + ';' + $env:PATH
    if (-not (Test-Path -LiteralPath $python) -or -not (Test-Path -LiteralPath $java)) {
        throw 'Bundled runtime missing'
    }
    $ErrorActionPreference = 'Continue'
    & $python -X utf8 (Join-Path $root 'scripts\windows_trial_check.py') --data $data *> $log
    $checkExit = $LASTEXITCODE
    $ErrorActionPreference = 'Stop'
    if ($checkExit -ne 0) { throw 'PDF runtime check failed' }
    $arguments = @('-Dfile.encoding=UTF-8', '-Dstdout.encoding=UTF-8', '-Dstderr.encoding=UTF-8',
        "-Dsynesis.appRoot=$root", "-Dsynesis.dataRoot=$data", "-Dsynesis.credentialsFile=$env:SYNESIS_CREDENTIALS_FILE",
        '-cp', (Join-Path $root 'lib\*'), 'dev.synesis.poc.pdf.WindowsPdfTrial')
    if ($CheckOnly) {
        $arguments += @('--check', (Join-Path $logs 'offline-check.pdf'))
    }
    $ErrorActionPreference = 'Continue'
    & $java @arguments *>> $log
    $appExit = $LASTEXITCODE
    $ErrorActionPreference = 'Stop'
    if ($appExit -ne 0) { throw 'Java process failed' }
    if ($CheckOnly) {
        [System.Windows.MessageBox]::Show("실행 환경 검사를 통과했어요. AI 유료 요청은 보내지 않았어요.`nSYNESIS-START.cmd를 실행해 주세요.", 'SYNESIS') | Out-Null
    }
} catch {
    $message = "시작하지 못했어요. ZIP 파일을 모두 풀었는지 확인해 주세요.`nWindows 10/11 64비트 Intel/AMD PC용 시험판이에요."
    if ($log) { $message += "`n`n검사 기록: $log" }
    [System.Windows.MessageBox]::Show($message, 'SYNESIS 실행 확인') | Out-Null
    exit 1
} finally {
    if ($owned) { $mutex.ReleaseMutex() }
    $mutex.Dispose()
}
