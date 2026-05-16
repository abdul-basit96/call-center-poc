import logging
import os
import sys
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

import psycopg2
from psycopg2 import pool
from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

load_dotenv()

logging.basicConfig(level=logging.INFO, stream=sys.stderr, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from backend.booking_guard import (
    normalize_phone,
    validate_booking_args,
    validate_reschedule_args,
)
from backend.embedding_util import get_embedding, is_embedding_loaded, preload_embedding_model
from backend.scheduling_core import (
    doctor_row_text,
    format_doctor_name,
    list_doctors_catalog,
    parse_iso_local,
    render_availability_report,
)

DB_URL = os.getenv("DATABASE_URL")

db_pool = None
try:
    db_pool = psycopg2.pool.SimpleConnectionPool(1, 20, DB_URL)
    logger.info("Database pool ready.")
except Exception as e:
    logger.critical("DB pool failed: %s", e)

mcp = FastMCP("AppointmentSystem")


@contextmanager
def get_db():
    if db_pool is None:
        raise RuntimeError("DATABASE_URL / DB pool not available.")
    conn = db_pool.getconn()
    try:
        yield conn
    finally:
        db_pool.putconn(conn)


@mcp.tool()
def validate_booking(
    patient_name: str | None = None,
    contact_info: str | dict | None = None,
    doctor_id: str | int | None = None,
    appointment_date: str | None = None,
    phone: str | None = None,
) -> str:
    """Dry-run booking checks (identity + slot). contact_info must be a phone number string (7+ digits), not email."""
    contact = normalize_phone(contact_info, phone)
    errors = validate_booking_args(patient_name, contact, doctor_id, appointment_date)
    if errors:
        return "\n".join(errors)
    return (
        "OK: Ready to book. Give the patient a short recap, then call book_appointment "
        "with these exact fields (system will ask them to confirm once)."
    )


@mcp.tool()
def validate_reschedule(appointment_id: str | int | None = None, new_datetime: str | None = None) -> str:
    """Dry-run reschedule checks. Call before reschedule_appointment with the same args."""
    errors = validate_reschedule_args(appointment_id, new_datetime)
    if errors:
        return "\n".join(errors)
    return (
        "OK: Ready to reschedule. Recap appointment id + new time, then call reschedule_appointment "
        "(patient confirms once in the UI)."
    )


@mcp.tool()
def list_doctors(specialty_filter: str | None = None, limit: int | None = None) -> str:
    """List doctors with hours and capacity. specialty_filter: optional text (e.g. 'cardio', 'hair', 'child'). Omit or leave empty for all."""
    sf = (specialty_filter or "").strip()
    lim = 100 if limit is None else int(limit)
    with get_db() as conn:
        with conn.cursor() as cur:
            return list_doctors_catalog(cur, sf, lim)


@mcp.tool()
def check_doctor_availability(doctor_id: str | int | None = None) -> str:
    """Required before telling a patient which times are free. Pass numeric doctor_id from list_doctors. Returns schedule, booked sample, and free start times (next ~14 days, excludes past times today)."""
    try:
        did = int(doctor_id)
    except (ValueError, TypeError):
        return f"Error: Invalid doctor_id '{doctor_id}'."
    with get_db() as conn:
        with conn.cursor() as cur:
            text = render_availability_report(cur, did)
            if text is None:
                return f"Error: No doctor with id {did}."
            return text


@mcp.tool()
def book_appointment(
    patient_name: str | None = None,
    contact_info: str | dict | None = None,
    doctor_id: str | int | None = None,
    appointment_date: str | None = None,
    phone: str | None = None,
) -> str:
    """Book a visit. patient_name, contact_info (phone number string, 7+ digits — no email), doctor_id, appointment_date ISO."""
    contact = normalize_phone(contact_info, phone)
    errors = validate_booking_args(patient_name, contact, doctor_id, appointment_date)
    if errors:
        return "\n".join(errors)
    try:
        did = int(doctor_id)
        start_dt = parse_iso_local(appointment_date or "")
    except (ValueError, TypeError):
        return "Error: Invalid booking fields."

    with get_db() as conn:
        with conn.cursor() as cur:
            try:
                cur.execute(
                    "SELECT name, schedule_start, schedule_end, slot_minutes, schedule_weekdays FROM doctors WHERE id = %s",
                    (did,),
                )
                drow = cur.fetchone()
                if not drow:
                    return f"Error: No doctor id {did}."
                dname, ss, se, sm, wk = drow

                cur.execute(
                    "INSERT INTO patients (name, contact_info) VALUES (%s, %s) "
                    "ON CONFLICT (contact_info) DO UPDATE SET name = EXCLUDED.name RETURNING id",
                    (patient_name, contact),
                )
                patient_id = cur.fetchone()[0]
                cur.execute(
                    "INSERT INTO appointments (patient_id, doctor_id, appointment_date, status) "
                    "VALUES (%s, %s, %s, 'booked') RETURNING id",
                    (patient_id, did, start_dt),
                )
                app_id = cur.fetchone()[0]
                conn.commit()
                return (
                    f"Booked appointment #{app_id}.\n"
                    f"Patient: {patient_name}\nPhone: {contact}\nDoctor: {format_doctor_name(dname)}\nTime: {appointment_date}"
                )
            except Exception as e:
                conn.rollback()
                return f"Database error: {e}"


@mcp.tool()
def reschedule_appointment(appointment_id: str | int | None = None, new_datetime: str | None = None) -> str:
    """Move an appointment. new_datetime: YYYY-MM-DDTHH:MM:SS."""
    errors = validate_reschedule_args(appointment_id, new_datetime)
    if errors:
        return "\n".join(errors)
    try:
        aid = int(appointment_id)
        new_dt = parse_iso_local(new_datetime or "")
    except (ValueError, TypeError):
        return "Error: Invalid reschedule fields."

    with get_db() as conn:
        with conn.cursor() as cur:
            try:
                cur.execute(
                    """
                    SELECT a.id, a.appointment_date, a.status, d.name, d.schedule_start, d.schedule_end,
                           d.slot_minutes, d.schedule_weekdays, a.doctor_id
                    FROM appointments a JOIN doctors d ON a.doctor_id = d.id WHERE a.id = %s
                    """,
                    (aid,),
                )
                row = cur.fetchone()
                if not row:
                    return f"Error: No appointment {aid}."

                _aid, old_dt, _st, doc_name, ss, se, sm, wk, doctor_id = row
                if isinstance(old_dt, datetime) and old_dt.tzinfo:
                    old_dt = old_dt.replace(tzinfo=None)
                old_date = old_dt.strftime("%Y-%m-%d %H:%M")

                cur.execute(
                    "UPDATE appointments SET appointment_date = %s, status = 'rescheduled' WHERE id = %s",
                    (new_datetime, aid),
                )
                conn.commit()
                cur.execute(
                    "SELECT p.name FROM appointments a JOIN patients p ON a.patient_id = p.id WHERE a.id = %s",
                    (aid,),
                )
                pname = cur.fetchone()[0]
                return (
                    f"Rescheduled #{aid}.\nPatient: {pname}\nDoctor: {format_doctor_name(doc_name)}\n"
                    f"Was: {old_date}\nNow: {new_datetime}"
                )
            except Exception as e:
                conn.rollback()
                return f"Database error: {e}"


@mcp.tool()
def verify_patient(
    name: str | None = None,
    contact_info: str | dict | None = None,
    phone: str | None = None,
) -> str:
    """Look up patient by phone number on file; lists active appointments with ids (for reschedule)."""
    contact = normalize_phone(contact_info, phone)
    if not contact:
        return "Error: Phone number is required (contact_info — digits only, no email)."
    if "@" in contact:
        return "Error: Email is not accepted — use the phone number on file."
    digits = sum(1 for c in contact if c.isdigit())
    if digits < 7:
        return "Error: Phone number must include at least 7 digits."
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, name, contact_info FROM patients WHERE contact_info = %s",
                (contact,),
            )
            row = cur.fetchone()
            if not row:
                return f"No patient on file for contact: {contact}. You can still book as a new patient."
            pid, p_name, p_contact = row
            cur.execute(
                """
                SELECT a.id, a.appointment_date, a.status, d.name
                FROM appointments a JOIN doctors d ON a.doctor_id = d.id
                WHERE a.patient_id = %s AND a.status != 'cancelled'
                ORDER BY a.appointment_date
                """,
                (pid,),
            )
            appts = cur.fetchall()
            lines = [f"Patient id {pid}: {p_name} ({p_contact})\nAppointments:"]
            if not appts:
                lines.append("None active.")
            else:
                for a_id, a_date, a_status, d_name in appts:
                    lines.append(f"  #{a_id} — {a_date} — {d_name} ({a_status})")
            return "\n".join(lines)


@mcp.tool()
def search_doctors(query: str, limit: int | None = None) -> str:
    """Find doctors using semantic search (e.g. 'heart expert', 'skin rash', 'pediatrician')."""
    vector = get_embedding(query)
    if not vector:
        return "Error: Could not process semantic search."

    lim = 5 if limit is None else int(limit)
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, name, specialty, schedule_start, schedule_end, slot_minutes, schedule_weekdays
                FROM doctors
                ORDER BY embedding <=> %s::vector
                LIMIT %s
                """,
                (vector, lim),
            )
            rows = cur.fetchall()
            if not rows:
                return "No matching doctors found."

            lines = [doctor_row_text(cur, *r) for r in rows]
            return "Top matches found via semantic search:\n" + "\n".join(lines)


if __name__ == "__main__":
    try:
        logger.info("MCP worker: loading embedding model (required)…")
        preload_embedding_model()
        if not is_embedding_loaded():
            raise RuntimeError("MCP worker failed to load embedding model")
    except Exception as e:
        logger.critical("MCP worker startup failed: %s", e)
        sys.exit(1)
    mcp.run()
