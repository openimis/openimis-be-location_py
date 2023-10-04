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
    code= "TST-" + hf_type
    if custom_props is not None and 'code' in custom_props:
        code = custom_props.pop('code')
    location = Location.objects.filter(code=code, validity_to__isnull= not valid).first()
    if location is not None:
        return location
    else:
        return Location.objects.create(
            **{
                "code": code,
                "type": hf_type,
                "name": "Test location " + hf_type,
                "validity_from": "2019-06-01",
                "validity_to": None if valid else "2019-06-01",
                "audit_user_id": -1,
                **custom_props
            }
        )

def create_test_village(custom_props={}):
    custom_props["name"]=custom_props['name'] if "name" in custom_props else "Test Village"
    test_region = create_test_location('R',custom_props={"name": "Region" + custom_props["name"]})
    test_district = create_test_location('D', custom_props={"parent": test_region,"name":"District " + custom_props["name"]})
    test_ward = create_test_location('W', custom_props={"parent": test_district,"name":"Ward" + custom_props["name"]})
    custom_props["parent"]=test_ward
    test_village = create_test_location('V', custom_props=custom_props)
    
    return test_village

def create_test_health_facility(code, location_id, valid=True, custom_props={}):
    code= "TST-" + code
    if custom_props is not None and 'code' in custom_props:
        code = custom_props.pop('code')
    hf = HealthFacility.objects.filter(code=code, validity_to__isnull= not valid).first()
    if hf is not None:
        return hf
    else:
        return HealthFacility.objects.create(
            **{
                "code": code,
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
