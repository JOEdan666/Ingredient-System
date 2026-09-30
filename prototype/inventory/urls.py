from django.urls import path

from . import views

urlpatterns = [
    path("", views.inventory_page, name="inventory"),
    path("move/", views.move, name="move"),
    path("reset-synthetic/", views.reset_synthetic, name="reset_synthetic"),
    path("imports/", views.import_preview_page, name="import_preview"),
    path("imports/<int:batch_id>/", views.import_detail, name="import_detail"),
    path("imports/<int:batch_id>/units/", views.import_units, name="import_units"),
    path("imports/<int:batch_id>/post/", views.import_post, name="import_post"),
    path("reset-empty/", views.reset_empty, name="reset_empty"),
    path("receiving/", views.receiving_page, name="receiving"),
    path("receiving/notice/", views.create_notice, name="create_notice"),
    path("receiving/receipt/", views.confirm_receipt, name="confirm_receipt"),
    path("receiving/notice/<int:notice_id>/receive/", views.receive_notice, name="receive_notice"),
    path("receiving/condition/", views.change_condition, name="change_condition"),
    path("outbound/", views.outbound_page, name="outbound"),
    path("outbound/accept/", views.accept_order, name="accept_order"),
    path("outbound/<int:order_id>/", views.order_page, name="order_detail"),
    path("outbound/<int:order_id>/allocate/", views.allocate, name="allocate"),
    path("outbound/<int:order_id>/ship/", views.ship, name="ship"),
    path("outbound/<int:order_id>/cancel/", views.cancel_line, name="cancel_line"),
    path("outbound/<int:order_id>/pallet-sheet/", views.pallet_sheet_form, name="pallet_sheet_form"),
    path("pallet-sheets/<int:sheet_id>/print/", views.pallet_sheet_print, name="pallet_sheet_print"),
    path("history/", views.history_page, name="history"),
    path("staff/", views.staff_page, name="staff"),
]
