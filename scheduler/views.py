
from django.shortcuts import render, redirect
from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.core.exceptions import ValidationError
from django.shortcuts import get_object_or_404

from .models import (
    TeachingSession,
    AcademicTerm,
    StudentGroup,
    TimeSlot,
    Lecturer,
    TimetableProposal,
)

from .services import create_timetable_proposal


def published_timetable(request):
    sessions = (
        TeachingSession.objects
        .filter(is_published=True)
        .select_related(
            "offering__course",
            "offering__term",
            "time_slot",
            "classroom",
        )
        .prefetch_related(
            "lecturers",
            "student_groups",
        )
    )

    # Academic terms that have published sessions.
    terms = AcademicTerm.objects.filter(
        id__in=TeachingSession.objects.filter(
            is_published=True
        ).values("offering__term_id")
    ).distinct().order_by("-start_date")

    selected_term = request.GET.get("term", "")

    if selected_term.isdigit():
        sessions = sessions.filter(
            offering__term_id=int(selected_term)
        )
        terms = terms.filter(id=int(selected_term))
    else:
        selected_term = ""

    # Student groups that have published sessions.
    groups = StudentGroup.objects.filter(
        teaching_sessions__is_published=True
    ).distinct().order_by("group_name")

    selected_group = request.GET.get("group", "")

    if selected_group.isdigit():
        sessions = sessions.filter(
            student_groups__id=int(selected_group)
        )
    else:
        selected_group = ""

    # Lecturers who have published teaching sessions.
    lecturers = Lecturer.objects.filter(
        teaching_sessions__is_published=True
    ).distinct().order_by("full_name")

    selected_lecturer = request.GET.get("lecturer", "")

    if selected_lecturer.isdigit():
        sessions = sessions.filter(
            lecturers__id=int(selected_lecturer)
        )
    else:
        selected_lecturer = ""

    sessions = sessions.order_by(
        "time_slot__weekday",
        "time_slot__start_time",
        "offering__course__code",
    ).distinct()

    # Prepare the Monday-to-Saturday weekly grid.
    
    # Prepare a consistent Monday-to-Saturday weekly grid.
    weekdays = [
        (0, "Monday"),
        (1, "Tuesday"),
        (2, "Wednesday"),
        (3, "Thursday"),
        (4, "Friday"),
        (5, "Saturday"),
    ]

    time_slots = list(
        TimeSlot.objects.filter(
            is_active=True,
            weekday__in=[0, 1, 2, 3, 4, 5],
        ).order_by("start_time", "end_time")
    )

    # Get unique teaching periods, regardless of the day.
    periods = sorted(
        {
            (slot.start_time, slot.end_time)
            for slot in time_slots
        }
    )

    grid = []

    for start_time, end_time in periods:
        row = {
            "start_time": start_time,
            "end_time": end_time,
            "is_break": False,
            "days": [],
        }

        for day_number, day_name in weekdays:
            day_sessions = [
                session
                for session in sessions
                if session.time_slot.weekday == day_number
                and session.time_slot.start_time == start_time
                and session.time_slot.end_time == end_time
            ]

            row["days"].append({
                "day_number": day_number,
                "day_name": day_name,
                "sessions": day_sessions,
            })

        grid.append(row)

    # Insert the lunch break between 12:00 and 12:30.
    grid.append({
        "start_time": None,
        "end_time": None,
        "is_break": True,
        "label": "12:00–12:30 BREAK",
        "days": [],
    })

    # Keep the break in chronological order.
    grid.sort(
        key=lambda row: (
            "12:00" if row["is_break"]
            else row["start_time"].strftime("%H:%M")
        )
    )


    context = {
        "sessions": sessions,
        "terms": terms,
        "selected_term": selected_term,
        "groups": groups,
        "selected_group": selected_group,
        "lecturers": lecturers,
        "selected_lecturer": selected_lecturer,
        "weekdays": weekdays,
        "grid": grid,
    }

    return render(
        request,
        "scheduler/published_timetable.html",
        context,
    )

@staff_member_required
def proposal_dashboard(request):
    proposals = (
        TimetableProposal.objects
        .select_related("term")
        .order_by("-created_at")
    )

    context = {
        "proposals": proposals,
    }

    return render(
        request,
        "scheduler/proposal_dashboard.html",
        context,
    )

@staff_member_required
def generate_proposal_view(request):

    if request.method == "POST":
        term_id = request.POST.get("term")
        proposal_name = request.POST.get("name", "").strip()

        term = AcademicTerm.objects.filter(
            pk=term_id
        ).first()

        if term is None:
            messages.error(request, "Please select a valid academic term.")
            return redirect("scheduler:generate_proposal")

        if not proposal_name:
            proposal_name = f"Generated proposal - {term.name}"

        try:
            result = create_timetable_proposal(
                term=term,
                name=proposal_name,
            )

            if result["success"]:
                messages.success(
                    request,
                    result["message"],
                )
            else:
                messages.warning(
                    request,
                    result["message"],
                )

        except ValidationError as error:
            messages.error(request, str(error))

        return redirect("scheduler:proposal_dashboard")

    terms = AcademicTerm.objects.all().order_by("-start_date")

    return render(
        request,
        "scheduler/generate_proposal.html",
        {"terms": terms},
    )

@staff_member_required
def proposal_detail(request, proposal_id):
    proposal = get_object_or_404(
        TimetableProposal.objects.select_related("term"),
        pk=proposal_id,
    )

    context = {
        "proposal": proposal,
        "proposed_sessions": proposal.proposal_data,
        "validation_errors": proposal.validation_errors,
    }

    return render(
        request,
        "scheduler/proposal_detail.html",
        context,
    )
