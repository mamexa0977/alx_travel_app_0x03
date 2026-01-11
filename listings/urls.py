from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import (
    ListingViewSet, 
    BookingViewSet, 
    PaymentViewSet,
    chapa_webhook
)

router = DefaultRouter()
router.register(r'listings', ListingViewSet)
router.register(r'bookings', BookingViewSet)
router.register(r'payments', PaymentViewSet, basename='payment')

urlpatterns = [
    path('', include(router.urls)),
    path('payments/webhook/', chapa_webhook, name='chapa-webhook'),
]