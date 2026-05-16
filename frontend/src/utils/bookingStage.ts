import type { Locale } from "../types/chat";

const LABELS: Record<string, Record<Locale, string>> = {
  choose_doctor: {
    en: "Choose a doctor",
    ar: "اختر طبيباً",
  },
  check_availability: {
    en: "Check available times",
    ar: "تحقق من الأوقات المتاحة",
  },
  collect_details: {
    en: "Share name & phone (7+ digits)",
    ar: "أدخل الاسم ورقم الهاتف (7 أرقام فأكثر)",
  },
  verify_patient: {
    en: "Verify patient for reschedule",
    ar: "تحقق من بيانات المريض لإعادة الجدولة",
  },
  chat: {
    en: "",
    ar: "",
  },
};

export function bookingStageLabel(stage: string | null | undefined, locale: Locale): string {
  if (!stage || stage === "chat") return "";
  return LABELS[stage]?.[locale] ?? LABELS[stage]?.en ?? "";
}
