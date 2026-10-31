
from django.db import models
from django.core.exceptions import ValidationError


class Campus(models.Model):
    name = models.CharField(max_length=150, unique=True)
    code = models.CharField(max_length=20, unique=True)
    address = models.CharField(max_length=255, blank=True)
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return self.name


class Department(models.Model):
    name = models.CharField(max_length=150)
    code = models.CharField(max_length=20, unique=True)
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return self.name


class Program(models.Model):
    name = models.CharField(max_length=150)
    code = models.CharField(max_length=20, unique=True)
    department = models.ForeignKey(
        Department,
        on_delete=models.PROTECT,
        related_name="programs",
    )
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return f"{self.code} - {self.name}"


class AcademicTerm(models.Model):
    name = models.CharField(max_length=100)
    start_date = models.DateField()
    end_date = models.DateField()
    is_active = models.BooleanField(default=False)

    def clean(self):
        if self.end_date < self.start_date:
            raise ValidationError(
                "The end date cannot be before the start date."
            )

    def __str__(self):
        return self.name



class StudentGroup(models.Model):
    program = models.ForeignKey(
        Program,
        on_delete=models.PROTECT,
        related_name="student_groups",
    )
    campus = models.ForeignKey(
        Campus,
        on_delete=models.PROTECT,
        related_name="student_groups",
    )
    level = models.CharField(max_length=30)
    group_name = models.CharField(max_length=50)
    student_count = models.PositiveIntegerField(default=0)


    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["program", "level", "group_name"],
                name="unique_student_group",
            )
        ]

    def __str__(self):
        return f"{self.program.code} - {self.level} - {self.group_name}"


class Lecturer(models.Model):
    staff_id = models.CharField(max_length=30, unique=True)
    full_name = models.CharField(max_length=150)
    email = models.EmailField(blank=True)
    departments = models.ManyToManyField(
        Department,
        related_name="lecturers",
        blank=True,
    )
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return f"{self.staff_id} - {self.full_name}"


class Classroom(models.Model):
    campus = models.ForeignKey(
        Campus,
        on_delete=models.PROTECT,
        related_name="classrooms",
    )
    building = models.CharField(max_length=100)
    name = models.CharField(max_length=100)
    capacity = models.PositiveIntegerField(default=0)
    equipment = models.TextField(
        blank=True,
        help_text="For example: projector, computers, laboratory equipment.",
    )
    is_active = models.BooleanField(default=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["campus", "building", "name"],
                name="unique_classroom_location",
            )
        ]

    def __str__(self):
        return f"{self.campus.code} - {self.building} - {self.name}"


class Course(models.Model):
    code = models.CharField(max_length=30, unique=True)
    title = models.CharField(max_length=200)
    weekly_hours = models.PositiveIntegerField(default=2)
    requires_lab = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return f"{self.code} - {self.title}"


class CourseOffering(models.Model):
    DELIVERY_CHOICES = [
        ("JOINT", "Joint/shared class"),
        ("SEPARATE", "Separate classes"),
        ("PARTIAL", "Partially shared class"),
    ]

    course = models.ForeignKey(
        Course,
        on_delete=models.PROTECT,
        related_name="offerings",
    )
    term = models.ForeignKey(
        AcademicTerm,
        on_delete=models.PROTECT,
        related_name="course_offerings",
    )
    student_groups = models.ManyToManyField(
        StudentGroup,
        related_name="course_offerings",
    )
    lecturers = models.ManyToManyField(
        Lecturer,
        related_name="course_offerings",
        blank=True,
    )
    delivery_type = models.CharField(
        max_length=10,
        choices=DELIVERY_CHOICES,
        default="SEPARATE",
    )

    def __str__(self):
        return f"{self.course.code} - {self.term.name}"


class LecturerAvailability(models.Model):
    WEEKDAYS = [
        (0, "Monday"),
        (1, "Tuesday"),
        (2, "Wednesday"),
        (3, "Thursday"),
        (4, "Friday"),
        (5, "Saturday"),
        (6, "Sunday"),
    ]

    lecturer = models.ForeignKey(
        Lecturer,
        on_delete=models.CASCADE,
        related_name="availability_records",
    )
    weekday = models.IntegerField(choices=WEEKDAYS)
    start_time = models.TimeField()
    end_time = models.TimeField()
    is_available = models.BooleanField(
        default=True,
        help_text="Uncheck to record a period when the lecturer is unavailable.",
    )
    approved = models.BooleanField(default=False)
    effective_from = models.DateField(null=True, blank=True)
    effective_until = models.DateField(null=True, blank=True)
    notes = models.TextField(blank=True)

    
    def clean(self):
        super().clean()

        if (
            self.start_time is not None
            and self.end_time is not None
            and self.end_time <= self.start_time
        ):
            raise ValidationError(
                "End time must be later than start time."
            )

        if (
            self.effective_from is not None
            and self.effective_until is not None
            and self.effective_until < self.effective_from
        ):
            raise ValidationError(
                "The effective end date cannot be before the start date."
            )


    def __str__(self):
        day = self.get_weekday_display()
        return f"{self.lecturer.full_name} - {day}"

class TimeSlot(models.Model):
    WEEKDAYS = [
        (0, "Monday"),
        (1, "Tuesday"),
        (2, "Wednesday"),
        (3, "Thursday"),
        (4, "Friday"),
        (5, "Saturday"),
        (6, "Sunday"),
    ]

    name = models.CharField(
        max_length=100,
        help_text="Example: Monday Morning, Period 1",
    )
    weekday = models.IntegerField(choices=WEEKDAYS)
    start_time = models.TimeField()
    end_time = models.TimeField()
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["weekday", "start_time"]
        constraints = [
            models.UniqueConstraint(
                fields=["weekday", "start_time", "end_time"],
                name="unique_weekday_time_slot",
            )
        ]

    def clean(self):
        super().clean()
        if (
            self.start_time is not None
            and self.end_time is not None
            and self.end_time <= self.start_time
        ):
            raise ValidationError(
                "The period end time must be later than its start time."
            )

    def __str__(self):
        return (
            f"{self.get_weekday_display()} "
            f"{self.start_time:%H:%M}-{self.end_time:%H:%M}"
            f" ({self.name})"
        )


class TeachingSession(models.Model):
    offering = models.ForeignKey(
        CourseOffering,
        on_delete=models.PROTECT,
        related_name="teaching_sessions",
    )
    time_slot = models.ForeignKey(
        TimeSlot,
        on_delete=models.PROTECT,
        related_name="teaching_sessions",
    )
    classroom = models.ForeignKey(
        Classroom,
        on_delete=models.PROTECT,
        related_name="teaching_sessions",
    )
    student_groups = models.ManyToManyField(
        StudentGroup,
        related_name="teaching_sessions",
    )
    lecturers = models.ManyToManyField(
        Lecturer,
        related_name="teaching_sessions",
        blank=True,
    )
    notes = models.TextField(blank=True)
    is_published = models.BooleanField(default=False)

    class Meta:
        ordering = [
            "time_slot__weekday",
            "time_slot__start_time",
        ]

    def clean(self):
        super().clean()

        if self.offering_id and self.classroom_id:
            group_ids = set()
            if self.pk:
                group_ids = set(
                    self.student_groups.values_list("id", flat=True)
                )

            if group_ids:
                total_students = sum(
                    StudentGroup.objects.filter(
                        id__in=group_ids
                    ).values_list("student_count", flat=True)
                )

                if total_students > self.classroom.capacity:
                    raise ValidationError({
                        "classroom": (
                            f"The selected groups have {total_students} "
                            f"students, but this room holds only "
                            f"{self.classroom.capacity}."
                        )
                    })

    def __str__(self):
        return (
            f"{self.offering.course.code} - "
            f"{self.classroom.name} - {self.time_slot}"
        )



class TimetableProposal(models.Model):
    STATUS_CHOICES = [
        ("DRAFT", "Draft"),
        ("VALIDATED", "Validated"),
        ("APPROVED", "Approved"),
        ("PUBLISHED", "Published"),
        ("REJECTED", "Rejected"),
    ]

    name = models.CharField(max_length=200)
    term = models.ForeignKey(
        AcademicTerm,
        on_delete=models.PROTECT,
        related_name="timetable_proposals",
    )
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default="DRAFT",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    proposal_data = models.JSONField(default=list)
    validation_errors = models.JSONField(default=list, blank=True)

    def __str__(self):
        return f"{self.name} - {self.term.name} ({self.status})"
