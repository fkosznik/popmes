"""HTTP handlers grouped by area. Domain rules stay in services."""

__all__ = [
    "LoginThrottle",
    "health",
    "version",
    "me",
    "sign_in",
    "sign_out",
    "mutation",
    "locked_order",
    "shell_settings",
    "state",
    "catalog",
    "delete_product",
    "delete_variant",
    "delete_customer",
    "restore_product",
    "restore_variant",
    "restore_customer",
    "undo_last",
    "save_order",
    "detail",
    "order_action",
    "task_action",
    "correction",
    "validate_file",
    "upload_label",
    "approve_label",
    "download_label",
    "stock_action",
    "account_update",
    "orders_filter",
    "account_password",
    "users",
    "save_user",
    "organization_update",
    "workspace_save",
    "workspace_select",
    "set_stock",
    "stock_category",
    "stock_product",
    "supplier_create",
    "stock_supplier",
    "stock_detail",
    "stock_edit",
    "stock_delete",
    "stock_restore",
    "supplier_update",
    "recipe_save",
    "stock_receipt",
]

from core.views.auth import LoginThrottle
from core.views.auth import health
from core.views.auth import version
from core.views.auth import me
from core.views.auth import sign_in
from core.views.auth import sign_out
from core.views.auth import mutation
from core.views.auth import locked_order
from core.views.catalog import shell_settings
from core.views.catalog import state
from core.views.catalog import catalog
from core.views.catalog import delete_product
from core.views.catalog import delete_variant
from core.views.catalog import delete_customer
from core.views.catalog import restore_product
from core.views.catalog import restore_variant
from core.views.catalog import restore_customer
from core.views.catalog import undo_last
from core.views.orders import save_order
from core.views.orders import detail
from core.views.orders import order_action
from core.views.orders import task_action
from core.views.orders import correction
from core.views.orders import validate_file
from core.views.orders import upload_label
from core.views.orders import approve_label
from core.views.orders import download_label
from core.views.production import stock_action
from core.views.account import account_update
from core.views.account import orders_filter
from core.views.account import account_password
from core.views.account import users
from core.views.account import save_user
from core.views.account import organization_update
from core.views.account import workspace_save
from core.views.account import workspace_select
from core.views.stock import set_stock
from core.views.stock import stock_category
from core.views.stock import stock_product
from core.views.stock import supplier_create
from core.views.stock import stock_supplier
from core.views.stock import stock_detail
from core.views.stock import stock_edit
from core.views.stock import stock_delete
from core.views.stock import stock_restore
from core.views.stock import supplier_update
from core.views.stock import recipe_save
from core.views.stock import stock_receipt
