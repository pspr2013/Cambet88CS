from aiohttp import web
import logging

logger = logging.getLogger(__name__)

async def health_check(request):
    return web.Response(text="OK", status=200)

async def start_web_server(port):
    app = web.Application()
    app.router.add_get('/', health_check)
    app.router.add_get('/healthz', health_check)
    
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', port)
    await site.start()
    logger.info(f"Web server started on port {port}")
