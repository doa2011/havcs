from Crypto.Cipher import AES
from base64 import b64decode, b64encode
import homeassistant.util.color as color_util
import time
import re
import jwt
from typing import cast
import logging
from packaging import version

_LOGGER = logging.getLogger(__name__)
# _LOGGER.setLevel(logging.DEBUG)
LOGGER_NAME = 'util'

ENTITY_KEY = ''

class AESCipher:
    """
    Tested under Python 3.x and PyCrypto 2.6.1.
    """
    def __init__(self, key):
        #加密需要的key值
        self.key=key
        self.mode = AES.MODE_CBC
    def encrypt(self, raw):
        # Padding for the input string --not
        # related to encryption itself.
        BLOCK_SIZE = 16  # Bytes
        pad = lambda s: s + (BLOCK_SIZE - len(s) % BLOCK_SIZE) * \
                        chr(BLOCK_SIZE - len(s) % BLOCK_SIZE).encode('utf8')
        raw = pad(raw)
        #通过key值，使用ECB模式进行加密
        cipher = AES.new(self.key, self.mode, b'0000000000000000')
        #返回得到加密后的字符串进行解码然后进行64位的编码
        return b64encode(cipher.encrypt(raw)).decode('utf8')

    def decrypt(self, enc):
        unpad = lambda s: s[:-ord(s[len(s) - 1:])]
        #首先对已经加密的字符串进行解码
        enc = b64decode(enc)
        #通过key值，使用ECB模式进行解密
        cipher = AES.new(self.key, self.mode, b'0000000000000000')
        return unpad(cipher.decrypt(enc)).decode('utf8')

def decrypt_device_id(device_id):
    try:
        if not ENTITY_KEY:
            new_device_id = device_id
        else:
            device_id = device_id.replace('-', '+')
            device_id = device_id.replace('_', '/')
            pad4 = '===='
            device_id += pad4[0:len(device_id) % 4]
            new_device_id = AESCipher(ENTITY_KEY.encode('utf-8')).decrypt(device_id)
    except:
        new_device_id = None
    finally:
        return new_device_id
def encrypt_device_id(device_id):
    if not ENTITY_KEY:
        new_device_id = device_id
    else:
        new_device_id = AESCipher(ENTITY_KEY.encode('utf-8')).encrypt(device_id.encode('utf8'))
        new_device_id = new_device_id.replace('+', '-')
        new_device_id = new_device_id.replace('/', '_')
        new_device_id = new_device_id.replace('=', '')
    return new_device_id

def hsv2rgb(hsvColorDic):

    h = float(hsvColorDic['hue'])
    s = float(hsvColorDic['saturation'])
    v = float(hsvColorDic['brightness'])
    rgb = color_util.color_hsv_to_RGB(h, s, v)

    return rgb

def timestamp2Delay(timestamp):
    delay = abs(int(time.time()) - timestamp)
    return delay

def get_platform_from_command(command):
    if 'AliGenie' in command:
        platform = 'aligenie'
    elif 'DuerOS' in command:
        platform = 'dueros'
    elif 'Alpha' in command:
        platform = 'jdwhale'
    else:
        platform = 'unknown'
    return platform

def get_token_from_command(command):
    result = re.search(r'(?:accessToken|token)[\'\"\s:]+(.*?)[\'\"\s]+(,|\})', command, re.M|re.I)
    return result.group(1) if result else None

def update_token_expiration(access_token, hass, expiration):
    """Update a HAVCS OAuth token's expiry, guarded for HA auth API changes."""
    try:
        if version.parse(jwt.__version__) < version.parse("2.0.0"):
            unverif_claims = jwt.decode(access_token, verify=False)
        else:
            unverif_claims = jwt.decode(
                access_token,
                algorithms=["HS256"],
                options={"verify_signature": False},
            )

        token_id = unverif_claims.get("iss")
        if not token_id:
            _LOGGER.debug("[util] access token has no refresh-token issuer claim")
            return False

        # Use Home Assistant's public lookup API instead of reaching into
        # AuthStore._users. Persisting an in-place expiry change still requires
        # the private save hook, so guard that dependency explicitly.
        refresh_token = hass.auth.async_get_refresh_token(cast(str, token_id))
        if refresh_token is None:
            _LOGGER.debug("[util] refresh token was not found")
            return False

        auth_store = getattr(hass.auth, "_store", None)
        schedule_save = getattr(auth_store, "_async_schedule_save", None)
        if not callable(schedule_save):
            _LOGGER.warning(
                "[util] cannot persist custom OAuth expiry: Home Assistant auth store API changed"
            )
            return False

        if refresh_token.access_token_expiration != expiration:
            refresh_token.access_token_expiration = expiration
            schedule_save()
            _LOGGER.debug(
                "[util] updated access token expiry for refresh_token[%s]",
                refresh_token.id,
            )
        return True
    except jwt.InvalidTokenError:
        _LOGGER.debug("[util] access token is invalid, reauthorization may be required")
        return False
