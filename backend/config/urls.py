from django.urls import path
from core import views as v

urlpatterns = [
    path("api/health/", v.health),
    path("api/auth/me/", v.me),
    path("api/auth/login/", v.sign_in),
    path("api/auth/logout/", v.sign_out),
    path("api/state/", v.state),
    path("api/catalog/<str:kind>/", v.catalog),
    path("api/orders/save/", v.save_order),
    path("api/orders/<int:pk>/", v.detail),
    path("api/orders/<int:pk>/<str:action>/", v.order_action),
    path("api/tasks/<int:pk>/<str:action>/", v.task_action),
    path("api/reports/<int:pk>/correct/", v.correction),
    path("api/items/<int:pk>/labels/", v.upload_label),
    path("api/labels/<int:pk>/approve/", v.approve_label),
    path("api/labels/<int:pk>/download/", v.download_label),
    path("api/batches/<int:pk>/move/", v.stock_action),
    path("api/users/", v.users),
]
