
from datetime import datetime, timedelta

from ortools.sat.python import cp_model

from .models import (
    Classroom,
    CourseOffering,
    TeachingSession,
    TimeSlot,
)
from .services import (
    lecturer_is_available_for_term,
    _cross_campus_travel_gap_too_short,
)


def _slot_duration_minutes(slot):
    """Return the duration of a time slot in minutes."""
    start = datetime.combine(datetime.today(), slot.start_time)
    end = datetime.combine(datetime.today(), slot.end_time)
    return int((end - start).total_seconds() // 60)


def _slots_overlap(slot_a, slot_b):
    """Return True if two slots overlap on the same weekday."""
    return (
        slot_a.weekday == slot_b.weekday
        and slot_a.start_time < slot_b.end_time
        and slot_a.end_time > slot_b.start_time
    )


def _room_meets_course_requirements(room, offering, groups):
    """Check capacity and basic laboratory requirements."""
    required_capacity = sum(
        group.student_count or 0 for group in groups
    )

    if room.capacity < required_capacity:
        return False

    if offering.course.requires_lab:
        equipment = str(room.equipment or "").lower()

        if "lab" not in equipment and "laboratory" not in equipment:
            return False

    return True


def generate_timetable_proposal(term):
    """
    Generate a timetable proposal using Google OR-Tools.

    Hard constraints:
    - Each offering receives its required weekly teaching hours.
    - Only approved lecturer availability is accepted.
    - Lecturers, student groups and classrooms cannot clash.
    - Rooms must have sufficient capacity.
    - Courses requiring laboratories need a room whose equipment
      description identifies it as a lab or laboratory.

    Existing sessions belonging to the offerings being regenerated
    are excluded from fixed-session checks. Other existing sessions
    in the same term are treated as already scheduled.

    This function does not create, update, publish or delete records.
    """

    offerings = list(
        CourseOffering.objects.filter(
            term=term,
            course__is_active=True,
        ).prefetch_related(
            "lecturers",
            "student_groups",
        ).select_related(
            "course",
            "term",
        ).order_by("id")
    )

    if not offerings:
        return {
            "status": "NO_COURSES",
            "sessions": [],
            "message": "No active course offerings were found for this term.",
        }

    slots = list(
        TimeSlot.objects.filter(
            is_active=True,
            start_time__lt=datetime.strptime("23:59", "%H:%M").time(),
        ).order_by("weekday", "start_time")
    )

    rooms = list(
        Classroom.objects.filter(is_active=True).order_by("id")
    )

    if not slots:
        return {
            "status": "INFEASIBLE",
            "sessions": [],
            "message": "No active time slots are available.",
        }

    if not rooms:
        return {
            "status": "INFEASIBLE",
            "sessions": [],
            "message": "No active classrooms are available.",
        }

    offering_ids = [offering.id for offering in offerings]

    # Keep unrelated existing sessions fixed, but allow the offerings
    # being regenerated to move away from their current assignments.
    fixed_sessions = list(
        TeachingSession.objects.filter(
            offering__term=term,
        ).exclude(
            offering_id__in=offering_ids,
        ).select_related(
            "offering",
            "time_slot",
            "classroom",
        ).prefetch_related(
            "lecturers",
            "student_groups",
        )
    )

    model = cp_model.CpModel()

    # Each variable represents one possible offering/slot/room assignment.
    assignments = {}
    variables_by_offering = {o.id: [] for o in offerings}
    variables_by_offering_slot = {}

    offering_data = {}

    for offering in offerings:
        lecturers = list(offering.lecturers.all())
        groups = list(offering.student_groups.all())

        offering_data[offering.id] = {
            "offering": offering,
            "lecturers": lecturers,
            "groups": groups,
            "lecturer_ids": {person.id for person in lecturers},
            "group_ids": {group.id for group in groups},
        }

        if offering.course.weekly_hours <= 0:
            return {
                "status": "INVALID_DATA",
                "sessions": [],
                "message": (
                    f"{offering.course.code} has no positive weekly-hours "
                    "requirement."
                ),
            }

        for slot in slots:
            duration = _slot_duration_minutes(slot)

            if duration <= 0:
                continue

            # This first version supports whole-slot scheduling.
            # The selected slots must add up to the course's weekly hours.
            if duration > offering.course.weekly_hours * 60:
                continue

            # Availability is a hard constraint for every lecturer.
            if any(
                not lecturer_is_available_for_term(
                    lecturer, slot, term
                )
                for lecturer in lecturers
            ):
                continue

            for room in rooms:
                if not _room_meets_course_requirements(
                    room, offering, groups
                ):
                    continue

              
            
            
            for room in rooms:
                if not _room_meets_course_requirements(
                    room, offering, groups
                ):
                    continue

                # Reject clashes and insufficient cross-campus travel
                # time against existing fixed sessions.
                blocked = False

                for existing in fixed_sessions:
                    overlaps = _slots_overlap(slot, existing.time_slot)

                    existing_lecturer_ids = {
                        person.id
                        for person in existing.lecturers.all()
                    }
                    existing_group_ids = {
                        group.id
                        for group in existing.student_groups.all()
                    }

                    shared_lecturers = (
                        offering_data[offering.id]["lecturer_ids"]
                        & existing_lecturer_ids
                    )

                    if overlaps:
                        if room.id == existing.classroom_id:
                            blocked = True
                            break

                        if shared_lecturers:
                            blocked = True
                            break

                        if (
                            offering_data[offering.id]["group_ids"]
                            & existing_group_ids
                        ):
                            blocked = True
                            break

                    if (
                        shared_lecturers
                        and _cross_campus_travel_gap_too_short(
                            slot,
                            room.campus_id,
                            existing.time_slot,
                            existing.classroom.campus_id,
                        )
                    ):
                        blocked = True
                        break

                if blocked:
                    continue

                key = (offering.id, slot.id, room.id)

                variable = model.NewBoolVar(
                    f"offering_{offering.id}_slot_{slot.id}_room_{room.id}"
                )

                assignments[key] = variable
                variables_by_offering[offering.id].append(variable)

                variables_by_offering_slot.setdefault(
                    (offering.id, slot.id), []
                ).append(variable)

    # Every offering must receive exactly its required weekly minutes.
    for offering in offerings:
        offering_variables = variables_by_offering[offering.id]

        if not offering_variables:
            return {
                "status": "INFEASIBLE",
                "sessions": [],
                "message": (
                    f"No eligible assignments were found for "
                    f"{offering.course.code}. Check availability, "
                    "active time slots, room capacity and course requirements."
                ),
            }

        model.Add(
            sum(
                _slot_duration_minutes(
                    TimeSlot.objects.get(pk=slot_id)
                ) * variable
                for (offering_id, slot_id, room_id), variable
                in assignments.items()
                if offering_id == offering.id
            )
            == offering.course.weekly_hours * 60
        )

    # An offering cannot use two rooms in the same time slot.
    for variables in variables_by_offering_slot.values():
        model.Add(sum(variables) <= 1)

    # Avoid scheduling an offering more than once on the same weekday.
    for offering in offerings:
        for weekday in range(7):
            daily_variables = [
                variable
                for (offering_id, slot_id, room_id), variable
                in assignments.items()
                if offering_id == offering.id
                and TimeSlot.objects.get(pk=slot_id).weekday == weekday
            ]

            if daily_variables:
                model.Add(sum(daily_variables) <= 1)

    # Prevent room, lecturer and student-group clashes between offerings.
    # Prevent resource clashes and insufficient cross-campus travel
    # time between generated assignments.
    assignment_items = list(assignments.items())
    rooms_by_id = {room.id: room for room in rooms}
    slots_by_id = {slot.id: slot for slot in slots}

    for index, (key_a, variable_a) in enumerate(assignment_items):
        offering_a_id, slot_a_id, room_a_id = key_a
        slot_a = slots_by_id[slot_a_id]
        room_a = rooms_by_id[room_a_id]
        data_a = offering_data[offering_a_id]

        for key_b, variable_b in assignment_items[index + 1:]:
            offering_b_id, slot_b_id, room_b_id = key_b

            if offering_a_id == offering_b_id:
                continue

            slot_b = slots_by_id[slot_b_id]
            room_b = rooms_by_id[room_b_id]
            data_b = offering_data[offering_b_id]

            overlaps = _slots_overlap(slot_a, slot_b)

            shared_lecturers = (
                data_a["lecturer_ids"] & data_b["lecturer_ids"]
            )

            conflict = False

            if overlaps:
                conflict = (
                    room_a_id == room_b_id
                    or bool(shared_lecturers)
                    or bool(data_a["group_ids"] & data_b["group_ids"])
                )

            if (
                shared_lecturers
                and _cross_campus_travel_gap_too_short(
                    slot_a,
                    room_a.campus_id,
                    slot_b,
                    room_b.campus_id,
                )
            ):
                conflict = True

            if conflict:
                model.Add(variable_a + variable_b <= 1)

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = 20.0

    status = solver.Solve(model)

    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return {
            "status": "INFEASIBLE",
            "sessions": [],
            "message": (
                "No valid timetable could be found with the current "
                "hard constraints and available resources."
            ),
        }

    proposed_sessions = []

    for (offering_id, slot_id, room_id), variable in assignments.items():
        if not solver.Value(variable):
            continue

        offering = offering_data[offering_id]["offering"]
        slot = next(slot for slot in slots if slot.id == slot_id)
        room = next(room for room in rooms if room.id == room_id)

        proposed_sessions.append({
            "offering_id": offering.id,
            "course_code": offering.course.code,
            "course_title": offering.course.title,
            "day": slot.get_weekday_display(),
            "time_slot": slot.name,
            "start_time": str(slot.start_time),
            "end_time": str(slot.end_time),
            "classroom": room.name,
            "lecturers": [
                person.full_name
                for person in offering_data[offering_id]["lecturers"]
            ],
            "student_groups": [
                group.group_name
                for group in offering_data[offering_id]["groups"]
            ],
        })

    proposed_sessions.sort(
        key=lambda item: (
            item["day"],
            item["start_time"],
            item["course_code"],
        )
    )

    return {
        "status": (
            "OPTIMAL" if status == cp_model.OPTIMAL else "FEASIBLE"
        ),
        "sessions": proposed_sessions,
        "message": (
            "A valid timetable proposal was generated. "
            "No database sessions were changed."
        ),
    }
