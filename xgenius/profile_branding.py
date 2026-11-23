"""Local toolbar name badge. It never reads or modifies website contents."""
import base64
import hashlib
import html
import json
import struct
import zlib
from pathlib import Path
from xgenius.browser_workspace import _atomic_json

_KEY='MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEAsO2dTcNNdKVZHfhmRJYi6YgmjIasNdo1egk/eFXS0ZF9hrXE6zvfnxBHnssCoHEf29R4zVZN9syFJuYK3nQapQhqaKZUhwCd9qSqC0JIbNJXZySXXKH1F6naddMSwl+7TeVLvWqEPrjW7Qr6RE6g42HYElN1RdJcNVouZ/aFCPTzEQaixAbsg8WumhDCdle/XSmiZG2cwADtuMHTGyPfTBVmMLQQx8HjsilSHQk7ZZksaRkLceDNzS1i5HDf4Y9dqNDRDxY8Y+gsSTldez4R3tcKm4CtbTrERHL/4UnEybJobVrlCuaSuH5YmLp95mU77TknCXxUdMKOtPmiVmKoxwIDAQAB'
EXTENSION_ID=''.join(chr(97+int(c,16)) for c in hashlib.sha256(base64.b64decode(_KEY)).hexdigest()[:32])


def _png(size,pixels):
    def chunk(kind,data):return struct.pack('>I',len(data))+kind+data+struct.pack('>I',zlib.crc32(kind+data)&0xffffffff)
    rows=b''.join(b'\0'+pixels[y*size*4:(y+1)*size*4] for y in range(size))
    return b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('>IIBBBBB',size,size,8,6,0,0,0))+chunk(b'IDAT',zlib.compress(rows))+chunk(b'IEND',b'')


def _icon_png(path,size):
    if path is None:return _png(size,bytes((81,55,128,255))*size*size)
    data=Path(path).read_bytes();count=struct.unpack_from('<H',data,4)[0]
    for index in range(count):
        width,height,_,_,_,bits,length,offset=struct.unpack_from('<BBBBHHII',data,6+index*16)
        if (width or 256)!=size or bits!=32:continue
        dib=data[offset:offset+length];header=struct.unpack_from('<I',dib)[0]
        pixels=dib[header:header+size*size*4]
        if len(pixels)!=size*size*4:break
        rgba=bytearray()
        for y in reversed(range(size)):
            row=pixels[y*size*4:(y+1)*size*4]
            for x in range(0,len(row),4):rgba.extend((row[x+2],row[x+1],row[x],row[x+3]))
        return _png(size,bytes(rgba))
    raise ValueError('Profile icon has no requested image')


def prepare_branding(profile,identity):
    profile=Path(profile);directory=profile/'.xanty-profile-label';directory.mkdir(parents=True,exist_ok=True)
    manifest={'manifest_version':3,'name':('Профиль: '+identity.name)[:75],'version':'1.0.0','key':_KEY,
              'icons':{str(size):f'icon{size}.png' for size in (16,32,48)},
              'action':{'default_title':identity.name,'default_popup':'profile.html',
                        'default_icon':{str(size):f'icon{size}.png' for size in (16,32,48)}}}
    _atomic_json(directory/'manifest.json',manifest)
    for size in (16,32,48):(directory/f'icon{size}.png').write_bytes(_icon_png(identity.icon_path,size))
    name=html.escape(identity.name)
    (directory/'profile.html').write_text('<!doctype html><html lang="ru"><meta charset="utf-8"><title>'+name+
        '</title><style>body{margin:0;padding:20px;width:320px;font:14px Segoe UI,sans-serif;background:#17171e;color:#f5f5fa}header{display:flex;align-items:center;gap:14px}img{width:48px;height:48px}h1{font-size:19px;line-height:1.4;overflow-wrap:anywhere;margin:0}p{color:#aaaab8;font-size:12px}</style><header><img src="icon48.png" alt=""><h1>'+name+
        '</h1></header><p>Профиль XAnty</p></html>',encoding='utf-8')
    prefs=profile/'Default/Preferences'
    try:
        data=json.loads(prefs.read_text(encoding='utf-8'));extensions=data.setdefault('extensions',{})
        pinned=extensions.setdefault('pinned_extensions',[])
        if isinstance(pinned,list) and EXTENSION_ID not in pinned:
            pinned.append(EXTENSION_ID);_atomic_json(prefs,data)
    except (OSError,ValueError,TypeError,AttributeError):pass
    return directory
