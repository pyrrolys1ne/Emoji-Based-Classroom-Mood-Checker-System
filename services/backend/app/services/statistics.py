import csv
import io
import re
from collections import defaultdict
from datetime import timedelta, timezone

from app.core.config import get_settings
from app.core.domain import Emotion
from app.db.session import transaction
from app.repositories.statistics import StatisticsRepository
from app.schemas.contracts import (
    EmotionStatistics, ExportFilters, MultidimensionalStatistics, StatisticsBucket,
    StatisticsFilters, StatisticsGroup,
)
from app.services.accounts import Principal
from app.services.record_scope import authorize_records


def statistics(principal: Principal, filters: StatisticsFilters, *, multidimensional=False):
    with transaction() as session:
        actor = authorize_records(session, principal, filters, aggregate=True)
        rows = StatisticsRepository(session).counts(actor.role, actor.id, filters,
            allow_simulated=get_settings().allow_simulated_ai, multidimensional=multidimensional)
        distribution = {emotion: 0 for emotion in Emotion}
        if not multidimensional:
            for emotion, count in rows:
                distribution[emotion] += count
            result = EmotionStatistics(total=sum(distribution.values()), distribution=distribution, source=filters.source)
        else:
            minutes = defaultdict(int)
            groups = {}
            for emotion, minute, course_id, course_name, class_name, source, count in rows:
                distribution[emotion] += count
                minutes[minute.astimezone(timezone.utc)] += count
                group = groups.setdefault((course_id, class_name), StatisticsGroup(
                    course_id=course_id, course_name=course_name, class_name=class_name, total=0, manual=0, ai=0))
                group.total += count
                if source == "MANUAL":
                    group.manual += count
                else:
                    group.ai += count
            timeline = []
            if minutes:
                first, last = min(minutes), max(minutes)
                span_minutes = int((last - first).total_seconds() // 60) + 1
                step_minutes = max(1, (span_minutes + 11) // 12)
                step = timedelta(minutes=step_minutes)
                totals = [0] * ((span_minutes + step_minutes - 1) // step_minutes)
                for minute, count in minutes.items():
                    totals[(minute - first) // step] += count
                timeline = [StatisticsBucket(starts_at=first + index * step,
                    ends_at=first + (index + 1) * step, total=count) for index, count in enumerate(totals)]
            result = MultidimensionalStatistics(total=sum(distribution.values()), distribution=distribution,
                source=filters.source, timeline=timeline,
                groups=sorted(groups.values(), key=lambda group: (group.course_name, str(group.course_id), group.class_name)))
    return result


CSV_COLUMNS = ["记录编号", "课堂编号", "用户编号", "用户", "学号", "课程", "班级", "情绪", "来源",
    "模型分数", "记录时间", "设备标识", "模拟输入", "推理提供方", "分数类型"]


def csv_value(value) -> str:
    text = "" if value is None else str(value)
    if re.match(r"^[\s\ufeff]*[=+@-]|^[\t\r\n]", text):
        return "'" + text
    return text


def export_csv(principal: Principal, filters: ExportFilters) -> str:
    with transaction() as session:
        actor = authorize_records(session, principal, filters, admin=True)
        repo = StatisticsRepository(session)
        rows = repo.export_rows(actor.role, actor.id, filters, allow_simulated=get_settings().allow_simulated_ai)
        output = io.StringIO(newline="")
        writer = csv.writer(output, quoting=csv.QUOTE_ALL, lineterminator="\r\n")
        writer.writerow(CSV_COLUMNS)
        for record, classroom, course_name, _teacher, student in rows:
            writer.writerow([csv_value(value) for value in (
                record.id, record.session_id, record.user_id,
                (student.real_name or student.username) if student else "匿名", student.student_no if student else None,
                course_name, classroom.class_name, record.emotion, record.source, record.confidence,
                record.recorded_at.astimezone(timezone.utc).isoformat(), record.device_id,
                "是" if record.simulated else "否", record.inference_provider, record.confidence_kind,
            )])
        repo.audit_export(actor.id, filters.session_id)
        result = "\ufeff" + output.getvalue()
    return result
