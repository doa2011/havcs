import json
import aiohttp
import asyncio
import async_timeout
import logging
import traceback
from datetime import timedelta

from homeassistant.const import EVENT_STATE_CHANGED, ATTR_ENTITY_ID
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.event import async_call_later, async_track_time_interval
from homeassistant.helpers.storage import Store

from .const import DUEROS_CHANGEREPORT_URL, DATA_HAVCS_HANDLER, DATA_HAVCS_BIND_MANAGER, DATA_HAVCS_ITEMS, STORAGE_VERSION, INTEGRATION

_LOGGER = logging.getLogger(__name__)
LOGGER_NAME = 'bind'

STORAGE_KEY='havcs_bind_manager'
STORAGE_VERSION

# 用于管理哪些平台哪些用户有哪些设备
class HavcsBindManager:
    def __init__(self, hass, platforms, bind_device = False, sync_device = False, app_key = None, decrypt_key = None, direct_report = False):
        _LOGGER.debug("[bindManager] ----init bindManager----")
        # 兼容不同版本HA的Store签名：新版需要hass参数，旧版不需要
        try:
            self._store = Store(hass, STORAGE_VERSION, STORAGE_KEY)
        except TypeError:
            self._store = Store(STORAGE_VERSION, STORAGE_KEY)
        self._platforms = platforms
        # Keep mutable synchronization state isolated per manager instance.
        self._privious_upload_devices = {}
        self._new_upload_devices = {platform: {} for platform in platforms}
        self._discovery = set()
        self._hass = hass
        self._sync_manager = {
            'bind_device': bind_device,
            'sync_device': sync_device,
            'app_key': app_key,
            'decrypt_key': decrypt_key,
            'direct_report': direct_report
        }
        self._pending_retries = set()
        self._retry_callbacks = {}
        self._retry_attempts = {}
        self._pending_report_callbacks = {}
        self._pending_report_tokens = {}
        self._report_semaphore = asyncio.Semaphore(3)

    async def async_init(self):
        await self.async_load()
        if self._sync_manager.get('sync_device'):
            self.sync_device()
        if self._sync_manager.get('direct_report'):
            # 启动30秒后全量上报一次，此后每30分钟对账一次
            self._sync_manager['remove_startup_report'] = async_call_later(
                self._hass, 30, self._make_full_report_job('startup')
            )
            # 新旧版本HA的参数顺序不同（新版hass,action,interval；旧版hass,interval,action），关键字传参兼容两者
            self._sync_manager['remove_interval_listener'] = async_track_time_interval(
                self._hass, action=self._make_full_report_job('periodic'), interval=timedelta(minutes=30))

    async def async_load(self):
        data =  await self._store.async_load()  # load task config from disk
        if data:
            self._privious_upload_devices = {
                device['device_id']: {'device_id': device['device_id'], 'linked_account': set(device['linked_account'])} for device in data.get('upload_devices',[])
            }
            self._discovery = set(data.get('discovery',[]))
            _LOGGER.debug("[bindManager] discovery:\n%s", self.discovery)

    def get_bind_entity_ids(self, platform, p_user_id = '', repeat_upload = True):
        _LOGGER.debug("[bindManager] privious_upload_devices:\n%s", self._privious_upload_devices)
        _LOGGER.debug("[bindManager] new_upload_devices:\n%s", self._new_upload_devices.get(platform))
        search = set([p_user_id + '@' + platform, '*@' + platform]) # @jdwhale获取平台所有设备，*@jdwhale表示该不限定用户
        if repeat_upload:
            bind_entity_ids = [device['device_id'] for device in self._new_upload_devices.get(platform).values() if search & device['linked_account'] ]
        else:
            bind_entity_ids = [device['device_id'] for device in self._new_upload_devices.get(platform).values() if (search & device['linked_account']) and not(search & self._privious_upload_devices.get(device['device_id'],{}).get('linked_account',set()))]
        return bind_entity_ids
    
    def get_unbind_entity_ids(self, platform, p_user_id = ''):
        search = set([p_user_id + '@' + platform, '*@' + platform])
        unbind_devices = [device['device_id'] for device in self._privious_upload_devices.values() if (search & device['linked_account']) and not(search & self._new_upload_devices.get(platform).get(device['device_id'],{}).get('linked_account',set()))]
        return unbind_devices

    def update_lists(self, devices, platform, p_user_id= '*',repeat_upload = True):
        if platform is None:
            platforms = [platform for platform in self._platforms]
        else:
            platforms = [platform]

        linked_account = set([p_user_id + '@' + platform for platform in platforms])
        # _LOGGER.debug("[bindManager]  0.linked_account:%s", linked_account)
        for device_id in devices:
            if device_id in self._new_upload_devices.get(platform):
                device =  self._new_upload_devices.get(platform).get(device_id)
                device['linked_account'] = device['linked_account'] | linked_account
                # _LOGGER.debug("[bindManager]  1.linked_account:%s", device['linked_account'])
            else:
                linked_account =linked_account | set(['@' + platform for pplatform in platform])
                device = {
                    'device_id': device_id,
                    'linked_account': linked_account,
                }
                # _LOGGER.debug("[bindManager]  1.linked_account:%s", device['linked_account'])
                self._new_upload_devices.get(platform)[device_id] = device

    async def async_save(self, platform, p_user_id= '*'):
        devices = {}         
        for device_id in self.get_unbind_entity_ids(platform, p_user_id):
            if device_id in devices:
                device =  devices.get(device_id)
                device['linked_account'] = device['linked_account'] | linked_account
                # _LOGGER.debug("1.linked_account:%s", device['linked_account'])
            else:
                linked_account =set([p_user_id +'@'+platform])
                device = {
                    'device_id': device_id,
                    'linked_account': linked_account,
                }
                # _LOGGER.debug("1.linked_account:%s", device['linked_account'])
                devices[device_id] = device
        _LOGGER.debug("[bindManager]  all_unbind_devices:\n%s", devices)

        upload_devices  = [
            {
            'device_id': device_id,
            'linked_account': list((self._privious_upload_devices.get(device_id,{}).get('linked_account',set()) | self._new_upload_devices.get(platform).get(device_id,{}).get('linked_account',set())) - devices.get(device_id,{}).get('linked_account',set()))
            } for device_id in set(list(self._privious_upload_devices.keys())+list(self._new_upload_devices.get(platform).keys()))
        ]
        _LOGGER.debug("[bindManager] upload_devices:\n%s", upload_devices)
        data = {
            'upload_devices':upload_devices,
            'discovery':self.discovery
        }
        await self._store.async_save(data)
        self._privious_upload_devices = {
                    device['device_id']: {'device_id': device['device_id'], 'linked_account': set(device['linked_account'])} for device in upload_devices
            }

    async def async_save_changed_devices(self, new_devices, platform, p_user_id = '*', force_save = False):
        self.update_lists(new_devices, platform)
        uid = p_user_id+'@'+platform
        if self.check_discovery(uid) and not force_save:
            # _LOGGER.debug("[bindManager] 用户(%s)已执行discovery", uid)
            bind_entity_ids = []
            unbind_entity_ids = []
        else:
            # _LOGGER.debug("用户(%s)启动首次执行discovery", uid)
            self.add_discovery(uid)
            bind_entity_ids = self.get_bind_entity_ids(platform = platform,p_user_id =p_user_id, repeat_upload = False)
            unbind_entity_ids = self.get_unbind_entity_ids(platform = platform,p_user_id=p_user_id)
        # 每次发现都落盘并更新正式绑定表，保证新添加的设备也能被状态推送覆盖
        await self.async_save(platform, p_user_id=p_user_id)
        # _LOGGER.debug("[bindManager] p_user_id:%s',p_user_id)
        # _LOGGER.debug("[bindManager] get_bind_entity_ids:%s", bind_entity_ids)
        # _LOGGER.debug("[bindManager] get_unbind_entity_ids:%s", unbind_entity_ids)
        return bind_entity_ids,unbind_entity_ids

    def check_discovery(self, uid):
        if uid in self._discovery:
            return True
        else:
            return False
    def add_discovery(self, uid):
        self._discovery = self._discovery | set([uid])

    @property
    def discovery(self):
        return list(self._discovery)

    def get_uids(self, platform, device_id):
        # _LOGGER.debug("[bindManager] %s", self._discovery)
        # _LOGGER.debug("[bindManager] %s", self._privious_upload_devices)
        p_user_ids = []
        for uid in self._discovery:
            p_user_id = uid.split('@')[0]
            p = uid.split('@')[1]
            if p == platform and (set([uid, '*@' + platform]) & self._privious_upload_devices.get(device_id,{}).get('linked_account',set())):
                p_user_ids.append(p_user_id)
        return p_user_ids

    def sync_device(self):
        @callback
        def report_device(event):
            """Debounce state changes and report only the latest state per device."""
            entity_id = event.data.get(ATTR_ENTITY_ID)
            entity = self._hass.states.get(entity_id) if entity_id else None
            if entity is None:
                return

            for platform, handler in self._hass.data[INTEGRATION][DATA_HAVCS_HANDLER].items():
                if not hasattr(handler, 'report_device'):
                    continue
                device_ids = handler.vcdm.get_entity_related_device_ids(self._hass, entity.entity_id)
                for device_id in device_ids:
                    _LOGGER.debug(
                        "[skill] queue state report to %s: device_id = %s (entity_id = %s)",
                        platform,
                        device_id,
                        entity_id,
                    )
                    self._schedule_direct_report(platform, handler, device_id)

        self.clear()
        self._sync_manager['remove_listener'] = self._hass.bus.async_listen(
            EVENT_STATE_CHANGED, report_device
        )

    def _schedule_direct_report(self, platform, handler, device_id):
        """Schedule a coalesced report, replacing an older pending report."""
        key = (platform, device_id)
        remove_callback = self._pending_report_callbacks.pop(key, None)
        if remove_callback is not None:
            remove_callback()

        token = object()
        self._pending_report_tokens[key] = token

        async def _report_latest(now):
            if self._pending_report_tokens.get(key) is not token:
                return
            self._pending_report_tokens.pop(key, None)
            self._pending_report_callbacks.pop(key, None)
            try:
                await self.async_send_direct_report(platform, handler, device_id)
            except Exception:
                _LOGGER.exception("[skill] state report failed for device_id=%s", device_id)

        self._pending_report_callbacks[key] = async_call_later(
            self._hass, 1, _report_latest
        )

    def clear(self):
        remove_listener = self._sync_manager.get('remove_listener')
        if remove_listener:
            remove_listener()
            self._sync_manager.pop('remove_listener')
        for key in ('remove_interval_listener', 'remove_startup_report'):
            remove_callback = self._sync_manager.pop(key, None)
            if remove_callback:
                remove_callback()

        for callback_map in (self._retry_callbacks, self._pending_report_callbacks):
            for remove_callback in callback_map.values():
                remove_callback()
            callback_map.clear()
        self._pending_report_tokens.clear()
        self._pending_retries.clear()
        self._retry_attempts.clear()

    @property
    def direct_report(self):
        return self._sync_manager.get('direct_report')

    async def async_send_all_direct_reports(self):
        """直连模式：向所有已绑定平台推送全部设备的状态变化通知（全量对账）"""
        for platform, handler in self._hass.data[INTEGRATION][DATA_HAVCS_HANDLER].items():
            if hasattr(handler, 'report_device'):
                for device_id in self._hass.data[INTEGRATION][DATA_HAVCS_ITEMS]:
                    await self.async_send_direct_report(platform, handler, device_id)

    def _make_full_report_job(self, trigger):
        async def _full_report(now):
            _LOGGER.info("[skill] full state report triggered by %s", trigger)
            try:
                await self.async_send_all_direct_reports()
            except:
                _LOGGER.error("[skill] full state report fail: %s", traceback.format_exc())
        return _full_report

    async def async_send_direct_report(self, platform, handler, device_id):
        """直连模式：明文JSON逐条推送百度官方"设备属性上报"接口，被限频(21207)时自动安排重试"""
        payload = handler.report_device(device_id)
        if not payload:
            _LOGGER.debug("[skill] skip report, no bound user on %s: device_id = %s", platform, device_id)
            return
        for report in payload:
            try:
                session = async_get_clientsession(self._hass)
                async with self._report_semaphore:
                    with async_timeout.timeout(5):
                        response = await session.post(DUEROS_CHANGEREPORT_URL, json=report)
                        text = await response.text()
                _LOGGER.info("[skill] get report device result from %s: %s", platform, text)
                try:
                    status = json.loads(text).get('status')
                except ValueError:
                    status = None
                retry_key = (platform, device_id)
                if status == 21207:
                    # Limit retries to one delayed attempt per device until a report succeeds.
                    retry_attempts = self._retry_attempts.get(retry_key, 0)
                    if retry_attempts < 1 and retry_key not in self._pending_retries:
                        self._retry_attempts[retry_key] = retry_attempts + 1
                        self._pending_retries.add(retry_key)
                        _LOGGER.info("[skill] report rate-limited, retry in 61s: device_id = %s", device_id)
                        self._retry_callbacks[retry_key] = async_call_later(
                            self._hass, 61, self._make_direct_report_retry(platform, handler, device_id)
                        )
                elif status is not None:
                    self._retry_attempts.pop(retry_key, None)
            except(asyncio.TimeoutError, aiohttp.ClientError):
                _LOGGER.error("[skill] fail to access %s, report device fail: timeout", DUEROS_CHANGEREPORT_URL)
            except:
                _LOGGER.error("[skill] fail to access %s, report device fail: %s", DUEROS_CHANGEREPORT_URL, traceback.format_exc())

    def _make_direct_report_retry(self, platform, handler, device_id):
        async def _retry(now):
            retry_key = (platform, device_id)
            self._pending_retries.discard(retry_key)
            self._retry_callbacks.pop(retry_key, None)
            try:
                await self.async_send_direct_report(platform, handler, device_id)
            except:
                _LOGGER.error("[skill] retry report device fail: %s", traceback.format_exc())
        return _retry