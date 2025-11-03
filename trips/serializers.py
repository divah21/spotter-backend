from rest_framework import serializers
from django.contrib.auth.password_validation import validate_password
from drf_spectacular.utils import extend_schema_field
from .models import User, Trip, Stop, ELDLog, LogSegment


# ============ USER & AUTH SERIALIZERS ============

class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ('id', 'username', 'email', 'first_name', 'last_name', 'role', 'phone', 'profile_picture', 'license_number', 'is_active', 'created_at', 'updated_at')
        read_only_fields = ('id', 'created_at', 'updated_at')


class UserCreateSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, required=True, validators=[validate_password])
    password_confirm = serializers.CharField(write_only=True, required=True)

    class Meta:
        model = User
        fields = ('username', 'email', 'password', 'password_confirm', 'first_name', 'last_name', 'role', 'phone', 'license_number')

    def validate(self, attrs):
        if attrs['password'] != attrs['password_confirm']:
            raise serializers.ValidationError({"password": "Passwords do not match."})
        return attrs

    def create(self, validated_data):
        validated_data.pop('password_confirm')
        user = User.objects.create_user(**validated_data)
        return user


class UserUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ('first_name', 'last_name', 'email', 'phone', 'profile_picture', 'license_number')


class ChangePasswordSerializer(serializers.Serializer):
    old_password = serializers.CharField(required=True)
    new_password = serializers.CharField(required=True, validators=[validate_password])


# ============ TRIP & LOG SERIALIZERS ============

class LogSegmentSerializer(serializers.ModelSerializer):
    class Meta:
        model = LogSegment
        fields = ("status", "start_hour", "duration", "location")


class ELDLogSerializer(serializers.ModelSerializer):
    id = serializers.IntegerField(read_only=True)
    trip = serializers.SerializerMethodField()
    driver = serializers.SerializerMethodField()
    driver_name = serializers.ReadOnlyField(source='trip.driver_name')
    segments = LogSegmentSerializer(many=True, read_only=True)
    reviewed_by_name = serializers.SerializerMethodField()

    class Meta:
        model = ELDLog
        fields = (
            "id",
            "trip",
            "driver",
            "driver_name",
            "date",
            "day_number",
            "total_miles",
            "hours_off_duty",
            "hours_sleeper",
            "hours_driving",
            "hours_on_duty",
            "submission_status",
            "submitted_at",
            "reviewed_by",
            "reviewed_by_name",
            "reviewed_at",
            "review_notes",
            "remarks",
            "segments",
        )

    @extend_schema_field(serializers.CharField(allow_null=True))
    def get_reviewed_by_name(self, obj):
        return obj.reviewed_by.get_full_name() if obj.reviewed_by else None
    
    def get_trip(self, obj):
        """Return trip details with pickup/dropoff locations"""
        if obj.trip:
            return {
                'id': obj.trip.id,
                'pickup_location': obj.trip.pickup_location,
                'dropoff_location': obj.trip.dropoff_location,
                'driver_name': obj.trip.driver_name,
            }
        return None
    
    def get_driver(self, obj):
        """Return driver info from trip"""
        if obj.trip and obj.trip.driver:
            return {
                'id': obj.trip.driver.id,
                'username': obj.trip.driver.username,
                'first_name': obj.trip.driver.first_name,
                'last_name': obj.trip.driver.last_name,
            }
        return None


class StopSerializer(serializers.ModelSerializer):
    class Meta:
        model = Stop
        fields = ("order", "type", "name", "location", "duration", "miles_from_start", "time_label")


class TripSerializer(serializers.ModelSerializer):
    stops = StopSerializer(many=True, read_only=True)
    eld_logs = ELDLogSerializer(many=True, read_only=True)
    driver_info = UserSerializer(source='driver', read_only=True)
    approved_by_name = serializers.SerializerMethodField()

    class Meta:
        model = Trip
        fields = (
            "id",
            "driver",
            "driver_info",
            "driver_name",
            "status",
            "current_location",
            "pickup_location",
            "dropoff_location",
            "current_cycle_used",
            "total_distance",
            "total_driving_time",
            "estimated_days",
            "approved_by",
            "approved_by_name",
            "approved_at",
            "notes",
            "stops",
            "eld_logs",
            "created_at",
            "updated_at",
        )

    @extend_schema_field(serializers.CharField(allow_null=True))
    def get_approved_by_name(self, obj):
        return obj.approved_by.get_full_name() if obj.approved_by else None


class TripCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Trip
        fields = (
            "driver",
            "driver_name",
            "current_location",
            "pickup_location",
            "dropoff_location",
            "current_cycle_used",
            "notes",
        )


class TripUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Trip
        fields = ('status', 'driver', 'notes', 'current_location', 'pickup_location', 'dropoff_location')


class LogSubmitSerializer(serializers.Serializer):
    log_ids = serializers.ListField(child=serializers.IntegerField())


class LogReviewSerializer(serializers.Serializer):
    action = serializers.ChoiceField(choices=['approve', 'reject'])
    review_notes = serializers.CharField(required=False, allow_blank=True)
