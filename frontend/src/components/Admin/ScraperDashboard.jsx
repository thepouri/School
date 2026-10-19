import { useState, useEffect } from 'react';
import {
  Activity,
  AlertCircle,
  Calendar,
  Check,
  CheckCircle2,
  Clock,
  Copy,
  Database,
  Download,
  Pause,
  RefreshCw,
  Search,
  Settings,
  Square,
  Terminal,
  Upload,
  UserCheck,
  Users,
  X,
  XCircle,
} from 'lucide-react';
import {
  useScraperStatus,
  useTriggerJob,
  useScraperLogs,
  useScraperSettings,
  useUpdateScraperSettings,
  useCancelJob,
  useImportScraperData,
  downloadScraperExport,
} from '../../api/scraperApi.js';

function formatTimestamp(isoStr) {
  if (!isoStr) return '—';
  try {
    const d = new Date(isoStr);
    if (isNaN(d.getTime())) return isoStr;
    return d.toLocaleString('en-US', {
      month: 'short',
      day: 'numeric',
      year: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
      hour12: false,
    });
  } catch {
    return isoStr;
  }
}

function formatRelative(isoStr) {
  if (!isoStr) return 'Never';
  try {
    const d = new Date(isoStr);
    const diffMs = Date.now() - d.getTime();
    const diffSec = Math.round(diffMs / 1000);
    if (diffSec < 0) {
      // Future
      const absSec = Math.abs(diffSec);
      if (absSec < 60) return `in ${absSec}s`;
      const absMin = Math.round(absSec / 60);
      if (absMin < 60) return `in ${absMin}m`;
      const absHours = Math.round(absMin / 60);
      if (absHours < 24) return `in ${absHours}h`;
      const absDays = Math.round(absHours / 24);
      return `in ${absDays}d`;
    }
    if (diffSec < 60) return `${diffSec}s ago`;
    const diffMin = Math.round(diffSec / 60);
    if (diffMin < 60) return `${diffMin}m ago`;
    const diffHours = Math.round(diffMin / 60);
    if (diffHours < 24) return `${diffHours}h ago`;
    const diffDays = Math.round(diffHours / 24);
    return `${diffDays}d ago`;
  } catch {
    return isoStr;
  }
}

function formatDuration(startedAt, finishedAt) {
  if (!startedAt) return '—';
  try {
    const start = new Date(startedAt).getTime();
    const end = finishedAt ? new Date(finishedAt).getTime() : Date.now();
    const diffSec = Math.max(0, Math.round((end - start) / 1000));
    if (diffSec < 60) return `${diffSec}s`;
    const mins = Math.floor(diffSec / 60);
    const secs = diffSec % 60;
    return `${mins}m ${secs}s`;
  } catch {
    return '—';
  }
}

function getStatusBadge(status) {
  switch (status?.toUpperCase()) {
    case 'SUCCESS':
      return {
        label: 'SUCCESS',
        bg: 'bg-emerald-50 text-emerald-700 border-emerald-200',
        dot: 'bg-emerald-500',
      };
    case 'RUNNING':
      return {
        label: 'RUNNING',
        bg: 'bg-blue-50 text-blue-700 border-blue-200',
        dot: 'bg-blue-500 animate-ping',
      };
    case 'FAILED':
      return {
        label: 'FAILED',
        bg: 'bg-red-50 text-red-700 border-red-200',
        dot: 'bg-red-500',
      };
    case 'PENDING':
      return {
        label: 'PENDING',
        bg: 'bg-amber-50 text-amber-700 border-amber-200',
        dot: 'bg-amber-500',
      };
    default:
      return {
        label: status || 'UNKNOWN',
        bg: 'bg-stone-50 text-stone-600 border-stone-200',
        dot: 'bg-stone-400',
      };
  }
}

export default function ScraperDashboard() {
  const { data: status, isLoading: statusLoading, error: statusError } = useScraperStatus();
  const { data: logsData, isLoading: logsLoading, error: logsError } = useScraperLogs(50);
  const { data: settingsData, isLoading: settingsLoading } = useScraperSettings();
  const triggerJob = useTriggerJob();
  const updateSettings = useUpdateScraperSettings();

  // Settings form draft state
  const [refreshDays, setRefreshDays] = useState(3);
  const [discoveryDays, setDiscoveryDays] = useState(7);
  const [isPaused, setIsPaused] = useState(false);
  const [settingsFeedback, setSettingsFeedback] = useState(null);

  // Sync loaded settings to draft form state
  useEffect(() => {
    if (settingsData) {
      if (settingsData.refresh_interval_days != null) {
        setRefreshDays(settingsData.refresh_interval_days);
      }
      if (settingsData.discovery_interval_days != null) {
        setDiscoveryDays(settingsData.discovery_interval_days);
      }
      if (settingsData.is_paused != null) {
        setIsPaused(Boolean(settingsData.is_paused));
      }
    }
  }, [settingsData]);

  // Trigger action state
  const [triggerBanner, setTriggerBanner] = useState(null);
  const [activeTriggerMode, setActiveTriggerMode] = useState(null);

  // Modal / drawer terminal console state
  const [selectedJob, setSelectedJob] = useState(null);
  const [copiedLogs, setCopiedLogs] = useState(false);
  const [logFilter, setLogFilter] = useState('all'); // 'all' | 'errors'

  const handleTrigger = (mode) => {
    setActiveTriggerMode(mode);
    setTriggerBanner(null);
    triggerJob.mutate(
      { mode },
      {
        onSuccess: (data) => {
          setActiveTriggerMode(null);
          setTriggerBanner({
            type: 'success',
            message: `Scraper job #${data.job_id} (${mode}) queued successfully! The scheduler will execute it shortly.`,
          });
        },
        onError: (err) => {
          setActiveTriggerMode(null);
          setTriggerBanner({
            type: 'error',
            message: `Failed to queue ${mode} job: ${err.message}`,
          });
        },
      },
    );
  };

  const handleSaveSettings = (e) => {
    e.preventDefault();
    setSettingsFeedback(null);
    updateSettings.mutate(
      {
        refresh_interval_days: Number(refreshDays),
        discovery_interval_days: Number(discoveryDays),
        is_paused: Boolean(isPaused),
      },
      {
        onSuccess: () => {
          setSettingsFeedback({
            type: 'success',
            message: 'Schedule intervals and parameters updated successfully.',
          });
          setTimeout(() => setSettingsFeedback(null), 4000);
        },
        onError: (err) => {
          setSettingsFeedback({
            type: 'error',
            message: `Failed to save settings: ${err.message}`,
          });
        },
      },
    );
  };

  const cancelJob = useCancelJob();
  const importDataMutation = useImportScraperData();

  // Export / Import state
  const [isExporting, setIsExporting] = useState(false);
  const [exportWithMetrics, setExportWithMetrics] = useState(true);
  const [exportError, setExportError] = useState(null);
  const [selectedFile, setSelectedFile] = useState(null);
  const [importStatus, setImportStatus] = useState(null);
  const [isImporting, setIsImporting] = useState(false);

  const handleCancelJob = (jobId) => {
    if (!jobId) return;
    if (!window.confirm(`Are you sure you want to stop/cancel Job #${jobId}?`)) return;
    cancelJob.mutate(jobId, {
      onSuccess: () => {
        setTriggerBanner({
          type: 'success',
          message: `Job #${jobId} cancellation requested successfully.`,
        });
        if (selectedJob && selectedJob.id === jobId) {
          setSelectedJob((prev) => ({ ...prev, status: 'CANCELLED' }));
        }
      },
      onError: (err) => {
        setTriggerBanner({
          type: 'error',
          message: `Failed to cancel Job #${jobId}: ${err.message || 'Unknown error'}`,
        });
      },
    });
  };

  const handleExport = async () => {
    setIsExporting(true);
    setExportError(null);
    try {
      await downloadScraperExport(exportWithMetrics);
    } catch (err) {
      setExportError(err.message || 'Export failed');
    } finally {
      setIsExporting(false);
    }
  };

  const handleImport = async () => {
    if (!selectedFile) return;
    setIsImporting(true);
    setImportStatus(null);
    try {
      const text = await selectedFile.text();
      const json = JSON.parse(text);
      const res = await importDataMutation.mutateAsync(json);
      const counts = res.imported || {};
      setImportStatus({
        type: 'success',
        message: `Import successful! Imported ${counts.groups || 0} groups, ${counts.users || 0} users, ${counts.user_groups || 0} user relationships, ${counts.group_metrics || 0} metric snapshots.`,
      });
      setSelectedFile(null);
    } catch (err) {
      setImportStatus({
        type: 'error',
        message: `Import failed: ${err.message || 'Invalid JSON format'}`,
      });
    } finally {
      setIsImporting(false);
    }
  };


  const handleCopyLogs = (lines) => {
    if (!lines) return;
    const text = lines.map((l) => `[${l.created_at || ''}] [${l.level || 'INFO'}] ${l.message || ''}`).join('\n');
    navigator.clipboard?.writeText(text);
    setCopiedLogs(true);
    setTimeout(() => setCopiedLogs(false), 1500);
  };

  // Derive daemon metrics
  const daemon = status?.daemon;
  const isDaemonRunning = daemon?.status === 'RUNNING';
  const schedules = status?.schedules;
  const stats = status?.stats;
  const activeJob = status?.active_job;

  const pastJobs = logsData?.items || [];

  return (
    <div className="space-y-6">
      {/* 0. ERROR BANNER (when daemon status query fails) */}
      {statusError && (
        <div
          role="alert"
          className="flex items-start justify-between rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-800 shadow-sm"
        >
          <div className="flex items-center gap-2">
            <AlertCircle size={18} className="shrink-0 text-red-600" />
            <span>
              <strong>Failed to fetch scraper daemon status:</strong>{' '}
              {statusError.message || 'API connection failure'}
            </span>
          </div>
        </div>
      )}

      {/* 1. TOP LIVE STATUS CARDS */}
      <section>
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-5">
          {/* Card 1: Daemon Health */}
          <div className="flex flex-col justify-between rounded-2xl border border-stone-200 bg-white p-4 shadow-sm transition-all hover:shadow-md">
            <div className="flex items-center justify-between">
              <span className="text-xs font-semibold uppercase tracking-wider text-stone-500">
                Daemon Health
              </span>
              <div className="flex h-8 w-8 items-center justify-center rounded-xl bg-stone-100 text-stone-700">
                <Activity size={17} />
              </div>
            </div>
            <div className="mt-3">
              {statusLoading && !status ? (
                <div className="space-y-2 animate-pulse py-1">
                  <div className="h-6 w-24 rounded bg-stone-200" />
                  <div className="h-3 w-32 rounded bg-stone-100" />
                </div>
              ) : statusError && !status ? (
                <div>
                  <div className="flex items-center gap-2">
                    <span className="inline-flex h-3 w-3 rounded-full bg-stone-300" />
                    <span className="text-lg font-bold text-stone-500">Unavailable</span>
                  </div>
                  <p className="mt-1 text-xs text-stone-400">Heartbeat: —</p>
                </div>
              ) : (
                <>
                  <div className="flex items-center gap-2">
                    <span className="relative flex h-3 w-3">
                      {isDaemonRunning && (
                        <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-emerald-400 opacity-75" />
                      )}
                      <span
                        className={`relative inline-flex h-3 w-3 rounded-full ${
                          isDaemonRunning ? 'bg-emerald-500' : 'bg-red-500'
                        }`}
                      />
                    </span>
                    <span className="text-lg font-bold text-stone-900">
                      {isDaemonRunning ? 'RUNNING' : 'STOPPED'}
                    </span>
                    {daemon?.is_paused && (
                      <span className="rounded-md bg-amber-100 px-1.5 py-0.5 text-[10px] font-bold uppercase text-amber-800">
                        Paused
                      </span>
                    )}
                  </div>
                  <p className="mt-1 text-xs text-stone-500">
                    Heartbeat: <span className="font-medium text-stone-700">{formatRelative(daemon?.last_heartbeat)}</span>
                  </p>
                </>
              )}
            </div>
          </div>

          {/* Card 2: Last Refresh & Next Scheduled Run */}
          <div className="flex flex-col justify-between rounded-2xl border border-stone-200 bg-white p-4 shadow-sm transition-all hover:shadow-md">
            <div className="flex items-center justify-between">
              <span className="text-xs font-semibold uppercase tracking-wider text-stone-500">
                Metrics Refresh
              </span>
              <div className="flex h-8 w-8 items-center justify-center rounded-xl bg-blue-50 text-blue-600">
                <RefreshCw size={17} />
              </div>
            </div>
            <div className="mt-3">
              {statusLoading && !status ? (
                <div className="space-y-2 animate-pulse py-1">
                  <div className="h-3 w-28 rounded bg-stone-200" />
                  <div className="h-3 w-28 rounded bg-stone-100" />
                  <div className="h-2 w-20 rounded bg-stone-100" />
                </div>
              ) : statusError && !status ? (
                <div>
                  <div className="text-xs text-stone-400">
                    Last: <span className="font-medium text-stone-500">—</span>
                  </div>
                  <div className="mt-1 text-xs text-stone-400">
                    Next: <span className="font-medium text-stone-500">—</span>
                  </div>
                  <div className="mt-2 text-[11px] text-stone-400">Interval: —</div>
                </div>
              ) : (
                <>
                  <div className="text-xs text-stone-500">
                    Last:{' '}
                    <span className="font-semibold text-stone-800">
                      {formatRelative(schedules?.refresh?.last_run)}
                    </span>
                  </div>
                  <div className="mt-1 text-xs text-stone-500">
                    Next:{' '}
                    <span className="font-semibold text-brand-600">
                      {formatRelative(schedules?.refresh?.next_run)}
                    </span>
                  </div>
                  <div className="mt-2 text-[11px] text-stone-400">
                    Interval: every {schedules?.refresh?.interval_days ?? 3}d
                  </div>
                </>
              )}
            </div>
          </div>

          {/* Card 3: Last Discovery & Next Scheduled Run */}
          <div className="flex flex-col justify-between rounded-2xl border border-stone-200 bg-white p-4 shadow-sm transition-all hover:shadow-md">
            <div className="flex items-center justify-between">
              <span className="text-xs font-semibold uppercase tracking-wider text-stone-500">
                Deep Discovery
              </span>
              <div className="flex h-8 w-8 items-center justify-center rounded-xl bg-purple-50 text-purple-600">
                <Search size={17} />
              </div>
            </div>
            <div className="mt-3">
              {statusLoading && !status ? (
                <div className="space-y-2 animate-pulse py-1">
                  <div className="h-3 w-28 rounded bg-stone-200" />
                  <div className="h-3 w-28 rounded bg-stone-100" />
                  <div className="h-2 w-20 rounded bg-stone-100" />
                </div>
              ) : statusError && !status ? (
                <div>
                  <div className="text-xs text-stone-400">
                    Last: <span className="font-medium text-stone-500">—</span>
                  </div>
                  <div className="mt-1 text-xs text-stone-400">
                    Next: <span className="font-medium text-stone-500">—</span>
                  </div>
                  <div className="mt-2 text-[11px] text-stone-400">Interval: —</div>
                </div>
              ) : (
                <>
                  <div className="text-xs text-stone-500">
                    Last:{' '}
                    <span className="font-semibold text-stone-800">
                      {formatRelative(schedules?.discovery?.last_run)}
                    </span>
                  </div>
                  <div className="mt-1 text-xs text-stone-500">
                    Next:{' '}
                    <span className="font-semibold text-purple-600">
                      {formatRelative(schedules?.discovery?.next_run)}
                    </span>
                  </div>
                  <div className="mt-2 text-[11px] text-stone-400">
                    Interval: every {schedules?.discovery?.interval_days ?? 7}d
                  </div>
                </>
              )}
            </div>
          </div>

          {/* Card 4: Total Groups Indexed */}
          <div className="flex flex-col justify-between rounded-2xl border border-stone-200 bg-white p-4 shadow-sm transition-all hover:shadow-md">
            <div className="flex items-center justify-between">
              <span className="text-xs font-semibold uppercase tracking-wider text-stone-500">
                Total Groups
              </span>
              <div className="flex h-8 w-8 items-center justify-center rounded-xl bg-emerald-50 text-emerald-600">
                <Database size={17} />
              </div>
            </div>
            <div className="mt-3">
              {statusLoading && !status ? (
                <div className="space-y-2 animate-pulse py-1">
                  <div className="h-8 w-24 rounded bg-stone-200" />
                  <div className="h-3 w-36 rounded bg-stone-100" />
                </div>
              ) : statusError && !status ? (
                <div>
                  <div className="text-2xl font-bold text-stone-400">—</div>
                  <p className="mt-1 text-xs text-stone-400">Data unavailable</p>
                </div>
              ) : (
                <>
                  <div className="text-2xl font-bold tabular-nums text-stone-900">
                    {(stats?.total_groups ?? 0).toLocaleString('en-US')}
                  </div>
                  <p className="mt-1 text-xs text-stone-500">Indexed in catalog database</p>
                </>
              )}
            </div>
          </div>

          {/* Card 5: Scraper Backlog */}
          <div className="flex flex-col justify-between rounded-2xl border border-stone-200 bg-white p-4 shadow-sm transition-all hover:shadow-md">
            <div className="flex items-center justify-between">
              <span className="text-xs font-semibold uppercase tracking-wider text-stone-500">
                Scraper Backlog
              </span>
              <div className="flex h-8 w-8 items-center justify-center rounded-xl bg-amber-50 text-amber-600">
                <AlertCircle size={17} />
              </div>
            </div>
            <div className="mt-3 space-y-1">
              {statusLoading && !status ? (
                <div className="space-y-2 animate-pulse py-1">
                  <div className="h-3 w-full rounded bg-stone-200" />
                  <div className="h-3 w-full rounded bg-stone-100" />
                  <div className="h-2 w-32 rounded bg-stone-100" />
                </div>
              ) : statusError && !status ? (
                <div>
                  <div className="text-xs text-stone-400">
                    Pending Details: <span className="font-medium text-stone-500">—</span>
                  </div>
                  <div className="mt-1 text-xs text-stone-400">
                    Pending Owners: <span className="font-medium text-stone-500">—</span>
                  </div>
                  <p className="pt-0.5 text-[11px] text-stone-400">Status check failed</p>
                </div>
              ) : (
                <>
                  <div className="flex items-center justify-between text-xs">
                    <span className="text-stone-500">Pending Details:</span>
                    <span
                      className={`font-bold tabular-nums ${
                        (stats?.pending_details ?? 0) > 0 ? 'text-amber-600' : 'text-stone-700'
                      }`}
                    >
                      {(stats?.pending_details ?? 0).toLocaleString('en-US')}
                    </span>
                  </div>
                  <div className="flex items-center justify-between text-xs">
                    <span className="text-stone-500">Pending Owners:</span>
                    <span
                      className={`font-bold tabular-nums ${
                        (stats?.pending_owners ?? 0) > 0 ? 'text-indigo-600' : 'text-stone-700'
                      }`}
                    >
                      {(stats?.pending_owners ?? 0).toLocaleString('en-US')}
                    </span>
                  </div>
                  <p className="pt-0.5 text-[11px] text-stone-400">
                    {(stats?.pending_details ?? 0) + (stats?.pending_owners ?? 0) === 0
                      ? 'Catalog queue fully synced'
                      : 'Items waiting for pipeline fetch'}
                  </p>
                </>
              )}
            </div>
          </div>
        </div>
      </section>

      {/* 2. ACTIVE JOB BANNER (when running) */}
      {activeJob && (
        <section className="relative overflow-hidden rounded-2xl border border-brand-300 bg-gradient-to-r from-brand-50 via-white to-blue-50 p-5 shadow-sm">
          <div className="flex flex-wrap items-center justify-between gap-4">
            <div className="flex items-center gap-3">
              <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-brand-500 text-white shadow-sm">
                <RefreshCw size={20} className="animate-spin" />
              </div>
              <div>
                <div className="flex items-center gap-2">
                  <span className="text-xs font-bold uppercase tracking-wider text-brand-700">
                    Active Scraper Job Running
                  </span>
                  <span className="rounded-full bg-brand-200 px-2 py-0.5 text-xs font-semibold text-brand-900">
                    Job #{activeJob.id}
                  </span>
                </div>
                <h3 className="text-base font-bold text-stone-900 capitalize">
                  Mode: {activeJob.job_type}
                </h3>
              </div>
            </div>
            <div className="flex items-center gap-4 text-xs">
              <div>
                <span className="text-stone-500">Started: </span>
                <span className="font-semibold text-stone-800">
                  {formatTimestamp(activeJob.started_at)}
                </span>
              </div>
              <div>
                <span className="text-stone-500">Elapsed: </span>
                <span className="font-semibold text-brand-700 tabular-nums">
                  {formatDuration(activeJob.started_at)}
                </span>
              </div>
              <span className="inline-flex items-center gap-1.5 rounded-full bg-emerald-100 px-3 py-1 font-semibold text-emerald-800">
                <span className="h-2 w-2 animate-ping rounded-full bg-emerald-500" />
                Executing
              </span>
              <button
                type="button"
                disabled={cancelJob.isPending}
                onClick={() => handleCancelJob(activeJob.id)}
                className="inline-flex items-center gap-1.5 rounded-lg border border-red-300 bg-red-50 px-3 py-1 text-xs font-bold text-red-700 shadow-xs hover:bg-red-100 hover:border-red-400 transition-colors disabled:opacity-50"
              >
                <Square size={13} className="fill-current text-red-600" />
                {cancelJob.isPending ? 'Stopping…' : 'Stop / Cancel Job'}
              </button>
            </div>
          </div>
        </section>
      )}

      {/* TRIGGER FEEDBACK BANNER */}
      {triggerBanner && (
        <div
          className={`flex items-start justify-between rounded-xl border p-4 text-sm ${
            triggerBanner.type === 'success'
              ? 'border-emerald-200 bg-emerald-50 text-emerald-800'
              : 'border-red-200 bg-red-50 text-red-800'
          }`}
        >
          <div className="flex items-center gap-2">
            {triggerBanner.type === 'success' ? (
              <CheckCircle2 size={18} className="shrink-0 text-emerald-600" />
            ) : (
              <XCircle size={18} className="shrink-0 text-red-600" />
            )}
            <span>{triggerBanner.message}</span>
          </div>
          <button
            type="button"
            onClick={() => setTriggerBanner(null)}
            className="text-stone-400 hover:text-stone-600"
          >
            <X size={16} />
          </button>
        </div>
      )}

      {/* 3. MANUAL CONTROL BUTTONS */}
      <section className="rounded-2xl border border-stone-200 bg-white p-5 shadow-sm">
        <div className="flex flex-wrap items-center justify-between gap-2 border-b border-stone-100 pb-4">
          <div>
            <h2 className="text-base font-bold text-stone-900">Manual Scraper Controls</h2>
            <p className="mt-0.5 text-xs text-stone-500">
              Dispatch immediate background worker jobs. Jobs run asynchronously on the harvester daemon.
            </p>
          </div>
          {activeJob && (
            <span className="rounded-lg bg-amber-50 px-2.5 py-1 text-xs font-semibold text-amber-700 border border-amber-200">
              A job is currently in progress
            </span>
          )}
        </div>

        <div className="mt-4 grid grid-cols-1 gap-3 sm:grid-cols-3">
          {/* Button 1: Trigger Refresh Now */}
          <button
            type="button"
            disabled={triggerJob.isPending || activeJob != null}
            onClick={() => handleTrigger('refresh')}
            className="flex items-center justify-between rounded-xl border border-stone-200 bg-stone-50/80 p-3.5 text-left transition-all hover:border-brand-300 hover:bg-brand-50/40 disabled:opacity-50"
          >
            <div>
              <div className="flex items-center gap-2">
                <RefreshCw
                  size={16}
                  className={`text-brand-500 ${
                    activeTriggerMode === 'refresh' && triggerJob.isPending ? 'animate-spin' : ''
                  }`}
                />
                <span className="text-sm font-bold text-stone-900">Trigger Refresh Now</span>
              </div>
              <p className="mt-1 text-xs text-stone-500">
                Re-fetch stale groups (&gt;3d) & append metrics
              </p>
            </div>
            {activeTriggerMode === 'refresh' && triggerJob.isPending && (
              <span className="text-xs font-semibold text-brand-600">Queuing…</span>
            )}
          </button>

          {/* Button 2: Trigger Deep Discovery Now */}
          <button
            type="button"
            disabled={triggerJob.isPending || activeJob != null}
            onClick={() => handleTrigger('all')}
            className="flex items-center justify-between rounded-xl border border-stone-200 bg-stone-50/80 p-3.5 text-left transition-all hover:border-purple-300 hover:bg-purple-50/40 disabled:opacity-50"
          >
            <div>
              <div className="flex items-center gap-2">
                <Search
                  size={16}
                  className={`text-purple-600 ${
                    activeTriggerMode === 'all' && triggerJob.isPending ? 'animate-spin' : ''
                  }`}
                />
                <span className="text-sm font-bold text-stone-900">Trigger Deep Discovery</span>
              </div>
              <p className="mt-1 text-xs text-stone-500">
                Crawl all categories, languages & search seeds
              </p>
            </div>
            {activeTriggerMode === 'all' && triggerJob.isPending && (
              <span className="text-xs font-semibold text-purple-600">Queuing…</span>
            )}
          </button>

          {/* Button 3: Trigger Missing Owners */}
          <button
            type="button"
            disabled={triggerJob.isPending || activeJob != null}
            onClick={() => handleTrigger('missing_owners')}
            className="flex items-center justify-between rounded-xl border border-stone-200 bg-stone-50/80 p-3.5 text-left transition-all hover:border-indigo-300 hover:bg-indigo-50/40 disabled:opacity-50"
          >
            <div>
              <div className="flex items-center gap-2">
                <UserCheck
                  size={16}
                  className={`text-indigo-600 ${
                    activeTriggerMode === 'missing_owners' && triggerJob.isPending ? 'animate-spin' : ''
                  }`}
                />
                <span className="text-sm font-bold text-stone-900">Trigger Missing Owners</span>
              </div>
              <p className="mt-1 text-xs text-stone-500">
                Recover creator and owner metadata for groups
              </p>
            </div>
            {activeTriggerMode === 'missing_owners' && triggerJob.isPending && (
              <span className="text-xs font-semibold text-indigo-600">Queuing…</span>
            )}
          </button>
        </div>
      </section>

      {/* 4. RECENT EXECUTION LOG CONSOLE & HISTORY TABLE */}
      <section className="rounded-2xl border border-stone-200 bg-white p-5 shadow-sm">
        <div className="flex flex-wrap items-center justify-between gap-3 border-b border-stone-100 pb-4">
          <div>
            <h2 className="flex items-center gap-2 text-base font-bold text-stone-900">
              <Terminal size={18} className="text-stone-700" />
              Recent Execution Logs & Job History
            </h2>
            <p className="mt-0.5 text-xs text-stone-500">
              Execution history, runtime durations, exit codes, and stdout/stderr stream outputs.
            </p>
          </div>
          <div className="flex items-center gap-2">
            <span className="text-xs text-stone-400">
              Showing last {pastJobs.length} execution records
            </span>
          </div>
        </div>

        {/* History Table */}
        <div className="mt-4 overflow-x-auto">
          <table className="w-full text-left text-sm">
            <thead>
              <tr className="border-b border-stone-200 bg-stone-50 text-xs font-semibold uppercase tracking-wider text-stone-400">
                <th className="px-4 py-3">Job ID</th>
                <th className="px-4 py-3">Type</th>
                <th className="px-4 py-3">Trigger</th>
                <th className="px-4 py-3">Status</th>
                <th className="px-4 py-3">Started</th>
                <th className="px-4 py-3">Duration</th>
                <th className="px-4 py-3">Exit Code</th>
                <th className="px-4 py-3 text-right">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-stone-100">
              {logsLoading && (
                <tr>
                  <td colSpan={8} className="px-4 py-8 text-center text-stone-400">
                    Loading job execution history…
                  </td>
                </tr>
              )}
              {!logsLoading && logsError && (
                <tr>
                  <td colSpan={8} className="px-4 py-8 text-center text-red-500">
                    Failed to load logs: {logsError.message}
                  </td>
                </tr>
              )}
              {!logsLoading && !logsError && pastJobs.length === 0 && (
                <tr>
                  <td colSpan={8} className="px-4 py-8 text-center text-stone-400">
                    No scraper execution jobs recorded yet.
                  </td>
                </tr>
              )}
              {pastJobs.map((job) => {
                const badge = getStatusBadge(job.status);
                const hasError = Boolean(job.error_message) || (job.exit_code != null && job.exit_code !== 0);

                return (
                  <tr key={job.id} className="hover:bg-stone-50/60 transition-colors">
                    <td className="px-4 py-3 font-mono text-xs font-bold text-stone-800">
                      #{job.id}
                    </td>
                    <td className="px-4 py-3">
                      <span className="inline-flex items-center rounded-md bg-stone-100 px-2 py-0.5 text-xs font-semibold text-stone-800 capitalize">
                        {job.job_type}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-xs text-stone-500 capitalize">
                      {job.trigger_type || 'manual'}
                    </td>
                    <td className="px-4 py-3">
                      <span
                        className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-xs font-semibold ${badge.bg}`}
                      >
                        <span className={`h-1.5 w-1.5 rounded-full ${badge.dot}`} />
                        {badge.label}
                      </span>
                    </td>
                    <td className="whitespace-nowrap px-4 py-3 text-xs text-stone-600">
                      {formatTimestamp(job.started_at)}
                    </td>
                    <td className="whitespace-nowrap px-4 py-3 font-mono text-xs text-stone-600">
                      {formatDuration(job.started_at, job.finished_at)}
                    </td>
                    <td className="px-4 py-3 font-mono text-xs">
                      {job.exit_code != null ? (
                        <span
                          className={`font-semibold ${
                            job.exit_code === 0 ? 'text-emerald-600' : 'text-red-600'
                          }`}
                        >
                          {job.exit_code}
                        </span>
                      ) : (
                        <span className="text-stone-400">—</span>
                      )}
                    </td>
                    <td className="px-4 py-3 text-right">
                      <div className="flex items-center justify-end gap-1.5">
                        {(job.status === 'RUNNING' || job.status === 'PENDING') && (
                          <button
                            type="button"
                            disabled={cancelJob.isPending}
                            onClick={() => handleCancelJob(job.id)}
                            className="inline-flex items-center gap-1 rounded-lg border border-red-200 bg-red-50 px-2.5 py-1 text-xs font-semibold text-red-700 shadow-xs transition-colors hover:bg-red-100 disabled:opacity-50"
                            title="Cancel job execution"
                          >
                            <Square size={12} className="fill-current text-red-600" />
                            Stop
                          </button>
                        )}
                        <button
                          type="button"
                          onClick={() => setSelectedJob(job)}
                          className="inline-flex items-center gap-1 rounded-lg border border-stone-200 bg-white px-2.5 py-1 text-xs font-semibold text-stone-700 shadow-sm transition-colors hover:border-stone-300 hover:bg-stone-50"
                        >
                          <Terminal size={13} />
                          View Output
                        </button>
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </section>

      {/* 5. DATA EXPORT & IMPORT */}
      <section className="rounded-2xl border border-stone-200 bg-white p-5 shadow-sm">
        <div className="border-b border-stone-100 pb-4">
          <h2 className="flex items-center gap-2 text-base font-bold text-stone-900">
            <Database size={18} className="text-brand-600" />
            Catalog Data Export & Import
          </h2>
          <p className="mt-0.5 text-xs text-stone-500">
            Export or import the complete catalog database (groups, users, relationships, and metrics history) safely and idempotently.
          </p>
        </div>

        <div className="mt-5 grid grid-cols-1 gap-6 lg:grid-cols-2">
          {/* Card 1: Export */}
          <div className="flex flex-col justify-between rounded-xl border border-stone-200 bg-stone-50/50 p-4">
            <div>
              <div className="flex items-center gap-2">
                <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-brand-50 text-brand-600">
                  <Download size={16} />
                </div>
                <div>
                  <h3 className="text-sm font-bold text-stone-900">Export Scraped Dataset</h3>
                  <p className="text-xs text-stone-500">Download catalog snapshot as a structured JSON file</p>
                </div>
              </div>

              <div className="mt-4 space-y-3">
                <label className="flex items-center gap-2.5 text-xs text-stone-700 cursor-pointer">
                  <input
                    type="checkbox"
                    checked={exportWithMetrics}
                    onChange={(e) => setExportWithMetrics(e.target.checked)}
                    className="h-4 w-4 rounded border-stone-300 text-brand-600 focus:ring-brand-500"
                  />
                  <span>Include time-series metrics history (growth snapshots)</span>
                </label>

                {exportError && (
                  <p className="rounded-lg bg-red-50 p-2 text-xs text-red-600 border border-red-200">
                    {exportError}
                  </p>
                )}
              </div>
            </div>

            <div className="mt-5">
              <button
                type="button"
                disabled={isExporting}
                onClick={handleExport}
                className="inline-flex items-center gap-2 rounded-lg bg-brand-500 px-4 py-2 text-xs font-semibold text-white shadow-sm transition-colors hover:bg-brand-600 disabled:opacity-60"
              >
                <Download size={14} className={isExporting ? 'animate-bounce' : ''} />
                {isExporting ? 'Generating Export…' : 'Export Data (JSON)'}
              </button>
            </div>
          </div>

          {/* Card 2: Import */}
          <div className="flex flex-col justify-between rounded-xl border border-stone-200 bg-stone-50/50 p-4">
            <div>
              <div className="flex items-center gap-2">
                <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-purple-50 text-purple-600">
                  <Upload size={16} />
                </div>
                <div>
                  <h3 className="text-sm font-bold text-stone-900">Import Scraped Dataset</h3>
                  <p className="text-xs text-stone-500">Restore or sync data from an exported JSON file</p>
                </div>
              </div>

              <div className="mt-4 space-y-3">
                <div className="flex items-center gap-3">
                  <input
                    type="file"
                    accept=".json,application/json"
                    id="scraper-import-input"
                    className="hidden"
                    onChange={(e) => {
                      if (e.target.files && e.target.files[0]) {
                        setSelectedFile(e.target.files[0]);
                        setImportStatus(null);
                      }
                    }}
                  />
                  <label
                    htmlFor="scraper-import-input"
                    className="inline-flex cursor-pointer items-center gap-1.5 rounded-lg border border-stone-300 bg-white px-3 py-1.5 text-xs font-medium text-stone-700 shadow-xs hover:bg-stone-50"
                  >
                    <Upload size={13} />
                    Choose File…
                  </label>
                  <span className="text-xs text-stone-500 truncate max-w-[220px]">
                    {selectedFile ? selectedFile.name : 'No file chosen (.json)'}
                  </span>
                </div>

                <p className="text-[11px] text-stone-400">
                  <strong>Safe & Idempotent:</strong> Existing records will be updated without duplicates or collision errors. Missing user references are healed automatically.
                </p>

                {importStatus && (
                  <div
                    className={`rounded-lg p-2.5 text-xs border ${
                      importStatus.type === 'success'
                        ? 'bg-emerald-50 text-emerald-800 border-emerald-200'
                        : 'bg-red-50 text-red-800 border-red-200'
                    }`}
                  >
                    {importStatus.message}
                  </div>
                )}
              </div>
            </div>

            <div className="mt-5">
              <button
                type="button"
                disabled={!selectedFile || isImporting}
                onClick={handleImport}
                className="inline-flex items-center gap-2 rounded-lg bg-purple-600 px-4 py-2 text-xs font-semibold text-white shadow-sm transition-colors hover:bg-purple-700 disabled:opacity-50"
              >
                <Upload size={14} className={isImporting ? 'animate-spin' : ''} />
                {isImporting ? 'Importing Dataset…' : 'Import Data'}
              </button>
            </div>
          </div>
        </div>
      </section>

      {/* 6. SCHEDULE SETTINGS */}
      <section className="rounded-2xl border border-stone-200 bg-white p-5 shadow-sm">
        <div className="flex flex-wrap items-center justify-between gap-2 border-b border-stone-100 pb-4">
          <div>
            <h2 className="flex items-center gap-2 text-base font-bold text-stone-900">
              <Settings size={18} className="text-stone-700" />
              Scraper Schedule Settings
            </h2>
            <p className="mt-0.5 text-xs text-stone-500">
              Configure automated intervals for group metric updates and deep discovery crawls.
            </p>
          </div>
          {daemon?.is_paused && (
            <span className="rounded-full bg-amber-100 px-3 py-1 text-xs font-bold text-amber-800">
              Scheduler is currently paused
            </span>
          )}
        </div>

        <form onSubmit={handleSaveSettings} className="mt-4 space-y-4">
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
            <div>
              <label className="block text-xs font-semibold text-stone-700">
                Refresh Interval (Days)
              </label>
              <p className="mt-0.5 text-[11px] text-stone-400">
                How often stale groups (&gt;N days) are re-fetched.
              </p>
              <input
                type="number"
                min={1}
                max={3650}
                required
                value={refreshDays}
                onChange={(e) => setRefreshDays(e.target.value)}
                className="mt-2 h-10 w-full rounded-lg border border-stone-200 px-3 text-sm outline-none focus:border-brand-500 focus:ring-2 focus:ring-brand-500/20"
              />
            </div>

            <div>
              <label className="block text-xs font-semibold text-stone-700">
                Discovery Interval (Days)
              </label>
              <p className="mt-0.5 text-[11px] text-stone-400">
                How often broad deep discovery across categories runs.
              </p>
              <input
                type="number"
                min={1}
                max={3650}
                required
                value={discoveryDays}
                onChange={(e) => setDiscoveryDays(e.target.value)}
                className="mt-2 h-10 w-full rounded-lg border border-stone-200 px-3 text-sm outline-none focus:border-brand-500 focus:ring-2 focus:ring-brand-500/20"
              />
            </div>

            <div className="flex flex-col justify-end">
              <label className="flex h-10 cursor-pointer items-center gap-3 rounded-lg border border-stone-200 px-3 hover:bg-stone-50">
                <input
                  type="checkbox"
                  checked={isPaused}
                  onChange={(e) => setIsPaused(e.target.checked)}
                  className="h-4 w-4 rounded border-stone-300 text-brand-600 focus:ring-brand-500"
                />
                <span className="text-xs font-medium text-stone-700">
                  Pause Automated Schedules
                </span>
              </label>
            </div>
          </div>

          <div className="flex items-center gap-3 pt-2">
            <button
              type="submit"
              disabled={updateSettings.isPending}
              className="inline-flex h-10 items-center justify-center rounded-lg bg-brand-500 px-4 text-sm font-semibold text-white shadow-sm transition-colors hover:bg-brand-600 disabled:opacity-60"
            >
              {updateSettings.isPending ? 'Saving…' : 'Save Schedule Settings'}
            </button>
            {settingsFeedback && (
              <span
                className={`text-xs font-medium ${
                  settingsFeedback.type === 'success' ? 'text-emerald-600' : 'text-red-600'
                }`}
              >
                {settingsFeedback.message}
              </span>
            )}
          </div>
        </form>
      </section>

      {/* 6. MODAL TERMINAL CONSOLE DRAWER */}
      {selectedJob && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4 backdrop-blur-xs">
          <div className="relative flex max-h-[90vh] w-full max-w-4xl flex-col rounded-2xl border border-stone-800 bg-stone-950 p-6 text-stone-100 shadow-2xl">
            {/* Modal Header */}
            <div className="flex items-start justify-between border-b border-stone-800 pb-4">
              <div>
                <div className="flex items-center gap-2">
                  <Terminal size={18} className="text-brand-400" />
                  <h3 className="font-mono text-base font-bold text-white">
                    Job #{selectedJob.id} Output Console
                  </h3>
                  <span
                    className={`rounded-full px-2 py-0.5 text-xs font-semibold ${
                      selectedJob.status === 'SUCCESS'
                        ? 'bg-emerald-950 text-emerald-400 border border-emerald-800'
                        : selectedJob.status === 'FAILED'
                        ? 'bg-red-950 text-red-400 border border-red-800'
                        : 'bg-blue-950 text-blue-400 border border-blue-800'
                    }`}
                  >
                    {selectedJob.status}
                  </span>
                </div>
                <p className="mt-1 font-mono text-xs text-stone-400">
                  Mode: <span className="text-stone-200">{selectedJob.job_type}</span> ·
                  Trigger: <span className="text-stone-200">{selectedJob.trigger_type}</span> ·
                  Started: <span className="text-stone-200">{formatTimestamp(selectedJob.started_at)}</span> ·
                  Duration: <span className="text-stone-200">{formatDuration(selectedJob.started_at, selectedJob.finished_at)}</span> ·
                  Exit Code: <span className="text-stone-200">{selectedJob.exit_code ?? '—'}</span>
                </p>
              </div>

              <div className="flex items-center gap-2">
                {(selectedJob.status === 'RUNNING' || selectedJob.status === 'PENDING') && (
                  <button
                    type="button"
                    disabled={cancelJob.isPending}
                    onClick={() => handleCancelJob(selectedJob.id)}
                    className="inline-flex items-center gap-1.5 rounded-lg border border-red-800 bg-red-950/80 px-3 py-1.5 text-xs font-semibold text-red-300 hover:bg-red-900 hover:text-red-100 disabled:opacity-50"
                  >
                    <Square size={13} className="fill-current text-red-400" />
                    Stop Job
                  </button>
                )}
                <button
                  type="button"
                  onClick={() => handleCopyLogs(selectedJob.lines)}
                  className="inline-flex items-center gap-1.5 rounded-lg border border-stone-700 bg-stone-900 px-3 py-1.5 text-xs font-medium text-stone-200 hover:border-stone-600 hover:bg-stone-800"
                >
                  {copiedLogs ? <Check size={14} className="text-emerald-400" /> : <Copy size={14} />}
                  {copiedLogs ? 'Copied!' : 'Copy Output'}
                </button>
                <button
                  type="button"
                  onClick={() => setSelectedJob(null)}
                  className="rounded-lg p-1.5 text-stone-400 hover:bg-stone-800 hover:text-white"
                >
                  <X size={18} />
                </button>
              </div>
            </div>

            {/* Error Message banner if present */}
            {selectedJob.error_message && (
              <div className="mt-3 rounded-lg border border-red-900/60 bg-red-950/40 p-3 font-mono text-xs text-red-300">
                <span className="font-bold uppercase tracking-wider text-red-400">Error: </span>
                {selectedJob.error_message}
              </div>
            )}

            {/* Terminal Lines */}
            <div className="mt-4 flex-1 overflow-y-auto rounded-xl border border-stone-800 bg-black/80 p-4 font-mono text-xs leading-relaxed text-stone-300">
              {(!selectedJob.lines || selectedJob.lines.length === 0) ? (
                <div className="py-8 text-center text-stone-500">
                  {selectedJob.error_message ? '[No stdout stream lines recorded. See error message above]' : '[No output logged for this job execution]'}
                </div>
              ) : (
                <div className="space-y-1">
                  {selectedJob.lines.map((line, idx) => {
                    const isErr = line.level === 'ERROR';
                    const isWarn = line.level === 'WARNING';

                    return (
                      <div
                        key={line.id || idx}
                        className={`flex items-start gap-2 ${
                          isErr ? 'text-red-400' : isWarn ? 'text-amber-300' : 'text-stone-300'
                        }`}
                      >
                        <span className="shrink-0 text-stone-600 select-none">
                          {formatTimestamp(line.created_at)}
                        </span>
                        <span
                          className={`shrink-0 rounded px-1 py-0.2 text-[10px] font-bold ${
                            isErr
                              ? 'bg-red-900/50 text-red-300'
                              : isWarn
                              ? 'bg-amber-900/50 text-amber-300'
                              : 'bg-stone-800 text-stone-400'
                          }`}
                        >
                          {line.level || 'INFO'}
                        </span>
                        <span className="min-w-0 flex-1 whitespace-pre-wrap break-all">
                          {line.message}
                        </span>
                      </div>
                    );
                  })}
                </div>
              )}
            </div>

            {/* Modal Footer */}
            <div className="mt-4 flex items-center justify-between text-xs text-stone-500 border-t border-stone-800 pt-3">
              <span>{selectedJob.lines?.length || 0} log events recorded</span>
              <button
                type="button"
                onClick={() => setSelectedJob(null)}
                className="rounded-lg bg-stone-800 px-3 py-1.5 text-xs font-semibold text-stone-200 hover:bg-stone-700"
              >
                Close Console
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
