from celery import shared_task
from django.core.mail import send_mail
from django.conf import settings
from django.template.loader import render_to_string
from django.utils.html import strip_tags
from django.contrib.auth.models import User
from .models import Booking, Payment
import logging

logger = logging.getLogger(__name__)

@shared_task(bind=True)
def debug_task(self):
    """Debug task to verify Celery is working"""
    print(f'Request: {self.request!r}')
    return 'Debug task executed successfully'

@shared_task
def send_booking_confirmation_email(booking_id):
    """
    Send booking confirmation email asynchronously
    """
    try:
        booking = Booking.objects.get(id=booking_id)
        user = booking.user
        
        subject = f"Booking Confirmation - {booking.reference}"
        
        # Prepare email context
        context = {
            'user_name': user.get_full_name() or user.username,
            'booking': booking,
            'site_name': 'ALX Travel'
        }
        
        # Render HTML and plain text templates
        html_message = render_to_string('emails/booking_confirmation.html', context)
        plain_message = render_to_string('emails/booking_confirmation.txt', context)
        
        # Send email
        send_mail(
            subject=subject,
            message=plain_message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[user.email],
            html_message=html_message,
            fail_silently=False,
        )
        
        logger.info(f"Booking confirmation email sent to {user.email} for booking #{booking.reference}")
        return f"Booking confirmation email sent to {user.email}"
        
    except Booking.DoesNotExist:
        logger.error(f"Booking with ID {booking_id} not found")
        return f"Booking with ID {booking_id} not found"
    except Exception as e:
        logger.error(f"Failed to send booking confirmation email: {str(e)}")
        return f"Failed to send email: {str(e)}"

@shared_task
def send_payment_confirmation_email(user_email, booking_id, transaction_id):
    """Send payment confirmation email asynchronously"""
    try:
        booking = Booking.objects.get(id=booking_id)
        payment = Payment.objects.get(transaction_id=transaction_id)
        
        subject = f"Payment Confirmed - Booking #{booking.reference}"
        
        # Prepare email context
        context = {
            'booking': booking,
            'payment': payment,
            'user_email': user_email,
            'site_name': 'ALX Travel'
        }
        
        # Render HTML email template
        html_message = render_to_string('emails/payment_confirmation.html', context)
        plain_message = strip_tags(html_message)
        
        # Send email
        send_mail(
            subject=subject,
            message=plain_message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[user_email],
            html_message=html_message,
            fail_silently=False,
        )
        
        logger.info(f"Payment confirmation email sent to {user_email} for booking #{booking.reference}")
        return f"Confirmation email sent to {user_email} for booking #{booking.reference}"
        
    except Booking.DoesNotExist:
        logger.error(f"Booking #{booking_id} not found")
        return f"Booking #{booking_id} not found"
    except Payment.DoesNotExist:
        logger.error(f"Payment with transaction ID {transaction_id} not found")
        return f"Payment with transaction ID {transaction_id} not found"
    except Exception as e:
        logger.error(f"Failed to send payment confirmation email: {str(e)}")
        return f"Failed to send email: {str(e)}"

@shared_task
def check_pending_payments():
    """Check and update status of pending payments"""
    from django.utils import timezone
    from datetime import timedelta
    
    # Find payments pending for more than 30 minutes
    time_threshold = timezone.now() - timedelta(minutes=30)
    pending_payments = Payment.objects.filter(
        status=Payment.PENDING,
        created_at__lt=time_threshold
    )
    
    updated_count = 0
    for payment in pending_payments:
        payment.status = Payment.FAILED
        payment.save()
        updated_count += 1
        
    logger.info(f"Updated {updated_count} expired payments")
    return f"Updated {pending_payments.count()} expired payments"