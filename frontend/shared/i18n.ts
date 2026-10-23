import i18n from "i18next";
import { initReactI18next } from "react-i18next";
import en from "./locales/en.json";
import hi from "./locales/hi.json";
import ta from "./locales/ta.json";

/** UI languages. Hindi and Tamil strings are machine-drafted and need native-speaker review. */
export const LANGUAGES = [
  { code: "en", label: "English", speech: "en-IN" },
  { code: "hi", label: "हिन्दी", speech: "hi-IN" },
  { code: "ta", label: "தமிழ்", speech: "ta-IN" },
] as const;
export type Lang = (typeof LANGUAGES)[number]["code"];

if (!i18n.isInitialized) {
  void i18n.use(initReactI18next).init({
    resources: { en: { translation: en }, hi: { translation: hi }, ta: { translation: ta } },
    lng: "en",
    fallbackLng: "en",
    interpolation: { escapeValue: false },
  });
}

/** Optional voice prompt (Web Speech API); silently does nothing where unsupported. */
export function speak(text: string, lang: string): void {
  try {
    const synth = window.speechSynthesis;
    if (!synth) return;
    synth.cancel();
    const u = new SpeechSynthesisUtterance(text);
    u.lang = LANGUAGES.find((l) => l.code === lang)?.speech ?? "en-IN";
    u.rate = 0.9;
    synth.speak(u);
  } catch {
    /* voice not available */
  }
}

export default i18n;
