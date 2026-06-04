from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin
from django.contrib.auth.forms import UserCreationForm, UserChangeForm
from django.utils.html import format_html
from django.utils.safestring import mark_safe
from unfold.admin import ModelAdmin
from apps.core.admin import TenantModelAdmin
from .models import Tenant, User, Branch


@admin.register(Branch)
class BranchAdmin(TenantModelAdmin):
    tenant_resource = 'branch'
    list_display = ('code', 'name', 'phone', 'is_primary', 'is_active',
                    'created_at')
    list_filter = ('is_active', 'is_primary')
    search_fields = ('code', 'name', 'phone', 'license_no', 'gst_no')
    fields = ('name', 'code', 'address', 'phone',
              'license_no', 'gst_no',
              ('is_primary', 'is_active'))


class TenantUserCreationForm(UserCreationForm):
    class Meta(UserCreationForm.Meta):
        model = User
        fields = ('username', 'email', 'tenant', 'is_tenant_owner', 'phone')


class TenantUserChangeForm(UserChangeForm):
    class Meta(UserChangeForm.Meta):
        model = User
        fields = '__all__'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Unfold's field template escapes help_text; mark the password help
        # safe so the built-in "change password using this form" link renders.
        password = self.fields.get('password')
        if password is not None and password.help_text:
            password.help_text = mark_safe(password.help_text)


@admin.register(Tenant)
class TenantAdmin(ModelAdmin):
    list_display = ('name', 'slug', 'status', 'plan',
                    'contact_phone', 'subdomain_link', 'created_at')
    list_filter = ('status', 'plan')
    search_fields = ('name', 'slug', 'contact_phone', 'contact_email',
                     'license_no', 'gst_no')
    readonly_fields = ('created_at', 'updated_at')
    prepopulated_fields = {'slug': ('name',)}
    fieldsets = (
        ('Business', {
            'fields': ('name', 'slug', 'status', 'plan', 'trial_ends_at',
                       'default_language', 'max_ltv_pct'),
        }),
        ('Compliance', {
            'fields': ('license_no', 'gst_no', 'pan_no'),
        }),
        ('Contact', {
            'fields': ('contact_name', 'contact_email', 'contact_phone',
                       'address'),
        }),
        ('Branding (white-label)', {
            'fields': ('logo', 'tagline', 'primary_color', 'accent_color'),
            'description': 'Per-tenant logo, tagline and colours. Applied '
                           'across the admin UI, emails and auction notices.',
        }),
        ('System', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',),
        }),
    )

    def subdomain_link(self, obj):
        return format_html(
            '<a href="{}" target="_blank">{}</a>',
            obj.subdomain_url, obj.subdomain_url,
        )
    subdomain_link.short_description = 'Tenant URL'

    def has_module_permission(self, request):
        # Super-admin sees Tenant module; tenant owners see only to edit their own.
        if request.user.is_superuser:
            return True
        return bool(getattr(request, 'tenant', None)
                    and getattr(request.user, 'is_tenant_owner', False))

    def has_view_permission(self, request, obj=None):
        if request.user.is_superuser:
            return True
        if not getattr(request.user, 'is_tenant_owner', False):
            return False
        # Owners may only see their own tenant
        if obj is not None:
            return obj.pk == request.user.tenant_id
        return True

    def has_add_permission(self, request):
        return request.user.is_superuser  # only super-admin creates tenants

    def has_change_permission(self, request, obj=None):
        return self.has_view_permission(request, obj)

    def has_delete_permission(self, request, obj=None):
        return request.user.is_superuser

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        if request.user.is_superuser:
            return qs
        if getattr(request.user, 'is_tenant_owner', False):
            return qs.filter(pk=request.user.tenant_id)
        return qs.none()


@admin.register(User)
class UserAdmin(DjangoUserAdmin, ModelAdmin):
    add_form = TenantUserCreationForm
    form = TenantUserChangeForm
    model = User

    list_display = ('username', 'email', 'tenant', 'is_tenant_owner',
                    'is_superuser', 'is_active', 'last_login')
    list_filter = ('is_superuser', 'is_staff', 'is_active', 'is_tenant_owner',
                   'tenant')
    search_fields = ('username', 'email', 'first_name', 'last_name', 'phone')

    fieldsets = (
        (None, {'fields': ('username', 'password')}),
        ('Personal', {'fields': ('first_name', 'last_name', 'email', 'phone',
                                 'language')}),
        ('Tenant', {'fields': ('tenant', 'is_tenant_owner', 'role', 'branch')}),
        ('Permissions', {
            'fields': ('is_active', 'is_staff', 'is_superuser',
                       'groups', 'user_permissions'),
        }),
        ('Important dates', {'fields': ('last_login', 'date_joined')}),
    )

    add_fieldsets = (
        (None, {
            'classes': ('wide',),
            'fields': ('username', 'email', 'tenant', 'is_tenant_owner',
                       'phone', 'password1', 'password2'),
        }),
    )

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        if request.user.is_superuser:
            return qs
        if request.tenant is not None and request.user.is_tenant_owner:
            return qs.filter(tenant=request.tenant)
        return qs.filter(pk=request.user.pk)

    def _has_user_access(self, request, mode='r'):
        from apps.core.permissions import role_can
        if request.user.is_superuser:
            return True
        if request.tenant is None or not request.user.is_staff:
            return False
        if request.user.tenant_id != request.tenant.id:
            return False
        return role_can(request.user, 'user', mode)

    def has_module_permission(self, request):
        return self._has_user_access(request, 'r')

    def has_view_permission(self, request, obj=None):
        return self._has_user_access(request, 'r')

    def has_add_permission(self, request):
        return self._has_user_access(request, 'w')

    def has_change_permission(self, request, obj=None):
        return self._has_user_access(request, 'w')

    def has_delete_permission(self, request, obj=None):
        return self._has_user_access(request, 'w')
