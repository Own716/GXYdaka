"""Pure helpers for pre-filling an account profile from remote account data."""
from typing import Any

from server.account_location import location_from_mapping


_PROFILE_FIELDS = (
    "name",
    "schoolName",
    "companyName",
    "companyAddress",
    "jobAddress",
    "planName",
)


def _mapping(value: Any) -> dict:
    return value if isinstance(value, dict) else {}


def _text(*values: Any) -> str:
    """Return the first non-empty string; never stringify arbitrary objects."""
    for value in values:
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def build_profile(user_info, plan_info, job_info) -> dict:
    """Build a fixed, safe profile from the platform's account/plan/job shapes.

    Only known string-valued fields are copied. Sensitive fields and arbitrary
    nested objects are never propagated into the returned profile.
    """
    user = _mapping(user_info)
    # Accept a full config-shaped object as well as the userInfo object itself.
    user_data = _mapping(user.get("userInfo")) or user
    org = _mapping(user_data.get("orgJson"))
    plan = _mapping(plan_info)
    job = _mapping(job_info)
    company = _mapping(job.get("practiceCompanyEntity"))

    return {
        "name": _text(user_data.get("nikeName"), user_data.get("nickName"), user_data.get("name")),
        "schoolName": _text(org.get("orgName"), org.get("schoolName"), user_data.get("schoolName")),
        "companyName": _text(company.get("companyName")),
        "companyAddress": _text(company.get("companyAddress"), company.get("address"), job.get("companyAddress")),
        "jobAddress": _text(job.get("jobAddress"), job.get("address")),
        "planName": _text(plan.get("planName")),
    }


def _has_coordinates(candidate: Any) -> bool:
    return bool(
        isinstance(candidate, dict)
        and candidate.get("latitude") is not None
        and candidate.get("longitude") is not None
    )


def _safe_location(data, source):
    if not isinstance(data, dict):
        return None
    clean = dict(data)
    for key in ("province", "city", "area", "district"):
        clean[key] = _text(data.get(key))
    return location_from_mapping(clean, source)


def job_location(job_info) -> dict | None:
    """Return the best semantically supported job-location candidate, if any.

    Explicit clock/work-location mappings take precedence. Job-level coordinates
    precede enterprise coordinates; enterprise coordinates are rejected when
    the job address identifies a different location. No geocoding or inference
    from school/city data is performed.
    """
    if not isinstance(job_info, dict):
        return None

    job_address = _text(job_info.get("jobAddress"), job_info.get("address"))
    incomplete = None
    for key in ("workLocation", "clockInLocation", "checkinLocation"):
        candidate = _safe_location(job_info.get(key), "实习岗位位置")
        if candidate is not None:
            if _has_coordinates(candidate):
                if not candidate["address"]:
                    candidate["address"] = job_address
                return candidate
            incomplete = incomplete or candidate

    # Job-level coordinates are usable only as explicit job coordinates and
    # are labeled with the platform's job address (never an enterprise address).
    coordinate_keys = ("latitude", "longitude", "lat", "lng", "lon")
    location_keys = coordinate_keys + ("province", "city", "area", "district")
    job_mapping = {key: job_info[key] for key in location_keys if key in job_info}
    if job_address:
        job_mapping["jobAddress"] = job_address
    candidate = _safe_location(job_mapping, "实习岗位位置")
    if job_address and _has_coordinates(candidate):
        return candidate

    company = _mapping(job_info.get("practiceCompanyEntity"))
    company_address = _text(company.get("companyAddress"), company.get("address"))
    if not company_address:
        company_address = _text(job_info.get("companyAddress"))
    job_address_key = job_address.casefold()
    company_address_key = company_address.casefold()
    enterprise_location_allowed = not job_address or (
        bool(company_address) and job_address_key == company_address_key
    )

    if enterprise_location_allowed:
        company_mapping = {
            key: company[key] for key in location_keys if key in company
        }
        if company_address:
            company_mapping["address"] = company_address
        candidate = _safe_location(company_mapping, "实习企业位置")
        if _has_coordinates(candidate):
            return candidate

    # Preserve a known job address for the UI to display, without inventing
    # coordinates or substituting a conflicting enterprise address.
    if incomplete:
        return incomplete
    if job_address:
        return _safe_location(job_mapping, "实习岗位位置")
    return None
