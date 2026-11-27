import type { SVGProps } from "react";

/** Own icon set (Material-style paths). No WhatsApp brand assets are used. */
type P = SVGProps<SVGSVGElement> & { size?: number };

function mk(d: string, vb = 24) {
  return function Icon({ size = 24, ...rest }: P) {
    return (
      <svg viewBox={`0 0 ${vb} ${vb}`} width={size} height={size} fill="currentColor" aria-hidden="true" focusable="false" {...rest}>
        <path d={d} />
      </svg>
    );
  };
}

export const SearchIcon = mk("M15.5 14h-.79l-.28-.27A6.471 6.471 0 0 0 16 9.5 6.5 6.5 0 1 0 9.5 16c1.61 0 3.09-.59 4.23-1.57l.27.28v.79l5 4.99L20.49 19l-4.99-5zm-6 0C7.01 14 5 11.99 5 9.5S7.01 5 9.5 5 14 7.01 14 9.5 11.99 14 9.5 14z");
export const MenuIcon = mk("M12 8c1.1 0 2-.9 2-2s-.9-2-2-2-2 .9-2 2 .9 2 2 2zm0 2c-1.1 0-2 .9-2 2s.9 2 2 2 2-.9 2-2-.9-2-2-2zm0 6c-1.1 0-2 .9-2 2s.9 2 2 2 2-.9 2-2-.9-2-2-2z");
export const BackIcon = mk("M20 11H7.83l5.59-5.59L12 4l-8 8 8 8 1.41-1.41L7.83 13H20v-2z");
export const CloseIcon = mk("M19 6.41 17.59 5 12 10.59 6.41 5 5 6.41 10.59 12 5 17.59 6.41 19 12 13.41 17.59 19 19 17.59 13.41 12z");
export const PlayIcon = mk("M8 5v14l11-7z");
export const PauseIcon = mk("M6 19h4V5H6v14zm8-14v14h4V5h-4z");
export const DownloadIcon = mk("M19 9h-4V3H9v6H5l7 7 7-7zM5 18v2h14v-2H5z");
export const DocIcon = mk("M14 2H6c-1.1 0-1.99.9-1.99 2L4 20c0 1.1.89 2 1.99 2H18c1.1 0 2-.9 2-2V8l-6-6zm2 16H8v-2h8v2zm0-4H8v-2h8v2zm-3-5V3.5L18.5 9H13z");
export const LockIcon = mk("M18 8h-1V6c0-2.76-2.24-5-5-5S7 3.24 7 6v2H6c-1.1 0-2 .9-2 2v10c0 1.1.9 2 2 2h12c1.1 0 2-.9 2-2V10c0-1.1-.9-2-2-2zm-6 9c-1.1 0-2-.9-2-2s.9-2 2-2 2 .9 2 2-.9 2-2 2zm3.1-9H8.9V6c0-1.71 1.39-3.1 3.1-3.1 1.71 0 3.1 1.39 3.1 3.1v2z");
export const ChevronDownIcon = mk("M7.41 8.59 12 13.17l4.59-4.58L18 10l-6 6-6-6z");
export const MicIcon = mk("M12 14c1.66 0 2.99-1.34 2.99-3L15 5c0-1.66-1.34-3-3-3S9 3.34 9 5v6c0 1.66 1.34 3 3 3zm5.3-3c0 3-2.54 5.1-5.3 5.1S6.7 14 6.7 11H5c0 3.41 2.72 6.23 6 6.72V21h2v-3.28c3.28-.48 6-3.3 6-6.72h-1.7z");
export const ClockIcon = mk("M11.99 2C6.47 2 2 6.48 2 12s4.47 10 9.99 10C17.52 22 22 17.52 22 12S17.52 2 11.99 2zM12 20c-4.42 0-8-3.58-8-8s3.58-8 8-8 8 3.58 8 8-3.58 8-8 8zm.5-13H11v6l5.25 3.15.75-1.23-4.5-2.67z");
export const SunIcon = mk("M6.76 4.84l-1.8-1.79-1.41 1.41 1.79 1.79 1.42-1.41zM4 10.5H1v2h3v-2zm9-9.95h-2V3.5h2V.55zm7.45 3.91l-1.41-1.41-1.79 1.79 1.41 1.41 1.79-1.79zm-3.21 13.7l1.79 1.8 1.41-1.41-1.8-1.79-1.4 1.4zM20 10.5v2h3v-2h-3zm-8-5c-3.31 0-6 2.69-6 6s2.69 6 6 6 6-2.69 6-6-2.69-6-6-6zm-1 16.95h2V19.5h-2v2.95zm-7.45-3.91l1.41 1.41 1.79-1.8-1.41-1.41-1.79 1.8z");
export const MoonIcon = mk("M10 2c-1.82 0-3.53.5-5 1.35C7.99 5.08 10 8.3 10 12s-2.01 6.92-5 8.65C6.47 21.5 8.18 22 10 22c5.52 0 10-4.48 10-10S15.52 2 10 2z");
export const LogoutIcon = mk("M17 7l-1.41 1.41L18.17 11H8v2h10.17l-2.58 2.58L17 17l5-5zM4 5h8V3H4c-1.1 0-2 .9-2 2v14c0 1.1.9 2 2 2h8v-2H4V5z");
export const PersonIcon = mk("M12 12c2.21 0 4-1.79 4-4s-1.79-4-4-4-4 1.79-4 4 1.79 4 4 4zm0 2c-2.67 0-8 1.34-8 4v2h16v-2c0-2.66-5.33-4-8-4z");
export const GroupIcon = mk("M16 11c1.66 0 2.99-1.34 2.99-3S17.66 5 16 5c-1.66 0-3 1.34-3 3s1.34 3 3 3zm-8 0c1.66 0 2.99-1.34 2.99-3S9.66 5 8 5C6.34 5 5 6.34 5 8s1.34 3 3 3zm0 2c-2.33 0-7 1.17-7 3.5V19h14v-2.5c0-2.33-4.67-3.5-7-3.5zm8 0c-.29 0-.62.02-.97.05 1.16.84 1.97 1.97 1.97 3.45V19h6v-2.5c0-2.33-4.67-3.5-7-3.5z");
export const VideoIcon = mk("M17 10.5V7c0-.55-.45-1-1-1H4c-.55 0-1 .45-1 1v10c0 .55.45 1 1 1h12c.55 0 1-.45 1-1v-3.5l4 4v-11l-4 4z");
export const ImageIcon = mk("M21 19V5c0-1.1-.9-2-2-2H5c-1.1 0-2 .9-2 2v14c0 1.1.9 2 2 2h14c1.1 0 2-.9 2-2zM8.5 13.5l2.5 3.01L14.5 12l4.5 6H5l3.5-4.5z");
export const ChevronRightIcon = mk("M8.59 16.59 13.17 12 8.59 7.41 10 6l6 6-6 6z");
export const ChevronLeftIcon = mk("M15.41 16.59 10.83 12l4.58-4.59L14 6l-6 6 6 6z");
export const ArchiveIcon = mk("M20.54 5.23l-1.39-1.68C18.88 3.21 18.47 3 18 3H6c-.47 0-.88.21-1.16.55L3.46 5.23C3.17 5.57 3 6.02 3 6.5V19c0 1.1.9 2 2 2h14c1.1 0 2-.9 2-2V6.5c0-.48-.17-.93-.46-1.27zM12 17.5L6.5 12H10v-2h4v2h3.5L12 17.5zM5.12 5l.81-1h12l.94 1H5.12z");

/** Message status ticks (WhatsApp geometry). */
export function Ticks({ status }: { status: number | null }) {
  if (status === null) return null;
  if (status <= 0)
    return (
      <span role="img" aria-label="Pending" className="inline-flex text-[color:var(--bubble-meta)]">
        <ClockIcon size={14} />
      </span>
    );
  const double = status >= 2;
  const read = status >= 3;
  const label = read ? "Read" : double ? "Delivered" : "Sent";
  return (
    <span role="img" aria-label={label} className="inline-flex" style={{ color: read ? "var(--tick-blue)" : "var(--bubble-meta)" }}>
      <svg viewBox="0 0 16 11" width="16" height="11" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
        {double ? (
          <>
            <path d="M0.800 5.800 3.900 8.900 9.600 1.800" />
            <path d="M5.400 5.800 8.500 8.900 14.200 1.800" />
          </>
        ) : (
          <path d="M3 5.800 6.100 8.900 11.800 1.800" />
        )}
      </svg>
    </span>
  );
}

export function Avatar({ group, size = 49, className = "" }: { group: boolean; size?: number; className?: string }) {
  const Icon = group ? GroupIcon : PersonIcon;
  return (
    <span
      className={`inline-flex shrink-0 items-center justify-center rounded-full ${className}`}
      style={{ width: size, height: size, background: "var(--avatar-bg)", color: "var(--avatar-fg)" }}
      aria-hidden="true"
    >
      <Icon size={Math.round(size * 0.66)} />
    </span>
  );
}
