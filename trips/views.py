from rest_framework import generics, status, permissions
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from drf_spectacular.utils import extend_schema, OpenApiParameter, OpenApiTypes
from django.db import transaction
from django.utils import timezone

from .models import Trip, Stop, ELDLog, LogSegment, User
from .serializers import (
	TripSerializer,
	TripCreateSerializer,
	TripUpdateSerializer,
	ELDLogSerializer,
	LogSubmitSerializer,
	LogReviewSerializer,
)
from .services import plan_route, generate_eld_logs


@extend_schema(
	tags=["Trips"],
	request=TripCreateSerializer,
	responses={201: TripSerializer},
	summary="Plan a trip and persist data",
	description="Compute route and ELD logs from locations and persist Trip, Stops, and ELD Logs.")
@api_view(["POST"])
def plan_trip(request):
	"""
	Plan a trip given locations and constraints, persist Trip/Stops/ELDLogs, and return the Trip data.

	Expected JSON body:
	{
	  "driver_name": str (optional),
	  "current_location": str,
	  "pickup_location": str,
	  "dropoff_location": str,
	  "current_cycle_used": float (optional)
	}
	"""
	serializer = TripCreateSerializer(data=request.data)
	serializer.is_valid(raise_exception=True)
	data = serializer.validated_data

	route_data = plan_route(
		data["current_location"],
		data["pickup_location"],
		data["dropoff_location"],
		float(data.get("current_cycle_used", 0) or 0),
	)
	eld_logs_data = generate_eld_logs(data, route_data)

	with transaction.atomic():
		trip = Trip.objects.create(
			driver=request.user if request.user.is_authenticated else None,
			driver_name=data.get("driver_name", ""),
			current_location=data["current_location"],
			pickup_location=data["pickup_location"],
			dropoff_location=data["dropoff_location"],
			current_cycle_used=float(data.get("current_cycle_used", 0) or 0),
			total_distance=int(route_data.get("totalDistance", 0) or 0),
			total_driving_time=float(route_data.get("totalDrivingTime", 0) or 0),
			estimated_days=int(route_data.get("estimatedDays", 1) or 1),
		)

		for idx, s in enumerate(route_data.get("restStops", []), start=1):
			Stop.objects.create(
				trip=trip,
				order=idx,
				type=s.get("type", "other"),
				name=s.get("name", ""),
				location=s.get("location", ""),
				duration=float(s.get("duration", 0) or 0),
				miles_from_start=int(s.get("milesFromStart", 0) or 0),
				time_label=s.get("time", ""),
			)

		for log in eld_logs_data:
			eld = ELDLog.objects.create(
				trip=trip,
				date=log["date"],
				day_number=int(log.get("dayNumber", 1)),
				total_miles=int(log.get("totalMiles", 0) or 0),
				hours_off_duty=float(log["hours"]["offDuty"]),
				hours_sleeper=float(log["hours"]["sleeperBerth"]),
				hours_driving=float(log["hours"]["driving"]),
				hours_on_duty=float(log["hours"]["onDuty"]),
			)
			for seg in log.get("segments", []):
				LogSegment.objects.create(
					log=eld,
					status=seg.get("status", "on-duty"),
					start_hour=float(seg.get("startHour", 0)),
					duration=float(seg.get("duration", 0)),
					location=seg.get("location", ""),
				)

	out = TripSerializer(trip)
	return Response(out.data, status=status.HTTP_201_CREATED)


@extend_schema(tags=["Trips"], parameters=[
	OpenApiParameter(name='driver', description='Filter by driver ID', required=False, type=OpenApiTypes.INT),
	OpenApiParameter(name='status', description='Filter by trip status', required=False, type=OpenApiTypes.STR),
	OpenApiParameter(name='start_date', description='Filter trips created after date', required=False, type=OpenApiTypes.DATE),
	OpenApiParameter(name='end_date', description='Filter trips created before date', required=False, type=OpenApiTypes.DATE),
])
class TripListCreateView(generics.ListCreateAPIView):
	queryset = Trip.objects.select_related('driver', 'approved_by').prefetch_related('stops', 'eld_logs').all().order_by("-created_at")
	permission_classes = [permissions.IsAuthenticated]

	def get_serializer_class(self):
		if self.request.method == "POST":
			return TripCreateSerializer
		return TripSerializer

	def perform_create(self, serializer):
		# Assign current user as driver if role is driver and no driver specified
		if self.request.user.role == 'driver' and not serializer.validated_data.get('driver'):
			serializer.save(driver=self.request.user, driver_name=self.request.user.get_full_name())
		else:
			serializer.save()

	def get_queryset(self):
		qs = super().get_queryset()
		user = self.request.user

		if user.role == 'driver':
			qs = qs.filter(driver=user)

		# Admin filters
		driver_id = self.request.query_params.get("driver")
		trip_status = self.request.query_params.get("status")
		start_date = self.request.query_params.get("start_date")
		end_date = self.request.query_params.get("end_date")

		if driver_id:
			qs = qs.filter(driver_id=driver_id)
		if trip_status:
			qs = qs.filter(status=trip_status)
		if start_date:
			qs = qs.filter(created_at__date__gte=start_date)
		if end_date:
			qs = qs.filter(created_at__date__lte=end_date)

		return qs


@extend_schema(tags=["Trips"])
class TripDetailView(generics.RetrieveUpdateDestroyAPIView):
	queryset = Trip.objects.select_related('driver', 'approved_by').prefetch_related('stops', 'eld_logs__segments').all()
	permission_classes = [permissions.IsAuthenticated]

	def get_serializer_class(self):
		if self.request.method in ['PUT', 'PATCH']:
			return TripUpdateSerializer
		return TripSerializer

	def get_queryset(self):
		qs = super().get_queryset()
		user = self.request.user
		if user.role == 'driver':
			qs = qs.filter(driver=user)
		return qs

	def perform_destroy(self, instance):
		if instance.status not in ['draft', 'cancelled'] and self.request.user.role != 'admin':
			raise permissions.PermissionDenied("Can only delete draft or cancelled trips.")
		instance.delete()


@extend_schema(tags=["Logs"], parameters=[
	OpenApiParameter(name='driver', description='Filter by driver name (icontains)', required=False, type=OpenApiTypes.STR),
	OpenApiParameter(name='trip', description='Filter by trip id', required=False, type=OpenApiTypes.INT),
	OpenApiParameter(name='start', description='Start date (YYYY-MM-DD)', required=False, type=OpenApiTypes.DATE),
	OpenApiParameter(name='end', description='End date (YYYY-MM-DD)', required=False, type=OpenApiTypes.DATE),
])
class LogListView(generics.ListAPIView):
	serializer_class = ELDLogSerializer

	def get_queryset(self):
		qs = ELDLog.objects.select_related("trip").prefetch_related("segments").all().order_by("-date")
		driver = self.request.query_params.get("driver")
		trip_id = self.request.query_params.get("trip")
		start = self.request.query_params.get("start")
		end = self.request.query_params.get("end")
		if driver:
			qs = qs.filter(trip__driver_name__icontains=driver)
		if trip_id:
			qs = qs.filter(trip_id=trip_id)
		if start:
			qs = qs.filter(date__gte=start)
		if end:
			qs = qs.filter(date__lte=end)
		return qs


@extend_schema(tags=["Logs"])
class LogDetailView(generics.RetrieveAPIView):
	queryset = ELDLog.objects.prefetch_related("segments").all()
	serializer_class = ELDLogSerializer
	permission_classes = [permissions.IsAuthenticated]

	def get_queryset(self):
		qs = super().get_queryset()
		user = self.request.user
		if user.role == 'driver':
			qs = qs.filter(trip__driver=user)
		return qs



@extend_schema(
	tags=["Trips"],
	request={'application/json': {'type': 'object', 'properties': {'notes': {'type': 'string'}}}},
	responses={200: TripSerializer},
	summary="Submit trip for approval",
	description="Driver submits a trip to admin for approval (changes status from draft to pending)."
)
@api_view(["POST"])
@permission_classes([permissions.IsAuthenticated])
def submit_trip(request, pk):
	try:
		trip = Trip.objects.get(pk=pk)
	except Trip.DoesNotExist:
		return Response({'error': 'Trip not found.'}, status=status.HTTP_404_NOT_FOUND)

	if request.user.role == 'driver' and trip.driver != request.user:
		return Response({'error': 'You can only submit your own trips.'}, status=status.HTTP_403_FORBIDDEN)

	if trip.status != 'draft':
		return Response({'error': f'Can only submit draft trips. Current status: {trip.status}'}, status=status.HTTP_400_BAD_REQUEST)

	trip.status = 'pending'
	if request.data.get('notes'):
		trip.notes = request.data['notes']
	trip.save()

	return Response(TripSerializer(trip).data)


@extend_schema(
	tags=["Trips"],
	request={'application/json': {'type': 'object', 'properties': {'notes': {'type': 'string'}}}},
	responses={200: TripSerializer},
	summary="Approve trip",
	description="Admin approves a pending trip."
)
@api_view(["POST"])
@permission_classes([permissions.IsAuthenticated])
def approve_trip(request, pk):
	if request.user.role != 'admin':
		return Response({'error': 'Admin only.'}, status=status.HTTP_403_FORBIDDEN)

	try:
		trip = Trip.objects.get(pk=pk)
	except Trip.DoesNotExist:
		return Response({'error': 'Trip not found.'}, status=status.HTTP_404_NOT_FOUND)

	if trip.status != 'pending':
		return Response({'error': f'Can only approve pending trips. Current status: {trip.status}'}, status=status.HTTP_400_BAD_REQUEST)

	trip.status = 'approved'
	trip.approved_by = request.user
	trip.approved_at = timezone.now()
	if request.data.get('notes'):
		trip.notes = request.data['notes']
	trip.save()

	return Response(TripSerializer(trip).data)


@extend_schema(
	tags=["Trips"],
	request={'application/json': {'type': 'object', 'properties': {'notes': {'type': 'string'}}}},
	responses={200: TripSerializer},
	summary="Reject trip",
	description="Admin rejects a pending trip (returns to draft)."
)
@api_view(["POST"])
@permission_classes([permissions.IsAuthenticated])
def reject_trip(request, pk):
	if request.user.role != 'admin':
		return Response({'error': 'Admin only.'}, status=status.HTTP_403_FORBIDDEN)

	try:
		trip = Trip.objects.get(pk=pk)
	except Trip.DoesNotExist:
		return Response({'error': 'Trip not found.'}, status=status.HTTP_404_NOT_FOUND)

	if trip.status != 'pending':
		return Response({'error': f'Can only reject pending trips. Current status: {trip.status}'}, status=status.HTTP_400_BAD_REQUEST)

	trip.status = 'draft'
	if request.data.get('notes'):
		trip.notes = request.data['notes']
	trip.save()

	return Response(TripSerializer(trip).data)


@extend_schema(
	tags=["Trips"],
	request=None,
	responses={200: TripSerializer},
	summary="Start trip",
	description="Driver starts an approved trip (changes status to in_progress)."
)
@api_view(["POST"])
@permission_classes([permissions.IsAuthenticated])
def start_trip(request, pk):
	try:
		trip = Trip.objects.get(pk=pk)
	except Trip.DoesNotExist:
		return Response({'error': 'Trip not found.'}, status=status.HTTP_404_NOT_FOUND)

	if request.user.role == 'driver' and trip.driver != request.user:
		return Response({'error': 'You can only start your own trips.'}, status=status.HTTP_403_FORBIDDEN)

	if trip.status != 'approved':
		return Response({'error': f'Can only start approved trips. Current status: {trip.status}'}, status=status.HTTP_400_BAD_REQUEST)

	trip.status = 'in_progress'
	trip.save()

	return Response(TripSerializer(trip).data)


@extend_schema(
	tags=["Trips"],
	request=None,
	responses={200: TripSerializer},
	summary="Complete trip",
	description="Driver marks a trip as completed."
)
@api_view(["POST"])
@permission_classes([permissions.IsAuthenticated])
def complete_trip(request, pk):
	try:
		trip = Trip.objects.get(pk=pk)
	except Trip.DoesNotExist:
		return Response({'error': 'Trip not found.'}, status=status.HTTP_404_NOT_FOUND)

	if request.user.role == 'driver' and trip.driver != request.user:
		return Response({'error': 'You can only complete your own trips.'}, status=status.HTTP_403_FORBIDDEN)

	if trip.status != 'in_progress':
		return Response({'error': f'Can only complete in-progress trips. Current status: {trip.status}'}, status=status.HTTP_400_BAD_REQUEST)

	trip.status = 'completed'
	trip.save()

	return Response(TripSerializer(trip).data)


@extend_schema(
	tags=["Trips"],
	request={'application/json': {'type': 'object', 'properties': {'notes': {'type': 'string'}}}},
	responses={200: TripSerializer},
	summary="Cancel trip",
	description="Cancel a trip (admin can cancel any; driver can cancel own draft/pending)."
)
@api_view(["POST"])
@permission_classes([permissions.IsAuthenticated])
def cancel_trip(request, pk):
	try:
		trip = Trip.objects.get(pk=pk)
	except Trip.DoesNotExist:
		return Response({'error': 'Trip not found.'}, status=status.HTTP_404_NOT_FOUND)

	if request.user.role == 'driver':
		if trip.driver != request.user:
			return Response({'error': 'You can only cancel your own trips.'}, status=status.HTTP_403_FORBIDDEN)
		if trip.status not in ['draft', 'pending']:
			return Response({'error': 'Drivers can only cancel draft or pending trips.'}, status=status.HTTP_400_BAD_REQUEST)

	trip.status = 'cancelled'
	if request.data.get('notes'):
		trip.notes = request.data['notes']
	trip.save()

	return Response(TripSerializer(trip).data)



@extend_schema(
	tags=["Logs"],
	request=LogSubmitSerializer,
	responses={200: {'type': 'object', 'properties': {'message': {'type': 'string'}, 'submitted_logs': {'type': 'array'}}}},
	summary="Submit ELD logs",
	description="Driver submits draft logs for admin review."
)
@api_view(["POST"])
@permission_classes([permissions.IsAuthenticated])
def submit_logs(request):
	if request.user.role != 'driver':
		return Response({'error': 'Only drivers can submit logs.'}, status=status.HTTP_403_FORBIDDEN)

	serializer = LogSubmitSerializer(data=request.data)
	serializer.is_valid(raise_exception=True)

	log_ids = serializer.validated_data['log_ids']
	logs = ELDLog.objects.filter(id__in=log_ids, trip__driver=request.user, submission_status='draft')

	if not logs.exists():
		return Response({'error': 'No eligible draft logs found for submission.'}, status=status.HTTP_400_BAD_REQUEST)

	logs.update(submission_status='submitted', submitted_at=timezone.now())

	return Response({
		'message': f'{logs.count()} log(s) submitted successfully.',
		'submitted_logs': list(logs.values_list('id', flat=True))
	})


@extend_schema(
	tags=["Logs"],
	request=LogReviewSerializer,
	responses={200: ELDLogSerializer},
	summary="Review ELD log",
	description="Admin approves or rejects a submitted log."
)
@api_view(["POST"])
@permission_classes([permissions.IsAuthenticated])
def review_log(request, pk):
	if request.user.role != 'admin':
		return Response({'error': 'Admin only.'}, status=status.HTTP_403_FORBIDDEN)

	try:
		log = ELDLog.objects.get(pk=pk)
	except ELDLog.DoesNotExist:
		return Response({'error': 'Log not found.'}, status=status.HTTP_404_NOT_FOUND)

	if log.submission_status != 'submitted':
		return Response({'error': f'Can only review submitted logs. Current status: {log.submission_status}'}, status=status.HTTP_400_BAD_REQUEST)

	serializer = LogReviewSerializer(data=request.data)
	serializer.is_valid(raise_exception=True)

	action = serializer.validated_data['action']
	review_notes = serializer.validated_data.get('review_notes', '')

	if action == 'approve':
		log.submission_status = 'approved'
	elif action == 'reject':
		log.submission_status = 'rejected'

	log.reviewed_by = request.user
	log.reviewed_at = timezone.now()
	log.review_notes = review_notes
	log.save()

	return Response(ELDLogSerializer(log).data)
