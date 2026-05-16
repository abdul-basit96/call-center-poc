"""Deterministic booking/reschedule validation, availability parsing, and workflow hints."""

from __future__ import annotations

import os
import re
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal

import psycopg2
from psycopg2 import pool

from backend.scheduling_core import (
    day_booking_count,
    format_doctor_name,
    parse_iso_local,
    slot_overlaps_existing,
    slots_per_day,
    validate_slot_request,
)

Intent = Literal["general", "list_doctors", "availability", "book", "reschedule", "verify"]

_db_pool: pool.SimpleConnectionPool | None = None


def _ensure_pool() -> pool.SimpleConnectionPool:
    global _db_pool
    if _db_pool is None:
        url = os.getenv("DATABASE_URL")
        if not url:
            raise RuntimeError("DATABASE_URL is not set.")
        _db_pool = psycopg2.pool.SimpleConnectionPool(1, 5, url)
    return _db_pool


@contextmanager
def db_cursor():
    p = _ensure_pool()
    conn = p.getconn()
    try:
        with conn.cursor() as cur:
            yield cur
            conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        p.putconn(conn)


def detect_intent(text: str) -> Intent:
    t = (text or "").strip().lower()
    if not t:
        return "general"
    # Reschedule
    if re.search(r"\b(reschedule|re-?schedule|move|change)\b.*\b(appointment|slot|time)\b", t):
        return "reschedule"
    if re.search(r"\b(reschedule|re-?schedule)\b", t) or any(p in t for p in ("تعديل", "تغيير", "إعادة جدولة")):
        return "reschedule"
    # Verify
    if re.search(r"\b(verify|look\s*up|find)\b.*\b(patient|appointment|record)\b", t) or any(p in t for p in ("تحقق", "بحث", "سجل")):
        return "verify"
    # Book
    if re.search(r"\b(book|booking|schedule|make an appointment|see (the )?dr)\b", t) or any(p in t for p in ("حجز", "موعد", "أريد أن أرى")):
        return "book"
    # Availability
    if re.search(r"\b(available|availability|free|openings?|slots?)\b", t) or any(p in t for p in ("متاح", "أوقات", "متى", "فراغ")):
        return "availability"
    if re.search(r"\b(doctor|dr\.?)\b", t) and re.search(r"\b(hours?|when|time)\b", t):
        return "availability"
    # List Doctors
    if re.search(r"\b(which|list|show)\b.*\b(doctors?|specialists?)\b", t) or any(p in t for p in ("قائمة الأطباء", "من هم")):
        return "list_doctors"
    return "general"


def parse_doctor_id_from_availability(text: str) -> int | None:
    m = re.search(r"Doctor\s+ID:\s*(\d+)", text, re.I)
    if m:
        return int(m.group(1))
    return None


def parse_availability_slots(text: str) -> dict[str, list[str]]:
    """Parse lines like '- 2026-05-20: 09:00 AM, 10:00 AM' from availability reports."""
    out: dict[str, list[str]] = {}
    for line in (text or "").splitlines():
        line = line.strip()
        m = re.match(r"^-\s*(\d{4}-\d{2}-\d{2}):\s*(.+)$", line)
        if not m:
            continue
        day, times_part = m.group(1), m.group(2)
        times = [x.strip() for x in times_part.split(",") if x.strip()]
        if times:
            out[day] = times
    return out


def format_slots_for_prompt(slots: dict[str, list[str]], max_days: int = 7) -> str:
    if not slots:
        return "(no parsed free slots — call check_doctor_availability again)"
    lines: list[str] = []
    for i, (day, times) in enumerate(sorted(slots.items())):
        if i >= max_days:
            lines.append(f"... and {len(slots) - max_days} more day(s)")
            break
        lines.append(f"- {day}: {', '.join(times[:8])}" + (" …" if len(times) > 8 else ""))
    return "\n".join(lines)


_PHONE_DICT_KEYS = (
    "phone",
    "phone_number",
    "mobile",
    "tel",
    "telephone",
    "contact",
    "contact_info",
    "number",
)


def normalize_phone(contact_info: Any = None, phone: str | None = None) -> str:
    """Coerce LLM tool args to a single phone string (dict/list/str)."""
    if phone is not None and str(phone).strip():
        return str(phone).strip()
    if contact_info is None:
        return ""
    if isinstance(contact_info, dict):
        for key in _PHONE_DICT_KEYS:
            val = contact_info.get(key)
            if val is not None and str(val).strip():
                return str(val).strip()
        return ""
    if isinstance(contact_info, (list, tuple)):
        for item in contact_info:
            s = normalize_phone(item, None)
            if s:
                return s
        return ""
    return str(contact_info).strip()


def booking_identity_errors(patient_name: str, phone: str) -> list[str]:
    errors: list[str] = []
    name = (patient_name or "").strip()
    contact = normalize_phone(phone)
    if len(name) < 2:
        errors.append("Error: Patient full name is required (at least 2 characters).")
    else:
        parts = [p for p in name.replace("-", " ").split() if p]
        if len(parts) < 2 and len(name) < 5:
            errors.append("Error: Please use the patient's full name (first and last).")
    if not contact:
        errors.append("Error: Phone number is required.")
    elif "@" in contact:
        errors.append(
            "Error: Email is not accepted — provide a phone number with at least 7 digits "
            "(e.g. 0529123456 or +971529123456)."
        )
    else:
        digits = sum(1 for c in contact if c.isdigit())
        if digits < 7:
            errors.append(
                "Error: Phone number must include at least 7 digits (e.g. 0529123456 or +971529123456)."
            )
    return errors


def validate_booking_args(
    patient_name: str | None,
    contact_info: Any = None,
    doctor_id: str | int | None = None,
    appointment_date: str | None = None,
    *,
    phone: str | None = None,
) -> list[str]:
    """Full booking validation (identity + slot grid). Returns user-facing error lines."""
    contact = normalize_phone(contact_info, phone)
    errors = booking_identity_errors(patient_name or "", contact)
    try:
        did = int(doctor_id)
    except (ValueError, TypeError):
        return errors + [f"Error: Invalid doctor_id '{doctor_id}'."]
    if not appointment_date:
        return errors + ["Error: appointment_date is required (ISO YYYY-MM-DDTHH:MM:SS)."]
    try:
        start_dt = parse_iso_local(appointment_date)
    except ValueError:
        return errors + ["Error: Use ISO datetime YYYY-MM-DDTHH:MM:SS for appointment_date."]

    try:
        with db_cursor() as cur:
            cur.execute(
                "SELECT name, schedule_start, schedule_end, slot_minutes, schedule_weekdays FROM doctors WHERE id = %s",
                (did,),
            )
            drow = cur.fetchone()
            if not drow:
                return errors + [f"Error: No doctor with id {did}."]
            _dname, ss, se, sm, wk = drow
            err = validate_slot_request(start_dt, ss, se, sm, wk)
            if err:
                return errors + [err]
            spd = slots_per_day(ss, se, sm)
            day_count = day_booking_count(cur, did, start_dt.date())
            if spd > 0 and day_count >= spd:
                return errors + [
                    "Error: That calendar day is already at full capacity for this doctor. "
                    "Call check_doctor_availability and choose a listed free time."
                ]
            if slot_overlaps_existing(cur, did, start_dt, sm, None):
                return errors + [
                    "Error: That slot overlaps another booking. "
                    "Call check_doctor_availability and pick a listed free time."
                ]
    except RuntimeError as e:
        return errors + [f"Error: Cannot validate booking ({e})."]
    except Exception as e:
        return errors + [f"Error: Validation failed ({e})."]
    return errors


def validate_reschedule_args(
    appointment_id: str | int | None,
    new_datetime: str | None,
) -> list[str]:
    errors: list[str] = []
    try:
        aid = int(appointment_id)
    except (ValueError, TypeError):
        return [f"Error: Bad appointment_id '{appointment_id}'."]
    if not new_datetime:
        return ["Error: new_datetime is required (ISO YYYY-MM-DDTHH:MM:SS)."]
    try:
        new_dt = parse_iso_local(new_datetime)
    except ValueError:
        return ["Error: Use ISO datetime for new_datetime."]

    try:
        with db_cursor() as cur:
            cur.execute(
                """
                SELECT a.status, d.schedule_start, d.schedule_end, d.slot_minutes, d.schedule_weekdays,
                       a.doctor_id, a.appointment_date
                FROM appointments a JOIN doctors d ON a.doctor_id = d.id WHERE a.id = %s
                """,
                (aid,),
            )
            row = cur.fetchone()
            if not row:
                return [f"Error: No appointment {aid}."]
            status, ss, se, sm, wk, doctor_id, old_dt = row
            if status == "cancelled":
                return [f"Error: Appointment {aid} is cancelled."]
            err = validate_slot_request(new_dt, ss, se, sm, wk)
            if err:
                return [err]
            if isinstance(old_dt, datetime) and old_dt.tzinfo:
                old_dt = old_dt.replace(tzinfo=None)
            spd = slots_per_day(ss, se, sm)
            day_count = day_booking_count(cur, doctor_id, new_dt.date())
            same_day = old_dt.date() == new_dt.date()
            effective = day_count - 1 if same_day else day_count
            if spd > 0 and effective >= spd:
                return ["Error: Target day is full. Pick another time from check_doctor_availability."]
            if slot_overlaps_existing(cur, doctor_id, new_dt, sm, aid):
                return ["Error: Overlaps another booking."]
    except RuntimeError as e:
        return [f"Error: Cannot validate reschedule ({e})."]
    except Exception as e:
        return [f"Error: Validation failed ({e})."]
    return errors


def normalize_tool_args(name: str, args: dict | None) -> dict:
    """Normalize tool arguments (e.g. contact_info dict → phone string)."""
    out = dict(args or {})
    if name in ("book_appointment", "validate_booking"):
        out["contact_info"] = normalize_phone(out.get("contact_info"), out.get("phone"))
        out.pop("phone", None)
    elif name == "verify_patient":
        out["contact_info"] = normalize_phone(out.get("contact_info"), out.get("phone"))
        out.pop("phone", None)
    return out


def validate_write_tool(name: str, args: dict) -> list[str]:
    args = normalize_tool_args(name, args)
    if name == "book_appointment":
        return validate_booking_args(
            args.get("patient_name"),
            args.get("contact_info"),
            args.get("doctor_id"),
            args.get("appointment_date"),
        )
    if name == "reschedule_appointment":
        return validate_reschedule_args(args.get("appointment_id"), args.get("new_datetime"))
    return []


def format_validation_reply(errors: list[str], locale: str = "en") -> str:
    quoted = "\n".join(f"- {e}" for e in errors if e.strip())
    if locale == "ar":
        return (
            "لا يمكن تأكيد هذا الحجز بعد — يرجى تصحيح التالي ثم المحاولة مرة أخرى:\n\n"
            f"{quoted}\n\n"
            "اقرأ كل سطر **Error:** كما هو عند شرح المشكلة للمريض."
        )
    return (
        "I cannot confirm this booking yet — please fix the following, then try again:\n\n"
        f"{quoted}\n\n"
        "Quote each **Error:** line exactly when explaining the issue to the patient."
    )


def stringify_message_content(content: Any) -> str:
    """Normalize AIMessage/ToolMessage content (str or LangChain block list) to plain text."""
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, str) and block.strip():
                parts.append(block.strip())
            elif isinstance(block, dict) and block.get("type") == "text":
                t = block.get("text", "")
                if isinstance(t, str) and t.strip():
                    parts.append(t.strip())
        return "\n".join(parts).strip()
    if content is not None:
        return str(content).strip()
    return ""


def tool_result_indicates_success(tool_name: str, content: Any) -> bool:
    c = stringify_message_content(content)
    if not c or c.startswith("Error:") or c.startswith("Database error:"):
        return False
    if tool_name == "book_appointment":
        return c.startswith("Booked appointment #") or "Booked appointment #" in c
    if tool_name == "reschedule_appointment":
        return c.startswith("Rescheduled #") or "Rescheduled #" in c
    return False


@dataclass
class SessionSnapshot:
    intent: Intent = "general"
    last_doctor_id: int | None = None
    free_slots: dict[str, list[str]] = field(default_factory=dict)
    last_tool_error: str | None = None


def scan_messages_for_session(messages: list, latest_human: str = "") -> SessionSnapshot:
    snap = SessionSnapshot(intent=detect_intent(latest_human))
    for msg in reversed(messages or []):
        from langchain_core.messages import ToolMessage

        if not isinstance(msg, ToolMessage):
            continue
        content = msg.content if isinstance(msg.content, str) else str(msg.content or "")
        if "Doctor ID:" in content and "Next available start times" in content:
            snap.last_doctor_id = parse_doctor_id_from_availability(content)
            snap.free_slots = parse_availability_slots(content)
            break
    for msg in reversed(messages or []):
        from langchain_core.messages import ToolMessage

        if isinstance(msg, ToolMessage):
            c = msg.content if isinstance(msg.content, str) else ""
            if isinstance(c, str) and c.strip().startswith("Error:"):
                snap.last_tool_error = c.strip().split("\n")[0]
                break
    return snap


def build_workflow_hint(snap: SessionSnapshot, locale: str = "en") -> str:
    lines: list[str] = ["\n## Workflow guide (follow in order — do not skip steps)\n"]
    intent_labels = {
        "general": "Help the patient (discover intent if unclear).",
        "list_doctors": "Show doctors: call `list_doctors` (use specialty_filter when relevant).",
        "availability": "Check schedule: call `check_doctor_availability` with doctor_id; only offer listed times.",
        "book": "New booking flow.",
        "reschedule": "Reschedule flow: `verify_patient` → pick appointment id → new slot from availability.",
        "verify": "Lookup: call `verify_patient` with contact on file.",
    }
    lines.append(f"**Detected goal:** {intent_labels.get(snap.intent, snap.intent)}")

    if snap.intent in ("availability", "book", "reschedule"):
        if snap.last_doctor_id:
            lines.append(f"**Last availability check:** doctor_id **{snap.last_doctor_id}**.")
        else:
            lines.append(
                "**Missing:** call `check_doctor_availability` before stating any date or time as free."
            )
        if snap.free_slots:
            lines.append("**Free slots from your last availability tool (only offer these):**")
            lines.append(format_slots_for_prompt(snap.free_slots))

    if snap.intent == "book":
        lines.append(
            "**Booking checklist:** (1) doctor + slot from availability, (2) full name, (3) phone ≥7 digits, "
            "(4) call `validate_booking` with the same fields, (5) short recap, (6) `book_appointment`. "
            "Never say the visit is saved until the tool returns success after patient confirmation."
        )
    elif snap.intent == "reschedule":
        lines.append(
            "**Reschedule checklist:** verify patient → confirm appointment id → availability for new time → "
            "`validate_reschedule` → recap → `reschedule_appointment`."
        )

    if snap.last_tool_error:
        lines.append(
            f"**Last tool error (quote verbatim to patient, then fix):** {snap.last_tool_error}"
        )

    lines.append(
        "**Rules:** Never invent dates/times. On any tool line starting with `Error:`, read it exactly — do not paraphrase as “conflict” or “issue”."
    )
    return "\n".join(lines)


def booking_stage_label(snap: SessionSnapshot) -> str:
    if snap.intent == "book":
        if not snap.last_doctor_id:
            return "choose_doctor"
        if not snap.free_slots:
            return "check_availability"
        return "collect_details"
    if snap.intent == "reschedule":
        return "verify_patient"
    if snap.intent == "availability":
        return "check_availability"
    return "chat"
