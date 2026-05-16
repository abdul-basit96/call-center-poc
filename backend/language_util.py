"""Locale helpers: infer Arabic vs English from user turns, and small canned strings."""

from __future__ import annotations

import re
from typing import Literal, cast

from langchain_core.messages import BaseMessage, HumanMessage

Locale = Literal["ar", "en"]

_AR_LETTERS = re.compile(
    r"[\u0600-\u06FF\u0750-\u077F\u08A0-\u08FF\uFB50-\uFDFF\uFE70-\uFEFF]+"
)
_LATIN_LETTERS = re.compile(r"[A-Za-z]+")


def _letter_counts(sample: str) -> tuple[int, int]:
    ar = len("".join(_AR_LETTERS.findall(sample)))
    la = len("".join(_LATIN_LETTERS.findall(sample)))
    return ar, la


def human_text(msg: HumanMessage) -> str:
    c = msg.content
    if isinstance(c, str):
        return c.strip()
    if isinstance(c, list):
        parts: list[str] = []
        for block in c:
            if isinstance(block, str) and block.strip():
                parts.append(block.strip())
            elif isinstance(block, dict) and block.get("type") == "text":
                t = block.get("text", "")
                if isinstance(t, str) and t.strip():
                    parts.append(t.strip())
        return "\n".join(parts).strip()
    return ""


def infer_locale_from_text(sample: str) -> Locale:
    """Classify one user utterance (not a multi-turn blob)."""
    if not (sample or "").strip():
        return "en"
    ar, la = _letter_counts(sample)
    if ar == 0 and la == 0:
        return "en"
    
    # Very short but clear English words (Yes, No, Ok, Hi)
    if la >= 2 and ar == 0:
        return "en"
    # Very short but clear Arabic words (نعم, لا)
    if ar >= 2 and la == 0:
        return "ar"
        
    # Clear English: enough Latin, little or no Arabic
    if la >= 5 and ar <= 1:
        return "en"
    if la >= 10 and ar < la * 0.3:
        return "en"
    # Clear Arabic
    if ar >= 3 and la == 0:
        return "ar"
    if ar >= 6 and ar >= la * 0.5:
        return "ar"
    # Mixed / code-switch: letter majority wins
    if la > ar:
        return "en"
    if ar > la:
        return "ar"
    return "en"


def infer_locale_from_messages(messages: list[BaseMessage] | None) -> Locale:
    """Use the latest human message for language — older Arabic must not override a new English turn."""
    texts: list[str] = []
    for msg in reversed(messages or []):
        if isinstance(msg, HumanMessage):
            hint = None
            if msg.additional_kwargs:
                hint = msg.additional_kwargs.get("voice_hint_locale")
            if hint in ("ar", "en"):
                return cast(Locale, hint)
            t = human_text(msg)
            if t:
                texts.append(t)
            if len(texts) >= 3:
                break
    if not texts:
        return "en"
    latest = texts[0]
    ar, la = _letter_counts(latest)
    # No script at all (digits / emoji / punctuation only) — inherit previous human
    if ar == 0 and la == 0 and len(texts) >= 2:
        return infer_locale_from_text(texts[1])
    return infer_locale_from_text(latest)


def reply_language_instruction_block(locale: Locale) -> str:
    if locale == "ar":
        return (
            "\n## Active reply language (required)\n"
            "Write **this entire assistant reply** in **Modern Standard Arabic**, including every explanation of "
            "schedules, doctors, and booking steps. Tool output may be English — **translate all patient-facing "
            "facts** into Arabic. Keep doctor names in Latin script when needed, with Arabic phrasing around them.\n"
        )
    return (
        "\n## Active reply language (required)\n"
        "Write **this entire assistant reply** in **English**.\n"
        "If the patient’s **current** message is clearly in English, use English even if they wrote Arabic earlier in the thread.\n"
    )


def canned_cancel_response(locale: Locale) -> str:
    if locale == "ar":
        return "لا مشكلة — ألغيتُ ذلك. كيف يمكنني مساعدتك الآن؟"
    return "No problem — I cancelled that. What would you like to do?"


def fallback_assistant_reply(locale: Locale) -> str:
    if locale == "ar":
        return "كيف يمكنني مساعدتك اليوم؟"
    return "How can I help you today?"


def book_confirmation_summary(args: dict, locale: Locale) -> str:
    if locale == "ar":
        return (
            "**يرجى تأكيد هذا الحجز**\n\n"
            f"- المريض: {args.get('patient_name', '')}\n"
            f"- الهاتف: {args.get('contact_info', '')}\n"
            f"- رقم الطبيب: {args.get('doctor_id', '')}\n"
            f"- الموعد (ISO): `{args.get('appointment_date', '')}`\n\n"
            "استخدم **تأكيد** أدناه، أو رد بـ **نعم** للحفظ."
        )
    return (
        "**Please confirm this booking**\n\n"
        f"- Patient: {args.get('patient_name', '')}\n"
        f"- Phone: {args.get('contact_info', '')}\n"
        f"- Doctor ID: {args.get('doctor_id', '')}\n"
        f"- Time (ISO): `{args.get('appointment_date', '')}`\n\n"
        "Use **Confirm** below, or reply with **yes** to save."
    )


def reschedule_confirmation_summary(args: dict, locale: Locale) -> str:
    if locale == "ar":
        return (
            "**يرجى تأكيد إعادة الجدولة**\n\n"
            f"- رقم الموعد: {args.get('appointment_id', '')}\n"
            f"- الوقت الجديد (ISO): `{args.get('new_datetime', '')}`\n\n"
            "استخدم **تأكيد** أدناه، أو رد بـ **نعم** للحفظ."
        )
    return (
        "**Please confirm this reschedule**\n\n"
        f"- Appointment ID: {args.get('appointment_id', '')}\n"
        f"- New time (ISO): `{args.get('new_datetime', '')}`\n\n"
        "Use **Confirm** below, or reply with **yes** to save."
    )
