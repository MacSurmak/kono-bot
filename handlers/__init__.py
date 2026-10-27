from aiogram import Router
from .commands import router as commands_router
from .menu import router as menu_router
from .admin import router as admin_router
from .invoices import router as invoices_router

main_router = Router(name="main_router")
main_router.include_router(commands_router)
main_router.include_router(menu_router)
main_router.include_router(admin_router)
main_router.include_router(invoices_router)

__all__ = ["main_router"]
