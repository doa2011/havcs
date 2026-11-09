"""
author: cnk700i
blog: ljr.im
recommended version HA version: 0.114.4
"""

import asyncio
from datetime import datetime, timedelta
import importlib
import voluptuous as vol
import os
import shutil
import logging
import traceback

from homeassistant import config_entries
from homeassistant.core import Event, Context, HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.typing import ConfigType
from homeassistant.const import (CONF_PORT, CONF_PROTOCOL, EVENT_HOMEASSISTANT_START)
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.network import get_url
from homeassistant import config as conf_util
from homeassistant.components.http import StaticPathConfig
from homeassistant.components.frontend import DATA_PANELS
from homeassistant.components import frontend


from . import util as havcs_util
from .bind import HavcsBindManager
from .http import HavcsHttpManager
from .const import INTEGRATION, CONF_SETTINGS_CONFIG_PATH, CONF_DEVICE_CONFIG_PATH, DEVICE_ATTRIBUTE_DICT, DATA_HAVCS_HANDLER, DATA_HAVCS_CONFIG, DATA_HAVCS_BIND_MANAGER, DATA_HAVCS_HTTP_MANAGER, DATA_HAVCS_SETTINGS, DATA_HAVCS_ITEMS, DEVICE_PLATFORM_DICT, ATTR_DEVICE_VISABLE, ATTR_DEVICE_ENTITY_ID, ATTR_DEVICE_TYPE, ATTR_DEVICE_NAME, ATTR_DEVICE_ZONE, ATTR_DEVICE_ICON, ATTR_DEVICE_ATTRIBUTES, ATTR_DEVICE_ACTIONS, DEVICE_TYPE_DICT, DEVICE_ATTRIBUTE_DICT, DEVICE_ACTION_DICT, DEVICE_PLATFORM_DICT

_LOGGER = logging.getLogger(__name__)
# _LOGGER.setLevel(logging.DEBUG)

DOMAIN = 'havcs'
MODE = []
SOURCE_PLATFORM = 'platform'

CONF_APP_KEY = 'app_key'
CONF_APP_SECRET = 'app_secret'
CONF_CLIENT_ID = 'client_id'
CONF_CLIENT_SECRET = 'client_secret'
CONF_KEEPALIVE = 'keepalive'
CONF_TOPIC = 'topic'
CONF_BROKER = 'broker'
CONF_CERTIFICATE = 'certificate'
CONF_CLIENT_KEY = 'client_key'
CONF_CLIENT_CERT = 'client_cert'
CONF_TLS_INSECURE = 'tls_insecure'
CONF_ALLOWED_URI = 'allowed_uri'
CONF_ENTITY_KEY = 'entity_key'
CONF_USER_ID = 'user_id'
CONF_HA_URL = 'ha_url'
CONF_SYNC_DEVICE = 'sync_device'
CONF_BIND_DEVICE = 'bind_device'

CONF_PLATFORM = 'platform'
CONF_HTTP = 'http'
CONF_CLIENTS = 'clients'
CONF_HTTP_PROXY = 'http_proxy'
CONF_SKILL = 'skill'
CONF_SETTING = 'setting'
CONF_DEVICE_CONFIG = 'device_config'
CONF_EXPIRE_IN_HOURS = 'expire_in_hours'

PROTOCOL_31 = '3.1'
PROTOCOL_311 = '3.1.1'

DEFAULT_BROKER = 'mqtt.ljr.im'
DEFAULT_PORT = 28883
DEFAULT_KEEPALIVE = 60
DEFAULT_QOS = 0
DEFAULT_PROTOCOL = PROTOCOL_311
DEFAULT_TLS_PROTOCOL = 'auto'
DEFAULT_EXPIRE_IN_HOURS = 24
DEFAULT_ALLOWED_URI = ['/havcs/auth/token', '/havcs/service']

CLIENT_KEY_AUTH_MSG = 'client_key and client_cert must both be present in the MQTT broker configuration'

SERVICE_RELOAD = 'reload'
SERVICE_DEBUG_DISCOVERY = 'debug_discovery'

SETTING_SCHEMA = vol.Schema({
    vol.Optional(CONF_ENTITY_KEY):vol.All(cv.string, vol.Any(vol.Length(min=16, max=16), '')),
    vol.Optional(CONF_APP_KEY): cv.string,
    vol.Optional(CONF_APP_SECRET): cv.string,

    vol.Optional(CONF_USER_ID): cv.string,
    vol.Optional(CONF_CERTIFICATE): vol.Any('auto', cv.isfile),
    vol.Optional(CONF_CLIENT_ID): cv.string,
    vol.Optional(CONF_KEEPALIVE, default=DEFAULT_KEEPALIVE): vol.All(vol.Coerce(int), vol.Range(min=15)),
    vol.Optional(CONF_BROKER, default=DEFAULT_BROKER): cv.string,
    vol.Optional(CONF_PORT, default=DEFAULT_PORT): cv.port,
    vol.Inclusive(CONF_CLIENT_KEY, 'client_key_auth', msg=CLIENT_KEY_AUTH_MSG): cv.isfile,
    vol.Inclusive(CONF_CLIENT_CERT, 'client_key_auth', msg=CLIENT_KEY_AUTH_MSG): cv.isfile,
    vol.Optional(CONF_TLS_INSECURE, default=True): cv.boolean,
    vol.Optional(CONF_PROTOCOL, default=DEFAULT_PROTOCOL): vol.All(cv.string, vol.In([PROTOCOL_31, PROTOCOL_311])),
})



def check_client_id(value):
    """Validate an client_id."""
    for platform in DEVICE_PLATFORM_DICT.keys():
        _LOGGER.debug(platform)
        if value.startswith(platform):
            return value
    raise vol.Invalid('Invalid client_id, starts with platform name')

CLIENT_SCHEMA = vol.Schema({
    check_client_id : cv.string,
})

HTTP_SCHEMA = vol.Schema({
    vol.Required(CONF_CLIENTS): CLIENT_SCHEMA,
    vol.Optional(CONF_HA_URL): cv.string,
    vol.Optional(CONF_EXPIRE_IN_HOURS, default=DEFAULT_EXPIRE_IN_HOURS): cv.positive_int
})

HTTP_PROXY = vol.Schema({
    vol.Optional(CONF_HA_URL): cv.string,
    vol.Optional(CONF_ALLOWED_URI, default=DEFAULT_ALLOWED_URI): vol.All(cv.ensure_list, vol.Length(min=0), [cv.string])
})

SKILL_SCHEMA = vol.Schema({
    vol.Optional(CONF_SYNC_DEVICE, default=True): cv.boolean,
    vol.Optional(CONF_BIND_DEVICE, default=True): cv.boolean
})

CONFIG_SCHEMA = vol.Schema({
    DOMAIN: vol.Schema({
        vol.Required(CONF_PLATFORM): vol.All(cv.ensure_list, vol.Length(min=1), list(DEVICE_PLATFORM_DICT.keys())),
        vol.Optional(CONF_HTTP): vol.Any(HTTP_SCHEMA, None),
        vol.Optional(CONF_HTTP_PROXY): vol.Any(HTTP_PROXY, None),
        vol.Optional(CONF_SKILL): vol.Any(SKILL_SCHEMA, None),
        vol.Optional(CONF_SETTING): vol.Any(SETTING_SCHEMA, None),
        vol.Optional(CONF_DEVICE_CONFIG, default='text'): vol.Any('text', 'ui'),
    })
}, extra=vol.ALLOW_EXTRA)

HAVCS_SERVICE_SCHEMA = vol.Schema({
})

DEVICD_ACTIONS_SCHEMA = vol.Schema({
    vol.In(list(DEVICE_ACTION_DICT.keys())): vol.All(cv.ensure_list, vol.Schema([vol.All(cv.ensure_list, vol.Length(min=3, max=3))]))
})

DEVICE_ENTRY_SCHEMA = vol.Schema({
    vol.Required(ATTR_DEVICE_ENTITY_ID): vol.All(cv.ensure_list, vol.Length(min=1), [cv.entity_id]),
    vol.Optional(ATTR_DEVICE_NAME): cv.string,
    vol.Optional(ATTR_DEVICE_ZONE): cv.string,
    vol.Optional(ATTR_DEVICE_VISABLE): vol.All(cv.ensure_list, list(DEVICE_PLATFORM_DICT.keys())),
    vol.Optional(ATTR_DEVICE_TYPE): vol.In(list(DEVICE_TYPE_DICT.keys())),
    vol.Optional(ATTR_DEVICE_ICON): cv.string,
    vol.Optional(ATTR_DEVICE_ATTRIBUTES): vol.All(cv.ensure_list, list(DEVICE_ATTRIBUTE_DICT.keys())),
    vol.Optional(ATTR_DEVICE_ACTIONS): vol.Any(DEVICD_ACTIONS_SCHEMA, vol.All(cv.ensure_list, list(DEVICE_ACTION_DICT.keys())))
},extra=vol.PREVENT_EXTRA)


def check_device_id(value):
    """Validate an client_id."""
    if value.startswith('havcs.') and len(value) > len('havcs.'):
        return value
    raise vol.Invalid('Invalid device_id, starts with "havcs."')

DEVICE_CONFIG_SCHEMA = vol.Schema({
    check_device_id: DEVICE_ENTRY_SCHEMA
},extra=vol.PREVENT_EXTRA)

ATTR_CONFIG_COMMAND_FILTER = 'command_filter'
SETTINGS_CONFIG_SCHEMA = vol.Schema({
    vol.Optional(ATTR_CONFIG_COMMAND_FILTER, default='none'): vol.Any('http', 'mqtt', 'none'),
    vol.Optional('dueros_bot_id', default=''): cv.string
},extra=vol.PREVENT_EXTRA)

async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:

    hass.data.setdefault(DOMAIN, {})
    conf = config.get(DOMAIN)  # type: ConfigType
 
    if conf is None:
        # If we have a config entry, setup is done by that config entry.
        # If there is no config entry, this should fail.
        return bool(hass.config_entries.async_entries(DOMAIN))     

    hass.data[DOMAIN][DATA_HAVCS_CONFIG] = conf

    if not [entry for entry in hass.config_entries.async_entries(DOMAIN) if entry.source == config_entries.SOURCE_IMPORT]:
        hass.async_create_task(hass.config_entries.flow.async_init(
                DOMAIN, context={'source': config_entries.SOURCE_IMPORT},
                data={'platform': conf.get(CONF_PLATFORM)}
            ))
    return True

async def async_setup_entry(hass, config_entry):
    """Load a config entry."""
    
    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN].setdefault(DATA_HAVCS_HANDLER, {})
    hass.data[DOMAIN].setdefault(DATA_HAVCS_CONFIG, {})
    hass.data[DOMAIN].setdefault(DATA_HAVCS_ITEMS, {})
    hass.data[DOMAIN].setdefault(DATA_HAVCS_SETTINGS, {})
    conf = hass.data[DOMAIN].get(DATA_HAVCS_CONFIG)
    
    _LOGGER.debug(conf)
    
    _LOGGER.debug(config_entry.source)
    
    local = hass.config.path("custom_components/" + INTEGRATION + "/html")
    if os.path.isdir(local) and not hass.data.get('_havcs_static_path_registered'):
        await hass.http.async_register_static_paths([StaticPathConfig('/havcs', local, False)])
        hass.data['_havcs_static_path_registered'] = True
    panels = hass.data.setdefault(DATA_PANELS, {})
    frontend_url_path = INTEGRATION+'_panel'
    if frontend_url_path not in panels:
        frontend.async_register_built_in_panel(
            hass,
            component_name = "iframe",
            sidebar_title = 'HAVCS设备',
            sidebar_icon = 'mdi:home-edit',
            frontend_url_path = frontend_url_path,
            config = {"url": '/havcs/index.html'},
            require_admin = True
        )
    
    # Config entry was created because user had configuration.yaml entry
    # They removed that, so remove entry.
    if config_entry.source == config_entries.SOURCE_IMPORT:
        if not conf:
            hass.async_create_task(
                hass.config_entries.async_remove(config_entry.entry_id))
            _LOGGER.info("[init] there is no config in yaml and havcs is managered by yaml, remove config entry. ")
            return False

    elif config_entry.source == SOURCE_PLATFORM:
        if not conf:
            if [entry for entry in hass.config_entries.async_entries(DOMAIN) if entry.source == config_entries.SOURCE_USER]:
                return True
            else:
                hass.async_create_task(
                    hass.config_entries.async_remove(config_entry.entry_id))
                return False
        else:
                return True

    # If user didn't have configuration.yaml config, generate defaults
    elif config_entry.source == config_entries.SOURCE_USER:
        if not conf:
            conf = CONFIG_SCHEMA({DOMAIN: dict(config_entry.data)})[DOMAIN]
        elif any(key in conf for key in config_entry.data):
            _LOGGER.warning(
                "[init] Data in your config entry is going to override your "
                "configuration.yaml: %s", config_entry.data)
            for key in config_entry.data:
                if key in conf:
                    if isinstance(conf[key], dict):
                        conf[key].update(config_entry.data[key])
                    else:
                        conf[key] = config_entry.data[key]
                else:
                    conf[key] = config_entry.data[key]
            if CONF_HTTP not in config_entry.data and CONF_HTTP in conf:
                conf.pop(CONF_HTTP)
            if CONF_HTTP_PROXY not in config_entry.data and CONF_HTTP_PROXY in conf:
                conf.pop(CONF_HTTP_PROXY)
            if CONF_SKILL not in config_entry.data and CONF_SKILL in conf:
                conf.pop(CONF_SKILL)
            conf = CONFIG_SCHEMA({DOMAIN: conf})[DOMAIN]

    http_manager = hass.data[DOMAIN][DATA_HAVCS_HTTP_MANAGER] = HavcsHttpManager(hass, conf.get(CONF_HTTP, {}).get(CONF_HA_URL, get_url(hass)), DEVICE_CONFIG_SCHEMA, SETTINGS_CONFIG_SCHEMA)
    if CONF_HTTP in conf:
        if conf.get(CONF_HTTP) is None:
            conf[CONF_HTTP] = HTTP_SCHEMA({})
        http_manager.set_expiration(timedelta(hours=conf.get(CONF_HTTP).get(CONF_EXPIRE_IN_HOURS, DEFAULT_EXPIRE_IN_HOURS)))
        http_manager.register_auth_authorize()
        http_manager.register_auth_token()
        http_manager.register_service()
        _LOGGER.info("[init] havcs enable \"http mode\"")

        MODE.append('http')
    if CONF_HTTP_PROXY in conf:
        _LOGGER.warning("[init] http_proxy模式依赖的ljr.im中转服务已停止，忽略该配置，仅按http直连模式运行")
    if CONF_SKILL in conf:
        _LOGGER.warning("[init] skill模式依赖的ljr.im中转服务已停止，忽略该配置，仅按http直连模式运行")
    
    havcs_util.ENTITY_KEY = conf.get(CONF_SETTING, {}).get(CONF_ENTITY_KEY)
    havcs_util.CONTEXT_HAVCS = Context(conf.get(CONF_SETTING, {}).get(CONF_USER_ID))

    platforms = conf.get(CONF_PLATFORM)

    device_config = conf.get(CONF_DEVICE_CONFIG)
    if device_config == 'text':
        havc_device_config_path = os.path.join(hass.config.config_dir, 'havcs.yaml')
        if not os.path.isfile(havc_device_config_path):
            with open(havc_device_config_path, "wt") as havc_device_config_file:
                havc_device_config_file.write('')
        frontend.async_remove_panel(DOMAIN)
    else:
        havc_device_config_path = os.path.join(hass.config.config_dir, 'havcs-ui.yaml')
        if not os.path.isfile(havc_device_config_path):
            if os.path.isfile(os.path.join(hass.config.config_dir, 'havcs.yaml')):
                shutil.copyfile(os.path.join(hass.config.config_dir, 'havcs.yaml'), havc_device_config_path)
            else:
                with open(havc_device_config_path, "wt") as havc_device_config_file:
                    havc_device_config_file.write('')
        http_manager.register_deivce_manager()
    hass.data[DOMAIN][CONF_DEVICE_CONFIG_PATH] = havc_device_config_path

    havc_settings_config_path = os.path.join(hass.config.config_dir, 'havcs-settings.yaml')
    if not os.path.isfile(havc_settings_config_path):
        with open(havc_settings_config_path, "wt") as havc_settings_config_file:
            havc_settings_config_file.write('')
    http_manager.register_settings_manager()
    hass.data[DOMAIN][CONF_SETTINGS_CONFIG_PATH] = havc_settings_config_path

    # ljr.im中转服务已停止：移除mqtt中转(http_proxy/skill模式)初始化，仅支持http直连模式
    _LOGGER.debug("[init] havcs run in http direct mode")
    # 直连模式：创建绑定管理器，启用状态变化主动上报（百度官方 changereport 接口）
    clients = conf.get(CONF_HTTP, {}).get(CONF_CLIENTS, {})
    if platforms and clients:
        bind_manager = hass.data[DOMAIN][DATA_HAVCS_BIND_MANAGER] = HavcsBindManager(hass, platforms, bind_device=False, sync_device=True, app_key=None, decrypt_key=None, direct_report=True)
        await bind_manager.async_init()

    async def start_havcs(event: Event):
        async def async_load_settings():
            _LOGGER.info("loading settings from file")
            try:
                settings_config = await hass.async_add_executor_job(
                    conf_util.load_yaml_config_file, havc_settings_config_path
                )
                hass.data[DOMAIN][DATA_HAVCS_SETTINGS] = SETTINGS_CONFIG_SCHEMA(settings_config)
                
            except HomeAssistantError as err:
                _LOGGER.error("Error loading %s: %s", havc_settings_config_path, err)
                return None
            except vol.error.Error as exception:
                _LOGGER.warning("failed to load all settings from file, find invalid data: %s", exception)
            except:
                _LOGGER.error("Error loading %s: %s", havc_settings_config_path, traceback.format_exc())
                return None
        await async_load_settings()

        async def async_load_device_info():
            _LOGGER.info("loading device info from file")
            try:
                device_config = await hass.async_add_executor_job(
                    conf_util.load_yaml_config_file, havc_device_config_path
                )
                hass.data[DOMAIN][DATA_HAVCS_ITEMS] = DEVICE_CONFIG_SCHEMA(device_config)
            except HomeAssistantError as err:
                _LOGGER.error("Error loading %s: %s", havc_device_config_path, err)
                return None
            except vol.error.Error as exception:
                _LOGGER.warning("failed to load all devices from file, find invalid data: %s", exception)
            except:
                _LOGGER.error("Error loading %s: %s", havc_device_config_path, traceback.format_exc())
                return None

        def sync_import_module(domain, platform):
            return importlib.import_module('custom_components.{}.{}'.format(domain, platform))
                
        async def async_init_sub_entry():
            # create when config change
            mode = []
            if CONF_HTTP in conf:
                mode.append(CONF_HTTP)
                if CONF_HTTP_PROXY in conf:
                    mode.append(CONF_HTTP_PROXY)
            if CONF_SKILL in conf:
                mode.append(CONF_SKILL)

            havcs_entries = hass.config_entries.async_entries(DOMAIN)
            # sub entry for every platform
            entry_platforms = set([entry.data.get('platform') for entry in havcs_entries if entry.source == SOURCE_PLATFORM])
            conf_platforms = set(conf.get(CONF_PLATFORM))
            new_platforms = conf_platforms - entry_platforms
            _LOGGER.debug("[post-task] load new platform entry %s", new_platforms)
            for platform in new_platforms:
                # 如果在async_setup_entry中执行无法await，async_init所触发的component_setup会不断等待之前的component_setup任务
                await hass.async_create_task(hass.config_entries.flow.async_init(
                    DOMAIN, context={'source': SOURCE_PLATFORM},
                    data={'platform': platform, 'mode': mode}
                ))
            remove_platforms = entry_platforms - conf_platforms
            _LOGGER.debug("[post-task] remove old platform entry %s", remove_platforms)
            for entry in [entry for entry in havcs_entries if entry.source == SOURCE_PLATFORM]:
                if entry.data.get('platform') in remove_platforms:
                    await hass.async_create_task(hass.config_entries.async_remove(entry.entry_id))
                else:
                    hass.config_entries.async_update_entry(entry, title=f"接入平台[{entry.data.get('platform')}-{DEVICE_PLATFORM_DICT[entry.data.get('platform')]['cn_name']}]，接入方式{mode}")

            # await async_load_device_info()
            
            loop = asyncio.get_event_loop()

            for platform in platforms:
                for ent in hass.config_entries.async_entries(DOMAIN):
                    if ent.source == SOURCE_PLATFORM and ent.data.get('platform') == platform:
                        try:
                            module = await loop.run_in_executor(None, sync_import_module, DOMAIN, platform)
                            _LOGGER.info("[post-task] import %s.%s", DOMAIN, platform)
                            hass.data[DOMAIN][DATA_HAVCS_HANDLER][platform] = await module.createHandler(hass, ent)

                        except ImportError as err:
                            _LOGGER.error("[post-task] Unable to import %s.%s, %s", DOMAIN, platform, err)
                            return False
                        except:
                            _LOGGER.error("[post-task] fail to create %s handler: %s", platform , traceback.format_exc())
                            return False
                        break
        await async_init_sub_entry()

        async def async_handler_service(service):
    
            if service.service == SERVICE_RELOAD:
                await async_load_device_info()
                for platform in hass.data[DOMAIN][DATA_HAVCS_HANDLER]:
                    devices = hass.data[DOMAIN][DATA_HAVCS_HANDLER][platform].vcdm.all(hass, True)
                    await hass.data[DOMAIN][DATA_HAVCS_HANDLER][platform].vcdm.async_reregister_devices(hass)
                    _LOGGER.info("[service] ------------%s 平台加载设备信息------------\n%s", platform, [device.attributes for device in devices])
                    mind_devices = [device.attributes for device in devices if None in device.attributes.values() or [] in device.attributes.values()]
                    if mind_devices:
                        _LOGGER.debug("!!!!!!!! 以下设备信息不完整，检查值为None或[]的属性并进行设置 !!!!!!!!")
                        for mind_device in mind_devices:
                            _LOGGER.debug("%s", mind_device)
                    _LOGGER.info("[service] ------------%s 平台加载设备信息------------\n", platform)
                # 直连模式：同步设备时向小度推送全部设备的状态变化通知，触发云端回查刷新
                bind_manager = hass.data[DOMAIN].get(DATA_HAVCS_BIND_MANAGER)
                if bind_manager is not None and bind_manager.direct_report:
                    await bind_manager.async_send_all_direct_reports()

            elif service.service == SERVICE_DEBUG_DISCOVERY:
                for platform, handler in hass.data[DOMAIN][DATA_HAVCS_HANDLER].items():
                    err_result, discovery_devices, entity_ids = handler.process_discovery_command("service_call")
                    _LOGGER.info("[service][%s] trigger discovery command, response: %s", platform, discovery_devices)
            else:
                pass
        hass.services.async_register(DOMAIN, SERVICE_RELOAD, async_handler_service, schema=HAVCS_SERVICE_SCHEMA)
        hass.services.async_register(DOMAIN, SERVICE_DEBUG_DISCOVERY, async_handler_service, schema=HAVCS_SERVICE_SCHEMA)

        await hass.services.async_call(DOMAIN, SERVICE_RELOAD)

        if CONF_HTTP in conf:
            hass.async_create_task(http_manager.async_check_http_oauth())

    if config_entry.source == config_entries.SOURCE_IMPORT:
        hass.bus.async_listen_once(EVENT_HOMEASSISTANT_START, start_havcs)
    elif config_entry.source == config_entries.SOURCE_USER:
        hass.async_create_task(start_havcs(None))

    _LOGGER.info("[init] havcs initialization finished.")
    return True

async def async_unload_entry(hass, config_entry):
    if config_entry.source in [config_entries.SOURCE_IMPORT, config_entries.SOURCE_USER]:
        tasks = [hass.config_entries.async_remove(entry.entry_id) for entry in hass.config_entries.async_entries(DOMAIN) if entry.source == SOURCE_PLATFORM and entry.data['platform'] in config_entry.data['platform']]
        if tasks:
            unload_ok = all(await asyncio.gather(*tasks))
        else:
            unload_ok =True
        if unload_ok:
            hass.services.async_remove(DOMAIN, SERVICE_RELOAD)
            hass.services.async_remove(DOMAIN, SERVICE_DEBUG_DISCOVERY)
            bind_manager = hass.data[DOMAIN].pop(DATA_HAVCS_BIND_MANAGER, None)
            if bind_manager is not None:
                bind_manager.clear()
            http_manager = hass.data[DOMAIN].get(DATA_HAVCS_HTTP_MANAGER)
            if http_manager is not None:
                http_manager.async_unload()
            hass.data[DOMAIN].pop(DATA_HAVCS_CONFIG)
            # hass.data[DOMAIN].pop(DATA_HAVCS_ITEMS)
            hass.data[DOMAIN].pop(DATA_HAVCS_HANDLER)
            hass.data[DOMAIN].pop(DATA_HAVCS_HTTP_MANAGER)
            hass.data[DOMAIN].pop(CONF_DEVICE_CONFIG_PATH)
            hass.data[DOMAIN].pop(CONF_SETTINGS_CONFIG_PATH)
            frontend.async_remove_panel(DOMAIN+'_panel')
            if not hass.data[DOMAIN]:
                hass.data.pop(DOMAIN)
            
        return unload_ok

    elif config_entry.source == SOURCE_PLATFORM:
        for entry in [entry for entry in hass.config_entries.async_entries(DOMAIN) if entry.source in [config_entries.SOURCE_IMPORT, config_entries.SOURCE_USER]]:
            if config_entry.data['platform'] in entry.data['platform']:
                entry.data['platform'].remove(config_entry.data['platform'])
        return True





