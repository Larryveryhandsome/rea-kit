"""One-request tenant-owned listings, never written to the customer store."""
from copy import deepcopy
from core.recent_listings import select_recent


class EphemeralListingSource:
    def __init__(self, tenant_id, listings, *, today):
        self.tenant_id = tenant_id
        result = select_recent(listings, today=today)
        self._rows = result["listings"]
        self.excluded = result["excluded"]

    def list_active(self, tenant_id):
        if tenant_id != self.tenant_id:
            return []
        return deepcopy(self._rows)
