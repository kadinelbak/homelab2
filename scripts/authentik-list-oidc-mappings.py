from authentik.core.models import PropertyMapping

for name in PropertyMapping.objects.values_list("name", flat=True).order_by("name"):
    if "openid" in name.lower() or "oauth" in name.lower() or "scope" in name.lower():
        print(name)

raise SystemExit
