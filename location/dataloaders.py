from promise.dataloader import DataLoader
from promise import Promise

from .models import Location, HealthFacility


class LocationLoader(DataLoader):
    def batch_load_fn(self, keys):
        locations = {
            location.id: location for location in Location.objects.filter(id__in=keys)
        }
        return Promise.resolve([locations.get(location_id) for location_id in keys])


class HealthFacilityLoader(DataLoader):
    def batch_load_fn(self, keys):
        facilities = {
            facility.id: facility
            for facility in HealthFacility.objects.filter(id__in=keys)
        }
        return Promise.resolve([facilities.get(facility_id) for facility_id in keys])
