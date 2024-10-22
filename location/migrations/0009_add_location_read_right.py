import logging

from django.db import migrations

from core.utils import insert_role_right_for_system

logger = logging.getLogger(__name__)


def add_rights(apps, schema_editor):
    """
    All roles that have access to the Insuree also need access to location filtering.
    This migration add's location perms to the roles which have access to gql query insuree perms.
    Based on SQL Query:
        select * from tblRole tr
        where RoleID in (
            select RoleID from tblRoleRight tr where RightID in (101101)
            group by RoleID)
        and RoleID not in (select RoleID from tblRoleRight tr where RightID in (121901)
            group by RoleID )
    """
    insert_role_right_for_system(4, 121901, apps)
    insert_role_right_for_system(8, 121901, apps)
    insert_role_right_for_system(128, 121901, apps)
    insert_role_right_for_system(256, 121901, apps)


class Migration(migrations.Migration):
    dependencies = [
        ("location", "0008_add_enrollment_officer_gql_query_location_right")
    ]

    operations = [
        migrations.RunPython(add_rights, migrations.RunPython.noop),
    ]
