import { useState, useMemo, useEffect } from 'react';
import { ChevronLeft, ChevronRight, Clock, Layers, Printer as PrinterIcon } from 'lucide-react';
import { formatDuration, parseUTCDate } from '../utils/date';
import type { PrintQueueItem } from '../api/client';
import { api } from '../api/client';
import { Button } from './Button';

type FilterMode = 'all' | 'printing' | 'queued';

interface ScheduleEvent {
  item: PrintQueueItem;
  estimatedEnd: Date;
  estimatedStart: Date;
  progress?: number;
  type: 'printing' | 'queued';
}

interface QueueTimelineViewProps {
  queueItems: PrintQueueItem[];
  printerStatuses: Record<number, { progress?: number; remaining_time?: number; state?: string }>;
  onItemClick: (item: PrintQueueItem) => void;
  t: (key: string, options?: Record<string, unknown>) => string;
}

function getStartOfDay(date: Date): Date {
  const d = new Date(date);
  d.setHours(0, 0, 0, 0);
  return d;
}

function formatDateLabel(date: Date): string {
  return date.toLocaleDateString(undefined, { weekday: 'short', month: 'short', day: 'numeric' });
}

function formatTimeOnly(date: Date): string {
  return date.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' });
}

function formatTimeLeft(ms: number, t: (key: string, opts?: Record<string, unknown>) => string): string {
  if (ms <= 0) return t('queue.timeline.time.anyMoment');
  const totalMin = Math.round(ms / 60000);
  if (totalMin < 60) return t('queue.timeline.time.minutesLeft', { minutes: totalMin });
  const hours = Math.floor(totalMin / 60);
  const mins = totalMin % 60;
  if (mins === 0) return t('queue.timeline.time.hoursLeft', { hours });
  return t('queue.timeline.time.hoursMinutesLeft', { hours, minutes: mins });
}

function getHourLabel(hour: number): string {
  const date = new Date();
  date.setHours(hour, 0, 0, 0);
  return date.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' });
}

function ScheduleCard({
  event,
  now,
  onItemClick,
  t,
}: {
  event: ScheduleEvent;
  now: Date;
  onItemClick: (item: PrintQueueItem) => void;
  t: (key: string, opts?: Record<string, unknown>) => string;
}) {
  const item = event.item;
  const displayName = item.archive_name || item.library_file_name || t('common.unknown');
  const printerName = item.printer_name || (item.target_model ? `${t('queue.filter.any')} ${item.target_model}` : t('queue.timeline.unassigned'));
  const isPrinting = event.type === 'printing';
  const timeLeft = event.estimatedEnd.getTime() - now.getTime();

  const thumbnailUrl = item.archive_thumbnail
    ? api.getArchiveThumbnail(item.archive_id!)
    : item.library_file_thumbnail
      ? api.getLibraryFileThumbnailUrl(item.library_file_id!)
      : null;

  return (
    <div
      className={`flex items-center gap-3 px-3 sm:px-4 py-3 bg-bambu-dark-secondary rounded-xl border cursor-pointer transition-all hover:border-bambu-green/40
        ${isPrinting ? 'border-blue-500/30' : 'border-bambu-dark-tertiary'}`}
      onClick={() => onItemClick(item)}
    >
      {/* Left accent */}
      <div className={`w-1 self-stretch rounded-full shrink-0 ${isPrinting ? 'bg-blue-500' : 'bg-bambu-green/40'}`} />

      {/* Thumbnail */}
      <div className="w-10 h-10 shrink-0 bg-bambu-dark rounded-lg overflow-hidden">
        {thumbnailUrl ? (
          <img src={thumbnailUrl} alt="" className="w-full h-full object-cover" />
        ) : (
          <div className="w-full h-full flex items-center justify-center text-bambu-gray">
            <Layers className="w-5 h-5" />
          </div>
        )}
      </div>

      {/* Info */}
      <div className="flex-1 min-w-0">
        <p className="text-sm text-white font-medium truncate">{displayName}</p>
        <div className="flex items-center gap-2 mt-0.5">
          <span className="flex items-center gap-1 text-xs text-bambu-gray">
            <PrinterIcon className="w-3 h-3" />
            <span className="truncate max-w-[120px] sm:max-w-none">{printerName}</span>
          </span>
          {item.print_time_seconds && (
            <span className="hidden sm:inline text-xs text-bambu-gray">
              {formatDuration(item.print_time_seconds)}
            </span>
          )}
        </div>

        {/* Progress bar for active prints */}
        {isPrinting && event.progress != null && (
          <div className="flex items-center gap-2 mt-1.5">
            <div className="flex-1 bg-bambu-dark-tertiary rounded-full h-1.5">
              <div
                className="bg-blue-500 h-1.5 rounded-full transition-all"
                style={{ width: `${event.progress}%` }}
              />
            </div>
            <span className="text-xs text-blue-400 shrink-0">{Math.round(event.progress)}%</span>
          </div>
        )}
      </div>

      {/* Time info */}
      <div className="text-right shrink-0">
        <p className="text-sm text-white font-medium">{formatTimeOnly(event.estimatedEnd)}</p>
        <p className={`text-xs mt-0.5 ${isPrinting ? 'text-blue-400' : 'text-bambu-gray'}`}>
          {formatTimeLeft(timeLeft, t)}
        </p>
      </div>
    </div>
  );
}

export function QueueTimelineView({
  queueItems,
  printerStatuses,
  onItemClick,
  t,
}: QueueTimelineViewProps) {
  const [viewDate, setViewDate] = useState(() => getStartOfDay(new Date()));
  const [now, setNow] = useState(() => new Date());
  const [filter, setFilter] = useState<FilterMode>('all');

  // Update "now" every 60 seconds
  useEffect(() => {
    const interval = setInterval(() => setNow(new Date()), 60000);
    return () => clearInterval(interval);
  }, []);

  const nowMs = now.getTime();
  const isToday = getStartOfDay(new Date()).getTime() === getStartOfDay(viewDate).getTime();

  // Build schedule events with ETA chaining
  const events = useMemo(() => {
    const result: ScheduleEvent[] = [];

    // Group pending items by printer for chaining
    const pendingByPrinter = new Map<number | null, PrintQueueItem[]>();

    for (const item of queueItems) {
      if (item.status === 'printing') {
        const status = item.printer_id != null ? printerStatuses[item.printer_id] : undefined;
        const start = parseUTCDate(item.started_at) || new Date();
        let endTime: Date;

        if (status?.remaining_time != null && status.remaining_time > 0) {
          endTime = new Date(nowMs + status.remaining_time * 60 * 1000);
        } else if (item.print_time_seconds) {
          const progress = status?.progress || 0;
          const remainingFraction = Math.max(0, 1 - progress / 100);
          endTime = new Date(nowMs + item.print_time_seconds * remainingFraction * 1000);
        } else {
          endTime = new Date(nowMs + 3600000);
        }

        result.push({
          item,
          estimatedStart: start,
          estimatedEnd: endTime,
          progress: status?.progress ?? undefined,
          type: 'printing',
        });
      } else if (item.status === 'pending') {
        const pid = item.printer_id;
        if (!pendingByPrinter.has(pid)) pendingByPrinter.set(pid, []);
        pendingByPrinter.get(pid)!.push(item);
      }
    }

    // Chain pending items per printer
    for (const [printerId, items] of pendingByPrinter) {
      items.sort((a, b) => a.position - b.position);

      // Find when the current active print on this printer ends
      let chainEnd = nowMs;
      for (const ev of result) {
        if (ev.item.printer_id === printerId && ev.type === 'printing') {
          chainEnd = Math.max(chainEnd, ev.estimatedEnd.getTime());
        }
      }

      for (const item of items) {
        // Respect scheduled_time
        const scheduledTime = parseUTCDate(item.scheduled_time);
        if (scheduledTime) {
          const sixMonthsFromNow = Date.now() + (180 * 24 * 60 * 60 * 1000);
          if (scheduledTime.getTime() <= sixMonthsFromNow) {
            chainEnd = Math.max(chainEnd, scheduledTime.getTime());
          }
        }

        const duration = (item.print_time_seconds || 3600) * 1000;
        const startTime = new Date(chainEnd);
        const endTime = new Date(chainEnd + duration);

        result.push({
          item,
          estimatedStart: startTime,
          estimatedEnd: endTime,
          type: 'queued',
        });

        chainEnd = endTime.getTime();
      }
    }

    // Sort by estimated end time
    result.sort((a, b) => a.estimatedEnd.getTime() - b.estimatedEnd.getTime());

    return result;
  }, [queueItems, printerStatuses, nowMs]);

  // Filter events for the selected day
  const viewDayStart = getStartOfDay(viewDate).getTime();
  const viewDayEnd = viewDayStart + 24 * 60 * 60 * 1000 - 1;

  const filteredEvents = useMemo(() => {
    return events.filter(ev => {
      // Event finishes within the viewed day
      const endMs = ev.estimatedEnd.getTime();
      if (endMs < viewDayStart || endMs > viewDayEnd) return false;

      // Filter by type
      if (filter === 'printing') return ev.type === 'printing';
      if (filter === 'queued') return ev.type === 'queued';
      return true;
    });
  }, [events, viewDayStart, viewDayEnd, filter]);

  // Group events by hour for time markers
  const groupedByHour = useMemo(() => {
    const groups: Map<number, ScheduleEvent[]> = new Map();
    for (const ev of filteredEvents) {
      const hour = ev.estimatedEnd.getHours();
      if (!groups.has(hour)) groups.set(hour, []);
      groups.get(hour)!.push(ev);
    }
    // Sort by hour
    return Array.from(groups.entries()).sort(([a], [b]) => a - b);
  }, [filteredEvents]);

  // Counts for filter tabs
  const printingCount = events.filter(ev => ev.type === 'printing' && ev.estimatedEnd.getTime() >= viewDayStart && ev.estimatedEnd.getTime() <= viewDayEnd).length;
  const queuedCount = events.filter(ev => ev.type === 'queued' && ev.estimatedEnd.getTime() >= viewDayStart && ev.estimatedEnd.getTime() <= viewDayEnd).length;

  // Overall completion estimate
  const allDoneBy = useMemo(() => {
    let latest = 0;
    for (const ev of events) {
      latest = Math.max(latest, ev.estimatedEnd.getTime());
    }
    return latest > 0 ? new Date(latest) : null;
  }, [events]);

  const goToday = () => setViewDate(getStartOfDay(new Date()));
  const goPrev = () => {
    const d = new Date(viewDate);
    d.setDate(d.getDate() - 1);
    setViewDate(d);
  };
  const goNext = () => {
    const d = new Date(viewDate);
    d.setDate(d.getDate() + 1);
    setViewDate(d);
  };

  const filterTabs: { key: FilterMode; label: string; count: number }[] = [
    { key: 'all', label: t('queue.timeline.filterAll'), count: printingCount + queuedCount },
    { key: 'printing', label: t('queue.timeline.filterPrinting'), count: printingCount },
    { key: 'queued', label: t('queue.timeline.filterQueued'), count: queuedCount },
  ];

  return (
    <div>
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 mb-5">
        {/* Day navigation */}
        <div className="flex items-center gap-2">
          <Button variant="ghost" size="sm" onClick={goPrev} className="p-1.5">
            <ChevronLeft className="w-4 h-4" />
          </Button>
          <span className="text-sm font-medium text-white min-w-[140px] text-center">
            {formatDateLabel(viewDate)}
          </span>
          <Button variant="ghost" size="sm" onClick={goNext} className="p-1.5">
            <ChevronRight className="w-4 h-4" />
          </Button>
          {!isToday && (
            <Button variant="ghost" size="sm" onClick={goToday} className="text-xs text-bambu-green">
              {t('queue.timeline.day.today')}
            </Button>
          )}
        </div>

        {allDoneBy && (
          <span className="text-xs text-bambu-gray flex items-center gap-1.5">
            <Clock className="w-3.5 h-3.5" />
            {t('queue.timeline.allDoneBy', {
              time: allDoneBy.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' }),
            })}
          </span>
        )}
      </div>

      {/* Filter tabs */}
      <div className="flex gap-2 mb-5">
        {filterTabs.map((tab) => (
          <button
            key={tab.key}
            onClick={() => setFilter(tab.key)}
            className={`px-3 py-1.5 rounded-lg text-sm font-medium transition-colors ${
              filter === tab.key
                ? 'bg-bambu-green text-white'
                : 'bg-bambu-dark-secondary border border-bambu-dark-tertiary text-bambu-gray hover:text-white'
            }`}
          >
            {tab.label}
            {tab.count > 0 && (
              <span className={`ml-1.5 text-xs ${filter === tab.key ? 'text-white/70' : 'text-bambu-gray'}`}>
                {tab.count}
              </span>
            )}
          </button>
        ))}
      </div>

      {/* Schedule feed */}
      {groupedByHour.length > 0 ? (
        <div className="space-y-6">
          {groupedByHour.map(([hour, hourEvents]) => (
            <div key={hour}>
              {/* Hour marker */}
              <div className="flex items-center gap-3 mb-3">
                <span className="text-xs font-medium text-bambu-gray w-14 shrink-0">
                  {getHourLabel(hour)}
                </span>
                <div className="flex-1 h-px bg-bambu-dark-tertiary" />
              </div>

              {/* Events in this hour */}
              <div className="space-y-2 sm:ml-[68px]">
                {hourEvents.map((event) => (
                  <ScheduleCard
                    key={event.item.id}
                    event={event}
                    now={now}
                    onItemClick={onItemClick}
                    t={t}
                  />
                ))}
              </div>
            </div>
          ))}
        </div>
      ) : (
        <div className="flex flex-col items-center justify-center py-16 text-bambu-gray">
          <Layers className="w-12 h-12 mb-3 opacity-30" />
          <p className="text-sm">{t('queue.timeline.noData')}</p>
        </div>
      )}
    </div>
  );
}
