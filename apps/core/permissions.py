"""Role-based permission helper for tenant staff.

Permission matrix (within a tenant):

                       Customer  Loan  GoldItem  Repayment  Reminder  Reports  Branches Users  Cashbook Auction
    Owner    (R)         RW      RW    RW        RW          R        R         RW       RW     RW       RW
    Manager              RW      RW    RW        RW          R        R         RW       R      RW       RW
    Cashier              R       R     R         RW          R        R         -        -      RW       -
    Appraiser            RW      RW    RW        R           R        R         -        -      -        -
    Auditor              R       R     R         R           R        R         R        -      R        R

R = read, W = write (create/change/delete), - = no access.
Super-admin always allowed everything (handled in admin mixins).
"""
from apps.iam.models import User

R = 'r'      # read (view)
W = 'w'      # write (add/change/delete)

# Logical permission keys — model classes won't be imported here to keep
# this file dependency-free.
MATRIX = {
    User.Role.OWNER: {
        'customer': {R, W}, 'loan': {R, W}, 'gold_item': {R, W},
        'repayment': {R, W}, 'reminder': {R}, 'reports': {R},
        'branch': {R, W}, 'user': {R, W}, 'tenant': {R, W},
        'rate': {R, W}, 'cashbook': {R, W}, 'auction': {R, W},
    },
    User.Role.MANAGER: {
        'customer': {R, W}, 'loan': {R, W}, 'gold_item': {R, W},
        'repayment': {R, W}, 'reminder': {R}, 'reports': {R},
        'branch': {R, W}, 'user': {R}, 'tenant': {R},
        'rate': {R, W}, 'cashbook': {R, W}, 'auction': {R, W},
    },
    User.Role.CASHIER: {
        'customer': {R}, 'loan': {R}, 'gold_item': {R},
        'repayment': {R, W}, 'reminder': {R}, 'reports': {R},
        'branch': set(), 'user': set(), 'tenant': set(),
        'rate': {R}, 'cashbook': {R, W}, 'auction': set(),
    },
    User.Role.APPRAISER: {
        'customer': {R, W}, 'loan': {R, W}, 'gold_item': {R, W},
        'repayment': {R}, 'reminder': {R}, 'reports': {R},
        'branch': set(), 'user': set(), 'tenant': set(),
        'rate': {R}, 'cashbook': set(), 'auction': set(),
    },
    User.Role.AUDITOR: {
        'customer': {R}, 'loan': {R}, 'gold_item': {R},
        'repayment': {R}, 'reminder': {R}, 'reports': {R},
        'branch': {R}, 'user': set(), 'tenant': {R},
        'rate': {R}, 'cashbook': {R}, 'auction': {R},
    },
}


def role_can(user, resource, mode=R):
    """Returns True if `user.role` has `mode` permission on `resource`."""
    if user is None or not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    role = getattr(user, 'role', None) or User.Role.OWNER
    return mode in MATRIX.get(role, {}).get(resource, set())
