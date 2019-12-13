import uuid
from core import fields
from django.db import models
from core import models as core_models
from .apps import LocationConfig


class Location(core_models.VersionedModel):
    id = models.AutoField(db_column='LocationId', primary_key=True)
    uuid = models.CharField(db_column='LocationUUID',
                            max_length=36, default=uuid.uuid4, unique=True)
    code = models.CharField(db_column='LocationCode',
                            max_length=8, blank=True, null=True)
    name = models.CharField(db_column='LocationName',
                            max_length=50, blank=True, null=True)
    parent = models.ForeignKey('Location', models.DO_NOTHING,
                               db_column='ParentLocationId',
                               blank=True, null=True, related_name='children')
    type = models.CharField(db_column='LocationType', max_length=1)

    male_population = models.IntegerField(
        db_column='MalePopulation', blank=True, null=True)
    female_population = models.IntegerField(
        db_column='FemalePopulation', blank=True, null=True)
    other_population = models.IntegerField(
        db_column='OtherPopulation', blank=True, null=True)
    families = models.IntegerField(db_column='Families', blank=True, null=True)

    # rowid = models.TextField(db_column='RowId')
    audit_user_id = models.IntegerField(
        db_column='AuditUserId', blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'tblLocations'


class HealthFacilityLegalForm(models.Model):
    code = models.CharField(db_column='LegalFormCode', primary_key=True, max_length=1)
    legal_form = models.CharField(db_column='LegalForms', max_length=50)
    sortorder = models.IntegerField(db_column='SortOrder', blank=True, null=True)
    altlanguage = models.CharField(db_column='AltLanguage', max_length=50, blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'tblLegalForms'


class HealthFacilitySubLevel(models.Model):
    code = models.CharField(db_column='HFSublevel', primary_key=True, max_length=1)
    health_facility_sub_level = models.CharField(db_column='HFSublevelDesc', max_length=50, blank=True, null=True)
    sortorder = models.IntegerField(db_column='SortOrder', blank=True, null=True)
    altlanguage = models.CharField(db_column='AltLanguage', max_length=50, blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'tblHFSublevel'


class HealthFacility(core_models.VersionedModel):
    id = models.AutoField(db_column='HfID', primary_key=True)
    uuid = models.CharField(
        db_column='HfUUID', max_length=36, default=uuid.uuid4, unique=True)

    code = models.CharField(db_column='HFCode', max_length=8)
    name = models.CharField(db_column='HFName', max_length=100)
    acc_code = models.CharField(
        db_column='AccCode', max_length=25, blank=True, null=True)
    legal_form = models.ForeignKey(
        HealthFacilityLegalForm, models.DO_NOTHING,
        db_column='LegalForm',
        related_name="health_facilities")
    level = models.CharField(db_column='HFLevel', max_length=1)
    sub_level = models.ForeignKey(
        HealthFacilitySubLevel, models.DO_NOTHING,
        db_column='HFSublevel', blank=True, null=True,
        related_name="health_facilities")
    location = models.ForeignKey(
        Location, models.DO_NOTHING, db_column='LocationId')
    address = models.CharField(
        db_column='HFAddress', max_length=100, blank=True, null=True)
    phone = models.CharField(
        db_column='Phone', max_length=50, blank=True, null=True)
    fax = models.CharField(
        db_column='Fax', max_length=50, blank=True, null=True)
    email = models.CharField(
        db_column='eMail', max_length=50, blank=True, null=True)

    care_type = models.CharField(db_column='HFCareType', max_length=1)

    services_pricelist = models.ForeignKey('medical_pricelist.ServicesPricelist', models.DO_NOTHING,
                                           db_column='PLServiceID', blank=True, null=True,
                                           related_name="health_facilities")
    items_pricelist = models.ForeignKey('medical_pricelist.ItemsPricelist', models.DO_NOTHING, db_column='PLItemID',
                                        blank=True, null=True, related_name="health_facilities")
    offline = models.BooleanField(db_column='OffLine')
    # row_id = models.BinaryField(db_column='RowID', blank=True, null=True)
    audit_user_id = models.IntegerField(db_column='AuditUserID')

    def __str__(self):
        return self.code + " " + self.name

    class Meta:
        managed = False
        db_table = 'tblHF'

    LEVEL_HEALTH_CENTER = 'C'
    LEVEL_DISPENSARY = 'D'
    LEVEL_HOSPITAL = 'H'

    CARE_TYPE_IN_PATIENT = 'I'
    CARE_TYPE_OUT_PATIENT = 'O'
    CARE_TYPE_BOTH = 'B'


class HealthFacilityCatchment(models.Model):
    id = models.AutoField(db_column='HFCatchmentId', primary_key=True)
    legacy_id = models.IntegerField(db_column='LegacyId', blank=True, null=True)
    health_facility = models.ForeignKey(
        HealthFacility,
        models.DO_NOTHING,
        db_column='HFID',
        related_name="catchments"
    )
    location = models.ForeignKey(
        Location,
        models.DO_NOTHING,
        db_column='LocationId',
        related_name="catchments"
    )
    catchment = models.IntegerField(db_column='Catchment', blank=True, null=True)
    validity_from = models.DateTimeField(db_column='ValidityFrom', blank=True, null=True)
    validity_to = models.DateTimeField(db_column='ValidityTo', blank=True, null=True)

    audit_user_id = models.IntegerField(db_column='AuditUserId', blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'tblHFCatchment'


class UserDistrict(models.Model):
    id = models.AutoField(db_column='UserDistrictID', primary_key=True)
    legacy_id = models.IntegerField(
        db_column='LegacyID', blank=True, null=True)
    user = models.ForeignKey(
        core_models.InteractiveUser, models.DO_NOTHING, db_column='UserID')
    location = models.ForeignKey(
        Location, models.DO_NOTHING, db_column='LocationId')
    validity_from = fields.DateTimeField(db_column='ValidityFrom')
    validity_to = fields.DateTimeField(
        db_column='ValidityTo', blank=True, null=True)
    audit_user_id = models.IntegerField(db_column='AuditUserID')

    class Meta:
        managed = False
        db_table = 'tblUsersDistricts'


class LocationMutation(core_models.UUIDModel):
    location = models.ForeignKey(Location, models.DO_NOTHING,
                                 related_name='mutations')
    mutation = models.ForeignKey(
        core_models.MutationLog, models.DO_NOTHING, related_name='locations')

    class Meta:
        managed = True
        db_table = "location_LocationMutation"


class HealthFacilityMutation(core_models.UUIDModel):
    health_facility = models.ForeignKey(HealthFacility, models.DO_NOTHING,
                                        related_name='mutations')
    mutation = models.ForeignKey(
        core_models.MutationLog, models.DO_NOTHING, related_name='health_facilities')

    class Meta:
        managed = True
        db_table = "location_HealthFacilityMutation"
