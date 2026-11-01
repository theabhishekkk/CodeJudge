import { createContext, useCallback, useContext, useMemo, useState } from 'react';

type NoticeTone = 'success' | 'error' | 'info';
interface Notice {
  message: string;
  tone: NoticeTone;
}
interface NoticeContextValue {
  notice: Notice | null;
  showNotice: (message: string, tone?: NoticeTone) => void;
  dismiss: () => void;
}

const NoticeContext = createContext<NoticeContextValue | null>(null);

export function NoticeProvider({ children }: { children: React.ReactNode }) {
  const [notice, setNotice] = useState<Notice | null>(null);
  const showNotice = useCallback((message: string, tone: NoticeTone = 'info') => {
    setNotice({ message, tone });
  }, []);
  const dismiss = useCallback(() => setNotice(null), []);
  const value = useMemo(() => ({ notice, showNotice, dismiss }), [notice, showNotice, dismiss]);
  return <NoticeContext.Provider value={value}>{children}</NoticeContext.Provider>;
}

export function useNotice() {
  const value = useContext(NoticeContext);
  if (!value) throw new Error('useNotice must be used within NoticeProvider');
  return value;
}
