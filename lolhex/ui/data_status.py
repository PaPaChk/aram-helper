"""資料來源一行字（主視窗和浮窗共用），文字都已轉義。"""
from datetime import datetime, timedelta, timezone
from html import escape


def _bjt(value, fmt="%m-%d"):
    try:
        stamp = datetime.fromisoformat(str(value))
        if stamp.tzinfo is not None:
            return stamp.astimezone(timezone(timedelta(hours=8))).strftime(fmt)
    except (TypeError, ValueError):
        pass
    return ""


def data_status_html(d):
    if not d.get("dataset"):
        parts = ["沒有統計資料"]
    else:
        parts = ([d["dataset_mode_label"]] if d.get("dataset_mode_label") else []) + [f"{d.get('dataset_patch')} 版本"]
        matches = d.get("dataset_matches")
        if isinstance(matches, int):
            parts.append(f"{matches / 10000:.0f} 萬局")
        day = _bjt(d.get("dataset_snapshot"))
        if day:
            parts.append(f"截至 {day}")
        if d.get("patch") and d.get("dataset_patch") and d["patch"] != d["dataset_patch"]:
            parts.append(f"遊戲已更新到 {d['patch']}，統計資料還沒更新")
    if d.get("event_fallback") and d.get("event_label"):
        parts.append(f"{d['event_label']}的資料還沒出，先用常規")
    if d.get("error"):
        parts.append("官方資料獲取失敗")
    return escape(" · ".join(parts))
