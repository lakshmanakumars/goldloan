from django.db import migrations
from django.utils import timezone


def backfill_receipt_no(apps, schema_editor):
    """Assign date-based receipt numbers (RCP-YYYYMMDD-NNN) to existing
    repayments that don't have one, per tenant per payment date."""
    Repayment = apps.get_model('loans', 'Repayment')
    counters = {}
    qs = Repayment.objects.filter(receipt_no='').order_by('paid_at', 'id')
    for rp in qs.iterator():
        pay_date = timezone.localtime(rp.paid_at).date()
        key = (rp.tenant_id, pay_date)
        seq = counters.get(key, 0) + 1
        counters[key] = seq
        rp.receipt_no = f'RCP-{pay_date:%Y%m%d}-{seq:03d}'
        rp.save(update_fields=['receipt_no'])


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('loans', '0006_alter_golditem_net_weight_g_and_more'),
    ]

    operations = [
        migrations.RunPython(backfill_receipt_no, noop),
    ]
