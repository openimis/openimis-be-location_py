from django.contrib import admin

from .models import HealthFacilityLegalForm, HealthFacilitySubLevel


@admin.register(HealthFacilityLegalForm)
class HealthFacilityLegalFormAdmin(admin.ModelAdmin):
    list_display = ["code", "legal_form", "sort_order", "alt_language"]
    list_display_links = ["code", "legal_form"]
    list_editable = ["sort_order"]
    search_fields = ["code", "legal_form", "alt_language"]
    ordering = ["sort_order", "code"]
    fields = ["code", "legal_form", "sort_order", "alt_language"]

    def get_readonly_fields(self, request, obj=None):
        # Prevent changing the PK (code) after the record is created
        if obj:
            return ["code"]
        return []


@admin.register(HealthFacilitySubLevel)
class HealthFacilitySubLevelAdmin(admin.ModelAdmin):
    list_display = ["code", "health_facility_sub_level", "sort_order", "alt_language"]
    list_display_links = ["code", "health_facility_sub_level"]
    list_editable = ["sort_order"]
    search_fields = ["code", "health_facility_sub_level", "alt_language"]
    ordering = ["sort_order", "code"]
    fields = ["code", "health_facility_sub_level", "sort_order", "alt_language"]

    def get_readonly_fields(self, request, obj=None):
        # Prevent changing the PK (code) after the record is created
        if obj:
            return ["code"]
        return []
