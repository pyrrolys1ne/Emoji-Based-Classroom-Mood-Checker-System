from datetime import timezone

from app.schemas.contracts import ClassroomStudent, ClassroomSummary, EmojiRecord


def record_response(row) -> EmojiRecord:
    record, classroom, course_name, teacher, student = row
    return EmojiRecord(
        id=record.id, user_id=record.user_id, session_id=record.session_id,
        emotion=record.emotion, source=record.source, confidence=record.confidence,
        recorded_at=record.recorded_at.astimezone(timezone.utc), simulated=record.simulated,
        inference_provider=record.inference_provider, confidence_kind=record.confidence_kind,
        classroom=ClassroomSummary(
            id=classroom.id, course_id=classroom.course_id, course_name=course_name,
            teacher_id=classroom.teacher_id, teacher_name=teacher.real_name or teacher.username,
            class_name=classroom.class_name, room=classroom.room,
            starts_at=classroom.starts_at.astimezone(timezone.utc), ends_at=classroom.ends_at.astimezone(timezone.utc),
        ),
        student=ClassroomStudent(
            id=student.id, username=student.username, student_no=student.student_no,
            real_name=student.real_name, class_name=student.class_name, status=student.status,
        ) if student is not None else None,
    )
