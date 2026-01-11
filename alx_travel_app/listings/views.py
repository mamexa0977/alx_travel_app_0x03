import requests
import json
from django.conf import settings
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import viewsets, status, generics
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView
from .models import Listing, Booking, Payment
from .serializers import (
    ListingSerializer, 
    BookingSerializer, 
    PaymentSerializer,
    PaymentInitiationSerializer,
    PaymentVerificationSerializer
)
from .tasks import send_booking_confirmation_email, send_payment_confirmation_email

class ListingViewSet(viewsets.ModelViewSet):
    """ViewSet for listing operations"""
    queryset = Listing.objects.filter(is_available=True)
    serializer_class = ListingSerializer
    permission_classes = [AllowAny]

class BookingViewSet(viewsets.ModelViewSet):
    """ViewSet for booking operations"""
    serializer_class = BookingSerializer
    permission_classes = [IsAuthenticated]
    
    def get_queryset(self):
        return Booking.objects.filter(user=self.request.user)
    
    def perform_create(self, serializer):
        """Save booking and trigger confirmation email"""
        booking = serializer.save(user=self.request.user)
        
        # Trigger booking confirmation email asynchronously
        send_booking_confirmation_email.delay(booking.id)
        
        # Return the booking instance
        return booking
    
    @action(detail=True, methods=['post'], url_path='resend-confirmation')
    def resend_confirmation(self, request, pk=None):
        """Resend booking confirmation email"""
        booking = self.get_object()
        
        # Trigger booking confirmation email asynchronously
        send_booking_confirmation_email.delay(booking.id)
        
        return Response({
            'message': 'Confirmation email has been sent',
            'booking_reference': booking.reference
        }, status=status.HTTP_200_OK)

class PaymentViewSet(viewsets.ViewSet):
    """ViewSet for payment operations"""
    permission_classes = [IsAuthenticated]
    
    @action(detail=False, methods=['post'], url_path='initiate')
    def initiate_payment(self, request):
        """Initiate payment with Chapa API"""
        serializer = PaymentInitiationSerializer(data=request.data)
        if serializer.is_valid():
            booking_id = serializer.validated_data['booking_id']
            booking = get_object_or_404(Booking, id=booking_id, user=request.user)
            
            # Check if payment already exists
            if hasattr(booking, 'payment'):
                return Response({
                    'error': 'Payment already initiated for this booking',
                    'payment_url': booking.payment.raw_response.get('data', {}).get('checkout_url') if booking.payment.raw_response else None
                }, status=status.HTTP_400_BAD_REQUEST)
            
            # Prepare Chapa API request
            chapa_url = f"{settings.CHAPA_BASE_URL}/transaction/initialize"
            headers = {
                'Authorization': f'Bearer {settings.CHAPA_SECRET_KEY}',
                'Content-Type': 'application/json'
            }
            
            payload = {
                'amount': str(booking.total_price),
                'currency': 'ETB',
                'email': request.user.email,
                'first_name': request.user.first_name or 'Customer',
                'last_name': request.user.last_name or 'User',
                'phone_number': '0912345678',  # In production, get from user profile
                'tx_ref': f"booking-{booking.id}-{timezone.now().timestamp()}",
                'callback_url': settings.CHAPA_WEBHOOK_URL,
                'return_url': f"http://localhost:3000/bookings/{booking.id}/payment/callback",
                'customization': {
                    'title': 'ALX Travel Booking',
                    'description': f'Payment for booking #{booking.reference}'
                }
            }
            
            try:
                # Make request to Chapa API
                response = requests.post(chapa_url, headers=headers, data=json.dumps(payload))
                response_data = response.json()
                
                if response.status_code == 200 and response_data.get('status') == 'success':
                    # Create payment record
                    payment = Payment.objects.create(
                        booking=booking,
                        amount=booking.total_price,
                        chapa_transaction_id=response_data.get('data', {}).get('reference'),
                        raw_response=response_data
                    )
                    
                    # Return payment URL to redirect user
                    return Response({
                        'message': 'Payment initiated successfully',
                        'payment_url': response_data.get('data', {}).get('checkout_url'),
                        'transaction_id': payment.transaction_id,
                        'booking_reference': booking.reference
                    }, status=status.HTTP_200_OK)
                else:
                    return Response({
                        'error': 'Failed to initiate payment',
                        'details': response_data.get('message', 'Unknown error')
                    }, status=status.HTTP_400_BAD_REQUEST)
                    
            except requests.exceptions.RequestException as e:
                return Response({
                    'error': 'Payment gateway connection failed',
                    'details': str(e)
                }, status=status.HTTP_503_SERVICE_UNAVAILABLE)
                
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    
    @action(detail=False, methods=['post'], url_path='verify')
    def verify_payment(self, request):
        """Verify payment status with Chapa API"""
        serializer = PaymentVerificationSerializer(data=request.data)
        if serializer.is_valid():
            transaction_id = serializer.validated_data['transaction_id']
            payment = get_object_or_404(Payment, transaction_id=transaction_id, booking__user=request.user)
            
            # Verify with Chapa API
            chapa_url = f"{settings.CHAPA_BASE_URL}/transaction/verify/{payment.chapa_transaction_id}"
            headers = {
                'Authorization': f'Bearer {settings.CHAPA_SECRET_KEY}'
            }
            
            try:
                response = requests.get(chapa_url, headers=headers)
                response_data = response.json()
                
                if response.status_code == 200 and response_data.get('status') == 'success':
                    transaction_data = response_data.get('data', {})
                    
                    # Update payment status
                    payment.status = Payment.COMPLETED
                    payment.payment_date = timezone.now()
                    payment.payment_method = transaction_data.get('payment_method', '')
                    payment.raw_response = response_data
                    payment.save()
                    
                    # Update booking status
                    booking = payment.booking
                    booking.status = Booking.CONFIRMED
                    booking.save()
                    
                    # Send confirmation email asynchronously
                    send_payment_confirmation_email.delay(
                        user_email=request.user.email,
                        booking_id=booking.id,
                        transaction_id=payment.transaction_id
                    )
                    
                    return Response({
                        'message': 'Payment verified successfully',
                        'status': payment.status,
                        'transaction_id': payment.transaction_id,
                        'booking_status': booking.status,
                        'verified_at': payment.payment_date
                    }, status=status.HTTP_200_OK)
                else:
                    # Payment failed or pending
                    payment.status = Payment.FAILED
                    payment.raw_response = response_data
                    payment.save()
                    
                    return Response({
                        'error': 'Payment verification failed',
                        'status': payment.status,
                        'details': response_data.get('message', 'Unknown error')
                    }, status=status.HTTP_400_BAD_REQUEST)
                    
            except requests.exceptions.RequestException as e:
                return Response({
                    'error': 'Payment verification service unavailable',
                    'details': str(e)
                }, status=status.HTTP_503_SERVICE_UNAVAILABLE)
                
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    
    @action(detail=False, methods=['get'], url_path='status/(?P<transaction_id>[^/.]+)')
    def payment_status(self, request, transaction_id=None):
        """Check payment status"""
        payment = get_object_or_404(Payment, transaction_id=transaction_id, booking__user=request.user)
        
        return Response({
            'transaction_id': payment.transaction_id,
            'status': payment.status,
            'amount': payment.amount,
            'booking_reference': payment.booking.reference,
            'created_at': payment.created_at,
            'updated_at': payment.updated_at
        }, status=status.HTTP_200_OK)

@api_view(['POST'])
@permission_classes([AllowAny])
def chapa_webhook(request):
    """Handle Chapa payment webhook"""
    # Verify webhook signature (in production, verify with Chapa's signature)
    data = request.data
    
    # Extract transaction reference
    tx_ref = data.get('tx_ref')
    status = data.get('status')
    
    if not tx_ref:
        return Response({'error': 'Missing transaction reference'}, status=status.HTTP_400_BAD_REQUEST)
    
    try:
        # Find payment by Chapa transaction ID
        payment = Payment.objects.get(chapa_transaction_id=tx_ref)
        
        if status == 'success':
            payment.status = Payment.COMPLETED
            payment.payment_date = timezone.now()
            payment.raw_response = data
            
            # Update booking status
            booking = payment.booking
            booking.status = Booking.CONFIRMED
            booking.save()
            
            # Send confirmation email
            send_payment_confirmation_email.delay(
                user_email=booking.user.email,
                booking_id=booking.id,
                transaction_id=payment.transaction_id
            )
            
        elif status == 'failed':
            payment.status = Payment.FAILED
            payment.raw_response = data
        
        payment.save()
        
        return Response({'message': 'Webhook processed successfully'}, status=status.HTTP_200_OK)
        
    except Payment.DoesNotExist:
        return Response({'error': 'Payment not found'}, status=status.HTTP_404_NOT_FOUND)
    except Exception as e:
        return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)