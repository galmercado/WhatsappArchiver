import { useEffect, useMemo, useRef, useState, type KeyboardEvent, type PointerEvent } from "react";
import { formatDuration } from "../lib/format";
import { waveformBars } from "../lib/waveform";
import { MicIcon, PauseIcon, PlayIcon } from "./Icons";

let current: HTMLAudioElement | null = null; // only one voice note plays at a time
const SPEEDS = [1, 1.5, 2] as const;

export function AudioPlayer({ id, url, durationHint, outgoing }: { id: number; url: string; durationHint: number | null; outgoing: boolean }) {
  const ref = useRef<HTMLAudioElement>(null);
  const bars = useMemo(() => waveformBars(id), [id]);
  const [playing, setPlaying] = useState(false);
  const [time, setTime] = useState(0);
  const [dur, setDur] = useState(durationHint ?? 0);
  const [speed, setSpeed] = useState<(typeof SPEEDS)[number]>(1);
  const [failed, setFailed] = useState(false);
  const dragging = useRef(false);

  useEffect(() => {
    const a = ref.current;
    return () => {
      if (a && current === a) current = null;
    };
  }, []);

  const toggle = (): void => {
    const a = ref.current;
    if (!a) return;
    if (a.paused) {
      if (current && current !== a) current.pause();
      current = a;
      a.playbackRate = speed;
      void a.play().catch(() => setFailed(true));
    } else {
      a.pause();
    }
  };
  const seekTo = (frac: number): void => {
    const a = ref.current;
    if (!a || !Number.isFinite(frac)) return;
    const total = Number.isFinite(a.duration) && a.duration > 0 ? a.duration : dur;
    if (total <= 0) return;
    a.currentTime = Math.min(Math.max(frac, 0), 1) * total;
    setTime(a.currentTime);
  };
  const fracFromEvent = (e: PointerEvent<HTMLDivElement>): number => {
    const r = e.currentTarget.getBoundingClientRect();
    return r.width > 0 ? (e.clientX - r.left) / r.width : 0;
  };
  const onKey = (e: KeyboardEvent<HTMLDivElement>): void => {
    const a = ref.current;
    if (!a) return;
    const step = e.key === "ArrowRight" ? 2 : e.key === "ArrowLeft" ? -2 : 0;
    if (step) {
      e.preventDefault();
      a.currentTime = Math.max(0, Math.min(a.currentTime + step, dur || a.duration || 0));
      setTime(a.currentTime);
    }
  };
  const progress = dur > 0 ? Math.min(time / dur, 1) : 0;
  const played = outgoing ? "var(--accent-strong)" : "var(--accent)";

  return (
    <div className="flex w-[min(280px,60vw)] items-center gap-2 py-1 pr-1">
      <audio
        ref={ref}
        src={url}
        preload="none"
        onPlay={() => setPlaying(true)}
        onPause={() => setPlaying(false)}
        onEnded={() => {
          setPlaying(false);
          setTime(0);
        }}
        onTimeUpdate={(e) => !dragging.current && setTime(e.currentTarget.currentTime)}
        onLoadedMetadata={(e) => Number.isFinite(e.currentTarget.duration) && setDur(e.currentTarget.duration)}
        onError={() => setFailed(true)}
      />
      <button type="button" onClick={toggle} aria-label={playing ? "Pause voice message" : "Play voice message"} className="shrink-0 text-icon">
        {playing ? <PauseIcon size={34} /> : <PlayIcon size={34} />}
      </button>
      <div className="min-w-0 flex-1">
        <div
          role="slider"
          tabIndex={0}
          aria-label="Seek voice message"
          aria-valuemin={0}
          aria-valuemax={Math.round(dur)}
          aria-valuenow={Math.round(time)}
          aria-valuetext={`${formatDuration(time)} of ${formatDuration(dur)}`}
          className="relative flex h-7 cursor-pointer touch-none items-center gap-[2px]"
          onKeyDown={onKey}
          onPointerDown={(e) => {
            dragging.current = true;
            e.currentTarget.setPointerCapture(e.pointerId);
            seekTo(fracFromEvent(e));
          }}
          onPointerMove={(e) => dragging.current && seekTo(fracFromEvent(e))}
          onPointerUp={() => {
            dragging.current = false;
          }}
        >
          {bars.map((h, i) => (
            <span
              key={i}
              className="w-[3px] shrink-0 rounded-full"
              style={{ height: `${Math.round(h * 100)}%`, background: i / bars.length < progress ? played : "var(--text-secondary)", opacity: i / bars.length < progress ? 1 : 0.45 }}
            />
          ))}
          <span className="absolute top-1/2 h-[13px] w-[13px] -translate-y-1/2 rounded-full" style={{ left: `calc(${progress * 100}% - 6px)`, background: played }} />
        </div>
        <div className="flex items-center justify-between text-meta text-[color:var(--bubble-meta)]">
          <span>{failed ? "Audio unavailable" : formatDuration(playing || time > 0 ? time : dur)}</span>
          <button
            type="button"
            className="rounded-full bg-[color:var(--hover-bg)] px-1.5 text-[10px] font-medium"
            aria-label={`Playback speed ${speed}x`}
            onClick={() => {
              const next = SPEEDS[(SPEEDS.indexOf(speed) + 1) % SPEEDS.length] ?? 1;
              setSpeed(next);
              if (ref.current) ref.current.playbackRate = next;
            }}
          >
            {speed}×
          </button>
        </div>
      </div>
      <span className="text-icon opacity-70">
        <MicIcon size={20} />
      </span>
    </div>
  );
}
