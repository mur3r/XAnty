"""Stream profile downloads in immutable chunks, including resumed requests."""
from aiohttp import web


class PackageFileResponse(web.FileResponse):
    async def _sendfile(self, request, fobj, offset, count):
        # asyncio's Windows sendfile path can reuse a mutable buffer while an
        # overlapped write still holds it (reproduced on Python 3.12.10).
        # aiohttp's fallback reads separate bytes and awaits backpressure.
        # FileResponse still owns range/conditional headers and file cleanup.
        writer = await web.StreamResponse.prepare(self, request)
        assert writer is not None
        return await self._sendfile_fallback(writer, fobj, offset, count)
