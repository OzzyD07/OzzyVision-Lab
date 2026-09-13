"""
Tarayıcıda oynatılabilir video çıktısı.

ComfyUI düğümleri MP4'ü farklı biçimlerde yazabilir (ör. çekirdek SaveVideo 10-bit
H.264 üretebilir). Tarayıcı video izini çözemezse hata vermez: ses çalar, görüntü
0×0 kalır. Galeriye bu yüzden her zaman 8-bit yuv420p H.264 (+ AAC/MP3 ses) konur.

Dönüştürme ayrı ve tek iş parçacıklı bir havuzda yapılır; böylece uzun bir dönüştürme
backend'in varsayılan iş parçacığı havuzunu (ComfyUI durum sorguları) doldurmaz.
"""

import asyncio
import os
from concurrent.futures import ThreadPoolExecutor
from fractions import Fraction
from typing import Any, Dict, Optional, Tuple

SAFE_VIDEO_CODECS = {"h264"}
SAFE_PIX_FMTS = {"yuv420p", "yuvj420p"}
SAFE_AUDIO_CODECS = {"aac", "mp3"}

_probe_pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="video-probe")
_transcode_pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="video-transcode")

# yol -> (mtime, bilgi): aynı dosya her istekte yeniden incelenmez
_cache: Dict[str, Tuple[float, Dict[str, Any]]] = {}
# yol -> devam eden görev: aynı video için eşzamanlı istekler tek dönüştürmeyi bekler
_inflight: Dict[str, "asyncio.Future"] = {}


def probe(path: str) -> Optional[Dict[str, Any]]:
    """Video/ses izlerinin kodek ve piksel formatını okur. Okunamazsa None."""
    try:
        import av
        with av.open(path) as container:
            info: Dict[str, Any] = {"video_codec": None, "audio_codec": None}
            if container.streams.video:
                cc = container.streams.video[0].codec_context
                info.update(
                    video_codec=cc.name,
                    pix_fmt=cc.pix_fmt,
                    profile=cc.profile,
                    width=cc.width,
                    height=cc.height,
                )
            if container.streams.audio:
                info["audio_codec"] = container.streams.audio[0].codec_context.name
            return info
    except Exception:
        return None


def is_browser_playable(info: Optional[Dict[str, Any]]) -> bool:
    if not info or not info.get("video_codec"):
        return False
    audio_ok = info.get("audio_codec") is None or info["audio_codec"] in SAFE_AUDIO_CODECS
    return (
        info["video_codec"] in SAFE_VIDEO_CODECS
        and info.get("pix_fmt") in SAFE_PIX_FMTS
        and audio_ok
    )


def _h264_encoder() -> str:
    import av
    for name in ("libx264", "h264", "libopenh264"):
        try:
            av.codec.Codec(name, "w")
            return name
        except Exception:
            continue
    raise RuntimeError("Bu ortamda H.264 kodlayıcı bulunamadı.")


def transcode(src: str, dst: str) -> None:
    """src'yi 8-bit yuv420p H.264'e dönüştürüp dst'ye yazar (sesi mümkünse kopyalar)."""
    import av

    encoder = _h264_encoder()
    part = dst + ".part"
    try:
        with av.open(src) as inp, av.open(part, "w", format="mp4", options={"movflags": "faststart"}) as out:
            vin = inp.streams.video[0]
            rate = vin.average_rate or vin.guessed_rate or Fraction(24, 1)
            vout = out.add_stream(encoder, rate=rate)
            # yuv420p çift boyut ister
            vout.width = vin.codec_context.width - (vin.codec_context.width % 2)
            vout.height = vin.codec_context.height - (vin.codec_context.height % 2)
            vout.pix_fmt = "yuv420p"
            if encoder in ("libx264", "h264"):
                vout.options = {"crf": "18", "preset": "veryfast", "profile": "high"}

            ain = inp.streams.audio[0] if inp.streams.audio else None
            aout = None
            copy_audio = False
            if ain is not None:
                if ain.codec_context.name in SAFE_AUDIO_CODECS:
                    aout = out.add_stream_from_template(ain)
                    copy_audio = True
                else:
                    aout = out.add_stream("aac", rate=ain.codec_context.sample_rate or 48000)
                    aout.layout = ain.codec_context.layout.name if ain.codec_context.layout else "stereo"

            streams = [vin] + ([ain] if ain is not None else [])
            for packet in inp.demux(streams):
                if packet.stream.index == vin.index:
                    for frame in packet.decode():
                        frame = frame.reformat(width=vout.width, height=vout.height, format="yuv420p")
                        frame.pts = None  # sabit kare hızında yeniden zaman damgası
                        for out_packet in vout.encode(frame):
                            out.mux(out_packet)
                elif aout is not None:
                    if copy_audio:
                        if packet.dts is None:
                            continue
                        packet.stream = aout
                        out.mux(packet)
                    else:
                        for frame in packet.decode():
                            frame.pts = None
                            for out_packet in aout.encode(frame):
                                out.mux(out_packet)

            for out_packet in vout.encode():
                out.mux(out_packet)
            if aout is not None and not copy_audio:
                for out_packet in aout.encode():
                    out.mux(out_packet)

        os.replace(part, dst)
    finally:
        if os.path.exists(part):
            os.remove(part)


def _ensure_sync(path: str, probed: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    original = {k: probed.get(k) for k in ("video_codec", "pix_fmt", "profile", "audio_codec")}
    transcode(path, path)
    final = probe(path) or {}
    return {**final, "browser_playable": is_browser_playable(final), "transcoded": True, "original": original}


async def ensure_playable(path: str) -> Dict[str, Any]:
    """
    Dosyayı gerekiyorsa yerinde tarayıcı dostu biçime çevirir ve video bilgisini döner.
    Okunamayan dosyalar olduğu gibi bırakılır ({"checked": False}).
    """
    if not os.path.exists(path):
        return {"checked": False}

    mtime = os.path.getmtime(path)
    cached = _cache.get(path)
    if cached and cached[0] == mtime:
        return cached[1]

    if path in _inflight:
        return await asyncio.shield(_inflight[path])

    loop = asyncio.get_running_loop()

    async def run() -> Dict[str, Any]:
        info = await loop.run_in_executor(_probe_pool, probe, path)
        if info is None:
            result: Dict[str, Any] = {"checked": False}
        elif is_browser_playable(info):
            result = {**info, "browser_playable": True, "transcoded": False}
        else:
            result = await loop.run_in_executor(_transcode_pool, _ensure_sync, path, info)
        _cache[path] = (os.path.getmtime(path), result)
        return result

    task = asyncio.ensure_future(run())
    _inflight[path] = task
    try:
        return await task
    finally:
        _inflight.pop(path, None)
