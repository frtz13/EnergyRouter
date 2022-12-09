# Energy Router

work in progress !!!

## Under which circumstances is this project useful?

- You have some energy production (typically solar panels).

- You want to consume as much as possible of this energy yourself.

- You have a device (typically a water heater) which can consume the part of the energy, which you cannot consume at certain moments.

- You have an energy meter which measures the power consumed by your household (typically a Shelly EM). The power can be either positive (power is consumed) or négative (power is injected into the public power grid).

## How it works

The energy meter is supposed to make power consumption information available via an MQTT broker or as a Sensor in Home Assistant.

The Energy Router, which is a Python script running in the background, monitors power measured by the energy meter. When power is injected into the public power grid (the power measurement becomes negative), the Energy Router communicates with a Dimmer device which gradually sends power to a water heater. A closed regulation loop keeps the power injected into the public power grid as low as possible, reacting permanently to the fluctuations in power consumption and power production.

The **Energy Router** is a python script...

- either running inside the Home Assistant AppDaemon environment.

- or running as a standalone program, typically running in the background on your home automation computer (which probably also runs the MQTT broker and your Home Assistant instance).

Which one to choose?

- If you run Home Assistant on top of Home Assistant OS, AppDaemon will be your friend.

- If you are using Home Assistant Supervised, both options are possible.

- If you are using some other kind or home automation system, the standalone version is the only choice.

The **Dimmer** device is composed of a ESP8266 microcontroller and a RobotDyn dimmer. The microcontroller receives commands from the Energy Router via the MQTT broker.

## Grid power measurement

If this task is performed by a Shelly EM, it should be configured to send measurements to the MQTT broker. On the web page of the Shelly EM, go to Internet and Security, Advanced - Developper settings.

The power reading should be positive for consumed power, negative for injected power.

## The Dimmer device

Chose a RobotDyn dimmer board which can handle the amount of current consumed by the water heater (recommended: the 600V / 24A version).

The ESPHome code for the ESP8266 microcontroller, and the wiring diagram are available in this repository.

## Energy Router installation

As already stated, the Energy Router script can run inside a Home Assistant installation as an [AppDaemon app](https:./EnergyRouter/blob/master/AppDaemon/AppDaemon.md), or run as a [standalone Python script](https:EnergyRouter/blob/master/ER_Python.md). For installation instructions, click on either of these links.

## Energy Router configuration

### Dimmer parameters

Set the MQTT topic parameters according to the ESPHome code, which you intend to flash to the ESP8266.

MAX_PERCENTAGE: you can set the maximum power percentage you want to allow to the water heater.

MQTT_TOPIC_DIMMER_STATUS: in DEBUG mode, the Energy Router sends internal values as payload for this MQTT topic.

#### Regulation parameters

The given values should be a good starting point. These are the coefficients for the proportional-integral closed regulation loop.

## Energy Router operation

The router is controlled by the payload of the `mode` topic (RouterMode parameter). This is typically a retained mqtt topic.

A **value of -1** means *automatic mode*. When the gridpower value is negative, the router will try send as much power as possible to the water heater, while keeping power injection to the public grid as small as possible. More precisely: keeping it close the the gridpower_bias value given in the parameters.

A **value of 0...100** means *manual mode*, meaning that the router will send this percentage of power to the water heater, regardless of the measurements of the energy meter. This should be handy when energy production is low over a longer period of time.

The `mode` topic is supposed to be set via your home automation user interface, in the form of a retained MQTT topic payload. Please see below for a way to do this inside Home Assistant.

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

In case we switch the Energy Router to manual mode, we configure an Automation to send the corresponding payload to its "mode" topic.

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

A chart to track grid power and the power sent to the water heater (in negative direction):

```
type: custom:apexcharts-card
graph_span: 1h
header:
  show: true
  title: ApexCharts-Card
  show_states: true
  colorize_states: true
series:
  - entity: sensor.house_real_power
    stroke_width: 2
    curve: stepline
    yaxis_id: power
  - entity: sensor.energy_router_dimmer
    stroke_width: 1
    curve: stepline
    yaxis_id: power
    transform: return -x
yaxis:
  - id: power
    opposite: false
    apex_config:
      forceNiceScale: true
```
