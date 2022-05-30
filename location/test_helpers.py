from location.models import (
    Location,
    UserDistrict,
    HealthFacility,
    HealthFacilityLegalForm
)


def assign_user_districts(user, district_codes):
    for dc in district_codes:
        dc_location = Location.objects.get(code=dc, validity_to__isnull=True)
        UserDistrict.objects.get_or_create(
            user=user.i_user,
            validity_to=None,
            location=dc_location,
            validity_from="2019-06-01",
            audit_user_id=-1,
        )


def create_test_location(hf_type, valid=True, custom_props={}):
    return Location.objects.create(
        **{
            "code": "TST-" + hf_type,
            "type": hf_type,
            "name": "Test location " + hf_type,
            "validity_from": "2019-06-01",
            "validity_to": None if valid else "2019-06-01",
            "audit_user_id": -1,
            **custom_props
        }
    )


def create_test_health_facility(code, location_id, valid=True, custom_props={}):
    return HealthFacility.objects.create(
        **{
            "code": "TST-" + code,
            "level": "H",
            "legal_form": HealthFacilityLegalForm.objects.filter(code='C').first(),
            "location_id": location_id,
            "name": "Test location " + code,
            "care_type": 'B',
            "validity_from": "2019-01-01",
            "validity_to": None if valid else "2019-06-01",
            "audit_user_id": -1,
            "offline": False,
            **custom_props
        }
    )
