import appdaemon.plugins.hass.hassapi as hass
import time
import asyncio
import json
import mqttapi as mqtt

SCRIPT_VERSION = "2022.12.09"
LOGLEVEL_DEBUG = "debug"

class EnergyRouter(hass.Hass, mqtt.Mqtt):
    async def initialize(self):
        self._gridpower = None
        self._router_off_no_gridpower_info = None
        self._confirmed_gridpower = False
        self._confirmed_routermode = False
        self._router = None
        self.DIMMER_IS_ONLINE = False
        self.log(f"Energy Router start ({SCRIPT_VERSION})")
        if not self._readparms():
            self.log("Program disabled. Please check parameters.")
            return
        if self._parm_LOGLEVEL == LOGLEVEL_DEBUG:
            self.log("Debug mode activated.")
        await self.run_in(self.energy_router_loop, 2)

    def _readparms(self):
        try:
            self._parm_go = (int(self.args["go"]) != 0)
            try:
                self._parm_mqtt_topic_gridpower = self.args["mqtt_topic_gridpower"]
                if len(self._parm_mqtt_topic_gridpower) == 0:
                    raise Exception()
            except:
                self._parm_mqtt_topic_gridpower = None
            if self._parm_mqtt_topic_gridpower is None:
                try:
                    self._parm_sensor_gridpower = self.args["sensor_gridpower"]
                    if len(self._parm_sensor_gridpower) == 0:
                        raise Exception()
                except:
                    raise Exception("No method for gridpower readings")
            else:
                self._parm_sensor_gridpower = None
            self._parm_regul_prop = self.args["regul_prop"]
            self._parm_regul_integ = self.args["regul_integ"]
            self._parm_max_dimmer_percentage = self.args["max_dimmer_percentage"]
            self._parm_load_max_power = self.args["load_max_power_w"]
            self._parm_gridpower_bias = self.args["gridpower_bias_w"]
            self._parm_mqtt_topic_dimmer_root = self.args["mqtt_topic_dimmer_root"]
            self._parm_mqtt_topic_dimmer_power = self.args["mqtt_topic_dimmer_power"]
            self._parm_mqtt_topic_dimmer_status = self.args["mqtt_topic_dimmer_status"]
            self._parm_mqtt_topic_dimmer_online = self.args["mqtt_topic_dimmer_online"]
            self._parm_mqtt_topic_routermode = self.args["mqtt_topic_routermode"]
            self._parm_mqtt_topic_router_online = self.args["mqtt_topic_router_online"]
            try:
                self._parm_LOGLEVEL = self.args["loglevel"]
            except:
                self._parm_LOGLEVEL = "normal"
            return True
        except Exception as e:
            self.log(f"[error] reading parameters: {e}")
            return False

    def on_message_dimmeronline(self, event_name, data, kwargs):
        self.DIMMER_IS_ONLINE = data["payload"] == "online"
        if self.DIMMER_IS_ONLINE:
            self.log("Dimmer is online")
        else:
            self.log("Dimmer is offline")

    def on_message_routermode(self, event_name, data, kwargs):
        self._routermode.set_mode(data["payload"])
        if not self._confirmed_routermode:
            self.log(f"Got RouterMode: {self._routermode.current_mode}")
            self._confirmed_routermode = True

    def on_mqtt_message_gridpower(self, event_name, data, kwargs):
        try:
            self._gridpower.setvalue(float(data["payload"]))
            if not self._confirmed_gridpower:
                self.log(f"Got gridpower: {self._gridpower.currentvalue}")
                self._confirmed_gridpower = True
        except:
            pass

    def get_gridpower(self, entity, attribute, old, new, kwargs):
        if (new is None) or (new == "unavailable"):
            self._gridpower.setvalue(None)
        else:
            self._gridpower.setvalue(float(new))
        if not self._confirmed_gridpower:
            self.log(f"Got gridpower: {self._gridpower.currentvalue}")
            self._confirmed_gridpower = True

    async def mqtt_router_online(self, is_online):
        if self.is_client_connected():
            if is_online:
                _payload = "online"
            else:
                _payload = "offline"
            await self.mqtt_publish(
                topic=self._parm_mqtt_topic_dimmer_root + "/" + self._parm_mqtt_topic_router_online,
                payload=_payload,
                retain=True
                )

# ============== main program ===================
    async def energy_router_loop(self, kwargs):
    # do some async stuff  
        if not self._parm_go:
            self.mqtt_router_online(False)
            self.log("disabled")
            return

        await self.mqtt_router_online(True)

        _topic = self._parm_mqtt_topic_dimmer_root + "/" + self._parm_mqtt_topic_dimmer_online
        self.listen_event(
            self.on_message_dimmeronline, "MQTT_MESSAGE",
            topic=_topic,
            namespace="mqtt")
        await self.mqtt_subscribe(_topic, namespace="mqtt")

        self._gridpower = GridPower()
        if self._parm_mqtt_topic_gridpower is not None:
            _topic = self._parm_mqtt_topic_gridpower
            self.listen_event(
                self.on_mqtt_message_gridpower, "MQTT_MESSAGE",
                topic=_topic,
                namespace="mqtt")
            await self.mqtt_subscribe(_topic, namespace="mqtt")
        if self._parm_sensor_gridpower is not None:
            self.listen_state(self.get_gridpower, self._parm_sensor_gridpower)

        self._routermode = RouterMode(self)
        _topic = self._parm_mqtt_topic_dimmer_root + "/" + self._parm_mqtt_topic_routermode
        self.listen_event(
            self.on_message_routermode, "MQTT_MESSAGE",
            topic=_topic,
            namespace="mqtt")
        await self.mqtt_subscribe(_topic, namespace="mqtt")

        self._router = Router(self)

    # main loop
        while(True):
            await asyncio.sleep(1)
            self.check_gridpower_info()
            if self._router_off_no_gridpower_info and self._routermode.in_auto_mode:
                await self._router.switch_off()
            else:
                await self._router.set_power(self._routermode, self._gridpower.currentvalue)

    def check_gridpower_info(self):
        TICK_GRIDPOWER_MAX = 60 #seconds

        global tick_gridpower

        if (tick_gridpower >= TICK_GRIDPOWER_MAX):
            # we switch off router in auto mode without news from grid power
            if not self._router_off_no_gridpower_info:
                self._router_off_no_gridpower_info = True
                msg = "[Timeout] No gridpower info. Router switched off."
                self.log(msg)
        else:
            if self._router_off_no_gridpower_info:
                msg = "Gridpower info available. Router switched on."
                self.log(msg)
                self._router_off_no_gridpower_info = False
            if tick_gridpower < TICK_GRIDPOWER_MAX:
                tick_gridpower += 1

    async def terminate(self):
        if self._router is not None:
            await self._router.switch_off()
        await self.mqtt_router_online(False)
        await self.mqtt_unsubscribe(self._parm_mqtt_topic_dimmer_root + "/" + self._parm_mqtt_topic_dimmer_online,
            namespace="mqtt")
        await self.mqtt_unsubscribe(self._parm_mqtt_topic_dimmer_root + "/" + self._parm_mqtt_topic_routermode,
            namespace="mqtt")
        if self._parm_mqtt_topic_gridpower is not None:
            await self.mqtt_unsubscribe(self._parm_mqtt_topic_gridpower, namespace="mqtt")

        self.log("Energy Router terminated.")


def inbetween(minv, val, maxv):
    return min(maxv, max(minv, val))


# ================= Router ==================
class Router:
    def __init__(self, parent):
        self._parent = parent
        self._routersum = 0
        self.set_prop(parent._parm_regul_prop)
        self.set_integ(parent._parm_regul_integ)
        self.set_gridpower_bias(parent._parm_gridpower_bias)
        self._maxdimmerpourcentage = parent._parm_max_dimmer_percentage
        self._cnt_publish_status = 0
        self._cnt_set_dimmer = 0
        self._last_dimpercent = -1

    def set_prop(self, value):
        self._prop = value / self._parent._parm_load_max_power

    def set_integ(self, value):
        self._integ = value / self._parent._parm_load_max_power

    def set_gridpower_bias(self, value):
        self._gridpower_bias = value

    async def set_power(self, routermode, gridpower):
        if not self._parent.DIMMER_IS_ONLINE:
            return
        if routermode.in_auto_mode:
            await self._set_power_auto(gridpower)
        else:
            _dimpercent = inbetween(0, routermode.current_mode, 100)
            _dimpercent = int(_dimpercent * 10) / 10
            await self._setdimmer(_dimpercent)

    async def _set_power_auto(self, gridpower):
        if gridpower is None:
            return
        else:
            diff = -gridpower + self._gridpower_bias
            self._routersum = self._routersum + diff

            _rsummax = self._maxdimmerpourcentage / self._integ
            self._routersum = inbetween(-100, self._routersum, _rsummax)

            pDiff = diff * self._prop
            iDiff = self._routersum * self._integ
            _dimmerpercent = inbetween(0, pDiff + iDiff, 100)
            _dimmerpercent = int(_dimmerpercent * 10) / 10
            await self._setdimmer(_dimmerpercent)
            if self._parent._parm_LOGLEVEL == LOGLEVEL_DEBUG:
                await self._publish_status(gridpower, _dimmerpercent, pDiff, iDiff)

    async def _setdimmer(self, percent):
#   only publish every 10th dimmerload value, unless its value changes
        CNT_MAX = 10
        try:
            if self._last_dimpercent != percent:
                self._cnt_set_dimmer = CNT_MAX

            if self._cnt_set_dimmer >= CNT_MAX:
                if self._parent.is_client_connected():
                    dictPayload = {
                        "dim_percent": percent,
                        "power_estim": int(percent * self._parent._parm_load_max_power / 100),
                        }
                    await self._parent.mqtt_publish(
                        topic=self._parent._parm_mqtt_topic_dimmer_root + "/" + self._parent._parm_mqtt_topic_dimmer_power,
                        payload=json.dumps(dictPayload))
                    self._cnt_set_dimmer = 0
                    self._last_dimpercent = percent
            else:
                self._cnt_set_dimmer += 1
        except Exception as e:
            self._parent.log(f"[error] setdimmer {e}")

    async def _publish_status(self, lastPower, dimmerLoad, pDiff, iDiff):
    # publish current gridpower, dimmersetting, _dimmersum
        dictPayload = {
            "gridpower_W": lastPower,
            "tick": tick_gridpower,
            "dimmer": dimmerLoad,
            "sum": self._routersum,
            "pDiff": pDiff,
            "iDiff": iDiff,
            }
        payload = json.dumps(dictPayload)
        try:
            if self._parent.is_client_connected():
                self._cnt_publish_status += 1
                if self._cnt_publish_status % 10 == 0:
                    self._cnt_publish_status = 0
                    await self._parent.mqtt_publish(
                        topic=self._parent._parm_mqtt_topic_dimmer_root + "/" + self._parent._parm_mqtt_topic_dimmer_status,
                        payload=json.dumps(dictPayload))
                    self._parent.log(f"status : {payload}")
        except Exception as e:
            self._parent.log(f"[exception] publish status: {e}")

    async def switch_off(self):
        await self._setdimmer(0)
        return

# =================== GridPower ================
class GridPower:
    def __init__(self):
        self._arr_gridpower = None

    def setvalue(self, new):
        global tick_gridpower

        self._arr_gridpower = new
        tick_gridpower = 0

    @property
    def currentvalue(self):
        return self._arr_gridpower

# ================== RouterMode =====================
class RouterMode:
    # supported modes: -1 (Auto), 0 (off), 1..100 (constant value)

    def __init__(self, outerclass):
        self._hass = outerclass
        self._ROUTERMODE_AUTO = -1
        self._current_mode = self._ROUTERMODE_AUTO

    def set_mode(self, newvalue):
        try:
            self._current_mode = inbetween(-1, int(float(newvalue)), 100)
#            self._hass.log(f"Set Routermode: {self._current_mode}")
        except Exception as e:
            self._hass.log(f"[Error] [Set Routermode] {e}")

    @property
    def current_mode(self):
        return self._current_mode

    @property
    def in_auto_mode(self):
        return self._current_mode == self._ROUTERMODE_AUTO

'''
TBD
'''