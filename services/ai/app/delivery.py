"""只在收到与原载荷一致的有效入库回执后确认出队。"""

from datetime import datetime
from math import isfinite
from uuid import UUID


def _time(value):
    if not isinstance(value, str):
        raise ValueError("缺少时间")
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None or result.utcoffset() is None:
        raise ValueError("时间缺少时区")
    return result


def confirmed_result(body, payload: dict) -> bool:
    if not isinstance(body, dict) or body.get("code") != "OK":
        raise ValueError("缺少成功包装")
    result = body.get("data")
    if not isinstance(result, dict) or type(result.get("accepted")) is not bool:
        raise ValueError("缺少入库结果")
    if not result["accepted"]:
        if result.get("reason") != "LOW_CONFIDENCE" or result.get("record") is not None:
            raise ValueError("未知过滤结果")
        return False
    record = result.get("record")
    if type(result.get("created")) is not bool or not isinstance(record, dict):
        raise ValueError("缺少已保存记录")
    try:
        UUID(record["id"])
        same_class = UUID(record["sessionId"]) == UUID(payload["sessionId"])
        same_time = _time(record["recordedAt"]) == _time(payload["recordedAt"])
    except (KeyError, TypeError, AttributeError):
        raise ValueError("记录标识或时间无效") from None
    score = record.get("confidence")
    if (
        not same_class or not same_time or record.get("emotion") != payload.get("emotion")
        or record.get("source") != "AI" or "userId" not in record or record["userId"] is not None
        or type(score) not in (int, float) or not 0 <= score <= 1 or not isfinite(score)
        or score != payload.get("confidence")
        or type(record.get("simulated", False)) is not bool
        or record.get("simulated", False) != payload.get("simulated", False)
        or record.get("inferenceProvider") != payload.get("inferenceProvider")
        or record.get("confidenceKind") != payload.get("confidenceKind")
        or ("deviceId" in record and record["deviceId"] != payload.get("deviceId"))
    ):
        raise ValueError("入库回执与原载荷不符")
    return True
