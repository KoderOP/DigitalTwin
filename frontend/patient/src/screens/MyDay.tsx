import { useTranslation } from "react-i18next";
import { ArrowDown, ArrowUp, Bell, Footprints, Moon, NotebookPen, Pill, Utensils } from "lucide-react";
import type { PatientView } from "../types";
import { WhyBlock } from "./Home";
import { FoodPatterns } from "./FoodPatterns";
import { Panel, time } from "./ui";

const ICONS = { moon: Moon, walk: Footprints, plate: Utensils, pill: Pill, "arrow-up": ArrowUp, "arrow-down": ArrowDown, bell: Bell, note: NotebookPen } as const;

export function MyDay({ v }: { v: PatientView }) {
  const { t } = useTranslation();
  return (
    <div className="space-y-4">
      <Panel title={t("home.why")}><WhyBlock v={v} /></Panel>
      {v.food && <FoodPatterns f={v.food} />}
      <Panel title={t("day.title")}>
        {v.my_day.length === 0 ? <p>{t("day.empty")}</p> : (
          <ol className="relative space-y-3 border-l-2 border-slate-200 pl-4 dark:border-slate-700">
            {v.my_day.map((i, k) => {
              const Icon = ICONS[i.icon as keyof typeof ICONS] ?? Bell;
              return (
                <li key={`${i.ts}-${k}`} className="flex items-start gap-3">
                  <span className="w-12 shrink-0 font-mono text-sm text-slate-500">{time(i.ts)}</span>
                  <Icon aria-hidden className="h-6 w-6 shrink-0 text-brand" />
                  <span className="text-base">{i.text}</span>
                </li>
              );
            })}
          </ol>
        )}
      </Panel>
    </div>
  );
}
