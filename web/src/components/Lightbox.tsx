import { useEffect, useRef } from "react";
import { formatClock, dayLabel } from "../lib/format";
import { ChevronLeftIcon, ChevronRightIcon, CloseIcon, DownloadIcon } from "./Icons";
import type { Message } from "../api/types";

export function Lightbox({ items, index, onIndex, onClose }: { items: Message[]; index: number; onIndex: (i: number) => void; onClose: () => void }) {
  // eslint-disable-next-line security/detect-object-injection -- numeric index
  const m = items[index];
  const closeRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    const prev = document.activeElement as HTMLElement | null;
    closeRef.current?.focus();
    return () => prev?.focus();
  }, []);

  useEffect(() => {
    const onKey = (e: KeyboardEvent): void => {
      if (e.key === "Escape") onClose();
      else if (e.key === "ArrowLeft" && index > 0) onIndex(index - 1);
      else if (e.key === "ArrowRight" && index < items.length - 1) onIndex(index + 1);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [index, items.length, onClose, onIndex]);

  if (!m?.media?.url) return null;
  const isVideo = m.media.mime?.startsWith("video/") ?? false;
  return (
    <div role="dialog" aria-modal="true" aria-label="Media viewer" className="fixed inset-0 z-50 flex flex-col" style={{ background: "rgba(11,20,26,.96)" }} onClick={onClose}>
      <div className="flex items-center gap-3 px-4 py-3 text-[#e9edef]" onClick={(e) => e.stopPropagation()}>
        <div className="min-w-0 flex-1">
          <div className="truncate text-[16px]">{m.from_me ? "You" : (m.sender_name ?? "")}</div>
          <div className="text-[13px] text-[#8696a0]">{dayLabel(m.ts)} at {formatClock(m.ts)}</div>
        </div>
        <a href={m.media.url} download={m.media.file_name ?? undefined} aria-label="Download" className="rounded-full p-2 hover:bg-white/10">
          <DownloadIcon />
        </a>
        <button ref={closeRef} type="button" aria-label="Close" className="rounded-full p-2 hover:bg-white/10" onClick={onClose}>
          <CloseIcon />
        </button>
      </div>
      <div className="relative flex min-h-0 flex-1 items-center justify-center p-4">
        {index > 0 && (
          <button type="button" aria-label="Previous" className="absolute left-2 z-10 rounded-full bg-black/40 p-2 text-white hover:bg-black/60" onClick={(e) => { e.stopPropagation(); onIndex(index - 1); }}>
            <ChevronLeftIcon size={28} />
          </button>
        )}
        {isVideo ? (
          <video key={m.id} src={m.media.url} controls autoPlay playsInline className="max-h-full max-w-full" onClick={(e) => e.stopPropagation()} />
        ) : (
          <img key={m.id} src={m.media.url} alt={m.text ?? "Photo"} className="max-h-full max-w-full object-contain" onClick={(e) => e.stopPropagation()} />
        )}
        {index < items.length - 1 && (
          <button type="button" aria-label="Next" className="absolute right-2 z-10 rounded-full bg-black/40 p-2 text-white hover:bg-black/60" onClick={(e) => { e.stopPropagation(); onIndex(index + 1); }}>
            <ChevronRightIcon size={28} />
          </button>
        )}
      </div>
      {m.text ? <div className="px-6 pb-5 text-center text-[15px] text-[#e9edef]" onClick={(e) => e.stopPropagation()}>{m.text}</div> : null}
    </div>
  );
}
