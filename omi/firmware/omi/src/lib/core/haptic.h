#ifndef HAPTIC_H_
#define HAPTIC_H_

#include <stdbool.h>
#include <stdint.h>
#include <zephyr/bluetooth/conn.h>

/**
 * @brief Initialize the haptic driver.
 *
 * Configures the GPIO pin for the haptic motor.
 *
 * @return 0 on success, negative error code otherwise.
 */
int haptic_init(void);

/**
 * @brief Play a haptic effect for a specified duration.
 *
 * Activates the haptic motor for the given duration in milliseconds.
 * The duration is capped by MAX_HAPTIC_DURATION.
 *
 * @param duration Duration in milliseconds.
 */
void play_haptic_milli(uint32_t duration);

/**
 * @brief Register the Haptic BLE service.
 *
 * Registers the GATT service for controlling the haptic motor over Bluetooth.
 */
void register_haptic_service(void);

void haptic_off();

/**
 * The capture alarm: on for @ref ALARM_PULSE_MS, off for @ref ALARM_GAP_MS,
 * repeated until somebody presses the button.
 *
 * Deliberately unlike the three single pulses the app can ask for over the air
 * (100/300/500 ms), because it has to be told apart from them at the neck --
 * and because the case it exists for is the one where the app cannot write at
 * all. A dropped link during a recording is raised by the device itself.
 */
#define ALARM_PULSE_MS 300
#define ALARM_GAP_MS 300

/** Raise the alarm. Idempotent: a second call while it runs changes nothing. */
void haptic_alarm_start(void);

/** Clear the alarm and stop the motor. Safe when no alarm is raised. */
void haptic_alarm_stop(void);

/** Whether an alarm is currently raised and unanswered. */
bool haptic_alarm_active(void);

/**
 * @brief The link went away; raise the alarm if a recording was under way.
 *
 * The rule from the transport layer, expressed here so it can be tested without
 * a radio. @p was_recording is the microphone hold that the recording itself
 * took -- there is no second notion of "recording" in this firmware.
 *
 * A disconnect with nothing recording is not a failure and stays silent. There
 * is deliberately no counterpart for reconnecting: an alarm is answered by a
 * finger and by nothing else.
 */
void haptic_alarm_on_disconnect(bool was_recording);

/**
 * @brief Whether the button currently belongs to the alarm.
 *
 * Called once per button sampling period with the physical state. The first
 * press while an alarm is raised answers it, and that whole press -- down and
 * up -- belongs to the alarm: the caller must report nothing to the phone for
 * it. Orb reads a single and a double tap as "record", so a press that escaped
 * here would start a recording nobody asked for.
 *
 * Once the finger is off, the button is the person's again.
 */
bool haptic_alarm_owns_button(bool pressed);

#endif // HAPTIC_H_
