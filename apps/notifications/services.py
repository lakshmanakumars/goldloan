"""Pluggable notification senders. Defaults to a log-only stub for dev;
swap to MSG91 / WhatsApp Cloud API by changing NOTIFICATION_CHANNEL or
wiring real client classes here.
"""
import logging
from django.conf import settings

log = logging.getLogger(__name__)


class LogSender:
    """Dev/test sender — just logs the message."""

    @staticmethod
    def send_whatsapp(to_phone, message):
        log.info('[WHATSAPP][LOG] to=%s msg=%s', to_phone, message[:120])
        return {'status': 'sent', 'channel': 'whatsapp', 'provider': 'log'}

    @staticmethod
    def send_sms(to_phone, message):
        log.info('[SMS][LOG] to=%s msg=%s', to_phone, message[:120])
        return {'status': 'sent', 'channel': 'sms', 'provider': 'log'}


class Msg91Sender:
    @staticmethod
    def send_sms(to_phone, message):
        # TODO: implement MSG91 HTTP call using settings.MSG91_AUTH_KEY
        log.warning('MSG91 SMS not yet implemented; falling back to log')
        return LogSender.send_sms(to_phone, message)


class WhatsAppCloudSender:
    @staticmethod
    def send_whatsapp(to_phone, message):
        # TODO: implement Meta WhatsApp Cloud API call
        log.warning('WhatsApp Cloud send not yet implemented; falling back to log')
        return LogSender.send_whatsapp(to_phone, message)


def send_whatsapp(to_phone, message):
    if settings.NOTIFICATION_CHANNEL == 'whatsapp_cloud':
        return WhatsAppCloudSender.send_whatsapp(to_phone, message)
    return LogSender.send_whatsapp(to_phone, message)


def send_sms(to_phone, message):
    if settings.NOTIFICATION_CHANNEL == 'msg91':
        return Msg91Sender.send_sms(to_phone, message)
    return LogSender.send_sms(to_phone, message)


# ---------- Email sender (SMTP via Django) -----------------------------

class EmailSender:
    """Uses Django's configured EMAIL_BACKEND (SMTP in prod, console in
    dev when no SMTP host is configured)."""

    @staticmethod
    def send(to_email, subject, text_body, html_body=None,
             from_email=None, attachments=None):
        from django.core.mail import EmailMultiAlternatives
        msg = EmailMultiAlternatives(
            subject=subject,
            body=text_body,
            from_email=from_email or settings.DEFAULT_FROM_EMAIL,
            to=[to_email] if isinstance(to_email, str) else list(to_email),
        )
        if html_body:
            msg.attach_alternative(html_body, 'text/html')
        for att in (attachments or []):
            # att = (filename, content_bytes, mimetype)
            msg.attach(*att)
        msg.send(fail_silently=False)
        return {'status': 'sent', 'channel': 'email', 'provider': 'smtp'}


def send_email(to_email, subject, text_body, html_body=None,
               from_email=None, attachments=None):
    """Top-level dispatcher. Skips cleanly if to_email is empty so callers
    can just blast every contact without pre-checking."""
    if not to_email:
        log.info('Email skipped: no recipient')
        return {'status': 'skipped', 'channel': 'email', 'reason': 'no_to'}
    try:
        return EmailSender.send(to_email, subject, text_body, html_body,
                                from_email, attachments)
    except Exception as exc:
        log.exception('Email send failed to %s', to_email)
        return {'status': 'failed', 'channel': 'email', 'error': str(exc)}


def render_email(template_base, context):
    """Render '<base>.txt' and '<base>.html' versions of an email template.
    Returns (text_body, html_body)."""
    from django.template.loader import render_to_string
    text = render_to_string(f'{template_base}.txt', context)
    try:
        html = render_to_string(f'{template_base}.html', context)
    except Exception:
        html = None
    return text, html
