"""Error types. Every BillingError carries a stable machine-readable ``code``.

RECONSTRUCTED STAND-IN (the original was not in the uploaded zips). Codes match what the
uploaded tests assert ('tax_configuration', 'inactive_product', 'invoice_data', ...).
The payment errors at the bottom are new.
"""


class BillingError(Exception):
    code = "billing_error"


class SubscriptionNotFoundError(BillingError):
    code = "subscription_not_found"


class InvoiceDataError(BillingError):
    code = "invoice_data"


class TaxConfigurationError(BillingError):
    code = "tax_configuration"


class DiscountConfigurationError(BillingError):
    code = "discount_configuration"


class ProductNotFoundError(BillingError):
    code = "product_not_found"


class InactiveProductError(BillingError):
    code = "inactive_product"


class VariantNotFoundError(BillingError):
    code = "variant_not_found"


class VariantMismatchError(BillingError):
    code = "variant_mismatch"


class InactiveVariantError(BillingError):
    code = "inactive_variant"


class PlanNotFoundError(BillingError):
    code = "plan_not_found"


# ---- payments (new) -------------------------------------------------------
class PaymentError(BillingError):
    code = "payment_error"


class InvalidPaymentError(PaymentError):
    code = "invalid_payment"


class InvoiceNotFoundError(PaymentError):
    code = "invoice_not_found"


class InvoiceNotPayableError(PaymentError):
    code = "invoice_not_payable"


class InvoiceCustomerMismatchError(PaymentError):
    code = "invoice_customer_mismatch"


class OverAllocationError(PaymentError):
    code = "over_allocation"


class DuplicateAllocationError(PaymentError):
    code = "duplicate_allocation"


class DuplicatePaymentReferenceError(PaymentError):
    code = "duplicate_payment_reference"
