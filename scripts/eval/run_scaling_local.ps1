<#
.SYNOPSIS
    Runs one scaling configuration end to end: replay producer -> N Tier-1
    processors -> analysis. Follows the protocol in thesis/THESIS_STATE.md §12.

.DESCRIPTION
    Everything an experiment touches is separate from the live system:
      * Kafka topic   perf_<run id>          (never universal_stream)
      * ES index      perf_<run id>          (never real_time_analysis)
      * processor log reports/scaling/<run>/ (never data/stream_log.csv)
    Each processor writes its timing row as soon as a message is finished, and
    each repeat has its own folder, so stopping the script never loses earlier
    results and never overwrites them.

.EXAMPLE
    # short chain test, about two minutes
    .\scripts\eval\run_scaling_local.ps1 -Partitions 2 -Processors 2 -N 2000

.EXAMPLE
    # a full protocol cell: three repeats of 10,000 messages
    .\scripts\eval\run_scaling_local.ps1 -Partitions 4 -Processors 4 -N 10000 -Repeats 3

.EXAMPLE
    # see the exact commands without running anything
    .\scripts\eval\run_scaling_local.ps1 -Partitions 2 -Processors 2 -N 100 -DryRun
#>
[CmdletBinding()]
param(
    [int]$Partitions = 1,
    [int]$Processors = 1,
    [int]$N = 10000,
    [int]$Repeats = 1,
    [ValidateSet('preload', 'rate')][string]$Mode = 'preload',
    [double]$Rate = 0,
    [int]$Threads = 1,
    [string]$Brokers = '',
    [string]$Python = 'python',
    [int]$TimeoutSec = 0,
    [switch]$Resources,
    [switch]$DryRun
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)

# Use the project venv unless a python was given explicitly: a shell without the
# venv active would otherwise start processors that cannot import torch.
$venvPython = Join-Path $root 'Hate_speach_env\Scripts\python.exe'
if (-not $PSBoundParameters.ContainsKey('Python') -and (Test-Path $venvPython)) { $Python = $venvPython }
Write-Host "Python: $Python"

# Preflight: fail in seconds rather than after a long run with nothing processed.
& $Python -c "import torch, transformers, kafka, elasticsearch" 2>$null
if ($LASTEXITCODE -ne 0) {
    throw "$Python cannot import torch/transformers/kafka/elasticsearch. Activate the venv, or pass -Python '$venvPython'."
}
if ($TimeoutSec -le 0) { $TimeoutSec = [int][math]::Max(300, $N / 2) }
if ($Processors -gt $Partitions) {
    Write-Warning "$Processors processors but only $Partitions partition(s): the extra consumers will sit idle."
}
if ($Mode -eq 'rate' -and $Rate -le 0) { throw "rate mode needs -Rate greater than 0" }

foreach ($rep in 1..$Repeats) {
    $stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
    $runId = "{0}_p{1}_c{2}_r{3}" -f $stamp, $Partitions, $Processors, $rep
    $topic = "perf_$($runId.ToLower())"
    $index = "perf_$($runId.ToLower())"
    $runDir = Join-Path $root "reports\scaling\$runId"
    $group = "grp_$runId"

    Write-Host ""
    Write-Host ("=" * 78)
    Write-Host "RUN $rep/$Repeats  $runId" -ForegroundColor Cyan
    Write-Host "  partitions=$Partitions processors=$Processors messages=$N mode=$Mode threads=$Threads"
    Write-Host "  topic=$topic  index=$index"
    Write-Host ("=" * 78)

    # ---- 1. producer -------------------------------------------------------
    $prodArgs = @("scripts/eval/replay_producer.py", "--topic", $topic, "--partitions", $Partitions,
                  "--n", $N, "--mode", $Mode, "--run-id", $runId)
    if ($Mode -eq 'rate') { $prodArgs += @("--rate", $Rate) }
    if ($Brokers)         { $prodArgs += @("--brokers", $Brokers) }

    if ($DryRun) {
        Write-Host "[dry run] $Python $($prodArgs -join ' ')" -ForegroundColor DarkGray
    } else {
        & $Python @prodArgs
        if ($LASTEXITCODE -ne 0) { throw "producer failed (exit $LASTEXITCODE)" }
    }

    if (-not $DryRun -and -not (Test-Path $runDir)) { throw "run folder missing: $runDir" }

    # ---- 2. processors -----------------------------------------------------
    $procs = @()
    $sampler = $null
    $saved = @{
        KAFKA_TOPICS = $env:KAFKA_TOPICS; PROCESSOR_GROUP_ID = $env:PROCESSOR_GROUP_ID
        BENCH_LOG = $env:BENCH_LOG; PROCESSOR_LOG_FILE = $env:PROCESSOR_LOG_FILE
        INDEX_NAME = $env:INDEX_NAME; NODE_NAME = $env:NODE_NAME
        OMP_NUM_THREADS = $env:OMP_NUM_THREADS; MKL_NUM_THREADS = $env:MKL_NUM_THREADS
        KAFKA_BROKERS = $env:KAFKA_BROKERS
        PYTHONIOENCODING = $env:PYTHONIOENCODING; PYTHONUNBUFFERED = $env:PYTHONUNBUFFERED
    }
    # emoji-safe, unbuffered logs for the redirected child processes
    $env:PYTHONIOENCODING = "utf-8"
    $env:PYTHONUNBUFFERED = "1"

    try {
        foreach ($i in 1..$Processors) {
            $env:KAFKA_TOPICS       = $topic
            $env:PROCESSOR_GROUP_ID = $group
            $env:BENCH_LOG          = Join-Path $runDir ("bench_{0}_{1}.csv" -f $env:COMPUTERNAME, $i)
            $env:PROCESSOR_LOG_FILE = Join-Path $runDir "stream_log_bench.csv"
            $env:INDEX_NAME         = $index
            $env:NODE_NAME          = $env:COMPUTERNAME
            $env:OMP_NUM_THREADS    = "$Threads"
            $env:MKL_NUM_THREADS    = "$Threads"
            if ($Brokers) { $env:KAFKA_BROKERS = $Brokers }

            $outLog = Join-Path $runDir "proc_$i.out.log"
            $errLog = Join-Path $runDir "proc_$i.err.log"
            if ($DryRun) {
                Write-Host "[dry run] processor $i : BENCH_LOG=$($env:BENCH_LOG) INDEX_NAME=$index GROUP=$group THREADS=$Threads" -ForegroundColor DarkGray
                continue
            }
            $procs += Start-Process -FilePath $Python -ArgumentList "src/static_classifier/distilbert_processor.py" `
                        -WorkingDirectory $root -PassThru -WindowStyle Hidden `
                        -RedirectStandardOutput $outLog -RedirectStandardError $errLog
            Write-Host "  started processor $i (pid $($procs[-1].Id))"
        }

        if ($Resources -and -not $DryRun) {
            $resOut = Join-Path $runDir ("resource_{0}.csv" -f $env:COMPUTERNAME)
            $sampler = Start-Process -FilePath $Python -WorkingDirectory $root -PassThru -WindowStyle Hidden `
                        -ArgumentList "scripts/eval/resource_snapshot.py", "--seconds", $TimeoutSec, "--interval", "2", "--out", $resOut `
                        -RedirectStandardOutput (Join-Path $runDir "resource.out.log") `
                        -RedirectStandardError  (Join-Path $runDir "resource.err.log")
            Write-Host "  started resource sampler -> $resOut"
        }

        if ($DryRun) {
            Write-Host "[dry run] would wait for $N messages (timeout ${TimeoutSec}s), then stop the processors" -ForegroundColor DarkGray
            Write-Host "[dry run] $Python scripts/eval/analyze_scaling.py --run $runId" -ForegroundColor DarkGray
            continue
        }

        # ---- 3. wait for the workload to drain -----------------------------
        $deadline = (Get-Date).AddSeconds($TimeoutSec)
        $done = 0; $last = -1; $stallSince = Get-Date
        while ((Get-Date) -lt $deadline) {
            Start-Sleep -Seconds 5
            $done = 0
            Get-ChildItem -Path $runDir -Filter "bench_*.csv" -ErrorAction SilentlyContinue | ForEach-Object {
                $lines = (Get-Content $_.FullName -ErrorAction SilentlyContinue | Measure-Object -Line).Lines
                if ($lines -gt 0) { $done += ($lines - 1) }
            }
            foreach ($p in $procs) { try { $p.Refresh() } catch { } }
            $alive = @($procs | Where-Object { -not $_.HasExited }).Count
            Write-Host ("  processed {0}/{1}  ({2} processor(s) alive)" -f $done, $N, $alive)
            if ($done -ge $N) { break }
            if ($alive -eq 0) {
                Write-Warning "all processors exited early. Last error lines:"
                Get-ChildItem -Path $runDir -Filter "proc_*.err.log" | ForEach-Object {
                    $tail = (Get-Content $_.FullName -Tail 3 -ErrorAction SilentlyContinue) -join ' '
                    Write-Host ("   {0}: {1}" -f $_.Name, $tail.Substring(0, [Math]::Min(300, $tail.Length)))
                }
                break
            }
            if ($done -ne $last) { $last = $done; $stallSince = Get-Date }
            elseif ($done -eq 0) {
                # still loading the model (several processes share the CPU); allow 10 minutes
                if (((Get-Date) - $stallSince).TotalSeconds -ge 600) {
                    Write-Warning "no message processed within 600s - stopping this run"; break
                }
            }
            elseif (((Get-Date) - $stallSince).TotalSeconds -ge 300) {
                Write-Warning "no progress for 300s - stopping this run"; break
            }
        }
        if ($done -lt $N) { Write-Warning "finished with $done of $N messages (timeout or stall). The analysis will report the gap." }
    }
    finally {
        # ---- 4. always stop what we started and restore the shell ----------
        foreach ($p in $procs) {
            if ($p -and -not $p.HasExited) { Stop-Process -Id $p.Id -Force -ErrorAction SilentlyContinue }
        }
        if ($sampler -and -not $sampler.HasExited) { Stop-Process -Id $sampler.Id -Force -ErrorAction SilentlyContinue }
        foreach ($k in $saved.Keys) {
            if ($null -eq $saved[$k]) { Remove-Item "Env:$k" -ErrorAction SilentlyContinue }
            else { Set-Item "Env:$k" $saved[$k] }
        }
    }

    # ---- 5. analysis -------------------------------------------------------
    Start-Sleep -Seconds 2
    & $Python "scripts/eval/analyze_scaling.py" "--run" $runId
}

Write-Host ""
Write-Host "All runs finished. Results are in reports\scaling\ (metrics.json + summary.txt per run)." -ForegroundColor Green
