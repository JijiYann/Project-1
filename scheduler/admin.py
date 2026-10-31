
from django.contrib import admin
from django import forms
from django.core.exceptions import ValidationError
from .services import (
    find_session_conflicts,
    suggest_alternative_classrooms,
    suggest_alternative_time_slots,
)
from .models import (
    Campus,
    Department,
    Program,
    AcademicTerm,
    StudentGroup,
    Lecturer,
    Classroom,
    Course,
    CourseOffering,
    LecturerAvailability,
    TimeSlot,
    TeachingSession,
    TimetableProposal,
)


@admin.register(Campus)
class CampusAdmin(admin.ModelAdmin):
    list_display = ("name", "code", "is_active")
    search_fields = ("name", "code")


@admin.register(Department)
class DepartmentAdmin(admin.ModelAdmin):
    list_display = ("name", "code", "is_active")
    search_fields = ("name", "code")


@admin.register(Program)
class ProgramAdmin(admin.ModelAdmin):
    list_display = ("name", "code", "department", "is_active")
    list_filter = ("department", "is_active")
    search_fields = ("name", "code")


@admin.register(AcademicTerm)
class AcademicTermAdmin(admin.ModelAdmin):
    list_display = ("name", "start_date", "end_date", "is_active")
    list_filter = ("is_active",)


@admin.register(StudentGroup)
class StudentGroupAdmin(admin.ModelAdmin):
    list_display = (
        "program", "level", "group_name", "student_count"
    )
    list_filter = ("program", "level")
    search_fields = ("group_name", "program__name")


@admin.register(Lecturer)
class LecturerAdmin(admin.ModelAdmin):
    list_display = ("staff_id", "full_name", "email", "is_active")
    list_filter = ("is_active", "departments")
    search_fields = ("staff_id", "full_name", "email")
    filter_horizontal = ("departments",)


@admin.register(Classroom)
class ClassroomAdmin(admin.ModelAdmin):
    list_display = (
        "name", "building", "campus", "capacity", "is_active"
    )
    list_filter = ("campus", "building", "is_active")
    search_fields = ("name", "building", "campus__name")


@admin.register(Course)
class CourseAdmin(admin.ModelAdmin):
    list_display = (
        "code", "title", "weekly_hours", "requires_lab", "is_active"
    )
    list_filter = ("requires_lab", "is_active")
    search_fields = ("code", "title")


@admin.register(CourseOffering)
class CourseOfferingAdmin(admin.ModelAdmin):
    list_display = ("course", "term", "delivery_type")
    list_filter = ("term", "delivery_type")
    search_fields = ("course__code", "course__title")
    filter_horizontal = ("student_groups", "lecturers")


@admin.register(LecturerAvailability)
class LecturerAvailabilityAdmin(admin.ModelAdmin):
    list_display = (
        "lecturer",
        "weekday",
        "start_time",
        "end_time",
        "is_available",
        "approved",
    )
    list_filter = ("weekday", "is_available", "approved")
    search_fields = ("lecturer__full_name", "lecturer__staff_id")

@admin.register(TimeSlot)
class TimeSlotAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "weekday",
        "start_time",
        "end_time",
        "is_active",
    )
    list_filter = ("weekday", "is_active")
    search_fields = ("name",)



class TeachingSessionForm(forms.ModelForm):
    class Meta:
        model = TeachingSession
        fields = "__all__"

    def clean(self):
        cleaned_data = super().clean()

        offering = cleaned_data.get("offering")
        slot = cleaned_data.get("time_slot")
        classroom = cleaned_data.get("classroom")
        lecturers = cleaned_data.get("lecturers")
        student_groups = cleaned_data.get("student_groups")

        if not all((offering, slot, classroom)):
            return cleaned_data

        # Create an in-memory session using the submitted assignments.
        session = self.instance
        session.offering = offering
        session.time_slot = slot
        session.classroom = classroom

        # Check existing sessions with the same term and overlapping time.
        candidates = (
            TeachingSession.objects
            .filter(
                offering__term=offering.term,
                time_slot__weekday=slot.weekday,
                time_slot__start_time__lt=slot.end_time,
                time_slot__end_time__gt=slot.start_time,
            )
            .exclude(pk=session.pk if session.pk else None)
            .select_related("offering__course", "time_slot", "classroom")
            .prefetch_related("lecturers", "student_groups")
        )

        lecturer_ids = set(lecturers.values_list("id", flat=True))
        group_ids = set(student_groups.values_list("id", flat=True))

        conflicts = []

        for other in candidates:
            reasons = []

            if other.classroom_id == classroom.id:
                reasons.append("Same classroom")

            other_lecturer_ids = set(
                other.lecturers.values_list("id", flat=True)
            )
            if lecturer_ids & other_lecturer_ids:
                reasons.append("Same lecturer")

            other_group_ids = set(
                other.student_groups.values_list("id", flat=True)
            )
            if group_ids & other_group_ids:
                reasons.append("Same student group")

            if reasons:
                conflicts.append(
                    f"Session {other.pk}: {', '.join(reasons)}"
                )

        if conflicts:
            raise ValidationError(
                "Cannot save this session because of timetable conflicts: "
                + " | ".join(conflicts)
            )

        return cleaned_data



@admin.register(TeachingSession)
class TeachingSessionAdmin(admin.ModelAdmin):
    form = TeachingSessionForm
    list_display = (
        "offering",
        "time_slot",
        "classroom",
        "conflict_status",
        "alternative_classrooms",
        "alternative_time_slots",
        "is_published",
    )

    list_filter = (
        "is_published",
        "time_slot__weekday",
        "classroom__campus",
    )

    search_fields = (
        "offering__course__code",
        "offering__course__title",
        "classroom__name",
    )
    
    filter_horizontal = ("student_groups", "lecturers")

    @admin.display(description="Conflict status")
    def conflict_status(self, obj):
        conflicts = find_session_conflicts(obj)

        if not conflicts:
            return "No conflicts"

        details = []

        for conflict in conflicts:
            reasons = ", ".join(conflict["reasons"])
            details.append(
                f"Session {conflict['session'].pk}: {reasons}"
            )

        return " | ".join(details)

    @admin.display(description="Alternative classrooms")
    def alternative_classrooms(self, obj):
        rooms = suggest_alternative_classrooms(obj)

        room_names = list(
            rooms.values_list("name", flat=True)
        )

        if not room_names:
            return "No alternatives found"

        return ", ".join(room_names)
    @admin.display(description="Alternative time slots")
    def alternative_time_slots(self, obj):
        slots = suggest_alternative_time_slots(obj)

        slot_names = [
           f"{slot.get_weekday_display()} "
           f"{slot.start_time.strftime('%H:%M')}-"
           f"{slot.end_time.strftime('%H:%M')}"
        for slot in slots
        ]

        if not slot_names:
            return "No alternatives found"

        return ", ".join(slot_names)


@admin.register(TimetableProposal)
class TimetableProposalAdmin(admin.ModelAdmin):
    actions = ["approve_proposals"]

    list_display = (
        "name",
        "term",
        "status",
        "proposed_session_count",
        "created_at",
        "updated_at",
    )

    list_filter = ("status", "term")
    search_fields = ("name", "term__name")
    readonly_fields = (
        "created_at",
        "updated_at",
        "proposed_session_count",
        "proposal_preview",
        "validation_errors",
    )

    fields = (
        "name",
        "term",
        "status",
        "proposed_session_count",
        "proposal_preview",
        "validation_errors",
        "created_at",
        "updated_at",
    )

    @admin.display(description="Proposed sessions")
    def proposed_session_count(self, obj):
        return len(obj.proposal_data or [])

    @admin.action(description="Approve selected validated proposals")
    def approve_proposals(self, request, queryset):
        approved_count = 0

        for proposal in queryset:
            if (
                proposal.status == "VALIDATED"
                and not proposal.validation_errors
            ):
                proposal.status = "APPROVED"
                proposal.save(update_fields=["status", "updated_at"])
                approved_count += 1

        if approved_count:
            self.message_user(
                request,
                f"{approved_count} proposal(s) approved successfully."
            )

        skipped_count = queryset.count() - approved_count

        if skipped_count:
            self.message_user(
                request,
                f"{skipped_count} proposal(s) skipped because they "
                "were not validated or had validation errors.",
                level="WARNING",
            )

    @admin.display(description="Proposal preview")
    def proposal_preview(self, obj):
        sessions = obj.proposal_data or []

        if not sessions:
            return "No proposed sessions."

        return "\n".join(
            (
                f"{item.get('course_code', 'Unknown course')} | "
                f"{item.get('day', 'Unknown day')} | "
                f"{item.get('start_time', '?')}-"
                f"{item.get('end_time', '?')} | "
                f"{item.get('classroom', 'No classroom')} | "
                f"Groups: {', '.join(item.get('student_groups', []))}"
            )
            for item in sessions
        )

