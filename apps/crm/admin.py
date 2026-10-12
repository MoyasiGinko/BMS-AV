"""Django Admin configuration for CRM resources."""

from django.contrib import admin

from apps.crm.models import CrmTask, Interaction, Lead, Opportunity, Pipeline, Stage, Tag


@admin.register(Pipeline)
class PipelineAdmin(admin.ModelAdmin):
    list_display = ["name", "code", "is_default", "is_active", "organization"]
    list_filter = ["is_default", "is_active"]
    search_fields = ["name", "code"]


@admin.register(Stage)
class StageAdmin(admin.ModelAdmin):
    list_display = ["name", "pipeline", "order", "probability_percent", "is_won", "is_lost"]
    list_filter = ["is_won", "is_lost", "pipeline"]
    search_fields = ["name", "code"]


@admin.register(Lead)
class LeadAdmin(admin.ModelAdmin):
    list_display = ["display_name", "status", "source", "estimated_value", "assigned_to", "created_at"]
    list_filter = ["status", "source"]
    search_fields = ["first_name", "last_name", "company_name", "email", "phone"]


@admin.register(Opportunity)
class OpportunityAdmin(admin.ModelAdmin):
    list_display = ["title", "pipeline", "stage", "expected_value", "status", "assigned_to"]
    list_filter = ["status", "pipeline", "stage"]
    search_fields = ["title"]


@admin.register(Interaction)
class InteractionAdmin(admin.ModelAdmin):
    list_display = ["type", "summary", "customer", "lead", "opportunity", "occurred_at"]
    list_filter = ["type"]
    search_fields = ["summary", "details"]


@admin.register(CrmTask)
class CrmTaskAdmin(admin.ModelAdmin):
    list_display = ["title", "priority", "status", "due_date", "assigned_to"]
    list_filter = ["priority", "status"]
    search_fields = ["title", "description"]


@admin.register(Tag)
class TagAdmin(admin.ModelAdmin):
    list_display = ["name", "color", "organization"]
    search_fields = ["name"]
