"""Validation d'un fichier audio par ses premiers octets (le Content-Type déclaré ne prouve rien)."""

# (extension, type MIME) selon la signature réelle du contenu.
def sniff_audio(data: bytes) -> tuple[str, str] | None:
    if data[:4] == b"\x1a\x45\xdf\xa3":
        return "webm", "audio/webm"
    if data[:4] == b"OggS":
        return "ogg", "audio/ogg"
    if data[4:8] == b"ftyp":
        return "mp4", "audio/mp4"
    if data[:4] == b"RIFF" and data[8:12] == b"WAVE":
        return "wav", "audio/wav"
    if data[:3] == b"ID3" or data[:2] in (b"\xff\xfb", b"\xff\xf3", b"\xff\xf2"):
        return "mp3", "audio/mpeg"
    return None
