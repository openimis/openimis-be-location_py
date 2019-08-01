from django.db import connection
import core


@core.comparable
class HealthFacilityFullPathRequest(object):

    def __init__(self, hf_id):
        self.hf_id = hf_id

    def __eq__(self, other):
        return isinstance(other, self.__class__) and self.__dict__ == other.__dict__


@core.comparable
class HealthFacilityFullPathResponse(object):

    def __init__(self, request, hf_id, hf_code, hf_name, hf_level,
                 district_id, district_code, district_name,
                 region_id, region_code, region_name):
        self.request = request
        self.hf_id = hf_id
        self.hf_code = hf_code
        self.hf_name = hf_name
        self.hf_level = hf_level
        self.district_id = district_id
        self.district_code = district_code
        self.district_name = district_name
        self.region_id = region_id
        self.region_code = region_code
        self.region_name = region_name


class HealthFacilityFullPathService(object):

    def __init__(self, user):
        self.user = user

    def request(self, req):
        # Today, there are only 2 levels (region and district)
        # in the HF (location) hierarchy...
        sql = """
            SELECT HF.HfID hf_id, HF.HFCODE hf_code, HF.HFNAME hf_name, HF.HFLEVEL hf_level,
                   District.LocationId district_id, District.LocationCode district_code, District.LocationName district_name,
                   Region.LocationId region_id, Region.LocationCode region_code, Region.LocationName region_name
            FROM tblHF HF
                 LEFT OUTER JOIN tblLocations District ON HF.LocationId = District.LocationId
                 LEFT OUTER JOIN tblLocations Region ON District.ParentLocationId = Region.LocationId
            WHERE HF.HfID = %s
            """
        with connection.cursor() as cur:
            cur.execute(sql, [int(req.hf_id)])
            row = cur.fetchone()
            if not row:
                return None
            return HealthFacilityFullPathResponse(
                request=req,
                hf_id=row[0],
                hf_code=row[1],
                hf_name=row[2],
                hf_level=row[3],
                district_id=row[4],
                district_code=row[5],
                district_name=row[6],
                region_id=row[7],
                region_code=row[8],
                region_name=row[9]
            )
