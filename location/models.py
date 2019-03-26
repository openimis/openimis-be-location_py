from django.db import models
from core import fields


class HealthFacility(models.Model):
    id = models.AutoField(db_column='HfID', primary_key=True)
    legacy_id = models.IntegerField(
        db_column='LegacyID', blank=True, null=True)

    code = models.CharField(db_column='HFCode', max_length=8)
    acc_code = models.CharField(
        db_column='AccCode', max_length=25, blank=True, null=True)
    name = models.CharField(db_column='HFName', max_length=100)
    # legalform = models.ForeignKey('Tbllegalforms', models.DO_NOTHING, db_column='LegalForm')
    level = models.CharField(db_column='HFLevel', max_length=1)
    # sublevel = models.ForeignKey('Tblhfsublevel', models.DO_NOTHING, db_column='HFSublevel', blank=True, null=True)
    # locationid = models.ForeignKey('Tbllocations', models.DO_NOTHING, db_column='LocationId')
    address = models.CharField(
        db_column='HFAddress', max_length=100, blank=True, null=True)
    phone = models.CharField(
        db_column='Phone', max_length=50, blank=True, null=True)
    fax = models.CharField(
        db_column='Fax', max_length=50, blank=True, null=True)
    email = models.CharField(
        db_column='eMail', max_length=50, blank=True, null=True)

    care_type = models.CharField(db_column='HFCareType', max_length=1)

    validity_from = fields.DateTimeField(db_column='ValidityFrom')
    validity_to = fields.DateTimeField(
        db_column='ValidityTo', blank=True, null=True)

    # plserviceid = models.ForeignKey('Tblplservices', models.DO_NOTHING, db_column='PLServiceID', blank=True, null=True)
    # plitemid = models.ForeignKey('Tblplitems', models.DO_NOTHING, db_column='PLItemID', blank=True, null=True)
    offline = models.BooleanField(db_column='OffLine')
    row_id = models.BinaryField(db_column='RowID', blank=True, null=True)
    audit_user_id = models.IntegerField(db_column='AuditUserID')

    class Meta:
        managed = False
        db_table = 'tblHF'
