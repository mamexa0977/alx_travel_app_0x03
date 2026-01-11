from rest_framework import serializers
from .models import Listing, Booking, Payment
from django.utils import timezone

class ListingSerializer(serializers.ModelSerializer):
    class Meta:
        model = Listing
        fields = '__all__'

class BookingSerializer(serializers.ModelSerializer):
    user = serializers.StringRelatedField(read_only=True)
    listing = serializers.PrimaryKeyRelatedField(queryset=Listing.objects.filter(is_available=True))
    reference = serializers.CharField(read_only=True)
    
    class Meta:
        model = Booking
        fields = '__all__'
        read_only_fields = ('user', 'status', 'total_price', 'reference')
    
    def validate(self, data):
        """Validate booking data"""
        # Check if check_out is after check_in
        if data['check_out'] <= data['check_in']:
            raise serializers.ValidationError("Check-out date must be after check-in date")
        
        # Check if dates are in the future
        if data['check_in'] < timezone.now().date():
            raise serializers.ValidationError("Check-in date must be in the future")
        
        # Check number of guests
        listing = data['listing']
        if data['number_of_guests'] > listing.max_guests:
            raise serializers.ValidationError(f"Maximum guests allowed is {listing.max_guests}")
        
        # Calculate total price
        nights = (data['check_out'] - data['check_in']).days
        data['total_price'] = listing.price_per_night * nights
        
        return data

class PaymentSerializer(serializers.ModelSerializer):
    booking_reference = serializers.CharField(source='booking.reference', read_only=True)
    
    class Meta:
        model = Payment
        fields = '__all__'
        read_only_fields = ('transaction_id', 'chapa_transaction_id', 'status', 
                           'payment_date', 'raw_response', 'created_at', 'updated_at')

class PaymentInitiationSerializer(serializers.Serializer):
    booking_id = serializers.IntegerField()
    
    def validate_booking_id(self, value):
        """Validate booking exists and belongs to user"""
        request = self.context.get('request')
        if request and request.user.is_authenticated:
            try:
                booking = Booking.objects.get(id=value, user=request.user)
                if booking.status != Booking.PENDING:
                    raise serializers.ValidationError("Booking is not in pending status")
                return value
            except Booking.DoesNotExist:
                raise serializers.ValidationError("Booking not found")
        return value

class PaymentVerificationSerializer(serializers.Serializer):
    transaction_id = serializers.CharField(max_length=100)
    
    def validate_transaction_id(self, value):
        """Validate transaction ID exists"""
        request = self.context.get('request')
        if request and request.user.is_authenticated:
            try:
                Payment.objects.get(transaction_id=value, booking__user=request.user)
                return value
            except Payment.DoesNotExist:
                raise serializers.ValidationError("Transaction not found")
        return value