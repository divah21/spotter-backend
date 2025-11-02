from django.db import models
from django.contrib.auth.models import AbstractUser


class User(AbstractUser):
	ROLE_CHOICES = (
		('driver', 'Driver'),
		('admin', 'Admin'),
	)
	role = models.CharField(max_length=10, choices=ROLE_CHOICES, default='driver')
	phone = models.CharField(max_length=20, blank=True)
	profile_picture = models.ImageField(upload_to='profiles/', blank=True, null=True)
	license_number = models.CharField(max_length=50, blank=True)
	created_at = models.DateTimeField(auto_now_add=True)
	updated_at = models.DateTimeField(auto_now=True)

	# Fix reverse accessor clashes
	groups = models.ManyToManyField(
		'auth.Group',
		related_name='spotter_users',
		blank=True,
		help_text='The groups this user belongs to.',
		verbose_name='groups',
	)
	user_permissions = models.ManyToManyField(
		'auth.Permission',
		related_name='spotter_users',
		blank=True,
		help_text='Specific permissions for this user.',
		verbose_name='user permissions',
	)

	def __str__(self):
		return f"{self.get_full_name() or self.username} ({self.role})"


class Trip(models.Model):
	STATUS_CHOICES = (
		('draft', 'Draft'),
		('pending', 'Pending Approval'),
		('approved', 'Approved'),
		('in_progress', 'In Progress'),
		('completed', 'Completed'),
		('cancelled', 'Cancelled'),
	)

	created_at = models.DateTimeField(auto_now_add=True)
	updated_at = models.DateTimeField(auto_now=True)

	driver = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='trips')
	driver_name = models.CharField(max_length=120, blank=True)  # fallback if no driver FK
	status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='draft')

	current_location = models.CharField(max_length=255)
	pickup_location = models.CharField(max_length=255)
	dropoff_location = models.CharField(max_length=255)
	current_cycle_used = models.FloatField(default=0)

	total_distance = models.IntegerField(default=0)  # miles
	total_driving_time = models.FloatField(default=0)  # hours
	estimated_days = models.IntegerField(default=1)

	approved_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='approved_trips')
	approved_at = models.DateTimeField(null=True, blank=True)
	notes = models.TextField(blank=True)

	def __str__(self):
		return f"Trip #{self.pk}: {self.pickup_location} -> {self.dropoff_location} ({self.status})"


class Stop(models.Model):
	trip = models.ForeignKey(Trip, on_delete=models.CASCADE, related_name='stops')
	order = models.IntegerField()
	type = models.CharField(max_length=32)
	name = models.CharField(max_length=255)
	location = models.CharField(max_length=255)
	duration = models.FloatField(default=0)
	miles_from_start = models.IntegerField(default=0)
	time_label = models.CharField(max_length=16, blank=True)

	class Meta:
		ordering = ['order']


class ELDLog(models.Model):
	SUBMISSION_STATUS_CHOICES = (
		('draft', 'Draft'),
		('submitted', 'Submitted'),
		('approved', 'Approved'),
		('rejected', 'Rejected'),
	)

	trip = models.ForeignKey(Trip, on_delete=models.CASCADE, related_name='eld_logs')
	date = models.DateField()
	day_number = models.IntegerField()
	total_miles = models.IntegerField(default=0)
	hours_off_duty = models.FloatField(default=0)
	hours_sleeper = models.FloatField(default=0)
	hours_driving = models.FloatField(default=0)
	hours_on_duty = models.FloatField(default=0)

	submission_status = models.CharField(max_length=20, choices=SUBMISSION_STATUS_CHOICES, default='draft')
	submitted_at = models.DateTimeField(null=True, blank=True)
	reviewed_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='reviewed_logs')
	reviewed_at = models.DateTimeField(null=True, blank=True)
	review_notes = models.TextField(blank=True)

	remarks = models.JSONField(default=list, blank=True)

	class Meta:
		ordering = ['day_number']

	def __str__(self):
		return f"ELD Log Day {self.day_number} - Trip #{self.trip_id} ({self.submission_status})"


class LogSegment(models.Model):
	log = models.ForeignKey(ELDLog, on_delete=models.CASCADE, related_name='segments')
	status = models.CharField(max_length=20)
	start_hour = models.FloatField()
	duration = models.FloatField()
	location = models.CharField(max_length=255, blank=True)

	def __str__(self):
		return f"{self.status} @ {self.start_hour}h for {self.duration}h"
