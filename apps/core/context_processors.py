def tenant_context(request):
    return {
        'current_tenant': getattr(request, 'tenant', None),
        'is_super_admin_host': getattr(request, 'is_super_admin_host', False),
    }
