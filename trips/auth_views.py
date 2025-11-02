"""
Authentication views for user registration, login, profile management.
"""
from rest_framework import status, generics, permissions
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from rest_framework_simplejwt.tokens import RefreshToken
from django.contrib.auth import authenticate
from drf_spectacular.utils import extend_schema, OpenApiResponse

from .models import User
from .serializers import (
    UserSerializer,
    UserCreateSerializer,
    UserUpdateSerializer,
    ChangePasswordSerializer,
)


@extend_schema(
    tags=["Auth"],
    request=UserCreateSerializer,
    responses={201: UserSerializer},
    summary="Register a new user",
    description="Create a new user account with role (driver or admin)."
)
@api_view(["POST"])
@permission_classes([permissions.AllowAny])
def register(request):
    serializer = UserCreateSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    user = serializer.save()
    refresh = RefreshToken.for_user(user)
    user_data = UserSerializer(user).data
    return Response({
        'user': user_data,
        'access': str(refresh.access_token),
        'refresh': str(refresh),
    }, status=status.HTTP_201_CREATED)


@extend_schema(
    tags=["Auth"],
    request={
        'application/json': {
            'type': 'object',
            'properties': {
                'username': {'type': 'string'},
                'password': {'type': 'string'}
            }
        }
    },
    responses={200: {
        'type': 'object',
        'properties': {
            'user': {'type': 'object'},
            'access': {'type': 'string'},
            'refresh': {'type': 'string'},
        }
    }},
    summary="Login user",
    description="Authenticate user and return JWT tokens."
)
@api_view(["POST"])
@permission_classes([permissions.AllowAny])
def login(request):
    username = request.data.get('username')
    password = request.data.get('password')
    
    if not username or not password:
        return Response({'error': 'Username and password required.'}, status=status.HTTP_400_BAD_REQUEST)
    
    user = authenticate(username=username, password=password)
    
    if user is None:
        return Response({'error': 'Invalid credentials.'}, status=status.HTTP_401_UNAUTHORIZED)
    
    if not user.is_active:
        return Response({'error': 'Account is inactive.'}, status=status.HTTP_403_FORBIDDEN)
    
    refresh = RefreshToken.for_user(user)
    user_data = UserSerializer(user).data
    
    return Response({
        'user': user_data,
        'access': str(refresh.access_token),
        'refresh': str(refresh),
    })


@extend_schema(
    tags=["Auth"],
    responses={200: UserSerializer},
    summary="Get current user profile",
    description="Retrieve authenticated user's profile information."
)
@api_view(["GET"])
@permission_classes([permissions.IsAuthenticated])
def me(request):
    serializer = UserSerializer(request.user)
    return Response(serializer.data)


@extend_schema(
    tags=["Auth"],
    request=UserUpdateSerializer,
    responses={200: UserSerializer},
    summary="Update user profile",
    description="Update authenticated user's profile information."
)
@api_view(["PATCH"])
@permission_classes([permissions.IsAuthenticated])
def update_profile(request):
    serializer = UserUpdateSerializer(request.user, data=request.data, partial=True)
    serializer.is_valid(raise_exception=True)
    serializer.save()
    return Response(UserSerializer(request.user).data)


@extend_schema(
    tags=["Auth"],
    request=ChangePasswordSerializer,
    responses={200: {'type': 'object', 'properties': {'message': {'type': 'string'}}}},
    summary="Change password",
    description="Change authenticated user's password."
)
@api_view(["POST"])
@permission_classes([permissions.IsAuthenticated])
def change_password(request):
    serializer = ChangePasswordSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    
    user = request.user
    if not user.check_password(serializer.validated_data['old_password']):
        return Response({'error': 'Old password is incorrect.'}, status=status.HTTP_400_BAD_REQUEST)
    
    user.set_password(serializer.validated_data['new_password'])
    user.save()
    
    return Response({'message': 'Password changed successfully.'})


# ============ USER MANAGEMENT (Admin only) ============

@extend_schema(tags=["Users"])
class UserListCreateView(generics.ListCreateAPIView):
    """List all users or create a new user (admin only)."""
    queryset = User.objects.all().order_by('-created_at')
    permission_classes = [permissions.IsAuthenticated]
    
    def get_serializer_class(self):
        if self.request.method == 'POST':
            return UserCreateSerializer
        return UserSerializer
    
    def get_queryset(self):
        qs = super().get_queryset()
        role = self.request.query_params.get('role')
        is_active = self.request.query_params.get('is_active')
        search = self.request.query_params.get('search')
        
        if role:
            qs = qs.filter(role=role)
        if is_active is not None:
            qs = qs.filter(is_active=is_active.lower() == 'true')
        if search:
            qs = qs.filter(username__icontains=search) | qs.filter(email__icontains=search) | qs.filter(first_name__icontains=search) | qs.filter(last_name__icontains=search)
        
        return qs
    
    def perform_create(self, serializer):
        # Admin creating users
        if self.request.user.role != 'admin':
            raise permissions.PermissionDenied("Only admins can create users via this endpoint.")
        serializer.save()


@extend_schema(tags=["Users"])
class UserDetailView(generics.RetrieveUpdateDestroyAPIView):
    """Retrieve, update, or delete a user (admin only for update/delete)."""
    queryset = User.objects.all()
    serializer_class = UserSerializer
    permission_classes = [permissions.IsAuthenticated]
    
    def get_serializer_class(self):
        if self.request.method in ['PUT', 'PATCH']:
            return UserUpdateSerializer
        return UserSerializer
    
    def perform_update(self, serializer):
        if self.request.user.role != 'admin' and self.request.user.id != self.get_object().id:
            raise permissions.PermissionDenied("You can only update your own profile.")
        serializer.save()
    
    def perform_destroy(self, instance):
        if self.request.user.role != 'admin':
            raise permissions.PermissionDenied("Only admins can delete users.")
        instance.delete()


@extend_schema(
    tags=["Users"],
    request={'application/json': {'type': 'object', 'properties': {'is_active': {'type': 'boolean'}}}},
    responses={200: UserSerializer},
    summary="Toggle user active status",
    description="Activate or deactivate a user (admin only)."
)
@api_view(["PATCH"])
@permission_classes([permissions.IsAuthenticated])
def toggle_user_status(request, pk):
    if request.user.role != 'admin':
        return Response({'error': 'Admin only.'}, status=status.HTTP_403_FORBIDDEN)
    
    try:
        user = User.objects.get(pk=pk)
    except User.DoesNotExist:
        return Response({'error': 'User not found.'}, status=status.HTTP_404_NOT_FOUND)
    
    is_active = request.data.get('is_active')
    if is_active is not None:
        user.is_active = is_active
        user.save()
    
    return Response(UserSerializer(user).data)
