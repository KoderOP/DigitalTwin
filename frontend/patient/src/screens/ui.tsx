import type { ReactNode } from "react";
import { Volume2 } from "lucide-react";
import { useTranslation } from "react-i18next";
import { speak } from "@shared/i18n";

/** Full-height single-column screen, readable at 360 px. */
export function Screen({ children }: { children: ReactNode }) {
  return <main className="mx-auto flex min-h-[80vh] w-full max-w-md flex-col justify-center gap-5 px-4 py-6">{children}</main>;
}

/** Large touch target (>= 48 px). */
export function BigButton({ children, onClick, disabled, variant = "primary", ...rest }: {
  children: ReactNode; onClick?: () => void; disabled?: boolean; variant?: "primary" | "secondary" | "danger"; "aria-label"?: string;
}) {
  const cls = { primary: "bg-brand text-white", secondary: "border-2 border-slate-300 bg-white text-slate-900 dark:bg-slate-800 dark:text-white", danger: "bg-red-700 text-white" }[variant];
  return (
    <button {...rest} onClick={onClick} disabled={disabled}
      className={`flex min-h-14 w-full items-center justify-center gap-2 rounded-2xl px-5 text-lg font-semibold disabled:opacity-40 ${cls}`}>
      {children}
    </button>
  );
}

export function Panel({ title, children, right }: { title?: ReactNode; children: ReactNode; right?: ReactNode }) {
  return (
    <section className="rounded-2xl bg-white p-4 shadow-sm dark:bg-slate-900">
      {(title || right) && (
        <div className="mb-2 flex items-center justify-between gap-2">
          {title && <h2 className="text-lg font-bold">{title}</h2>}
          {right}
        </div>
      )}
      {children}
    </section>
  );
}

/** Optional voice prompt for key messages (low-literacy support). */
export function ReadAloud({ text }: { text: string }) {
  const { t, i18n } = useTranslation();
  return (
    <button onClick={() => speak(text, i18n.language)} aria-label={t("common.read_aloud")}
      className="inline-flex min-h-11 min-w-11 items-center justify-center gap-1 rounded-full border-2 border-slate-300 px-3 text-sm">
      <Volume2 aria-hidden className="h-5 w-5" /> {t("common.read_aloud")}
    </button>
  );
}

export const time = (iso: string) => new Date(iso).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
