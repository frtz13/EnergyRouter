# Energy Router

work in progress !!!

Send Energy which would otherwise be injected into the public power grid, to a water heater (or some other energy consuming device).

## How it works

The project assumes that you already have a device (typically a Shelly EM) which measures the grid power of the household, which can be either positive (power is consumed) or négative (power is injected into the public power grid). This information is supposed to be available via a MQTT broker.

When power is injected into the public power grid, the Energy Router communicates with a Dimmer device which gradually sends power to a water heater. A closed regulation loop keeps the injected power as low as possible, while switching off power to the water heater, when the household power consumption is higher than the produced power. The Energy Router is a python program, typically running on a Raspberry Pi (which probably also runs the MQTT broker).

The Dimmer device is composed of a ESP8266 microcontroller and a RobotDyn dimmer. The microcontroller receives commands from the Energy Router via the MQTT broker.

## Grid power measurement

If this task is performed by a Shelly EM, it should be configured to send measurements to a MQTT broker. On the web page of the Shelly EM, go to Internet and Security, Advanced - Developper settings.

The power reading should be positive for consumed power, negative for injected power.

## The Dimmer device

Chose a RobotDyn dimmer board which can handle the amount of current consumed by the water heater (recommended: the 600V / 24A version).

The ESPHome home code for the ESP8266 microcontroller, and the wiring diagram are available in this repository.

## Energy Router installation

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



### Energy Router operation





## Home Assistant integration

To interact with the Energy Router, we can set up two Entities in Home Assistant:

- a Switch to set the Energy Router to automatic mode, or to manual mode,

- an Input Number to set the power percentage for manual mode.

You can use the following code in configuration.yaml to define these entities. You will also get a sensor with the (estimated) power sent to the water heater.

```
input_number:
  energy_router_power:
    name: Energy router manual mode power
    min: 0
    max: 100
    step: 1
    mode: box
    unit_of_measurement: "%"
    icon: mdi:radiator

mqtt:
    sensor:
      - name: "Energy router dimmer"
        state_topic: "home/solarheat-dimmer/power"
        value_template: '{{ value_json.power_estim }}'
        expire_after: 20
        device_class: power
        unit_of_measurement: W

    switch:
      - name: "Energy router mode auto"
        state_topic: "home/solarheat-dimmer/mode"
        value_template: >
          {%- if int(value) == -1 -%}ON{%- else -%}OFF{%- endif -%}
        availability:
          - topic: "home/solarheat-dimmer/RouterLWT"
            payload_available: "online"
            payload_not_available: "offline"
        state_on: "ON"
        state_off: "OFF"
        command_topic: "home/solarheat-dimmer/mode"
        payload_on: -1
        payload_off: 0
        optimistic: false
        qos: 0
        retain: true
        icon: mdi:routes

```

In case we switch the Energy Router to manual mode, we configure an Automation to send the corresponding value to its "mode" topic.

```
alias: Energy router mode to manual
description: ""
trigger:
  - platform: state
    entity_id:
      - switch.energy_router_mode_auto
    from: "on"
    to: "off"
condition: []
action:
  - delay:
      hours: 0
      minutes: 0
      seconds: 1
      milliseconds: 0
  - service: mqtt.publish
    data:
      topic: home/solarheat-dimmer/mode
      qos: "0"
      retain: true
      payload: "{{ states.input_number.energy_router_power.state }}"
mode: single
```

When the Energy Router is in manual mode, and we change the power percentage, we use an Automation to send the new value.

```
alias: Energy router manual mode power
description: ""
trigger:
  - platform: state
    entity_id:
      - input_number.energy_router_power
condition:
  - condition: state
    entity_id: switch.energy_router_mode_auto
    state: "off"
action:
  - service: mqtt.publish
    data:
      retain: true
      topic: home/solarheat-dimmer/mode
      payload: "{{ trigger.to_state.state }}"
mode: single
```

To put these controls on our dashboard, you can use the following code:

```
  - type: horizontal-stack
    cards:
      - type: conditional
        conditions:
          - entity: switch.energy_router_mode_auto
            state: 'off'
        card:
          type: entities
          entities:
            - entity: input_number.energy_router_power
              name: Power
              secondary_info: none
          state_color: true
          title: Energy
      - type: entities
        entities:
          - entity: switch.energy_router_mode_auto
            name: Automatic
        state_color: true
        title: Router
```

This code will hide the energy_router_power numeric input, when the Energy Router is in automatic mode.