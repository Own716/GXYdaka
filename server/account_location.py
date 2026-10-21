"""只读位置候选；不把下班记录或配置中的旧坐标冒充上班位置。"""
import math
from typing import Any


def _coordinate(value: Any, bound: float):
    if isinstance(value, bool) or value is None or value == "":
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) and -bound <= number <= bound else None


def location_from_mapping(data: Any, source: str):
    if not isinstance(data, dict):
        return None
    latitude = _coordinate(data.get("latitude", data.get("lat")), 90)
    longitude = _coordinate(data.get("longitude", data.get("lng", data.get("lon"))), 180)
    address = next((str(data[k]).strip() for k in (
        "detailAddress", "address", "lastDetailAddress", "jobAddress", "workAddress",
        "practiceAddress", "companyAddress",
    ) if isinstance(data.get(k), str) and data[k].strip()), "")
    if not address and (latitude is None or longitude is None):
        return None
    return {
        "address": address,
        "latitude": latitude,
        "longitude": longitude,
        "province": str(data.get("province") or ""),
        "city": str(data.get("city") or ""),
        "area": str(data.get("area") or data.get("district") or ""),
        "source": source,
    }


def saved_account_location(user_info: Any, plan_info: Any):
    # 仅使用有明确上班位置含义的结构；不把学校/企业地址中的坐标猜成打卡点。
    for info in (user_info, plan_info):
        if not isinstance(info, dict):
            continue
        for key in ("workLocation", "clockInLocation", "checkinLocation"):
            candidate = location_from_mapping(info.get(key), "账号上班位置")
            if candidate:
                return candidate
    return None


def latest_start_location(records: Any):
    if not isinstance(records, list):
        return None
    starts = [row for row in records if isinstance(row, dict)
              and str(row.get("type") or row.get("checkinType") or "").upper() == "START"]
    starts.sort(key=lambda row: str(row.get("attendenceTime") or row.get("createTime") or ""), reverse=True)
    # 始终展示最新上班记录，不用更旧的坐标掩盖最新记录坐标缺失。
    return location_from_mapping(starts[0], "最近上班打卡记录") if starts else None


def account_location_payload(candidate):
    complete = bool(candidate and candidate.get("latitude") is not None and candidate.get("longitude") is not None)
    return {
        "accountLocation": candidate,
        "locationMessage": "已读取上班位置，请核对后点击一键应用；保存后才生效" if complete else (
            "已读取上班地址，但远端未提供有效经纬度，请手动补全后应用" if candidate else
            "未获取到上班位置（本月暂无上班记录或账号未提供位置）；原打卡坐标保持不变"
        ),
    }
