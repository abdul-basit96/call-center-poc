"""Shared doctor schedule / availability logic used by the MCP server and the FastAPI chat layer."""

from __future__ import annotations

import re
from datetime import date, datetime, time, timedelta


def format_doctor_name(name: str) -> str:
    n = (name or "").strip()
    if not n:
        return "Doctor"
    lower = n.lower()
    if lower.startswith("dr.") or lower.startswith("dr "):
        return n
    return f"Dr. {n}"


def weekday_set(csv: str) -> set[int]:
    return {int(x.strip()) for x in csv.split(",") if x.strip().isdigit()}


def time_to_minutes(t: time) -> int:
    return t.hour * 60 + t.minute


def slots_per_day(schedule_start: time, schedule_end: time, slot_minutes: int) -> int:
    span = time_to_minutes(schedule_end) - time_to_minutes(schedule_start)
    if span <= 0 or slot_minutes <= 0:
        return 0
    return span // slot_minutes


def iter_slot_starts(day: date, schedule_start: time, schedule_end: time, slot_minutes: int) -> list[datetime]:
    out: list[datetime] = []
    t = datetime.combine(day, schedule_start)
    end_dt = datetime.combine(day, schedule_end)
    slot = timedelta(minutes=slot_minutes)
    while t + slot <= end_dt:
        out.append(t)
        t += slot
    return out


def intervals_overlap_half_open(a0: datetime, a1: datetime, b0: datetime, b1: datetime) -> bool:
    return a0 < b1 and b0 < a1


def day_booking_count(cur, doctor_id: int, day: date) -> int:
    cur.execute(
        """
        SELECT COUNT(*) FROM appointments
        WHERE doctor_id = %s AND status <> 'cancelled'
          AND appointment_date::date = %s
        """,
        (doctor_id, day),
    )
    return int(cur.fetchone()[0])


def slot_overlaps_existing(
    cur,
    doctor_id: int,
    new_start: datetime,
    slot_minutes: int,
    ignore_appointment_id: int | None = None,
) -> bool:
    slot = timedelta(minutes=slot_minutes)
    new_end = new_start + slot
    cur.execute(
        """
        SELECT id, appointment_date FROM appointments
        WHERE doctor_id = %s AND status <> 'cancelled'
          AND appointment_date::date = %s
        """,
        (doctor_id, new_start.date()),
    )
    for eid, estart in cur.fetchall():
        if ignore_appointment_id is not None and eid == ignore_appointment_id:
            continue
        if isinstance(estart, datetime) and estart.tzinfo is not None:
            estart = estart.replace(tzinfo=None)
        eend = estart + slot
        if intervals_overlap_half_open(new_start, new_end, estart, eend):
            return True
    return False


def format_time_hm(t: time) -> str:
    return t.strftime("%I:%M %p")


def schedule_blurb(start: time, end: time, slot_m: int, weekdays_csv: str) -> str:
    names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    allowed = sorted(weekday_set(weekdays_csv))
    daypart = ",".join(names[i - 1] for i in allowed if 1 <= i <= 7) if allowed else "by appointment"
    return (
        f"{daypart} {format_time_hm(start)}–{format_time_hm(end)}, "
        f"{slot_m} min slots (max {slots_per_day(start, end, slot_m)} appointments/day)"
    )


def weekday_allowlist_words(weekdays_csv: str) -> str:
    """Human-readable clinic days from schedule_weekdays CSV (1=Mon … 7=Sun)."""
    allowed = sorted(weekday_set(weekdays_csv))
    if not allowed:
        return "as posted"
    full = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    return ", ".join(full[i - 1] for i in allowed if 1 <= i <= 7)


def remaining_slots_next_days(
    cur,
    doctor_id: int,
    schedule_start: time,
    schedule_end: time,
    slot_minutes: int,
    weekdays_csv: str,
    horizon_days: int = 7,
) -> tuple[int, int]:
    allowed = weekday_set(weekdays_csv)
    today = date.today()
    cap_sum = 0
    free_sum = 0
    for i in range(horizon_days):
        d = today + timedelta(days=i)
        if allowed and d.isoweekday() not in allowed:
            continue
        anchors = iter_slot_starts(d, schedule_start, schedule_end, slot_minutes)
        cap = len(anchors)
        if cap == 0:
            continue
        booked = day_booking_count(cur, doctor_id, d)
        cap_sum += cap
        free_sum += max(0, cap - booked)
    return cap_sum, free_sum


def render_availability_report(cur, doctor_id: int) -> str | None:
    """Return the same narrative as MCP `check_doctor_availability`, or None if doctor missing."""
    cur.execute(
        """
        SELECT name, specialty, schedule_start, schedule_end, slot_minutes, schedule_weekdays
        FROM doctors WHERE id = %s
        """,
        (doctor_id,),
    )
    row = cur.fetchone()
    if not row:
        return None
    name, spec, ss, se, sm, wk = row
    spd = slots_per_day(ss, se, sm)
    cap7, free7 = remaining_slots_next_days(cur, doctor_id, ss, se, sm, wk, 7)

    cur.execute(
        """
        SELECT appointment_date, status FROM appointments
        WHERE doctor_id = %s AND status <> 'cancelled'
          AND appointment_date::date >= CURRENT_DATE
        ORDER BY appointment_date ASC
        LIMIT 40
        """,
        (doctor_id,),
    )
    appts = cur.fetchall()

    busy_lines = "\n".join(f"- {a[0].strftime('%Y-%m-%d %I:%M %p')} ({a[1]})" for a in appts) or "(none in the near window)"

    free_samples: list[str] = []
    today = date.today()
    now = datetime.now()
    for i in range(14):
        d = today + timedelta(days=i)
        if weekday_set(wk) and d.isoweekday() not in weekday_set(wk):
            continue
        day_slots = []
        for slot_start in iter_slot_starts(d, ss, se, sm):
            if slot_start <= now:
                continue
            if not slot_overlaps_existing(cur, doctor_id, slot_start, sm, None):
                day_slots.append(slot_start.strftime("%I:%M %p"))
        if day_slots:
            free_samples.append(f"- {d.strftime('%Y-%m-%d')}: {', '.join(day_slots)}")

    openings = "\n".join(free_samples) if free_samples else (
        "(no free slots found in the next two weeks at current booking volume)"
    )

    cal_lines: list[str] = []
    for i in range(21):
        d = today + timedelta(days=i)
        wd = d.strftime("%A")
        if weekday_set(wk) and d.isoweekday() not in weekday_set(wk):
            cal_lines.append(f"- {d.strftime('%Y-%m-%d')} ({wd}) — not a clinic day for this doctor")
        else:
            cal_lines.append(f"- {d.strftime('%Y-%m-%d')} ({wd})")
    calendar_block = "\n".join(cal_lines)

    return (
        f"Doctor ID: {doctor_id} — {format_doctor_name(name)} ({spec})\n"
        f"**Stored schedule:** {schedule_blurb(ss, se, sm, wk)}\n"
        f"**Next 7 days:** about {free7} free slots out of {cap7} slot-capacity (each new booking consumes one slot).\n\n"
        f"**Already booked (sample / near future):**\n{busy_lines}\n\n"
        f"**Next available start times (sample):**\n{openings}\n\n"
        "**Dates vs weekdays (server clock — use this to map “Wednesday” / “20 May” to YYYY-MM-DD):**\n"
        f"{calendar_block}\n\n"
        f"This doctor sees patients on: **{weekday_allowlist_words(wk)}**.\n"
        "Bookings must use a date that is both a clinic day above and a time on the slot grid from the schedule start."
    )


def parse_iso_local(s: str) -> datetime:
    dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    if dt.tzinfo is not None:
        dt = dt.replace(tzinfo=None)
    return dt


def validate_slot_request(
    dt: datetime,
    schedule_start: time,
    schedule_end: time,
    slot_minutes: int,
    weekdays_csv: str,
) -> str | None:
    if dt <= datetime.now():
        return "Error: That start time is already in the past. Pick a future slot from check_doctor_availability."
    allowed = weekday_set(weekdays_csv)
    if allowed and dt.isoweekday() not in allowed:
        return (
            f"Error: {dt.strftime('%Y-%m-%d')} is a {dt.strftime('%A')}; this doctor only sees patients on "
            f"{weekday_allowlist_words(weekdays_csv)}. Use the calendar in check_doctor_availability to pick a clinic day."
        )

    sm = time_to_minutes(dt.time())
    start_m = time_to_minutes(schedule_start)
    end_m = time_to_minutes(schedule_end)
    if sm < start_m or sm >= end_m:
        return (
            "Error: Time is outside this doctor's scheduled hours "
            f"({format_time_hm(schedule_start)}–{format_time_hm(schedule_end)})."
        )
    if (sm - start_m) % slot_minutes != 0:
        return (
            f"Error: Appointments start every {slot_minutes} minutes from {format_time_hm(schedule_start)} "
            f"(e.g. align to that grid). Pick a time that matches check_doctor_availability."
        )
    if sm + slot_minutes > end_m:
        return "Error: Appointment would extend past this doctor's end of day."
    return None


def doctor_row_text(cur, doc_id: int, name: str, spec: str, ss: time, se: time, sm: int, wk: str) -> str:
    """One doctor block: ID, name, specialty, clinic hours, 7-day slot capacity (live from DB)."""
    cap7, free7 = remaining_slots_next_days(cur, doc_id, ss, se, sm, wk, 7)
    sched = schedule_blurb(ss, se, sm, wk)
    return (
        f"- Doctor ID: {doc_id}, Name: {format_doctor_name(name)}, Specialty: {spec}\n"
        f"  **Clinic schedule:** {sched}\n"
        f"  **Next 7 days (approx):** {free7} open slots out of {cap7} total slot-capacity (bookings reduce availability)."
    )


def specialty_filter_token(user_filter: str) -> str:
    """Map common phrases to substrings that match our `doctors.specialty` column (ILIKE)."""
    t = (user_filter or "").strip().lower()
    if not t:
        return ""
    if re.search(r"\b(hair|scalp|alopecia|skin|rash|acne|mole|nail|dermat)\b", t):
        return "derma"
    if re.search(r"\b(heart|cardio|cardiac|chest|hypertension)\b", t):
        return "cardio"
    if re.search(r"\b(child|kid|children|pediat|infant|baby|toddler)\b", t):
        return "pediat"
    return (user_filter or "").strip()


def list_doctors_catalog(cur, specialty_filter: str = "", limit: int = 100) -> str:
    """Return a multi-doctor roster string from the database (no embeddings)."""
    lim = min(max(int(limit), 1), 200)
    raw = (specialty_filter or "").strip()
    sf = specialty_filter_token(raw) if raw else ""
    if sf:
        cur.execute(
            """
            SELECT id, name, specialty, schedule_start, schedule_end, slot_minutes, schedule_weekdays
            FROM doctors
            WHERE specialty ILIKE %s
            ORDER BY id
            LIMIT %s
            """,
            (f"%{sf}%", lim),
        )
    else:
        cur.execute(
            """
            SELECT id, name, specialty, schedule_start, schedule_end, slot_minutes, schedule_weekdays
            FROM doctors
            ORDER BY id
            LIMIT %s
            """,
            (lim,),
        )
    rows = cur.fetchall()
    if not rows:
        return (
            "No doctors in the database match that filter."
            if sf
            else "No doctors are on file in the database."
        )
    lines = [doctor_row_text(cur, *r) for r in rows]
    return "Available doctors (from database):\n" + "\n".join(lines)


def render_doctor_directory_block(cur, user_text_lower: str) -> str | None:
    """Build per-doctor rows (hours + 7-day capacity), optionally filtered by specialty."""
    tl = (user_text_lower or "").lower()
    extra = ""
    params: list = []
    if re.search(r"cardio|heart\s+doctor|heart\s+special", tl):
        extra = " AND specialty ILIKE %s"
        params.append("%cardio%")
    elif re.search(r"dermat|skin\s+doctor|skin\s+special", tl):
        extra = " AND specialty ILIKE %s"
        params.append("%derma%")

    cur.execute(
        f"""
        SELECT id, name, specialty, schedule_start, schedule_end, slot_minutes, schedule_weekdays
        FROM doctors
        WHERE 1=1 {extra}
        ORDER BY id
        """,
        params,
    )
    rows = cur.fetchall()
    if not rows:
        return None

    lines = [doctor_row_text(cur, *r) for r in rows]

    preamble = (
        "Each doctor below includes **clinic hours / weekdays**, **slot length**, **max visits per day**, "
        "and **approximate openings in the next 7 days**. Reproduce every bullet for every doctor for the patient "
        "before suggesting booking.\n\n"
    )
    return preamble + "Available doctors:\n" + "\n".join(lines)


def extract_doctor_ids_from_text(text: str) -> list[int]:
    """Parse 'Doctor ID: 3' lines from assistant search output."""
    return [int(x) for x in re.findall(r"(?i)doctor\s*id\s*[:#]?\s*(\d+)", text)]


_NAME_STOPWORDS = frozenset(
    {"doctor", "dr", "the", "and", "for", "with", "medicine", "general", "internal", "family"}
)


def resolve_doctor_id_for_availability(user_text: str, transcript: str, cur) -> int | None:
    """Prefer name tokens from the latest user message; otherwise use last Doctor ID from transcript."""
    tl = (user_text or "").lower()
    cur.execute("SELECT id, name FROM doctors ORDER BY id")
    rows = cur.fetchall()

    best_name_id: int | None = None
    best_score = 0
    for did, nm in rows:
        tokens = [
            t
            for t in re.findall(r"[a-z]{3,}", (nm or "").lower())
            if t not in _NAME_STOPWORDS
        ]
        score = sum(len(t) for t in tokens if t in tl)
        if score > best_score:
            best_score = score
            best_name_id = did

    if best_score >= 3:
        return best_name_id

    ids = extract_doctor_ids_from_text(transcript)
    if ids:
        last = ids[-1]
        cur.execute("SELECT 1 FROM doctors WHERE id = %s", (last,))
        if cur.fetchone():
            return last

    return best_name_id if best_score > 0 else None
