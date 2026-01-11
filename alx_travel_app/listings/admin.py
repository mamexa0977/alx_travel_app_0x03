from django.contrib import admin
from .models import Listing, Booking, Payment

@admin.register(Listing)
class ListingAdmin(admin.ModelAdmin):
    list_display = ('title', 'price_per_night', 'location', 'bedrooms', 'bathrooms', 'is_available')
    list_filter = ('is_available', 'location')
    search_fields = ('title', 'description', 'location')
    list_per_page = 20

@admin.register(Booking)
class BookingAdmin(admin.ModelAdmin):
    list_display = ('id', 'user', 'listing', 'check_in', 'check_out', 'status', 'total_price')
    list_filter = ('status', 'check_in', 'check_out')
    search_fields = ('user__username', 'listing__title', 'special_requests')
    readonly_fields = ('reference',)
    list_per_page = 20

@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = ('transaction_id', 'booking', 'amount', 'status', 'payment_date', 'created_at')
    list_filter = ('status', 'payment_date', 'created_at')
    search_fields = ('transaction_id', 'chapa_transaction_id', 'booking__reference')
    readonly_fields = ('transaction_id', 'chapa_transaction_id', 'raw_response')
    list_per_page = 20