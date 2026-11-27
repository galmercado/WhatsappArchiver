import { useCallback, useState } from "react";
import { FatalScreen, LoginScreen, UnlockScreen } from "./components/AuthScreens";
import { ChatView } from "./components/ChatView";
import { LockIcon } from "./components/Icons";
import { SearchPanel } from "./components/SearchPanel";
import { Sidebar } from "./components/Sidebar";
import { useRoute } from "./lib/route";
import { SessionProvider, useSession } from "./state/session";

function Empty() {
  return (
    <div className="hidden h-full flex-1 flex-col items-center justify-center gap-3 border-b-[6px] border-accent bg-panel px-10 text-center md:flex">
      <svg width="112" height="112" viewBox="0 0 64 64" aria-hidden="true" className="text-ink2 opacity-40">
        <path d="M32 10C19 10 9 19.500 9 31.500c0 5 1.800 9.600 5 13.300L10 56l12-4c3 1.200 6.200 1.800 10 1.800 13 0 23-9.500 23-21.500S45 10 32 10z" fill="none" stroke="currentColor" strokeWidth="3" strokeLinejoin="round" />
      </svg>
      <h1 className="text-[32px] font-light text-ink">WhatsApp Archive</h1>
      <p className="max-w-[460px] text-[14px] leading-5 text-ink2">Select a chat to read your archived messages. Everything here is read-only.</p>
      <p className="mt-6 flex items-center gap-1.5 text-[13px] text-ink2"><LockIcon size={13} /> Encrypted at rest. Decryption keys live only in server memory.</p>
    </div>
  );
}

function Main() {
  const [route, go] = useRoute();
  const [searchOpen, setSearchOpen] = useState(false);
  const [terms, setTerms] = useState<string[]>([]);
  const { chatId, messageId } = route;
  const onTerms = useCallback((t: string[]) => setTerms(t), []);

  return (
    <div className="app-frame">
      <aside className={`${chatId ? "hidden md:flex" : "flex"} w-full flex-col border-r border-line bg-sidebar md:w-[30%] md:min-w-[340px] md:max-w-[480px]`}>
        <Sidebar selectedId={chatId} onOpenChat={(c, m) => { setSearchOpen(false); go(c, m); }} />
      </aside>
      <main className={`${chatId ? "flex" : "hidden md:flex"} min-w-0 flex-1`}>
        {chatId ? (
          <ChatView
            chatId={chatId}
            anchor={messageId}
            terms={searchOpen ? terms : []}
            searchOpen={searchOpen}
            onToggleSearch={() => setSearchOpen((o) => !o)}
            onBack={() => { setSearchOpen(false); go(null); }}
            onJump={(id) => go(chatId, id)}
            onLatest={() => go(chatId)}
          />
        ) : (
          <Empty />
        )}
      </main>
      {chatId && searchOpen ? (
        <SearchPanel chatId={chatId} onClose={() => setSearchOpen(false)} onJump={(id) => go(chatId, id)} onTerms={onTerms} />
      ) : null}
    </div>
  );
}

function Gate() {
  const { phase } = useSession();
  switch (phase) {
    case "loading": return <div role="status" className="fixed inset-0 flex items-center justify-center bg-app text-ink2">Loading…</div>;
    case "login": return <LoginScreen />;
    case "unlock": return <UnlockScreen />;
    case "error": return <FatalScreen />;
    case "ready": return <Main />;
  }
}

export function App() {
  return (
    <SessionProvider>
      <Gate />
    </SessionProvider>
  );
}
