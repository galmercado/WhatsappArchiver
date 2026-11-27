import { useEffect, useRef, useState, type ReactNode } from "react";
import { MenuIcon } from "./Icons";

export interface MenuItem {
  label: string;
  icon?: ReactNode;
  onSelect: () => void;
}

export function IconButton({ label, onClick, children, pressed }: { label: string; onClick: () => void; children: ReactNode; pressed?: boolean }) {
  return (
    <button type="button" aria-label={label} title={label} aria-pressed={pressed} onClick={onClick} className="inline-flex h-10 w-10 items-center justify-center rounded-full text-icon hover:bg-[color:var(--hover-bg)] aria-pressed:bg-[color:var(--selected-bg)]">
      {children}
    </button>
  );
}

export function Menu({ items, label = "Menu" }: { items: MenuItem[]; label?: string }) {
  const [open, setOpen] = useState(false);
  const box = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const onDoc = (e: MouseEvent): void => {
      if (box.current && !box.current.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent): void => {
      if (e.key === "Escape") setOpen(false);
    };
    document.addEventListener("mousedown", onDoc);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDoc);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);
  return (
    <div ref={box} className="relative">
      <IconButton label={label} onClick={() => setOpen((o) => !o)} pressed={open}>
        <MenuIcon />
      </IconButton>
      {open ? (
        <ul role="menu" className="absolute right-0 top-11 z-30 min-w-[200px] animate-pop rounded-[3px] bg-sidebar py-2 shadow-[0_2px_5px_0_rgba(11,20,26,.26),0_2px_10px_0_rgba(11,20,26,.16)]">
          {items.map((it) => (
            <li key={it.label} role="none">
              <button
                role="menuitem"
                type="button"
                className="flex w-full items-center gap-3 px-6 py-[9px] text-left text-[14.5px] text-ink hover:bg-[color:var(--hover-bg)]"
                onClick={() => {
                  setOpen(false);
                  it.onSelect();
                }}
              >
                {it.icon}
                {it.label}
              </button>
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}
