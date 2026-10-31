
from datetime import date, time

from django.core.exceptions import ValidationError
from django.test import TestCase

from scheduler.models import (
    AcademicTerm,
    Campus,
    Classroom,
    Course,
    CourseOffering,
    Department,
    Lecturer,
    LecturerAvailability,
    Program,
    StudentGroup,
    TimeSlot,
    TimetableProposal,
    TeachingSession,
)
from scheduler.services import (
    publish_timetable_proposal,
    validate_timetable_proposal,
)


class TimetableValidationTestBase(TestCase):
    """Create isolated test data for timetable validation tests."""

    def setUp(self):
        self.campus = Campus.objects.create(
            name="Test Campus",
            code="TC",
        )
        self.department = Department.objects.create(
            name="Test Department",
            code="TDEP",
        )
        self.program = Program.objects.create(
            name="Test Program",
            code="TPROG",
            department=self.department,
        )
        self.term = AcademicTerm.objects.create(
            name="Test Term",
            start_date=date(2026, 10, 5),
            end_date=date(2027, 1, 15),
            is_active=True,
        )

        self.group = StudentGroup.objects.create(
            program=self.program,
            campus=self.campus,
            level="HND 1",
            group_name="Group A",
            student_count=20,
        )
        self.group_b = StudentGroup.objects.create(
            program=self.program,
            campus=self.campus,
            level="HND 1",
            group_name="Group B",
            student_count=15,
        )

        self.room = Classroom.objects.create(
            campus=self.campus,
            building="Block A",
            name="Test Hall",
            capacity=40,
            equipment="Benches",
            is_active=True,
        )
        self.room_b = Classroom.objects.create(
            campus=self.campus,
            building="Block A",
            name="Test Hall 2",
            capacity=40,
            equipment="Benches",
            is_active=True,
        )

        self.monday_morning = TimeSlot.objects.create(
            name="Test Monday Morning",
            weekday=0,
            start_time=time(8, 0),
            end_time=time(10, 0),
            is_active=True,
        )
        self.monday_midday = TimeSlot.objects.create(
            name="Test Monday Midday",
            weekday=0,
            start_time=time(10, 0),
            end_time=time(12, 0),
            is_active=True,
        )
        self.monday_afternoon = TimeSlot.objects.create(
            name="Test Monday Afternoon",
            weekday=0,
            start_time=time(13, 0),
            end_time=time(15, 0),
            is_active=True,
        )

        self.lecturer = Lecturer.objects.create(
            staff_id="TEST-LECT-1",
            full_name="Test Lecturer",
            is_active=True,
        )
        self.lecturer_b = Lecturer.objects.create(
            staff_id="TEST-LECT-2",
            full_name="Test Lecturer B",
            is_active=True,
        )

        # Approve recurring availability for both test lecturers.
        # If your LecturerAvailability model requires extra fields,
        # Django will report which fields need to be supplied.
       
        for lecturer in (self.lecturer, self.lecturer_b):
            LecturerAvailability.objects.create(
                lecturer=lecturer,
                weekday=0,
                start_time=time(8, 0),
                end_time=time(15, 0),
                is_available=True,
                approved=True,
                effective_from=date(2026, 10, 5),
                effective_until=date(2027, 1, 15),
            )


        self.course_a = Course.objects.create(
            code="TEST01",
            title="Test Course A",
            weekly_hours=2,
        )
        self.course_b = Course.objects.create(
            code="TEST02",
            title="Test Course B",
            weekly_hours=2,
        )

        self.offering_a = self.make_offering(
            self.course_a,
            self.group,
            self.lecturer,
        )
        self.offering_b = self.make_offering(
            self.course_b,
            self.group_b,
            self.lecturer_b,
        )

    def make_offering(self, course, group, lecturer):
        offering = CourseOffering.objects.create(
            course=course,
            term=self.term,
            delivery_type="SEPARATE",
        )
        offering.student_groups.add(group)
        offering.lecturers.add(lecturer)
        return offering

    def make_entry(self, offering, slot, room):
        return {
            "day": slot.get_weekday_display(),
            "start_time": slot.start_time.strftime("%H:%M:%S"),
            "end_time": slot.end_time.strftime("%H:%M:%S"),
            "time_slot": slot.name,
            "classroom": room.name,
            "offering_id": offering.id,
            "course_code": offering.course.code,
            "course_title": offering.course.title,
            "student_groups": list(
                offering.student_groups.values_list(
                    "group_name", flat=True
                )
            ),
            "lecturers": list(
                offering.lecturers.values_list(
                    "full_name", flat=True
                )
            ),
        }


class PublishCampusValidationTest(TestCase):
    def test_wrong_campus_prevents_publishing(self):
        campus_a = Campus.objects.create(name="Test Campus A", code="TCA")
        campus_b = Campus.objects.create(name="Test Campus B", code="TCB")

        department = Department.objects.create(
            name="Test Department",
            code="TDEP",
        )
        program = Program.objects.create(
            name="Test Program",
            code="TPROG",
            department=department,
        )
        group = StudentGroup.objects.create(
            program=program,
            campus=campus_a,
            level="HND 1",
            group_name="Test Group",
            student_count=20,
        )

        term = AcademicTerm.objects.create(
            name="Campus Test Term",
            start_date=date(2026, 10, 5),
            end_date=date(2027, 1, 15),
            is_active=True,
        )
        course = Course.objects.create(
            code="TEST01",
            title="Campus Validation Test",
            weekly_hours=2,
        )
        offering = CourseOffering.objects.create(
            course=course,
            term=term,
            delivery_type="SEPARATE",
        )
        offering.student_groups.add(group)

        room = Classroom.objects.create(
            campus=campus_b,
            building="Test Building",
            name="Test Hall",
            capacity=30,
        )
        slot = TimeSlot.objects.create(
            name="Test Monday Morning",
            weekday=0,
            start_time=time(8, 0),
            end_time=time(10, 0),
        )

        proposal = TimetableProposal.objects.create(
            name="Campus Mismatch Test",
            term=term,
            status="APPROVED",
            proposal_data=[{
                "day": "Monday",
                "start_time": "08:00:00",
                "end_time": "10:00:00",
                "time_slot": slot.name,
                "classroom": room.name,
                "offering_id": offering.id,
                "course_code": course.code,
                "course_title": course.title,
                "student_groups": [group.group_name],
                "lecturers": [],
            }],
        )

        sessions_before = TeachingSession.objects.count()

        with self.assertRaises(ValidationError):
            publish_timetable_proposal(proposal.id)

        self.assertEqual(
            TeachingSession.objects.count(),
            sessions_before,
        )
        proposal.refresh_from_db()
        self.assertEqual(proposal.status, "APPROVED")


class TimetableConflictValidationTests(TimetableValidationTestBase):
    def test_room_capacity_too_small_is_rejected(self):
        small_room = Classroom.objects.create(
            campus=self.campus,
            building="Block A",
            name="Small Hall",
            capacity=10,
            equipment="Benches",
        )

        entry = self.make_entry(
            self.offering_a,
            self.monday_morning,
            small_room,
        )

        errors = validate_timetable_proposal([entry], self.term)

        self.assertTrue(
            any("not have enough capacity" in error for error in errors),
            errors,
        )

    def test_same_lecturer_cannot_teach_overlapping_courses(self):
        self.offering_b.lecturers.set([self.lecturer])

        entries = [
            self.make_entry(
                self.offering_a,
                self.monday_morning,
                self.room,
            ),
            self.make_entry(
                self.offering_b,
                self.monday_morning,
                self.room_b,
            ),
        ]

        errors = validate_timetable_proposal(entries, self.term)

        self.assertTrue(
            any("lecturer clash" in error for error in errors),
            errors,
        )

    def test_same_group_cannot_attend_overlapping_courses(self):
        self.offering_b.student_groups.set([self.group])

        entries = [
            self.make_entry(
                self.offering_a,
                self.monday_morning,
                self.room,
            ),
            self.make_entry(
                self.offering_b,
                self.monday_morning,
                self.room_b,
            ),
        ]

        errors = validate_timetable_proposal(entries, self.term)

        self.assertTrue(
            any("student-group clash" in error for error in errors),
            errors,
        )

    def test_same_room_cannot_host_overlapping_courses(self):
        entries = [
            self.make_entry(
                self.offering_a,
                self.monday_morning,
                self.room,
            ),
            self.make_entry(
                self.offering_b,
                self.monday_morning,
                self.room,
            ),
        ]

        errors = validate_timetable_proposal(entries, self.term)

        self.assertTrue(
            any("classroom clash" in error for error in errors),
            errors,
        )

class PublishWorkflowTests(TimetableValidationTestBase):
    def make_proposal(self, entries, status="APPROVED"):
        return TimetableProposal.objects.create(
            name="Publishing Workflow Test",
            term=self.term,
            status=status,
            proposal_data=entries,
        )

    def test_invalid_capacity_proposal_does_not_publish(self):
        small_room = Classroom.objects.create(
            campus=self.campus,
            building="Block A",
            name="Too Small Hall",
            capacity=10,
            equipment="Benches",
        )

        entry = self.make_entry(
            self.offering_a,
            self.monday_morning,
            small_room,
        )
        proposal = self.make_proposal([entry])

        # Add an existing session for the same offering.
        existing = TeachingSession.objects.create(
            offering=self.offering_a,
            time_slot=self.monday_midday,
            classroom=self.room,
            is_published=True,
        )
        existing.student_groups.set(self.offering_a.student_groups.all())
        existing.lecturers.set(self.offering_a.lecturers.all())

        session_ids_before = list(
            TeachingSession.objects.order_by("id").values_list("id", flat=True)
        )

        with self.assertRaises(ValidationError):
            publish_timetable_proposal(proposal.id)

        session_ids_after = list(
            TeachingSession.objects.order_by("id").values_list("id", flat=True)
        )
        self.assertEqual(session_ids_after, session_ids_before)

        proposal.refresh_from_db()
        self.assertEqual(proposal.status, "APPROVED")

    
    def test_valid_approved_proposal_publishes(self):
        entries = [
             self.make_entry(
                self.offering_a,
                 self.monday_morning,
                self.room,
            ),
            self.make_entry(
                self.offering_b,
                self.monday_midday,
                self.room_b,
            ),
        ]

        proposal = self.make_proposal(entries)

        published_count = publish_timetable_proposal(proposal.id)

        self.assertEqual(published_count, 2)

        proposal.refresh_from_db()
        self.assertEqual(proposal.status, "PUBLISHED")

        session_a = TeachingSession.objects.get(
            offering=self.offering_a,
            time_slot=self.monday_morning,
        )
        self.assertTrue(session_a.is_published)
        self.assertEqual(session_a.classroom, self.room)

        session_b = TeachingSession.objects.get(
            offering=self.offering_b,
            time_slot=self.monday_midday,
        )
        self.assertTrue(session_b.is_published)
        self.assertEqual(session_b.classroom, self.room_b)


    def test_unapproved_proposal_cannot_publish(self):
        entry = self.make_entry(
            self.offering_a,
            self.monday_morning,
            self.room,
        )
        proposal = self.make_proposal([entry], status="DRAFT")

        sessions_before = TeachingSession.objects.count()

        with self.assertRaises(ValidationError):
            publish_timetable_proposal(proposal.id)

        self.assertEqual(
            TeachingSession.objects.count(),
            sessions_before,
        )

        proposal.refresh_from_db()
        self.assertEqual(proposal.status, "DRAFT")

class CrossCampusLecturerConflictTests(TimetableValidationTestBase):
    def test_same_lecturer_cannot_teach_on_two_campuses_at_same_time(self):
        # Create a second campus and a classroom there.
        campus_b = Campus.objects.create(name="TC2")

        room_campus_b = Classroom.objects.create(
            campus=campus_b,
            building="Block B",
            name="Campus B Test Hall",
            capacity=40,
            equipment="Benches",
            is_active=True,
        )

        # Move the second test group to the second campus.
        group_b = self.offering_b.student_groups.get()
        group_b.campus = campus_b
        group_b.save()

        # Assign the same lecturer to both course offerings.
        shared_lecturer = self.offering_a.lecturers.get()
        self.offering_b.lecturers.set([shared_lecturer])

        # Both courses are scheduled at the same time on different campuses.
        entries = [
            self.make_entry(
                self.offering_a,
                self.monday_morning,
                self.room,
            ),
            self.make_entry(
                self.offering_b,
                self.monday_morning,
                room_campus_b,
            ),
        ]

        errors = validate_timetable_proposal(entries, self.term)

        self.assertTrue(
            any(
                "lecturer clash" in error.lower()
                for error in errors
            ),
            msg=f"Expected a cross-campus lecturer clash, got: {errors}",
        )

class CrossCampusGeneratorConflictTests(TimetableValidationTestBase):
    def test_generator_does_not_schedule_shared_lecturer_simultaneously(self):
        from .generator import generate_timetable_proposal

        # Create a second campus and its classroom.
        campus_b = Campus.objects.create(name="TC2")

        room_campus_b = Classroom.objects.create(
            campus=campus_b,
            building="Block B",
            name="Campus B Generator Hall",
            capacity=40,
            equipment="Benches",
            is_active=True,
        )

        # Put the second student group on Campus B.
        group_b = self.offering_b.student_groups.get()
        group_b.campus = campus_b
        group_b.save()

        # Both offerings now use the same lecturer.
        shared_lecturer = self.offering_a.lecturers.get()
        self.offering_b.lecturers.set([shared_lecturer])

        result = generate_timetable_proposal(self.term)

        self.assertIn(
            result["status"],
            ("OPTIMAL", "FEASIBLE"),
            msg=result.get("message", "Generation failed."),
        )

        sessions = result["sessions"]
        self.assertEqual(len(sessions), 2)

        # Both sessions use the shared lecturer, so their time
        # intervals must not overlap.
        first, second = sessions

        first_start = time.fromisoformat(first["start_time"])
        first_end = time.fromisoformat(first["end_time"])
        second_start = time.fromisoformat(second["start_time"])
        second_end = time.fromisoformat(second["end_time"])

        same_day = first["day"] == second["day"]
        overlaps = (
            same_day
            and first_start < second_end
            and second_start < first_end
        )

        self.assertFalse(
            overlaps,
            msg=f"Generator scheduled overlapping sessions: {sessions}",
        )
        
        # Verify the 45-minute cross-campus travel requirement.
        if same_day:
            first_room = Classroom.objects.get(name=first["classroom"])
            second_room = Classroom.objects.get(name=second["classroom"])

            if first_room.campus_id != second_room.campus_id:
                if first_end <= second_start:
                    travel_gap = (
                        second_start.hour * 60 + second_start.minute
                    ) - (
                        first_end.hour * 60 + first_end.minute
                    )
                else:
                    travel_gap = (
                        first_start.hour * 60 + first_start.minute
                    ) - (
                        second_end.hour * 60 + second_end.minute
                    )

                self.assertGreaterEqual(
                    travel_gap,
                    45,
                    msg=(
                        "Generator scheduled a lecturer at different "
                        f"campuses with only {travel_gap} minutes "
                        f"for travel: {sessions}"
                    ),
                )


class CrossCampusTravelGapTests(TimetableValidationTestBase):

    def test_44_minute_gap_between_campuses_is_rejected(self):
        from .services import _cross_campus_travel_gap_too_short

        campus_b = Campus.objects.create(name="Travel Test Campus B")

        slot_b = TimeSlot.objects.create(
            weekday=0,
            start_time=time(10, 44),
            end_time=time(12, 44),
            is_active=True,
        )

        result = _cross_campus_travel_gap_too_short(
            self.monday_morning,
            self.room.campus_id,
            slot_b,
            campus_b.id,
        )

        self.assertTrue(
            result,
            "A 44-minute gap between campuses must be rejected.",
        )

    def test_exactly_45_minute_gap_between_campuses_is_allowed(self):
        from .services import _cross_campus_travel_gap_too_short

        campus_b = Campus.objects.create(name="Travel Test Campus B")

        slot_b = TimeSlot.objects.create(
            weekday=0,
            start_time=time(10, 45),
            end_time=time(12, 45),
            is_active=True,
        )

        result = _cross_campus_travel_gap_too_short(
            self.monday_morning,
            self.room.campus_id,
            slot_b,
            campus_b.id,
        )

        self.assertFalse(
            result,
            "Exactly 45 minutes between campuses must be allowed.",
        )

    def test_same_campus_does_not_require_travel_gap(self):
        from .services import _cross_campus_travel_gap_too_short

        result = _cross_campus_travel_gap_too_short(
            self.monday_morning,
            self.room.campus_id,
            self.monday_midday,
            self.room.campus_id,
        )

        self.assertFalse(
            result,
            "Back-to-back sessions on the same campus must be allowed.",
        )

    def test_different_weekdays_do_not_require_travel_gap(self):
        from .services import _cross_campus_travel_gap_too_short

        campus_b = Campus.objects.create(name="Travel Test Campus B")

        tuesday_slot = TimeSlot.objects.create(
            weekday=1,
            start_time=time(8, 0),
            end_time=time(10, 0),
            is_active=True,
        )

        result = _cross_campus_travel_gap_too_short(
            self.monday_morning,
            self.room.campus_id,
            tuesday_slot,
            campus_b.id,
        )

        self.assertFalse(
            result,
            "Sessions on different weekdays must not require a travel gap.",
        )

class CrossCampusTravelValidatorTests(TimetableValidationTestBase):

    def setUp(self):
        super().setUp()

        self.campus_b = Campus.objects.create(
            name="Validator Travel Campus B"
        )

        self.room_campus_b = Classroom.objects.create(
            campus=self.campus_b,
            building="Block B",
            name="Travel Test Hall",
            capacity=40,
            equipment="Benches",
            is_active=True,
        )

        # Move the second group to Campus B.
        self.group_b = self.offering_b.student_groups.get()
        self.group_b.campus = self.campus_b
        self.group_b.save()

        # Both offerings use the same lecturer.
        shared_lecturer = self.offering_a.lecturers.get()
        self.offering_b.lecturers.set([shared_lecturer])

    def validate_with_second_slot(self, second_start):
        second_slot = TimeSlot.objects.create(
            weekday=0,
            start_time=second_start,
            end_time=time(
                second_start.hour + 2,
                second_start.minute,
            ),
            is_active=True,
        )

        entries = [
            self.make_entry(
                self.offering_a,
                self.monday_morning,
                self.room,
            ),
            self.make_entry(
                self.offering_b,
                second_slot,
                self.room_campus_b,
            ),
        ]

        return validate_timetable_proposal(entries, self.term)

    def test_validator_rejects_44_minute_cross_campus_gap(self):
        errors = self.validate_with_second_slot(time(10, 44))

        self.assertTrue(
            any(
                "cross-campus travel gap" in error.lower()
                for error in errors
            ),
            msg=f"Expected a 44-minute travel-gap error, got: {errors}",
        )

    def test_validator_accepts_exactly_45_minute_cross_campus_gap(self):
        errors = self.validate_with_second_slot(time(10, 45))

        travel_errors = [
            error for error in errors
            if "cross-campus travel gap" in error.lower()
        ]

        self.assertEqual(
            travel_errors,
            [],
            msg=f"Exactly 45 minutes should be allowed: {errors}",
        )
class CrossCampusGeneratorTravelGapTests(TimetableValidationTestBase):

    def setUp(self):
        super().setUp()

        # Create a second campus and its classroom.
        self.campus_b = Campus.objects.create(
            name="Travel Test Campus B",
            code="TTCB",
        )

        self.room_campus_b = Classroom.objects.create(
            campus=self.campus_b,
            building="Block B",
            name="Travel Test Hall B",
            capacity=40,
            equipment="Benches",
            is_active=True,
        )

        # Move Group B to Campus B.
        self.group_b.campus = self.campus_b
        self.group_b.save()

        # Both offerings use the same lecturer.
        self.offering_b.lecturers.set([self.lecturer])

        # Create a fixed session for offering A.
        TeachingSession.objects.create(
            offering=self.offering_a,
            time_slot=self.monday_morning,
            classroom=self.room,
            is_published=True,
        ).student_groups.add(self.group)

        fixed_session = TeachingSession.objects.get(
    offering=self.offering_a
)
        fixed_session.lecturers.set([self.lecturer])

        # Exclude offering A from generation while keeping its
        # existing session as a fixed session.
        self.course_a.is_active = False
        self.course_a.save()

        # Keep only Campus B's classroom available for generation.
        self.room.is_active = False
        self.room.save()

        self.room_b.is_active = False
        self.room_b.save()

        # Disable all existing time slots except Monday morning.
        TimeSlot.objects.exclude(
            pk=self.monday_morning.pk
        ).update(is_active=False)

    def create_second_slot(self, start_time):
        from datetime import datetime, timedelta

        start = datetime.combine(date.today(), start_time)
        end = start + timedelta(hours=2)

        return TimeSlot.objects.create(
            name="Travel Test Slot",
            weekday=0,
            start_time=start.time(),
            end_time=end.time(),
            is_active=True,
        )

    def test_generator_rejects_44_minute_cross_campus_gap(self):
        from .generator import generate_timetable_proposal

        second_slot = self.create_second_slot(time(10, 44))

        result = generate_timetable_proposal(self.term)

        self.assertEqual(
            result["status"],
            "INFEASIBLE",
            msg=(
                "Generator should reject a 44-minute cross-campus "
                f"travel gap. Result: {result}"
            ),
        )

    def test_generator_accepts_45_minute_cross_campus_gap(self):
        from .generator import generate_timetable_proposal

        second_slot = self.create_second_slot(time(10, 45))

        result = generate_timetable_proposal(self.term)

        self.assertIn(
            result["status"],
            ("OPTIMAL", "FEASIBLE"),
            msg=result.get("message", "Generation failed."),
        )

        self.assertEqual(len(result["sessions"]), 1)

        generated = result["sessions"][0]

        self.assertEqual(
            generated["course_code"],
            self.course_b.code,
        )

        self.assertEqual(
            generated["start_time"],
            "10:45:00",
        )