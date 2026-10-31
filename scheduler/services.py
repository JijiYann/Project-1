
from datetime import timedelta

from .models import (
    Classroom,
    LecturerAvailability,
    TeachingSession,
    TimeSlot,
)
def _slots_overlap(slot_a, slot_b):
    """Return True if two time slots overlap on the same weekday."""
    return (
        slot_a.weekday == slot_b.weekday
        and slot_a.start_time < slot_b.end_time
        and slot_a.end_time > slot_b.start_time
    )
def _cross_campus_travel_gap_too_short(
    slot_a,
    campus_a_id,
    slot_b,
    campus_b_id,
    minimum_minutes=45,
):
    """
    Return True when a lecturer has insufficient travel time
    between different campuses on the same weekday.
    """
    if slot_a.weekday != slot_b.weekday:
        return False

    if campus_a_id == campus_b_id:
        return False

    if _slots_overlap(slot_a, slot_b):
        return False

    def minutes_since_midnight(value):
        return value.hour * 60 + value.minute

    a_start = minutes_since_midnight(slot_a.start_time)
    a_end = minutes_since_midnight(slot_a.end_time)
    b_start = minutes_since_midnight(slot_b.start_time)
    b_end = minutes_since_midnight(slot_b.end_time)

    if a_end <= b_start:
        gap = b_start - a_end
    elif b_end <= a_start:
        gap = a_start - b_end
    else:
        return False

    return gap < minimum_minutes

def find_session_conflicts(session):
    """
    Find overlapping sessions in the same academic term that share
    a classroom, lecturer, or student group.
    """
    if not session.pk:
        return []

    slot = session.time_slot

    candidates = (
        TeachingSession.objects
        .filter(
            offering__term_id=session.offering.term_id,
            time_slot__weekday=slot.weekday,
            time_slot__start_time__lt=slot.end_time,
            time_slot__end_time__gt=slot.start_time,
        )
        .exclude(pk=session.pk)
        .select_related("offering", "time_slot", "classroom")
        .prefetch_related("lecturers", "student_groups")
    )

    session_lecturers = set(
        session.lecturers.values_list("id", flat=True)
    )
    session_groups = set(
        session.student_groups.values_list("id", flat=True)
    )

    conflicts = []

    for other in candidates:
        reasons = []

        if other.classroom_id == session.classroom_id:
            reasons.append("Same classroom")

        other_lecturers = set(
            other.lecturers.values_list("id", flat=True)
        )
        if session_lecturers.intersection(other_lecturers):
            reasons.append("Same lecturer")

        other_groups = set(
            other.student_groups.values_list("id", flat=True)
        )
        if session_groups.intersection(other_groups):
            reasons.append("Same student group")

        if reasons:
            conflicts.append({
                "session": other,
                "reasons": reasons,
            })

    return conflicts




def suggest_alternative_classrooms(session):
    """
    Suggest alternative classrooms that are active, on the same campus,
    unoccupied during the proposed time, large enough for the assigned
    student groups, and suitable for laboratory requirements.
    """
    if not session.pk or not session.classroom_id:
        return Classroom.objects.none()

    slot = session.time_slot
    term = session.offering.term
    course = session.offering.course

    candidates = Classroom.objects.filter(
        campus_id=session.classroom.campus_id,
        is_active=True,
    ).exclude(
        pk=session.classroom_id
    )

    session_groups = list(session.student_groups.all())

    required_capacity = sum(
        group.student_count or 0
        for group in session_groups
    )

    suitable_room_ids = []

    for room in candidates:
        # Check that the room has enough capacity.
        if room.capacity < required_capacity:
            continue

        # Check laboratory requirements.
        if course.requires_lab:
            equipment_text = str(room.equipment or "").lower()

            if (
                "lab" not in equipment_text
                and "laboratory" not in equipment_text
            ):
                continue

        # A classroom cannot host another session at an overlapping time.
        room_is_occupied = TeachingSession.objects.filter(
            offering__term=term,
            time_slot__weekday=slot.weekday,
            time_slot__start_time__lt=slot.end_time,
            time_slot__end_time__gt=slot.start_time,
            classroom=room,
        ).exclude(
            pk=session.pk
        ).exists()

        if room_is_occupied:
            continue

        suitable_room_ids.append(room.pk)

    return Classroom.objects.filter(
        pk__in=suitable_room_ids
    ).order_by("building", "name")

from django.db.models import Q


def models_q_effective_date(day):
    return (
        (Q(effective_from__isnull=True) | Q(effective_from__lte=day))
        & (Q(effective_until__isnull=True) | Q(effective_until__gte=day))
    )


def lecturer_is_available_for_term(lecturer, slot, term):
    """
    Check whether an approved recurring availability pattern
    covers this entire time slot on every matching weekday
    during the academic term.

    An approved unavailable period overrides an available period.
    """
    current_date = term.start_date
    has_matching_date = False

    while current_date <= term.end_date:
        if current_date.weekday() == slot.weekday:
            has_matching_date = True

            records = LecturerAvailability.objects.filter(
                lecturer=lecturer,
                weekday=slot.weekday,
                approved=True,
            ).filter(
                models_q_effective_date(current_date)
            )

            available_windows = [
                record for record in records
                if record.is_available
            ]

            unavailable_windows = [
                record for record in records
                if not record.is_available
            ]

            # Availability must be explicitly approved.
            if not any(
                record.start_time <= slot.start_time
                and record.end_time >= slot.end_time
                for record in available_windows
            ):
                return False

            # An approved unavailable period overrides availability.
            if any(
                record.start_time < slot.end_time
                and record.end_time > slot.start_time
                for record in unavailable_windows
            ):
                return False

        current_date += timedelta(days=1)

    return has_matching_date




def suggest_alternative_time_slots(session):
    """
    Suggest active time slots that avoid lecturer, student-group,
    and classroom clashes, and satisfy approved lecturer availability.
    """
    if not session.pk:
        return TimeSlot.objects.none()

    term = session.offering.term

    lecturers = list(session.lecturers.all())
    session_groups = set(
        session.student_groups.values_list("id", flat=True)
    )

    candidates = TimeSlot.objects.filter(
        is_active=True,
    ).exclude(
        pk=session.time_slot_id
    ).order_by(
        "weekday", "start_time"
    )

    suitable_slot_ids = []

    for slot in candidates:
        # Every assigned lecturer must have approved availability
        # covering this entire slot throughout the term.
        if any(
            not lecturer_is_available_for_term(lecturer, slot, term)
            for lecturer in lecturers
        ):
            continue

        overlapping = TeachingSession.objects.filter(
            offering__term=term,
            time_slot__weekday=slot.weekday,
            time_slot__start_time__lt=slot.end_time,
            time_slot__end_time__gt=slot.start_time,
        ).exclude(
            pk=session.pk
        ).prefetch_related(
            "lecturers", "student_groups"
        )

        slot_is_suitable = True

        for other in overlapping:
            other_lecturers = set(
                other.lecturers.values_list("id", flat=True)
            )
            other_groups = set(
                other.student_groups.values_list("id", flat=True)
            )

            if (
                session.classroom_id == other.classroom_id
                or set(l.pk for l in lecturers).intersection(other_lecturers)
                or session_groups.intersection(other_groups)
            ):
                slot_is_suitable = False
                break

        if slot_is_suitable:
            suitable_slot_ids.append(slot.pk)

    return TimeSlot.objects.filter(
        pk__in=suitable_slot_ids
    ).order_by("weekday", "start_time")

def validate_timetable_proposal(proposed_sessions, term):
    """
    Validate a generated timetable proposal without changing the database.

    proposed_sessions is the list returned by generate_timetable_proposal().
    Returns a list of validation errors. An empty list means that the
    checks implemented here passed.
    """
    from .models import CourseOffering

    errors = []
        # Check that every active course offering for this term is included.
    required_offerings = {
        offering.id: offering
        for offering in CourseOffering.objects.filter(
            term=term,
            course__is_active=True,
        ).select_related("course")
    }

    proposed_offering_ids = [
        item.get("offering_id")
        for item in proposed_sessions
    ]

    proposed_offering_id_set = set(proposed_offering_ids)

    missing_offerings = set(required_offerings) - proposed_offering_id_set

    for offering_id in sorted(missing_offerings):
        offering = required_offerings[offering_id]
        errors.append(
            f"{offering.course.code}: missing from the timetable proposal."
        )

    # Check that each offering receives exactly its required weekly hours.
    minutes_by_offering = {}

    for item in proposed_sessions:
        offering_id = item.get("offering_id")

        if offering_id not in required_offerings:
            continue

        try:
            slot = TimeSlot.objects.get(
                name=item["time_slot"],
                is_active=True,
            )
        except (TimeSlot.DoesNotExist, TimeSlot.MultipleObjectsReturned):
            continue

        duration_minutes = (
            slot.end_time.hour * 60 + slot.end_time.minute
            - slot.start_time.hour * 60 - slot.start_time.minute
        )

        minutes_by_offering[offering_id] = (
            minutes_by_offering.get(offering_id, 0) + duration_minutes
        )

    for offering_id, offering in required_offerings.items():
        required_minutes = offering.course.weekly_hours * 60
        actual_minutes = minutes_by_offering.get(offering_id, 0)

        if actual_minutes != required_minutes:
            errors.append(
                f"{offering.course.code}: requires "
                f"{required_minutes} minutes per week, but the proposal "
                f"contains {actual_minutes} minutes."
            )

    # Reject duplicate assignments for the same offering and time slot.
    seen_assignments = set()

    for item in proposed_sessions:
        assignment_key = (
            item.get("offering_id"),
            item.get("time_slot"),
        )

        if assignment_key in seen_assignments:
            errors.append(
                f"{item.get('course_code', 'Unknown course')}: "
                "duplicate assignment for the same time slot."
            )

        seen_assignments.add(assignment_key)
    offerings = {
        offering.id: offering
        for offering in CourseOffering.objects.filter(
            term=term
        ).select_related("course", "term").prefetch_related(
            "lecturers", "student_groups"
        )
    }

    resolved = []

    for index, proposed in enumerate(proposed_sessions, start=1):
        offering = offerings.get(proposed.get("offering_id"))

        if offering is None:
            errors.append(
                f"Session {index}: offering does not belong to this term."
            )
            continue

        try:
            slot = TimeSlot.objects.get(
                name=proposed["time_slot"],
                weekday__in=range(7),
                is_active=True,
            )
        except (TimeSlot.DoesNotExist, TimeSlot.MultipleObjectsReturned):
            errors.append(
                f"Session {index}: time slot could not be uniquely identified."
            )
            continue

        try:
            room = Classroom.objects.get(
                name=proposed["classroom"],
                is_active=True,
            )
        except (Classroom.DoesNotExist, Classroom.MultipleObjectsReturned):
            errors.append(
                f"Session {index}: classroom could not be uniquely identified."
            )
            continue

        lecturers = list(offering.lecturers.all())
        groups = list(offering.student_groups.all())
        
        # Ensure the classroom belongs to every assigned student group's campus.
        for group in groups:
            if group.campus_id != room.campus_id:
                errors.append(
                    f"{offering.course.code}: student group "
                    f"{group.group_name} (ID {group.id}) belongs to "
                    f"{group.campus.name}, but classroom {room.name} "
                    f"is at {room.campus.name}."
                )

        for lecturer in lecturers:
            if not lecturer_is_available_for_term(lecturer, slot, term):
                errors.append(
                    f"{offering.course.code}: {lecturer.full_name} is not "
                    f"approved for {slot.name}."
                )

        required_capacity = sum(
            group.student_count or 0 for group in groups
        )

        if room.capacity < required_capacity:
            errors.append(
                f"{offering.course.code}: {room.name} does not have "
                f"enough capacity ({room.capacity}; required "
                f"{required_capacity})."
            )

        if offering.course.requires_lab:
            equipment = str(room.equipment or "").lower()
            if "lab" not in equipment and "laboratory" not in equipment:
                errors.append(
                    f"{offering.course.code}: {room.name} does not meet "
                    "the laboratory requirement."
                )

        resolved.append({
            "offering": offering,
            "slot": slot,
            "room": room,
            "lecturers": {person.id for person in lecturers},
            "groups": {group.id for group in groups},
            "course_code": offering.course.code,
        })

    # Check all proposed sessions against one another.
        # Check proposed sessions against one another, including travel time.
    for i, first in enumerate(resolved):
        for second in resolved[i + 1:]:
            overlaps = _slots_overlap(first["slot"], second["slot"])
            shared_lecturers = first["lecturers"] & second["lecturers"]

            reasons = []

            if overlaps:
                if first["room"].id == second["room"].id:
                    reasons.append("classroom clash")

                if shared_lecturers:
                    reasons.append("lecturer clash")

                if first["groups"] & second["groups"]:
                    reasons.append("student-group clash")

            if (
                shared_lecturers
                and _cross_campus_travel_gap_too_short(
                    first["slot"],
                    first["room"].campus_id,
                    second["slot"],
                    second["room"].campus_id,
                )
            ):
                reasons.append(
                    "cross-campus travel gap is less than 45 minutes"
                )

            if reasons:
                errors.append(
                    f"{first['course_code']} and {second['course_code']}: "
                    + ", ".join(reasons)
                    + "."
                )

    # Check proposed sessions against existing sessions outside the proposal.
    proposed_offering_ids = {
        item["offering"].id for item in resolved
    }

    fixed_sessions = TeachingSession.objects.filter(
        offering__term=term
    ).exclude(
        offering_id__in=proposed_offering_ids
    ).select_related(
        "time_slot", "classroom", "offering__course"
    ).prefetch_related(
        "lecturers", "student_groups"
    )

    for item in resolved:
        for existing in fixed_sessions:
            overlaps = _slots_overlap(item["slot"], existing.time_slot)

            existing_lecturers = set(
                existing.lecturers.values_list("id", flat=True)
            )
            shared_lecturers = item["lecturers"] & existing_lecturers

            reasons = []

            if overlaps:
                if item["room"].id == existing.classroom_id:
                    reasons.append("classroom clash")

                if shared_lecturers:
                    reasons.append("lecturer clash")

                existing_groups = set(
                    existing.student_groups.values_list("id", flat=True)
                )
                if item["groups"] & existing_groups:
                    reasons.append("student-group clash")

            if (
                shared_lecturers
                and _cross_campus_travel_gap_too_short(
                    item["slot"],
                    item["room"].campus_id,
                    existing.time_slot,
                    existing.classroom.campus_id,
                )
            ):
                reasons.append(
                    "cross-campus travel gap is less than 45 minutes"
                )

            if reasons:
                errors.append(
                    f"{item['course_code']} conflicts with existing "
                    f"{existing.offering.course.code}: "
                    + ", ".join(reasons)
                    + "."
                )

    return errors


def create_timetable_proposal(term, name="Generated timetable proposal"):
    """
    Generate, validate and save a proposal without modifying live sessions.
    """
    from django.db import transaction
    from .generator import generate_timetable_proposal
    from .models import TimetableProposal

    generation = generate_timetable_proposal(term)

    if generation["status"] not in ("OPTIMAL", "FEASIBLE"):
        return {
            "success": False,
            "proposal": None,
            "message": generation["message"],
        }

    proposed_sessions = generation["sessions"]
    errors = validate_timetable_proposal(proposed_sessions, term)

    with transaction.atomic():
        proposal = TimetableProposal.objects.create(
            name=name,
            term=term,
            status="VALIDATED" if not errors else "DRAFT",
            proposal_data=proposed_sessions,
            validation_errors=errors,
        )

    return {
        "success": not errors,
        "proposal": proposal,
        "message": (
            "Proposal saved and validated successfully."
            if not errors
            else "Proposal saved as a draft because validation errors were found."
        ),
    }
from django.db import transaction
from django.core.exceptions import ValidationError
from django.utils import timezone


@transaction.atomic
def publish_timetable_proposal(proposal_id):
    """
    Publish an approved timetable proposal safely.

    This function is intentionally conservative: it validates the proposal
    and checks that the referenced records are unambiguous before changing
    any live timetable sessions.
    """
    from .models import (
        TimetableProposal,
        TeachingSession,
        CourseOffering,
        TimeSlot,
        Classroom,
    )

    proposal = (
        TimetableProposal.objects
        .select_for_update()
        .select_related("term")
        .get(pk=proposal_id)
    )

    if proposal.status != "APPROVED":
        raise ValidationError(
            "Only an approved timetable proposal can be published."
        )

    if not proposal.proposal_data:
        raise ValidationError("The proposal contains no timetable sessions.")

    # Revalidate the proposal before making any changes.
    errors = validate_timetable_proposal(proposal.proposal_data, proposal.term)

    if errors:
        proposal.validation_errors = errors
        proposal.save(update_fields=["validation_errors", "updated_at"])
        raise ValidationError(
            "Publishing stopped because validation failed. Review the proposal errors."
        )

    resolved_sessions = []

    # Resolve every record before changing the live timetable.
    for item in proposal.proposal_data:
        offering = CourseOffering.objects.filter(
            pk=item["offering_id"],
            term=proposal.term,
        ).first()

        if offering is None:
            raise ValidationError(
                f"Course offering {item.get('offering_id')} was not found "
                "in this academic term."
            )

        slot_matches = TimeSlot.objects.filter(
            name=item["time_slot"],
            is_active=True,
            start_time=item["start_time"],
            end_time=item["end_time"],
        )

        # Match the displayed weekday to the actual weekday field.
        matching_slots = [
            slot for slot in slot_matches
            if slot.get_weekday_display() == item["day"]
        ]

        if len(matching_slots) != 1:
            raise ValidationError(
                f"Could not uniquely identify the time slot "
                f"'{item['time_slot']}' on {item['day']}."
            )

        room_matches = Classroom.objects.filter(
            name=item["classroom"],
            is_active=True,
        )

        if room_matches.count() != 1:
            raise ValidationError(
                f"Could not uniquely identify classroom "
                f"'{item['classroom']}'. "
                "Room names must be unambiguous before publishing."
            )

       
        room = room_matches.first()

        # Enforce campus consistency for every student group.
        for group in offering.student_groups.select_related("campus"):
            if group.campus_id != room.campus_id:
                raise ValidationError(
                    f"{offering.course.code}: student group "
                    f"{group.group_name} (ID {group.id}) belongs to "
                    f"{group.campus.name}, but classroom {room.name} "
                    f"is at {room.campus.name}."
                )

        # Add the proposed session once, after all groups pass validation.
        resolved_sessions.append({
            "offering": offering,
            "time_slot": matching_slots[0],
            "classroom": room,
        })

    # Do not replace sessions until every proposal entry has been resolved.
    offering_ids = {
        item["offering"].id for item in resolved_sessions
    }

    # Replace only sessions belonging to offerings in this proposal.
    # Sessions for other offerings and academic terms are preserved.
    TeachingSession.objects.filter(
        offering_id__in=offering_ids,
        offering__term=proposal.term,
    ).delete()

    for item in resolved_sessions:
        offering = item["offering"]

        session = TeachingSession.objects.create(
            offering=offering,
            time_slot=item["time_slot"],
            classroom=item["classroom"],
            is_published=True,
        )

        session.student_groups.set(offering.student_groups.all())
        session.lecturers.set(offering.lecturers.all())

    proposal.status = "PUBLISHED"
    proposal.validation_errors = []
    proposal.save(update_fields=[
        "status",
        "validation_errors",
        "updated_at",
    ])

    return len(resolved_sessions)


@transaction.atomic
def approve_timetable_proposal(proposal_id):
    """
    Approve a validated timetable proposal without publishing it.
    """

    from .models import TimetableProposal

    proposal = (
        TimetableProposal.objects
        .select_for_update()
        .select_related("term")
        .get(pk=proposal_id)
    )

    if proposal.status != "VALIDATED":
        raise ValidationError(
            "Only a validated proposal can be approved."
        )

    if not proposal.proposal_data:
        raise ValidationError(
            "Cannot approve an empty timetable proposal."
        )

    if proposal.validation_errors:
        raise ValidationError(
            "This proposal still contains validation errors."
        )

    # Revalidate immediately before approval.
    errors = validate_timetable_proposal(
        proposal.proposal_data,
        proposal.term,
    )

    if errors:
        proposal.status = "DRAFT"
        proposal.validation_errors = errors
        proposal.save(update_fields=[
            "status",
            "validation_errors",
            "updated_at",
        ])
        return proposal

    # No errors: approve, but do not publish.
    proposal.status = "APPROVED"
    proposal.save(update_fields=[
        "status",
        "updated_at",
    ])

    return proposal
