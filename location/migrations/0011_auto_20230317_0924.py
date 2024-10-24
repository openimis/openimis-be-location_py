# Generated by Django 3.2.16 on 2023-03-17 09:24

import core.fields
import datetime
from django.db import migrations, models
import django.db.models.deletion
import uuid


class Migration(migrations.Migration):

    dependencies = [
        ("location", "0010_insert_create_region_location_perms"),
        ("medical_pricelist", "0002_itemspricelistmutation_servicespricelistmutation"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="healthfacility",
            name="row_id",
        ),
        migrations.AddField(
            model_name="healthfacility",
            name="items_pricelist",
            field=models.ForeignKey(
                blank=True,
                db_column="PLItemID",
                null=True,
                on_delete=django.db.models.deletion.DO_NOTHING,
                related_name="health_facilities",
                to="medical_pricelist.itemspricelist",
            ),
        ),
        migrations.AddField(
            model_name="healthfacility",
            name="legal_form",
            field=models.ForeignKey(
                db_column="LegalForm",
                default="G",
                on_delete=django.db.models.deletion.DO_NOTHING,
                related_name="health_facilities",
                to="location.healthfacilitylegalform",
            ),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name="healthfacility",
            name="location",
            field=models.ForeignKey(
                db_column="LocationId",
                default=1,
                on_delete=django.db.models.deletion.DO_NOTHING,
                to="location.location",
            ),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name="healthfacility",
            name="services_pricelist",
            field=models.ForeignKey(
                blank=True,
                db_column="PLServiceID",
                null=True,
                on_delete=django.db.models.deletion.DO_NOTHING,
                related_name="health_facilities",
                to="medical_pricelist.servicespricelist",
            ),
        ),
        migrations.AddField(
            model_name="healthfacility",
            name="sub_level",
            field=models.ForeignKey(
                blank=True,
                db_column="HFSublevel",
                null=True,
                on_delete=django.db.models.deletion.DO_NOTHING,
                related_name="health_facilities",
                to="location.healthfacilitysublevel",
            ),
        ),
        migrations.AddField(
            model_name="healthfacility",
            name="uuid",
            field=models.CharField(
                db_column="HfUUID", default=uuid.uuid4, max_length=36, unique=True
            ),
        ),
        migrations.AddField(
            model_name="location",
            name="uuid",
            field=models.CharField(
                db_column="LocationUUID", default=uuid.uuid4, max_length=36, unique=True
            ),
        ),
        migrations.AlterField(
            model_name="healthfacility",
            name="offline",
            field=models.BooleanField(db_column="OffLine", default=False),
        ),
        migrations.AlterField(
            model_name="healthfacility",
            name="validity_from",
            field=core.fields.DateTimeField(
                db_column="ValidityFrom", default=datetime.datetime.now
            ),
        ),
        migrations.AlterField(
            model_name="location",
            name="legacy_id",
            field=models.IntegerField(blank=True, db_column="LegacyID", null=True),
        ),
        migrations.AlterField(
            model_name="location",
            name="parent",
            field=models.ForeignKey(
                blank=True,
                db_column="ParentLocationId",
                null=True,
                on_delete=django.db.models.deletion.DO_NOTHING,
                related_name="children",
                to="location.location",
            ),
        ),
        migrations.AlterField(
            model_name="location",
            name="validity_from",
            field=core.fields.DateTimeField(
                db_column="ValidityFrom", default=datetime.datetime.now
            ),
        ),
    ]
