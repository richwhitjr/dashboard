EMAIL_TO_EMPLOYEE: dict[str, str] = {}
NAME_TO_EMPLOYEE: dict[str, str] = {}


def _get_email_domain() -> str:
    """Get the user's email domain from profile config."""
    try:
        from app_config import get_profile

        return get_profile().get("user_email_domain", "")
    except Exception:
        return ""


def _get_user_email() -> str:
    """Get the user's email from profile config."""
    try:
        from app_config import get_profile

        return get_profile().get("user_email", "")
    except Exception:
        return ""


def build_employee_mapping(employees: list[dict]):
    global EMAIL_TO_EMPLOYEE, NAME_TO_EMPLOYEE
    EMAIL_TO_EMPLOYEE.clear()
    NAME_TO_EMPLOYEE.clear()

    domain = _get_email_domain()

    for emp in employees:
        name = emp["name"]
        emp_id = emp["id"]
        parts = name.lower().split()

        NAME_TO_EMPLOYEE[name.lower()] = emp_id

        if len(parts) >= 2:
            first, last = parts[0], parts[-1]
            if domain:
                EMAIL_TO_EMPLOYEE[f"{first}@{domain}"] = emp_id
                EMAIL_TO_EMPLOYEE[f"{first}.{last}@{domain}"] = emp_id
                EMAIL_TO_EMPLOYEE[f"{first[0]}{last}@{domain}"] = emp_id
                EMAIL_TO_EMPLOYEE[f"{last}@{domain}"] = emp_id
            NAME_TO_EMPLOYEE[first] = emp_id
            NAME_TO_EMPLOYEE[last] = emp_id
            NAME_TO_EMPLOYEE[f"{first} {last}"] = emp_id

            # Common nicknames / short names
            NICKNAMES = {
                "benjamin": ["ben"],
                "michael": ["mike"],
                "katherine": ["kate"],
                "samuel": ["sam"],
                "richard": ["rich", "rick"],
                "william": ["will"],
                "alexander": ["alex"],
                "nicholas": ["nick"],
                "elizabeth": ["liz", "beth"],
                "frances": ["fran"],
                "guillaume": ["gui"],
            }
            for nick in NICKNAMES.get(first, []):
                NAME_TO_EMPLOYEE[nick] = emp_id
                if domain:
                    EMAIL_TO_EMPLOYEE[f"{nick}@{domain}"] = emp_id


def rebuild_from_db():
    """Rebuild employee matching maps from database."""
    from database import get_db_connection

    with get_db_connection(readonly=True) as db:
        rows = db.execute("SELECT id, name FROM employees").fetchall()
    build_employee_mapping([dict(r) for r in rows])


def match_email_to_employee(email: str) -> str | None:
    return EMAIL_TO_EMPLOYEE.get(email.lower())


def match_name_to_employee(name: str) -> str | None:
    return NAME_TO_EMPLOYEE.get(name.lower())


def get_employee_email_patterns(employee_id: str) -> list[str]:
    """Return all email patterns that could match this employee in calendar attendees."""
    return [email for email, eid in EMAIL_TO_EMPLOYEE.items() if eid == employee_id]


def match_attendees_to_employee(attendees: list[dict], exclude_email: str | None = None) -> str | None:
    """Given meeting attendees, find the non-user employee."""
    if exclude_email is None:
        exclude_email = _get_user_email()

    user_local = exclude_email.split("@")[0].lower() if exclude_email else ""

    for a in attendees:
        email = a.get("email", "").lower()
        name = a.get("name", "").lower()

        if exclude_email and exclude_email.lower() in email:
            continue
        if user_local and user_local == email.split("@")[0]:
            continue

        match = match_email_to_employee(email)
        if match:
            return match
        match = match_name_to_employee(name)
        if match:
            return match

    return None
