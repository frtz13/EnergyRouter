# Install Energy Router as a standalone Python script

Copy EnergyRouter.py and EnergyRouterModel.ini to some folder. Copy or rename EnergyRouterModel.ini to EnergyRouter.ini.

### Parameters

#### [mqtt] section

Configure access to your MQTT broker.

#### [grid] section

Enter the MQTT topic, where the power consumption/injection of the household is available.

#### [dimmer] section

Set parameters in this section according to your ESPHome code.

MAX_PERCENTAGE: you can set the maximum power you want to allow to the water heater.

MQTT_TOPIC_DIMMER_STATUS: in DEBUG mode, the Energy Router sends internal values via this MQTT topic.

#### [regulation] section

The given values should be a good starting point.
